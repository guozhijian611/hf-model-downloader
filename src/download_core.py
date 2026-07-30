"""
Qt-free download core used by subprocess workers.

IMPORTANT: This module must NOT import PyQt. Spawned download processes load
this module only — importing Qt in a child of a GUI app can crash the app
(especially frozen PyInstaller builds on Windows/macOS).
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fnmatch import fnmatch

from tqdm.auto import tqdm

from .hf_hub_env import (
    apply_hf_download_env,
    configure_hf_hub_http,
    resolve_hf_endpoint,
    xet_available,
)
from .proxy_env import apply_proxy_env, normalize_proxy

PLATFORM_LABELS = {
    "huggingface": "Hugging Face",
    "modelscope": "ModelScope",
}

PLATFORM_CONFIGS = {
    "huggingface": {
        "token_env": "HF_TOKEN",
        "endpoint_env": "HF_ENDPOINT",
        "logger_name": "huggingface_hub",
        "default_endpoint": "https://huggingface.co",
        "mirror_endpoint": "https://hf-mirror.com",
        "ssl_verification": True,
    },
    "modelscope": {
        "token_env": "MODELSCOPE_API_TOKEN",
        "endpoint_env": "MODELSCOPE_ENDPOINT",
        "logger_name": "modelscope",
        "default_endpoint": "https://modelscope.cn",
        "mirror_endpoint": "https://modelscope.cn",
        "ssl_verification": True,
    },
}


def platform_label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, platform)


def repo_type_label(repo_type: str) -> str:
    return "模型" if repo_type == "model" else "数据集"


def _abort_download(pipe, message: str) -> None:
    if pipe:
        try:
            pipe.send(f"错误：{message}")
        except Exception:
            pass
    print(f"错误：{message}", flush=True)
    sys.exit(1)


class UnifiedProgressBar(tqdm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current = self.n

    def update(self, n):
        super().update(n)
        self._current += n


# Pipe-backed per-file tqdm used by parallel hf_hub_download.
# snapshot_download intentionally swallows per-file bars into one aggregate bar
# ("Downloading (incomplete total...)"), which looks like a single-thread hang.
_PIPE_TQDM_LOCK = threading.Lock()
_PIPE_TQDM_LAST: dict[str, float] = {}
_PIPE_TQDM_PIPE = None
_PIPE_TQDM_STATS_LOCK = threading.Lock()
_PIPE_TQDM_ACTIVE: dict[str, tuple[int, int]] = {}  # name -> (n, total)
_PIPE_TQDM_REPO_DIR: str | None = None
_PIPE_TQDM_MANUAL_N: dict[str, int] = {}  # fallback byte counter


def _pipe_tqdm_reset(pipe, repo_dir: str | None = None) -> None:
    global _PIPE_TQDM_PIPE, _PIPE_TQDM_REPO_DIR
    with _PIPE_TQDM_LOCK:
        _PIPE_TQDM_PIPE = pipe
        _PIPE_TQDM_LAST.clear()
        _PIPE_TQDM_MANUAL_N.clear()
        _PIPE_TQDM_REPO_DIR = repo_dir
    with _PIPE_TQDM_STATS_LOCK:
        _PIPE_TQDM_ACTIVE.clear()


def _file_bytes_on_disk(repo_dir: str, filename: str) -> int:
    """Bytes already written for a hub local_dir download (final or .incomplete)."""
    try:
        from pathlib import Path as _Path

        from huggingface_hub._local_folder import (  # type: ignore
            _short_hash,
            get_local_download_paths,
        )

        paths = get_local_download_paths(_Path(repo_dir), filename)
        if paths.file_path.is_file():
            return int(paths.file_path.stat().st_size)
        parent = paths.metadata_path.parent
        if not parent.is_dir():
            return 0
        prefix = _short_hash(paths.metadata_path.name)
        best = 0
        for p in parent.glob(f"{prefix}.*.incomplete"):
            try:
                best = max(best, int(p.stat().st_size))
            except OSError:
                continue
        return best
    except Exception:
        # Fallback: final path only
        try:
            p = os.path.join(repo_dir, *filename.split("/"))
            if os.path.isfile(p):
                return int(os.path.getsize(p))
            if os.path.isfile(p + ".incomplete"):
                return int(os.path.getsize(p + ".incomplete"))
        except OSError:
            pass
        return 0


def _human_bytes(n: int) -> str:
    n = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)}{unit}"
            return f"{n:.2f}{unit}"
        n /= 1024.0
    return f"{n:.2f}TB"


class PipeFileTqdm(tqdm):
    """tqdm that reports structured per-file progress over the download pipe.

    Also merges on-disk incomplete size because Xet/http paths sometimes leave
    ``tqdm.n`` at 0 until a file finishes (UI looks stuck at 0%).
    """

    def __init__(self, *args, **kwargs):
        kwargs = dict(kwargs)
        self._fname = str(kwargs.get("desc") or "file")
        # Never write multi-bar noise to stdout (pipe captures stdout too).
        kwargs["disable"] = True
        kwargs["mininterval"] = 0.25
        super().__init__(*args, **kwargs)
        self._last_human = 0.0
        self._manual_n = int(kwargs.get("initial") or 0)
        self._emit(force=True)

    def update(self, n=1):
        try:
            amount = 0 if n is None else int(n)
        except (TypeError, ValueError):
            amount = 0
        if amount:
            self._manual_n += amount
            with _PIPE_TQDM_LOCK:
                _PIPE_TQDM_MANUAL_N[self._fname] = self._manual_n
        try:
            r = super().update(n)
        except Exception:
            r = None
        self._emit()
        return r

    def close(self):
        try:
            self._emit(force=True, final=True)
        finally:
            super().close()

    def _resolved_n(self) -> int:
        n = max(int(self.n or 0), int(self._manual_n or 0))
        repo = _PIPE_TQDM_REPO_DIR
        if repo:
            try:
                n = max(n, _file_bytes_on_disk(repo, self._fname))
            except Exception:
                pass
        return n

    def _emit(self, force: bool = False, final: bool = False) -> None:
        pipe = _PIPE_TQDM_PIPE
        if not pipe:
            return
        now = time.monotonic()
        name = self._fname
        n = self._resolved_n()
        total = int(self.total or 0)
        with _PIPE_TQDM_LOCK:
            last = _PIPE_TQDM_LAST.get(name, 0.0)
            if not force and (now - last) < 0.5:
                return
            _PIPE_TQDM_LAST[name] = now
        status = "done" if final or (total > 0 and n >= total) else "downloading"
        try:
            pipe.send(f"[HF_FILE]\t{name}\t{n}\t{total}\t{status}")
        except Exception:
            return
        with _PIPE_TQDM_STATS_LOCK:
            if status == "done":
                _PIPE_TQDM_ACTIVE.pop(name, None)
            else:
                _PIPE_TQDM_ACTIVE[name] = (n, total)
            active = len(_PIPE_TQDM_ACTIVE)
        # Human log: throttle harder to avoid flooding the main log panel
        if force or final or (now - self._last_human) >= 2.0:
            self._last_human = now
            try:
                if total > 0:
                    pct = min(100.0, 100.0 * n / total)
                    size_txt = f"{_human_bytes(n)}/{_human_bytes(total)}"
                else:
                    pct = 0.0
                    size_txt = _human_bytes(n)
                short = name if len(name) <= 48 else ("…" + name[-47:])
                pipe.send(
                    f"文件 [{active}并发] {short}: {pct:.1f}% ({size_txt})"
                    + (" ✓" if status == "done" else "")
                )
            except Exception:
                pass


class SafePipeWriter:
    """Process-safe pipe writer that doesn't hold PyQt references."""

    def __init__(self, pipe):
        if hasattr(pipe, "send"):
            self.pipe = pipe
        else:
            self.pipe = None
        self.buffer = ""
        self.last_progress = ""
        self._closed = False

    def send(self, message):
        if self._closed or not self.pipe:
            return
        try:
            self.pipe.send(str(message))
        except (BrokenPipeError, OSError, EOFError):
            self._closed = True

    def write(self, text):
        if self._closed:
            return

        if "\r" in text:
            self.buffer = text.split("\r")[-1]
            if self.buffer.strip() and self.buffer != self.last_progress:
                self.send(self.buffer)
                self.last_progress = self.buffer
        elif "\n" in text:
            self.buffer += text
            lines = self.buffer.split("\n")
            self.buffer = lines[-1]
            for line in lines[:-1]:
                if line.strip() and line != self.last_progress:
                    self.send(line)
        else:
            self.buffer += text

    def flush(self):
        if (
            not self._closed
            and self.buffer.strip()
            and self.buffer != self.last_progress
        ):
            self.send(self.buffer)
            self.buffer = ""

    def close(self):
        self._closed = True
        self.pipe = None


