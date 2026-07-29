"""Online update check and in-place installer for GitHub Releases."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from .proxy_env import (
    is_socks_proxy,
    normalize_proxy,
    proxies_dict,
    socks_support_available,
)
from .version import get_app_version, is_remote_newer, normalize_version

logger = logging.getLogger(__name__)

GITHUB_OWNER = "guozhijian611"
GITHUB_REPO = "hf-model-downloader"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
# (connect timeout, read timeout) — avoid hanging forever on bad networks/proxies.
DEFAULT_TIMEOUT = (10, 20)
DOWNLOAD_TIMEOUT = (15, 60)


def _http_get(
    url: str,
    *,
    proxy: str | None = None,
    timeout=DEFAULT_TIMEOUT,
    headers: dict | None = None,
    stream: bool = False,
):
    """GET with optional proxy.

    ``trust_env`` must be set on Session (not passed to get()) — passing it to
    ``requests.get`` raises TypeError on modern requests and silently kills the
    update-check worker thread.
    """
    proxy = normalize_proxy(proxy)
    session = requests.Session()
    # Only honor system HTTP(S)_PROXY when the user explicitly set an app proxy.
    # Otherwise a broken env proxy can hang/fail GitHub checks with no UI feedback.
    session.trust_env = bool(proxy)
    return session.get(
        url,
        headers=headers or {},
        timeout=timeout,
        proxies=proxies_dict(proxy),
        stream=stream,
    )


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int = 0


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    release_url: str
    release_name: str | None
    update_available: bool
    message: str
    error: str | None = None
    asset: ReleaseAsset | None = None
    assets: tuple[ReleaseAsset, ...] = field(default_factory=tuple)


def _system_arch() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine in ("x86_64", "amd64"):
        arch = "x86_64"
    else:
        arch = machine
    return system, arch


def preferred_asset_name(
    system: str | None = None, arch: str | None = None
) -> str | None:
    """Return the expected release asset filename for this platform."""
    system = (system or platform.system()).lower()
    if arch is None:
        _, arch = _system_arch()
    if system.startswith("win"):
        return "hf-model-downloader-windows-x86_64.zip"
    if system == "darwin":
        if arch == "arm64":
            return "hf-model-downloader-arm64.dmg"
        return "hf-model-downloader-x86_64.dmg"
    return None


def pick_release_asset(assets: list[dict]) -> ReleaseAsset | None:
    """Pick the best matching install asset from a GitHub release assets list."""
    want = preferred_asset_name()
    parsed: list[ReleaseAsset] = []
    for item in assets:
        name = item.get("name") or ""
        url = item.get("browser_download_url") or ""
        if not name or not url:
            continue
        parsed.append(
            ReleaseAsset(name=name, download_url=url, size=int(item.get("size") or 0))
        )

    if not parsed:
        return None
    if want:
        for asset in parsed:
            if asset.name == want:
                return asset
        # Loose match by keywords
        system, arch = _system_arch()
        for asset in parsed:
            lower = asset.name.lower()
            if (
                system.startswith("win")
                and lower.endswith(".zip")
                and "windows" in lower
            ):
                return asset
            if system == "darwin" and lower.endswith(".dmg") and arch in lower:
                return asset
    return None


def check_for_update(
    proxy: str | None = None,
    timeout=DEFAULT_TIMEOUT,
) -> UpdateCheckResult:
    """Query GitHub for the latest release and compare with the local version."""
    current = normalize_version(get_app_version())
    proxy = normalize_proxy(proxy)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"hf-model-downloader/{current}",
    }

    if proxy and is_socks_proxy(proxy) and not socks_support_available():
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=RELEASES_PAGE_URL,
            release_name=None,
            update_available=False,
            message=(
                "检查更新失败：缺少 SOCKS 依赖（PySocks）。"
                "请安装含 PySocks 的新版本，或改用 http:// 代理。"
            ),
            error="missing_socks",
        )

    try:
        response = _http_get(
            LATEST_RELEASE_API,
            proxy=proxy,
            timeout=timeout,
            headers=headers,
        )
        if response.status_code == 404:
            return UpdateCheckResult(
                current_version=current,
                latest_version=None,
                release_url=RELEASES_PAGE_URL,
                release_name=None,
                update_available=False,
                message=(
                    f"当前版本 v{current}。远程尚未发布 Release，无法判断是否有新版本。"
                ),
            )
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=RELEASES_PAGE_URL,
            release_name=None,
            update_available=False,
            message="检查更新超时，请检查网络或代理后重试。",
            error="timeout",
        )
    except requests.RequestException as exc:
        err = str(exc)
        if "SOCKS" in err.upper() or "socks" in err.lower():
            err = (
                f"{err}\n"
                "提示：使用 socks5 代理需要 PySocks。"
                "请更新到最新安装包，或改用 http://127.0.0.1:端口 形式代理。"
            )
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=RELEASES_PAGE_URL,
            release_name=None,
            update_available=False,
            message=f"检查更新失败：{err}",
            error=str(exc),
        )
    except ValueError as exc:
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=RELEASES_PAGE_URL,
            release_name=None,
            update_available=False,
            message=f"解析更新信息失败：{exc}",
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected error during update check")
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=RELEASES_PAGE_URL,
            release_name=None,
            update_available=False,
            message=f"检查更新失败：{exc}",
            error=str(exc),
        )

    tag = normalize_version(data.get("tag_name") or data.get("name") or "")
    html_url = data.get("html_url") or RELEASES_PAGE_URL
    release_name = data.get("name") or data.get("tag_name")
    raw_assets = data.get("assets") or []
    assets = tuple(
        ReleaseAsset(
            name=a.get("name") or "",
            download_url=a.get("browser_download_url") or "",
            size=int(a.get("size") or 0),
        )
        for a in raw_assets
        if a.get("name") and a.get("browser_download_url")
    )
    asset = pick_release_asset(raw_assets)

    if not tag:
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=html_url,
            release_name=release_name,
            update_available=False,
            message="远程 Release 缺少版本号，无法比较。",
            error="missing_tag",
            assets=assets,
        )

    if is_remote_newer(current, tag):
        if asset:
            msg = (
                f"发现新版本：v{tag}（当前 v{current}）。"
                f"可自动下载安装包 {asset.name} 并替换当前程序。"
            )
        else:
            msg = (
                f"发现新版本：v{tag}（当前 v{current}），"
                "但未找到适合本机系统的安装包，请手动到 Releases 下载。"
            )
        return UpdateCheckResult(
            current_version=current,
            latest_version=tag,
            release_url=html_url,
            release_name=release_name,
            update_available=True,
            message=msg,
            asset=asset,
            assets=assets,
        )

    return UpdateCheckResult(
        current_version=current,
        latest_version=tag,
        release_url=html_url,
        release_name=release_name,
        update_available=False,
        message=f"已是最新版本（v{current}）。",
        asset=asset,
        assets=assets,
    )


def is_frozen_install() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_install_root() -> Path:
    """Directory that should be replaced by an update (onedir / .app contents root)."""
    if not is_frozen_install():
        return Path.cwd()
    exe = Path(sys.executable).resolve()
    # macOS app bundle: .../Foo.app/Contents/MacOS/executable
    parts = exe.parts
    if ".app" in exe.suffixes or any(p.endswith(".app") for p in parts):
        for parent in exe.parents:
            if parent.name.endswith(".app"):
                return parent
    return exe.parent


def get_launch_target(install_root: Path) -> Path:
    """Executable / .app path to relaunch after update."""
    if install_root.name.endswith(".app"):
        return install_root
    system = platform.system().lower()
    if system.startswith("win"):
        candidates = list(install_root.glob("*.exe"))
        # Prefer main app exe names
        for name in (
            "hf-model-downloader-windows-x86_64.exe",
            "hf-model-downloader.exe",
        ):
            path = install_root / name
            if path.is_file():
                return path
        if candidates:
            return candidates[0]
    # macOS onedir or linux binary
    for name in (
        "hf-model-downloader",
        "hf-model-downloader-macos-arm64",
        "hf-model-downloader-macos-x86_64",
    ):
        path = install_root / name
        if path.is_file():
            return path
    return install_root / Path(sys.executable).name


def download_file(
    url: str,
    dest: Path,
    proxy: str | None = None,
    timeout=DOWNLOAD_TIMEOUT,
    progress_cb=None,
) -> None:
    headers = {"User-Agent": f"hf-model-downloader/{get_app_version()}"}
    with _http_get(
        url,
        proxy=proxy,
        timeout=timeout,
        headers=headers,
        stream=True,
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if progress_cb:
                    if total:
                        progress_cb(done, total)
                    elif done % (1024 * 1024) < 256 * 1024:
                        # No Content-Length: still emit coarse progress.
                        progress_cb(done, max(done, 1))


def _extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract zip and return the root directory that contains the app files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    # Common layout: <dir>/hf-model-downloader-windows-x86_64/...
    children = [p for p in dest_dir.iterdir() if p.name not in (".", "..")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    # Or files extracted directly into dest_dir
    return dest_dir


def _find_app_in_dmg_mount(mount_point: Path) -> Path | None:
    apps = list(mount_point.glob("*.app"))
    if apps:
        return apps[0]
    for path in mount_point.rglob("*.app"):
        return path
    return None


def _extract_dmg(dmg_path: Path, dest_dir: Path) -> Path:
    """Mount dmg, copy .app (or onedir) to dest_dir, detach, return copied path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    attach = subprocess.run(
        ["hdiutil", "attach", str(dmg_path), "-nobrowse", "-readonly"],
        check=True,
        capture_output=True,
        text=True,
    )
    # hdiutil table output ends with the mount point path.
    mount_point = None
    for line in attach.stdout.splitlines():
        if "/Volumes/" in line:
            mount_point = Path(line[line.index("/Volumes/") :].strip())
    if mount_point is None or not mount_point.exists():
        raise RuntimeError("无法挂载 DMG 安装包")

    try:
        app = _find_app_in_dmg_mount(mount_point)
        if app is not None:
            target = dest_dir / app.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(app, target, symlinks=True)
            return target
        # Copy whole volume contents as fallback
        target = dest_dir / "payload"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(mount_point, target, symlinks=True)
        return target
    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount_point), "-quiet"],
            check=False,
            capture_output=True,
            text=True,
        )


