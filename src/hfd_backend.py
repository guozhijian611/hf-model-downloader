"""Optional hfd (aria2/wget) download backend.

Script source: https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f
Bundled at scripts/hfd.sh — users can choose this backend in the GUI when
downloading from Hugging Face (not ModelScope).
"""

from __future__ import annotations

import os
import platform
import re
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


def tools_bin_dir() -> Path:
    """User-local tools dir for portable deps (no admin / no winget)."""
    if platform.system().lower().startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        root = base / "hf-model-downloader" / "tools"
    else:
        root = Path.home() / ".hf-model-downloader" / "tools"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root


def find_aria2c() -> str | None:
    found = shutil.which("aria2c") or shutil.which("aria2c.exe")
    if found:
        return found
    # Portable install from one-click button
    for name in ("aria2c.exe", "aria2c"):
        p = tools_bin_dir() / name
        if p.is_file():
            return str(p)
    # Nested extract folders
    try:
        for p in tools_bin_dir().rglob("aria2c.exe"):
            return str(p)
        for p in tools_bin_dir().rglob("aria2c"):
            if p.is_file():
                return str(p)
    except OSError:
        pass
    return None


def find_wget() -> str | None:
    return shutil.which("wget") or shutil.which("wget.exe")


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


# Sentinel argv for portable aria2 zip install (no winget/choco/scoop).
_PORTABLE_ARIA2_CMD = ["__portable_aria2_windows__"]
ARIA2_RELEASES_API = "https://api.github.com/repos/aria2/aria2/releases/latest"
GIT_FOR_WINDOWS_URL = "https://git-scm.com/download/win"