def _hf_friendly_error(exc: Exception, endpoint: str) -> str:
    msg = str(exc)
    tips: list[str] = [f"Hugging Face 下载失败：{msg}"]
    lower = msg.lower()
    if (
        "429" in lower
        or "rate limit" in lower
        or "too many requests" in lower
        or "ratelimit" in lower
    ):
        tips.append("可能原因与建议（疑似限速/限流）：")
        tips.append("1) 降低「hub文件」并发（例如 16→6～8）后重试")
        tips.append("2) 填写 HF Token，认证用户额度通常高于匿名")
        tips.append("3) 换节点或稍后再试；短时间密集重连会加重 429")
        tips.append("4) 已下载部分会断点续传，不必清空目录")
        return "\n".join(tips)
    if (
        "cannot find the requested files in the local cache" in lower
        or "error happened while trying to locate the file" in lower
        or "connection" in lower
        or "timed out" in lower
        or "timeout" in lower
        or "max retries" in lower
    ):
        tips.append("可能原因与建议：")
        tips.append(
            f"1) 当前 Endpoint「{endpoint}」连不上或镜像不完整，"
            "可改试 https://huggingface.co（需代理时请启用代理）"
        )
        tips.append("2) 网络不稳定：开启应用内代理或 TUN 后重试（支持断点续传）")
        tips.append("3) 私有/门禁仓库：请填写有效 HF Token")
        tips.append("4) 超大仓库文件很多时，可降低并发或换网络环境再试")
        tips.append("5) 若日志曾提示 proxies 被忽略：请更新到已修复 httpx 代理的版本")
    return "\n".join(tips)