def _windows_update_log_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    log_dir = Path(local) / "hf-model-downloader" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "update.log"


def _write_windows_updater(
    staging_dir: Path,
    install_root: Path,
    launch_target: Path,
    app_pid: int | None = None,
) -> Path:
    """Write a robust ASCII .bat that waits for the app PID, copies files, restarts."""
    script = Path(tempfile.gettempdir()) / "hf_model_downloader_update.bat"
    log_path = _windows_update_log_path()
    pid = app_pid or os.getpid()

    # Keep the bat pure ASCII (cmd.exe default code page is often not UTF-8).
    staging = str(staging_dir)
    install = str(install_root)
    launch = str(launch_target)
    log = str(log_path)

    lines = [
        "@echo off",
        "setlocal EnableExtensions",
        f'set "LOG={log}"',
        f'set "STAGING={staging}"',
        f'set "INSTALL={install}"',
        f'set "LAUNCH={launch}"',
        f"set APP_PID={pid}",
        'echo ==== update start %DATE% %TIME% ====>>"%LOG%"',
        'echo STAGING=%STAGING%>>"%LOG%"',
        'echo INSTALL=%INSTALL%>>"%LOG%"',
        'echo LAUNCH=%LAUNCH%>>"%LOG%"',
        'echo APP_PID=%APP_PID%>>"%LOG%"',
        "echo Waiting for app PID %APP_PID% to exit...",
        'echo Waiting for PID %APP_PID%>>"%LOG%"',
        ":wait_loop",
        'tasklist /FI "PID eq %APP_PID%" 2>NUL | findstr /I "%APP_PID%" >NUL',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >NUL",
        "  goto wait_loop",
        ")",
        "timeout /t 1 /nobreak >NUL",
        'echo App exited, copying files...>>"%LOG%"',
        "echo Applying update files...",
        # /E copy subdirs; /IS /IT include same/tweaked; retries help with locks
        (
            'robocopy "%STAGING%" "%INSTALL%" /E /IS /IT /R:5 /W:2 '
            '/NFL /NDL /NJH /NJS /nc /ns /np >>"%LOG%" 2>&1'
        ),
        "set RC=%ERRORLEVEL%",
        'echo robocopy exit=%RC%>>"%LOG%"',
        # robocopy: 0-7 success-ish, >=8 failure
        "if %RC% GEQ 8 (",
        '  echo COPY FAILED rc=%RC%>>"%LOG%"',
        "  echo Update copy failed with code %RC%",
        "  echo See log: %LOG%",
        "  pause",
        "  exit /b %RC%",
        ")",
        'echo Restarting app...>>"%LOG%"',
        'if not exist "%LAUNCH%" (',
        '  echo Launch target missing: %LAUNCH%>>"%LOG%"',
        "  echo Launch target not found:",
        "  echo %LAUNCH%",
        "  pause",
        "  exit /b 2",
        ")",
        'start "" "%LAUNCH%"',
        'echo started ok>>"%LOG%"',
        "endlocal",
        'del "%~f0" >NUL 2>&1',
        "exit /b 0",
        "",
    ]
    # Write as ANSI/UTF-8 without requiring Chinese — ASCII only content.
    script.write_text("\r\n".join(lines), encoding="utf-8")
    return script


