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