def download_huggingface(
    model_id: str,
    save_path: str,
    token: str = None,
    endpoint: str = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str = None,
    max_workers: int | None = None,
):
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        _abort_download(pipe, f"无法导入 huggingface_hub：{exc}")

    resolved_endpoint = resolve_hf_endpoint(endpoint)
    apply_hf_download_env(token=token, endpoint=resolved_endpoint)
    # Hub 1.x ignores snapshot_download(proxies=...); use env + httpx factory.
    active_proxy = configure_hf_hub_http(proxy)

    repo_dir = os.path.join(save_path, model_id.split("/")[-1])
    using_mirror = "mirror" in resolved_endpoint.lower()

    # User-configurable concurrency; fall back to previous auto defaults.
    cpu_count = multiprocessing.cpu_count()
    if max_workers is None or int(max_workers) <= 0:
        max_workers = min(cpu_count, 4) if using_mirror else min(cpu_count + 2, 8)
    else:
        max_workers = max(1, min(int(max_workers), 32))

    if pipe:
        if using_mirror:
            pipe.send("提示：镜像站已禁用 Xet 传输，改用标准 HTTP（兼容性更好）。")
        elif not xet_available():
            pipe.send(
                "警告：未检测到 hf_xet，"
                "大文件可能回退为普通 HTTP 下载（速度可能较慢）。"
            )
        if active_proxy:
            pipe.send(
                f"Hugging Face 下载使用代理：{active_proxy}"
                "（HTTP_PROXY + httpx client，不再使用已废弃的 proxies= 参数）"
            )
        else:
            pipe.send("提示：未配置应用内代理；若仅开 TUN，流量仍可能走系统隧道。")
        pipe.send(f"开始从 Hugging Face 下载：{model_id}")
        pipe.send(f"仓库类型：{repo_type}")
        pipe.send(f"保存目录：{repo_dir}")
        pipe.send(f"Endpoint：{resolved_endpoint}")
        pipe.send(f"并发 max_workers={max_workers}")

    # Datasets often need many file types; only skip junk / VCS noise for them.
    if repo_type == "dataset":
        ignore_patterns = [".*", "__pycache__/*"]
    else:
        ignore_patterns = [
            "*.h5",
            "*.ot",
            "*.msgpack",
            "*.bin",
            "*.pkl",
            "*.onnx",
            ".*",
        ]

    try:
        # Prefer parallel hf_hub_download so each concurrent file reports progress.
        # snapshot_download merges all bars into "incomplete total" only — looks stuck.
        result = _download_hf_parallel_with_file_progress(
            model_id=model_id,
            repo_dir=repo_dir,
            token=token,
            endpoint=resolved_endpoint,
            repo_type=repo_type,
            max_workers=max_workers,
            ignore_patterns=ignore_patterns,
            pipe=pipe,
        )
    except Exception as exc:
        if pipe:
            pipe.send(f"并行分文件下载失败，回退 snapshot_download：{exc}")
        try:
            # Fallback: official snapshot (aggregate progress only).
            result = snapshot_download(
                repo_id=model_id,
                repo_type=repo_type,
                local_dir=repo_dir,
                token=token,
                force_download=False,
                max_workers=max_workers,
                tqdm_class=UnifiedProgressBar,
                ignore_patterns=ignore_patterns,
                local_files_only=False,
                etag_timeout=60,
                endpoint=resolved_endpoint,
            )
        except Exception as exc2:
            _abort_download(pipe, _hf_friendly_error(exc2, resolved_endpoint))

    if pipe:
        pipe.send(f"Hugging Face 下载完成：{result}")


