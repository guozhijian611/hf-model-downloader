"""Optional hfd (aria2/wget) download backend.

Script source: https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f
Bundled at scripts/hfd.sh — users can choose this backend in the GUI when
downloading from Hugging Face (not ModelScope).
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from .resource_utils import get_resource_path

BACKEND_HUB = "huggingface-hub"
BACKEND_HFD = "hfd"

BACKEND_CHOICES = [
    (BACKEND_HUB, "huggingface-hub（内置）"),
    (BACKEND_HFD, "hfd / aria2（高速，需 aria2c）"),
]


def find_bash() -> str | None:
    """Locate a bash interpreter (needed to run hfd.sh on all platforms)."""
    for name in ("bash", "sh"):
        path = shutil.which(name)
        if path:
            return path
    if platform.system().lower().startswith("win"):
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
            r"C:\Windows\System32\bash.exe",  # WSL launcher — may not run scripts well
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
    return None


def find_aria2c() -> str | None:
    return shutil.which("aria2c")


def find_wget() -> str | None:
    return shutil.which("wget")


def find_hfd_script() -> Path | None:
    """Resolve bundled scripts/hfd.sh in dev and frozen builds."""
    candidates = [
        Path(get_resource_path(os.path.join("scripts", "hfd.sh"))),
        Path(__file__).resolve().parents[1] / "scripts" / "hfd.sh",
    ]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                exe_dir / "scripts" / "hfd.sh",
                exe_dir / "_internal" / "scripts" / "hfd.sh",
            ]
        )
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def hfd_availability() -> tuple[bool, str]:
    """Return (ok, message) describing whether hfd can run on this machine."""
    script = find_hfd_script()
    if not script:
        return False, "未找到内置 scripts/hfd.sh"
    bash = find_bash()
    if not bash:
        return (
            False,
            "未找到 bash（Windows 请安装 Git for Windows 并确保 bash 在 PATH）",
        )
    if find_aria2c():
        return True, f"可用（aria2c + bash + {script.name}）"
    if find_wget():
        return True, f"可用（wget 回退 + bash + {script.name}，速度较慢）"
    return False, "未找到 aria2c 或 wget，请先安装 aria2c 以使用 hfd 高速下载"


def missing_hfd_deps() -> list[str]:
    """Human-readable list of missing pieces for hfd."""
    missing: list[str] = []
    if not find_hfd_script():
        missing.append("内置 hfd.sh 脚本")
    if not find_bash():
        missing.append("bash（Windows 需 Git for Windows）")
    if not find_aria2c() and not find_wget():
        missing.append("aria2c（推荐）或 wget")
    return missing


def hfd_install_plan() -> tuple[list[list[str]], list[str]]:
    """Return (shell commands as argv lists, manual tips) to install missing deps.

    Commands are best-effort via brew / winget / choco / scoop / apt / dnf.
    """
    cmds: list[list[str]] = []
    tips: list[str] = []
    system = platform.system().lower()
    need_aria = not find_aria2c() and not find_wget()
    need_bash = not find_bash()

    if need_aria:
        if system == "darwin":
            if shutil.which("brew"):
                cmds.append(["brew", "install", "aria2"])
            else:
                tips.append(
                    "macOS：先安装 Homebrew，再执行 brew install aria2\nhttps://brew.sh"
                )
        elif system.startswith("win"):
            if shutil.which("winget"):
                cmds.append(
                    [
                        "winget",
                        "install",
                        "-e",
                        "--id",
                        "aria2.aria2",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ]
                )
            elif shutil.which("choco"):
                cmds.append(["choco", "install", "aria2", "-y"])
            elif shutil.which("scoop"):
                cmds.append(["scoop", "install", "aria2"])
            else:
                tips.append(
                    "Windows：安装 winget/scoop/choco 后装 aria2，或从\n"
                    "https://github.com/aria2/aria2/releases 下载并加入 PATH"
                )
        else:  # linux
            if shutil.which("apt-get"):
                cmds.append(["sudo", "apt-get", "update"])
                cmds.append(["sudo", "apt-get", "install", "-y", "aria2"])
            elif shutil.which("dnf"):
                cmds.append(["sudo", "dnf", "install", "-y", "aria2"])
            elif shutil.which("pacman"):
                cmds.append(["sudo", "pacman", "-S", "--noconfirm", "aria2"])
            elif shutil.which("zypper"):
                cmds.append(["sudo", "zypper", "install", "-y", "aria2"])
            else:
                tips.append("Linux：请用发行版包管理器安装 aria2（aria2c）")

    if need_bash and system.startswith("win"):
        if shutil.which("winget"):
            cmds.append(
                [
                    "winget",
                    "install",
                    "-e",
                    "--id",
                    "Git.Git",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            )
        elif shutil.which("choco"):
            cmds.append(["choco", "install", "git", "-y"])
        else:
            tips.append(
                "Windows 还需 bash：安装 Git for Windows\n"
                "https://git-scm.com/download/win"
            )

    if not find_hfd_script():
        tips.append("未找到内置 hfd.sh，请重新安装/解压本程序完整包")

    if not cmds and not tips and missing_hfd_deps():
        tips.append("请手动安装缺失依赖后重启本程序")

    return cmds, tips


def can_auto_install_hfd_deps() -> bool:
    cmds, _tips = hfd_install_plan()
    return bool(cmds)


def run_hfd_deps_install(
    log_cb=None,
    *,
    timeout_per_cmd: int = 600,
) -> tuple[bool, str]:
    """Run install plan commands. Returns (success, summary)."""
    missing_before = missing_hfd_deps()
    if not missing_before:
        return True, "依赖已齐全，无需安装"

    cmds, tips = hfd_install_plan()
    if not cmds:
        msg = "无法自动安装：\n" + ("\n".join(tips) if tips else "未找到包管理器")
        if log_cb:
            log_cb(msg)
        return False, msg

    logs: list[str] = []
    for cmd in cmds:
        line = "$ " + " ".join(cmd)
        logs.append(line)
        if log_cb:
            log_cb(line)
        try:
            run_kwargs: dict = {
                "capture_output": True,
                "text": True,
                "timeout": timeout_per_cmd,
            }
            if platform.system().lower().startswith("win"):
                run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run(cmd, **run_kwargs)
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if out:
                for part in out.splitlines()[-20:]:
                    logs.append(part)
                    if log_cb:
                        log_cb(part)
            if err:
                for part in err.splitlines()[-10:]:
                    logs.append(part)
                    if log_cb:
                        log_cb(part)
            if proc.returncode != 0:
                msg = f"命令失败（退出码 {proc.returncode}）：{' '.join(cmd)}"
                logs.append(msg)
                if log_cb:
                    log_cb(msg)
                # Continue other commands (e.g. git after aria2)
        except subprocess.TimeoutExpired:
            msg = f"命令超时：{' '.join(cmd)}"
            logs.append(msg)
            if log_cb:
                log_cb(msg)
            return False, msg
        except FileNotFoundError:
            msg = f"找不到命令：{cmd[0]}"
            logs.append(msg)
            if log_cb:
                log_cb(msg)
            return False, msg
        except Exception as exc:
            msg = f"执行失败：{exc}"
            logs.append(msg)
            if log_cb:
                log_cb(msg)
            return False, msg

    # PATH may not refresh in current process — re-check which()
    # On Windows, winget installs often need new shell; try common locations.
    _refresh_path_hints()

    missing_after = missing_hfd_deps()
    if not missing_after:
        ok_msg = "安装完成，hfd 依赖已就绪。若仍提示不可用，请完全退出后重开本程序。"
        if log_cb:
            log_cb(ok_msg)
        return True, ok_msg

    tip_txt = "\n".join(tips) if tips else ""
    fail = (
        "安装命令已执行，但仍缺："
        + "、".join(missing_after)
        + "。请关闭本程序后重新打开（刷新 PATH），"
        "或按提示手动安装。\n" + tip_txt
    )
    if log_cb:
        log_cb(fail)
    return False, fail


def _refresh_path_hints() -> None:
    """Append common install dirs so shutil.which can see new binaries."""
    extras: list[str] = []
    system = platform.system().lower()
    if system.startswith("win"):
        extras.extend(
            [
                r"C:\Program Files\Git\bin",
                r"C:\Program Files (x86)\Git\bin",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin"),
                r"C:\ProgramData\chocolatey\bin",
                os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
                r"C:\Program Files\aria2",
            ]
        )
    elif system == "darwin":
        extras.extend(["/opt/homebrew/bin", "/usr/local/bin"])
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep)
    for e in extras:
        if e and e not in parts and os.path.isdir(e):
            parts.insert(0, e)
    os.environ["PATH"] = os.pathsep.join(parts)


def ensure_hfd_executable(script: Path) -> None:
    try:
        mode = script.stat().st_mode
        script.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def download_with_hfd(
    model_id: str,
    save_path: str,
    token: str | None = None,
    endpoint: str | None = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str | None = None,
    threads: int = 8,
    jobs: int = 5,
) -> str:
    """
    Run bundled hfd.sh and stream output to pipe.

    Returns local directory path on success; aborts process on failure.
    """
    from .download_core import _abort_download
    from .hf_hub_env import resolve_hf_endpoint
    from .proxy_env import apply_proxy_env, normalize_proxy

    ok, reason = hfd_availability()
    if not ok:
        _abort_download(pipe, f"hfd 不可用：{reason}")

    script = find_hfd_script()
    bash = find_bash()
    assert script is not None and bash is not None
    ensure_hfd_executable(script)

    tool = "aria2c" if find_aria2c() else "wget"
    resolved_endpoint = resolve_hf_endpoint(endpoint)
    apply_proxy_env(proxy)
    proxy = normalize_proxy(proxy)

    repo_dir = os.path.join(save_path, model_id.split("/")[-1])
    os.makedirs(repo_dir, exist_ok=True)

    cmd = [
        bash,
        str(script),
        model_id,
        "--tool",
        tool,
        "-x",
        str(max(1, min(int(threads), 10))),
        "-j",
        str(max(1, min(int(jobs), 10))),
        "--local-dir",
        repo_dir,
    ]
    if (repo_type or "model").lower() == "dataset":
        cmd.append("--dataset")
    if token:
        cmd.extend(["--hf_token", token])

    env = os.environ.copy()
    env["HF_ENDPOINT"] = resolved_endpoint
    env["HF_TOKEN"] = token or env.get("HF_TOKEN", "")
    # Make aria2c / curl honor proxy when set.
    if proxy:
        env.setdefault("http_proxy", proxy)
        env.setdefault("https_proxy", proxy)
        env.setdefault("HTTP_PROXY", proxy)
        env.setdefault("HTTPS_PROXY", proxy)
        env.setdefault("ALL_PROXY", proxy)

    if pipe:
        pipe.send("下载后端：hfd（gist.github.com/padeoe/…）")
        pipe.send(f"工具：{tool}  bash：{bash}")
        pipe.send(f"脚本：{script}")
        pipe.send(f"Endpoint：{resolved_endpoint}")
        pipe.send(f"保存目录：{repo_dir}")
        pipe.send(f"并发：-x {threads}（单文件连接） -j {jobs}（并行文件）")
        pipe.send(f"命令：{' '.join(cmd[:6])} … --local-dir {repo_dir}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
    except OSError as exc:
        _abort_download(pipe, f"无法启动 hfd：{exc}")

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            if pipe:
                pipe.send(line)
            else:
                print(line, flush=True)
        code = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _abort_download(pipe, "用户已取消下载")

    if code != 0:
        log_hint = os.path.join(repo_dir, ".hfd", "download.log")
        extra = f"（详见 {log_hint}）" if os.path.isfile(log_hint) else ""
        _abort_download(
            pipe,
            f"hfd 下载失败，退出码 {code}{extra}。"
            "可安装/检查 aria2c，或改回 huggingface-hub 后端重试。",
        )

    if pipe:
        pipe.send(f"hfd 下载完成：{repo_dir}")
    return repo_dir
