"""
Utility functions for the Model Downloader
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys

logger = logging.getLogger("huggingface_hub")
logger.setLevel(logging.INFO)


def cleanup_lock_files(directory):
    """Clean up any .lock files in the directory and its subdirectories."""
    logger.info("正在清理下载锁文件（保留已下载分块以便断点续传）...")
    try:
        for root, _dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".lock"):
                    lock_file = os.path.join(root, file)
                    try:
                        os.remove(lock_file)
                        logger.info(f"已删除锁文件：{lock_file}")
                    except Exception as e:
                        logger.warning(f"无法删除锁文件 {lock_file}：{e!s}")
    except Exception as e:
        logger.warning(f"清理锁文件时出错：{e!s}")


def cleanup_environment():
    """Clean up environment variables."""
    env_vars = ["HF_TOKEN", "HF_HUB_DISABLE_SSL_VERIFICATION"]
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]


def kill_process_tree(
    pid: int | None,
    *,
    grace_sec: float = 2.0,
    include_root: bool = True,
) -> None:
    """
    Terminate a process and all of its descendants.

    On Windows, Process.terminate() only kills the target PID; grandchildren
    like bash → aria2c (hfd backend) become orphans and keep downloading.

    Set ``include_root=False`` to only kill descendants (e.g. in a signal
    handler inside the download worker itself).
    """
    if pid is None or pid <= 0:
        return

    try:
        import psutil
    except ImportError:
        if include_root:
            _kill_process_tree_fallback(pid)
        return

    try:
        parent = psutil.Process(pid)
    except (psutil.Error, ValueError, OSError):
        return

    # Children first, then parent — reduces the chance of orphans.
    try:
        procs = parent.children(recursive=True)
    except (psutil.Error, OSError):
        procs = []
    if include_root:
        procs.append(parent)

    if not procs:
        return

    for proc in procs:
        try:
            proc.terminate()
        except (psutil.Error, OSError):
            pass

    try:
        _gone, alive = psutil.wait_procs(procs, timeout=max(0.1, float(grace_sec)))
    except Exception:
        alive = procs

    for proc in alive:
        try:
            proc.kill()
        except (psutil.Error, OSError):
            pass

    # Windows fallback if anything still lingers (Job-less trees).
    if include_root and sys.platform.startswith("win"):
        try:
            still = psutil.pid_exists(pid)
        except Exception:
            still = False
        if still:
            _kill_process_tree_fallback(pid, force=True)


def _kill_process_tree_fallback(pid: int, *, force: bool = False) -> None:
    """Platform-native tree kill when psutil is unavailable or incomplete."""
    try:
        if sys.platform.startswith("win"):
            flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            cmd = ["taskkill", "/PID", str(pid), "/T"]
            if force:
                cmd.append("/F")
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=flags,
            )
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
            if force:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
    except Exception as exc:
        logger.warning("kill_process_tree fallback failed for pid=%s: %s", pid, exc)


def _path_match_variants(path: str) -> set[str]:
    variants: set[str] = set()
    if not path:
        return variants
    raw = path.strip().rstrip("/\\")
    if not raw:
        return variants
    candidates = [raw, os.path.normpath(raw)]
    try:
        candidates.append(os.path.abspath(raw))
    except OSError:
        pass
    for item in candidates:
        if not item:
            continue
        variants.add(item)
        variants.add(item.replace("\\", "/"))
        variants.add(item.replace("/", "\\"))
        variants.add(os.path.normcase(item))
        variants.add(os.path.normcase(item.replace("\\", "/")))
    return {v for v in variants if v}


def kill_hfd_related_processes(local_dir: str | None) -> int:
    """
    Kill residual hfd.sh / aria2c workers targeting ``local_dir``.

    Safety net after cancel when the download process tree was incomplete
    (orphans from prior versions or failed kills).
    """
    if not local_dir:
        return 0

    try:
        import psutil
    except ImportError:
        return 0

    needles = _path_match_variants(local_dir)
    if not needles:
        return 0

    def _matches_dir(text: str) -> bool:
        if not text:
            return False
        norm = text.replace("\\", "/")
        norm_case = os.path.normcase(norm)
        for n in needles:
            n_fwd = n.replace("\\", "/")
            if n_fwd in norm or os.path.normcase(n_fwd) in norm_case:
                return True
        return False

    targets: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            cl = " ".join(str(x) for x in cmdline if x)
            cl_fwd = cl.replace("\\", "/")

            is_bash_hfd = (
                name in ("bash.exe", "bash", "sh.exe", "sh")
                and "hfd.sh" in cl_fwd
                and _matches_dir(cl)
            )
            is_aria = name.startswith("aria2c") and (
                _matches_dir(cl)
                or ".hfd/aria2c_urls" in cl_fwd
                or ".hfd\\aria2c_urls" in cl
            )
            if is_aria and not _matches_dir(cl):
                # aria2 often runs with cwd=local_dir and relative -i .hfd/...
                try:
                    cwd = proc.cwd()
                except (psutil.Error, OSError):
                    cwd = ""
                if _matches_dir(cwd):
                    is_aria = True
                else:
                    is_aria = False

            if is_bash_hfd or is_aria:
                targets.append(int(proc.info["pid"]))
        except (psutil.Error, OSError, TypeError, ValueError, KeyError):
            continue

    # Unique, children-first-ish: kill each tree (duplicates ok / no-ops).
    seen: set[int] = set()
    killed = 0
    for pid in targets:
        if pid in seen:
            continue
        seen.add(pid)
        try:
            kill_process_tree(pid, grace_sec=1.0)
            killed += 1
        except Exception as exc:
            logger.warning("Failed to kill hfd-related pid=%s: %s", pid, exc)
    if killed:
        logger.info(
            "Cleaned %s residual hfd/aria2 process tree(s) for %s", killed, local_dir
        )
    return killed