def _match_ignore(path: str, ignore_patterns: list[str]) -> bool:
    """True if path should be ignored (fnmatch on full path and basename)."""
    base = path.rsplit("/", 1)[-1]
    for pat in ignore_patterns or []:
        if fnmatch(path, pat) or fnmatch(base, pat):
            return True
        # patterns like ".*" for hidden
        if pat.startswith("*.") and base.endswith(pat[1:]):
            return True
    return False


def _download_hf_parallel_with_file_progress(
    *,
    model_id: str,
    repo_dir: str,
    token: str | None,
    endpoint: str,
    repo_type: str,
    max_workers: int,
    ignore_patterns: list[str],
    pipe=None,
) -> str:
    """List repo files and download with ThreadPoolExecutor + per-file progress."""
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(endpoint=endpoint, token=token)
    if pipe:
        pipe.send("正在列出仓库文件（用于分文件并发进度）…")
    try:
        all_files = api.list_repo_files(
            repo_id=model_id, repo_type=repo_type, token=token
        )
    except TypeError:
        all_files = api.list_repo_files(repo_id=model_id, repo_type=repo_type)

    files = [f for f in all_files if not _match_ignore(f, ignore_patterns)]
    if pipe:
        pipe.send(
            f"共 {len(files)} 个文件待下载（已过滤 ignore），"
            f"并发 max_workers={max_workers}"
        )
        pipe.send(
            "说明：官方 snapshot_download 只显示合并总进度；"
            "本模式为每个并发文件单独上报进度。"
        )
        pipe.send(f"[HF_META]\tfiles\t{len(files)}")

    if not files:
        os.makedirs(repo_dir, exist_ok=True)
        return repo_dir

    _pipe_tqdm_reset(pipe, repo_dir=repo_dir)
    os.makedirs(repo_dir, exist_ok=True)

    errors: list[str] = []
    errors_lock = threading.Lock()
    completed = 0
    completed_lock = threading.Lock()
    stop_poll = threading.Event()

    def _disk_progress_poller() -> None:
        """Xet/http sometimes leave tqdm.n at 0; poll .incomplete sizes instead."""
        while not stop_poll.wait(1.0):
            pipe_ref = _PIPE_TQDM_PIPE
            if not pipe_ref:
                continue
            with _PIPE_TQDM_STATS_LOCK:
                items = list(_PIPE_TQDM_ACTIVE.items())
            if not items:
                # Also discover incomplete files not yet in ACTIVE
                try:
                    cache = os.path.join(repo_dir, ".cache", "huggingface", "download")
                    if os.path.isdir(cache):
                        # At least emit overall sum of incomplete bytes
                        total_inc = 0
                        count_inc = 0
                        for root, _dirs, names in os.walk(cache):
                            for name in names:
                                if name.endswith(".incomplete"):
                                    try:
                                        total_inc += os.path.getsize(
                                            os.path.join(root, name)
                                        )
                                        count_inc += 1
                                    except OSError:
                                        pass
                        if count_inc and pipe_ref:
                            try:
                                pipe_ref.send(
                                    f"磁盘缓存中 incomplete：{count_inc} 个，"
                                    f"合计 {_human_bytes(total_inc)}"
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
                continue
            for fname, (_old_n, total) in items:
                try:
                    n = _file_bytes_on_disk(repo_dir, fname)
                except Exception:
                    continue
                if n <= 0:
                    continue
                status = "done" if total > 0 and n >= total else "downloading"
                try:
                    pipe_ref.send(f"[HF_FILE]\t{fname}\t{n}\t{total}\t{status}")
                except Exception:
                    return

    poller = threading.Thread(
        target=_disk_progress_poller, name="hf-disk-progress", daemon=True
    )
    poller.start()

    def _one(filename: str) -> str:
        nonlocal completed
        # Register as active early so disk poller can track incomplete size
        with _PIPE_TQDM_STATS_LOCK:
            _PIPE_TQDM_ACTIVE[filename] = (0, 0)
        path = hf_hub_download(
            repo_id=model_id,
            filename=filename,
            repo_type=repo_type,
            revision=None,
            endpoint=endpoint,
            local_dir=repo_dir,
            token=token,
            force_download=False,
            etag_timeout=60,
            tqdm_class=PipeFileTqdm,
        )
        # Final size report
        try:
            final_n = _file_bytes_on_disk(repo_dir, filename)
            if pipe and final_n > 0:
                pipe.send(f"[HF_FILE]\t{filename}\t{final_n}\t{final_n}\tdone")
        except Exception:
            pass
        with completed_lock:
            completed += 1
            done_n = completed
        with _PIPE_TQDM_STATS_LOCK:
            _PIPE_TQDM_ACTIVE.pop(filename, None)
        if pipe and (done_n % 10 == 0 or done_n == len(files) or done_n <= 3):
            try:
                pipe.send(f"已完成文件 {done_n}/{len(files)}：{filename}")
            except Exception:
                pass
        return path

    workers = max(1, min(int(max_workers), 32, len(files)))
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, f): f for f in files}
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    with errors_lock:
                        errors.append(f"{name}: {exc}")
                    if pipe:
                        try:
                            pipe.send(f"错误：文件下载失败 {name}：{exc}")
                        except Exception:
                            pass
                    with _PIPE_TQDM_STATS_LOCK:
                        _PIPE_TQDM_ACTIVE.pop(name, None)
    finally:
        stop_poll.set()
        poller.join(timeout=2.0)

    if errors:
        sample = "\n".join(errors[:8])
        more = f"\n… 另有 {len(errors) - 8} 个文件失败" if len(errors) > 8 else ""
        raise RuntimeError(
            f"{len(errors)}/{len(files)} 个文件下载失败。示例：\n{sample}{more}"
        )

    return os.path.realpath(repo_dir)