def hfd_install_plan() -> tuple[list[list[str]], list[str]]:
    """Return (shell commands as argv lists, manual tips) to install missing deps.

    Windows without winget: download official portable aria2 zip into
    %LOCALAPPDATA%\\hf-model-downloader\\tools (no admin required).
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
                cmds.append(list(_PORTABLE_ARIA2_CMD))
                tips.append(
                    "未检测到 winget/scoop/choco：将下载官方便携版 aria2 到\n"
                    f"{tools_bin_dir()}\n"
                    "（无需管理员权限；仅当前用户可用）"
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
        elif shutil.which("scoop"):
            cmds.append(["scoop", "install", "git"])
        else:
            tips.append(
                "Windows 还需 bash（hfd.sh 依赖）：\n"
                f"请安装 Git for Windows：{GIT_FOR_WINDOWS_URL}\n"
                "安装时勾选 Git from the command line，装完重启本程序。\n"
                "（无 winget 时无法静默安装 Git，需手动安装）"
            )

    if not find_hfd_script():
        tips.append("未找到内置 hfd.sh，请重新安装/解压本程序完整包")

    if not cmds and not tips and missing_hfd_deps():
        tips.append("请手动安装缺失依赖后重启本程序")

    return cmds, tips


def can_auto_install_hfd_deps() -> bool:
    """True if something can be installed automatically (incl. portable aria2)."""
    cmds, _tips = hfd_install_plan()
    return bool(cmds)


def install_portable_aria2_windows(log_cb=None) -> tuple[bool, str]:
    """Download official win64 aria2 zip into tools_bin_dir()."""
    if not platform.system().lower().startswith("win"):
        return False, "便携 aria2 安装仅支持 Windows"

    def _log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    try:
        import json
        import zipfile
        from urllib.request import Request, urlopen
    except ImportError as exc:
        return False, f"缺少解压/下载库：{exc}"

    dest = tools_bin_dir()
    _log(f"准备下载便携版 aria2 → {dest}")

    zip_url = None
    zip_name = "aria2-win-64bit.zip"
    try:
        req = Request(
            ARIA2_RELEASES_API,
            headers={
                "User-Agent": "hf-model-downloader",
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        for asset in data.get("assets") or []:
            name = asset.get("name") or ""
            url = asset.get("browser_download_url") or ""
            if "win-64bit" in name.lower() and name.lower().endswith(".zip") and url:
                zip_url = url
                zip_name = name
                break
    except Exception as exc:
        _log(f"读取 GitHub Releases 失败，使用固定版本链接：{exc}")

    if not zip_url:
        zip_name = "aria2-1.37.0-win-64bit-build1.zip"
        zip_url = (
            "https://github.com/aria2/aria2/releases/download/release-1.37.0/"
            + zip_name
        )

    zip_path = dest / zip_name
    try:
        _log(f"下载：{zip_url}")
        req = Request(zip_url, headers={"User-Agent": "hf-model-downloader"})
        with urlopen(req, timeout=120) as resp, zip_path.open("wb") as fh:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
        _log(f"已保存：{zip_path}（{zip_path.stat().st_size} bytes）")
    except Exception as exc:
        return False, f"下载 aria2 失败：{exc}"

    extract_dir = dest / "aria2-portable"
    try:
        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        _log(f"已解压到：{extract_dir}")
    except Exception as exc:
        return False, f"解压 aria2 失败：{exc}"

    exe = None
    for p in extract_dir.rglob("aria2c.exe"):
        exe = p
        break
    if not exe:
        return False, "压缩包中未找到 aria2c.exe"

    target = dest / "aria2c.exe"
    try:
        shutil.copy2(exe, target)
        _log(f"aria2c 已就绪：{target}")
    except OSError:
        target = exe
        _log(f"使用解压路径中的 aria2c：{target}")

    tools = str(dest)
    path = os.environ.get("PATH", "")
    if tools not in path.split(os.pathsep):
        os.environ["PATH"] = tools + os.pathsep + path
    _refresh_path_hints()

    if find_aria2c():
        return True, f"便携 aria2 安装成功：{find_aria2c()}"
    return False, f"已解压但仍检测不到 aria2c，请检查 {target}"


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

    for cmd in cmds:
        if cmd == _PORTABLE_ARIA2_CMD or (
            len(cmd) == 1 and cmd[0] == _PORTABLE_ARIA2_CMD[0]
        ):
            if log_cb:
                log_cb("使用便携包安装 aria2（无需 winget）…")
            ok, summary = install_portable_aria2_windows(log_cb=log_cb)
            if log_cb:
                log_cb(summary)
            continue

        line = "$ " + " ".join(cmd)
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
            if out and log_cb:
                for part in out.splitlines()[-20:]:
                    log_cb(part)
            if err and log_cb:
                for part in err.splitlines()[-10:]:
                    log_cb(part)
            if proc.returncode != 0 and log_cb:
                log_cb(f"命令失败（退出码 {proc.returncode}）：{' '.join(cmd)}")
        except subprocess.TimeoutExpired:
            msg = f"命令超时：{' '.join(cmd)}"
            if log_cb:
                log_cb(msg)
            return False, msg
        except FileNotFoundError:
            msg = f"找不到命令：{cmd[0]}"
            if log_cb:
                log_cb(msg)
            if cmd[0].lower() in ("winget", "choco", "scoop") and not find_aria2c():
                if log_cb:
                    log_cb("包管理器不可用，回退便携 aria2…")
                install_portable_aria2_windows(log_cb=log_cb)
            continue
        except Exception as exc:
            msg = f"执行失败：{exc}"
            if log_cb:
                log_cb(msg)
            return False, msg

    _refresh_path_hints()

    missing_after = missing_hfd_deps()
    if not missing_after:
        ok_msg = "安装完成，hfd 依赖已就绪。若仍提示不可用，请完全退出后重开本程序。"
        if log_cb:
            log_cb(ok_msg)
        return True, ok_msg

    only_bash = len(missing_after) == 1 and "bash" in missing_after[0].lower()
    tip_txt = "\n".join(tips) if tips else ""
    if only_bash and find_aria2c():
        fail = (
            "aria2 已就绪，但仍缺少 bash。\n"
            f"请安装 Git for Windows：{GIT_FOR_WINDOWS_URL}\n"
            "装完后重启本程序，再选 hfd 下载。\n" + tip_txt
        )
        if log_cb:
            log_cb(fail)
        return False, fail

    fail = (
        "安装步骤已执行，但仍缺："
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
                str(tools_bin_dir()),
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
        if e and e not in parts and (os.path.isdir(e) or e == str(tools_bin_dir())):
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
        for raw in proc.stdout:
            # hfd uses \r + ANSI; normalize for UI/monitor parsing.
            line = _normalize_hfd_output_line(raw)
            if not line:
                continue
            if pipe:
                for msg in _hfd_progress_messages(line):
                    pipe.send(msg)
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


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]")
# [ 14%]  400/10755 files | 5.56G/39.9G | 10.7M/s | ETA 05:12
_HFD_PROGRESS_RE = re.compile(
    r"\[\s*(?P<pct>\d+)%\]\s*"
    r"(?P<dfiles>\d+)\s*/\s*(?P<tfiles>\d+)\s+files\s*\|"
    r"\s*(?P<done>[\d.,]+\s*[kKmMgGtTpP]?i?B?)"
    r"\s*/\s*"
    r"(?P<total>[\d.,]+\s*[kKmMgGtTpP]?i?B?)"
    r"(?:\s*\|\s*(?P<rate>[\d.,]+\s*[kKmMgGtTpP]?i?B?)\s*/s)?",
    re.IGNORECASE,
)
_HFD_LISTED_RE = re.compile(
    r"Listed\s+(?P<n>\d+)\s+files",
    re.IGNORECASE,
)


def _normalize_hfd_output_line(raw: str) -> str:
    """Strip CR/ANSI so progress lines become parseable single lines."""
    if not raw:
        return ""
    text = raw.replace("\r", "\n")
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        return ""
    return _ANSI_RE.sub("", parts[-1]).strip()


def _hfd_progress_messages(line: str) -> list[str]:
    """Map hfd status lines to messages the monitor progress tracker understands."""
    out: list[str] = []
    m = _HFD_LISTED_RE.search(line)
    if m:
        out.append(f"[HF_META]\tfiles\t{m.group('n')}")
        return out
    m = _HFD_PROGRESS_RE.search(line)
    if not m:
        return out
    pct = m.group("pct")
    done = m.group("done").replace(" ", "")
    total = m.group("total").replace(" ", "")
    rate = (m.group("rate") or "").replace(" ", "")
    dfiles = m.group("dfiles")
    tfiles = m.group("tfiles")
    out.append(f"[HF_META]\tfiles\t{tfiles}")
    out.append(f"[HF_META]\tdone_files\t{dfiles}")
    # tqdm-style overall line (same parser as hub incomplete total)
    human = f"Downloading (hfd total...):  {pct}%| | {done}/{total}"
    if rate:
        human += f" [{rate}/s]"
    out.append(human)
    return out