def _write_posix_updater(
    staging_dir: Path,
    install_root: Path,
    launch_target: Path,
) -> Path:
    script = Path(tempfile.gettempdir()) / "hf_model_downloader_update.sh"
    if install_root.name.endswith(".app"):
        # Replace whole .app bundle
        body = f"""#!/bin/bash
set -e
sleep 2
echo "Applying update..."
rm -rf "{install_root}"
cp -R "{staging_dir}" "{install_root}"
chmod -R u+rwX "{install_root}" || true
echo "Restarting..."
open "{launch_target}"
rm -f "$0"
"""
    else:
        body = f"""#!/bin/bash
set -e
sleep 2
echo "Applying update..."
# Copy new files over the install directory
rsync -a --delete "{staging_dir}/" "{install_root}/" 2>/dev/null || \\
  (cp -R "{staging_dir}/." "{install_root}/")
chmod -R u+rwX "{install_root}" || true
echo "Restarting..."
if [[ "{launch_target}" == *.app ]]; then
  open "{launch_target}"
else
  nohup "{launch_target}" >/dev/null 2>&1 &
fi
rm -f "$0"
"""
    script.write_text(body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def apply_update_package(
    package_path: Path,
    proxy: str | None = None,
    progress_cb=None,
) -> Path:
    """
    Prepare an extracted update and return the path to an updater script.

    Caller should launch the script and quit the running application so files
    can be replaced.
    """
    if not is_frozen_install():
        raise RuntimeError("开发模式不支持自动替换，请重新打包安装或手动更新。")

    install_root = get_install_root()
    work = Path(tempfile.mkdtemp(prefix="hfmd-update-"))
    suffix = package_path.suffix.lower()

    if progress_cb:
        progress_cb("正在解压安装包...")

    if suffix == ".zip":
        staging = _extract_zip(package_path, work / "extracted")
    elif suffix == ".dmg":
        staging = _extract_dmg(package_path, work / "extracted")
    else:
        raise RuntimeError(f"不支持的安装包格式：{suffix}")

    # Decide install target + relaunch path after replacement.
    if staging.name.endswith(".app"):
        # Replace the .app bundle itself when possible.
        if install_root.name.endswith(".app"):
            target_root = install_root
        else:
            target_root = install_root / staging.name
        final_launch = target_root
        copy_source = staging
    else:
        target_root = install_root
        staged_launch = get_launch_target(staging)
        try:
            final_launch = target_root / staged_launch.relative_to(staging)
        except ValueError:
            final_launch = target_root / staged_launch.name
        copy_source = staging

    if progress_cb:
        progress_cb("正在生成更新脚本...")

    system = platform.system().lower()
    if system.startswith("win"):
        script = _write_windows_updater(
            copy_source,
            target_root,
            final_launch,
            app_pid=os.getpid(),
        )
        logger.info(
            "Windows updater ready script=%s staging=%s install=%s launch=%s pid=%s",
            script,
            copy_source,
            target_root,
            final_launch,
            os.getpid(),
        )
        return script
    return _write_posix_updater(copy_source, target_root, final_launch)


def download_and_prepare_update(
    asset: ReleaseAsset,
    proxy: str | None = None,
    progress_cb=None,
) -> Path:
    """Download asset and prepare updater script; return script path."""
    if progress_cb:
        progress_cb(f"正在下载 {asset.name} ...")

    tmp_dir = Path(tempfile.mkdtemp(prefix="hfmd-dl-"))
    package_path = tmp_dir / asset.name

    def _dl_progress(done: int, total: int) -> None:
        if progress_cb and total:
            pct = int(done * 100 / total)
            progress_cb(f"正在下载 {asset.name} ... {pct}%")

    download_file(
        asset.download_url,
        package_path,
        proxy=proxy,
        progress_cb=_dl_progress,
    )
    if progress_cb:
        progress_cb("下载完成，正在准备安装...")
    return apply_update_package(package_path, proxy=proxy, progress_cb=progress_cb)


def launch_updater_and_exit(script_path: Path) -> None:
    """Start the updater script in a detached process (caller should then exit)."""
    script_path = Path(script_path).resolve()
    if not script_path.is_file():
        raise FileNotFoundError(f"更新脚本不存在：{script_path}")

    system = platform.system().lower()
    logger.info("Launching updater script: %s", script_path)

    if system.startswith("win"):
        # DETACHED_PROCESS + cmd /c is unreliable. Use `start` so the updater
        # outlives this process even after we force-exit.
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        # start "" "path\to\script.bat"
        cmd = f'start "hf-update" /min cmd.exe /c ""{script_path}""'
        subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(script_path.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=create_no_window,
            close_fds=False,
        )
    else:
        subprocess.Popen(
            ["/bin/bash", str(script_path)],
            start_new_session=True,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    logger.info("Updater process spawned")


class UpdateCheckWorker(QThread):
    """Background worker so the UI stays responsive while checking updates."""

    finished_result = pyqtSignal(object)

    def __init__(self, proxy: str | None = None, parent=None):
        super().__init__(parent)
        self.proxy = proxy

    def run(self):
        try:
            result = check_for_update(proxy=self.proxy)
        except Exception as exc:
            logger.exception("UpdateCheckWorker crashed")
            current = normalize_version(get_app_version())
            result = UpdateCheckResult(
                current_version=current,
                latest_version=None,
                release_url=RELEASES_PAGE_URL,
                release_name=None,
                update_available=False,
                message=f"检查更新失败：{exc}",
                error=str(exc),
            )
        self.finished_result.emit(result)


class UpdateApplyWorker(QThread):
    """Download package and prepare in-place replacement."""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(str)  # updater script path
    failed = pyqtSignal(str)

    def __init__(self, asset: ReleaseAsset, proxy: str | None = None, parent=None):
        super().__init__(parent)
        self.asset = asset
        self.proxy = proxy

    def run(self):
        try:
            script = download_and_prepare_update(
                self.asset,
                proxy=self.proxy,
                progress_cb=self.progress.emit,
            )
            self.finished_ok.emit(str(script))
        except Exception as exc:
            self.failed.emit(str(exc))