def download_modelscope(
    model_id: str,
    save_path: str,
    token: str = None,
    endpoint: str = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str = None,
):
    try:
        from modelscope import HubApi, MsDataset
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError:
        _abort_download(pipe, "未安装 ModelScope 库。")

    apply_proxy_env(proxy)

    if token:
        try:
            api = HubApi()
            api.login(token)
            if pipe:
                pipe.send("ModelScope 登录成功")
        except Exception as e:
            if pipe:
                pipe.send(f"ModelScope 登录失败：{e!s}")

    if endpoint:
        os.environ["MODELSCOPE_ENDPOINT"] = endpoint

    repo_name = model_id.split("/")[-1]
    repo_dir = os.path.join(save_path, repo_name)

    if pipe:
        if normalize_proxy(proxy):
            pipe.send(f"ModelScope 下载使用代理：{normalize_proxy(proxy)}")
        pipe.send(f"开始从 ModelScope 下载：{model_id}")
        if repo_type == "dataset":
            pipe.send(f"正在下载数据集到：{repo_dir}")
        else:
            pipe.send(f"正在下载模型到：{repo_dir}")

    try:
        if repo_type == "dataset":
            if pipe:
                pipe.send("使用 MsDataset 下载数据集...")

            os.makedirs(repo_dir, exist_ok=True)

            MsDataset.load(
                dataset_name=model_id,
                cache_dir=repo_dir,
            )

            if pipe:
                pipe.send(f"ModelScope 数据集已缓存到：{repo_dir}")

            result = repo_dir
        else:
            result = snapshot_download(
                model_id=model_id,
                local_dir=repo_dir,
                revision="master",
                ignore_patterns=[
                    "*.h5",
                    "*.ot",
                    "*.msgpack",
                    "*.bin",
                    "*.pkl",
                    "*.onnx",
                    ".*",
                ],
            )

        if pipe:
            pipe.send(f"ModelScope 下载完成：{result}")

    except Exception as exc:
        _abort_download(pipe, f"ModelScope 下载失败：{exc}")


def unified_download_model(
    platform: str,
    model_id: str,
    save_path: str,
    token: str = None,
    endpoint: str = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str = None,
    backend: str = "huggingface-hub",
    max_workers: int | None = None,
    hfd_threads: int | None = None,
    hfd_jobs: int | None = None,
):
    """Download entry used by subprocess workers (no Qt)."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected = False
    try:
        if platform not in PLATFORM_CONFIGS:
            _abort_download(pipe, f"不支持的平台「{platform}」")

        print(f"\n=== {platform.title()} Download Process Debug Info ===")
        print("Process ID:", os.getpid())
        print("Parent Process ID:", os.getppid())
        print("Current Working Directory:", os.getcwd())
        print("Python Executable:", sys.executable)
        print("Download Backend:", backend or "huggingface-hub")
        print("max_workers:", max_workers)
        print("hfd_threads:", hfd_threads, "hfd_jobs:", hfd_jobs)
        try:
            print("Process Start Method:", multiprocessing.get_start_method())
        except RuntimeError:
            print("Process Start Method: (not set)")
        print("=== End Debug Info ===\n")

        if pipe:
            sys.stdout = pipe
            sys.stderr = pipe
            redirected = True

        def signal_handler(signum, frame):
            if pipe:
                try:
                    pipe.send("下载被系统信号中断")
                except Exception:
                    pass
            sys.exit(1)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:
            if platform == "huggingface":
                from .hfd_backend import BACKEND_HFD, download_with_hfd

                if (backend or "").strip() == BACKEND_HFD:
                    download_with_hfd(
                        model_id,
                        save_path,
                        token,
                        endpoint,
                        pipe,
                        repo_type,
                        proxy,
                        threads=hfd_threads if hfd_threads else 8,
                        jobs=hfd_jobs if hfd_jobs else 5,
                    )
                else:
                    download_huggingface(
                        model_id,
                        save_path,
                        token,
                        endpoint,
                        pipe,
                        repo_type,
                        proxy,
                        max_workers=max_workers,
                    )
            elif platform == "modelscope":
                if (backend or "").strip() == "hfd":
                    _abort_download(
                        pipe,
                        "hfd 仅支持 Hugging Face，请切换平台或改用 huggingface-hub。",
                    )
                download_modelscope(
                    model_id, save_path, token, endpoint, pipe, repo_type, proxy
                )
            else:
                _abort_download(pipe, f"不支持的平台「{platform}」")
        except KeyboardInterrupt:
            _abort_download(pipe, "用户已取消下载")

    except SystemExit:
        raise
    except Exception as exc:
        _abort_download(pipe, f"{platform_label(platform)} 下载出错：{exc}")
    finally:
        if redirected:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        if pipe:
            try:
                pipe.send("DOWNLOAD_COMPLETE")
            except (BrokenPipeError, OSError, EOFError):
                pass


def isolated_download_main(
    platform,
    model_id,
    save_path,
    token,
    endpoint,
    pipe,
    repo_type,
    proxy=None,
    backend="huggingface-hub",
    max_workers=None,
    hfd_threads=None,
    hfd_jobs=None,
):
    """
    Top-level process entry point (must stay free of PyQt imports).

    Used as multiprocessing.Process(target=isolated_download_main, ...).
    """
    try:
        safe_pipe = SafePipeWriter(pipe)
        unified_download_model(
            platform,
            model_id,
            save_path,
            token,
            endpoint,
            safe_pipe,
            repo_type,
            proxy,
            backend=backend,
            max_workers=max_workers,
            hfd_threads=hfd_threads,
            hfd_jobs=hfd_jobs,
        )
        safe_pipe.close()
    except SystemExit:
        raise
    except Exception as e:
        if pipe:
            try:
                pipe.send(f"下载进程错误：{e!s}")
            except (BrokenPipeError, OSError, EOFError):
                pass
        sys.exit(1)


# Keep logger quiet in child unless configured by parent.
logging.getLogger("download_core").addHandler(logging.NullHandler())
