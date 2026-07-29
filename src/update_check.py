"""Online update check against GitHub Releases."""

from __future__ import annotations

from dataclasses import dataclass

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from .proxy_env import normalize_proxy, proxies_dict
from .version import get_app_version, is_remote_newer, normalize_version

GITHUB_OWNER = "guozhijian611"
GITHUB_REPO = "hf-model-downloader"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
DEFAULT_TIMEOUT_SEC = 15


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    release_url: str
    release_name: str | None
    update_available: bool
    message: str
    error: str | None = None


def check_for_update(
    proxy: str | None = None,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> UpdateCheckResult:
    """Query GitHub for the latest release and compare with the local version."""
    current = normalize_version(get_app_version())
    proxy = normalize_proxy(proxy)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"hf-model-downloader/{current}",
    }

    try:
        response = requests.get(
            LATEST_RELEASE_API,
            headers=headers,
            timeout=timeout_sec,
            proxies=proxies_dict(proxy),
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
                error=None,
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
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=RELEASES_PAGE_URL,
            release_name=None,
            update_available=False,
            message=f"检查更新失败：{exc}",
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

    tag = normalize_version(data.get("tag_name") or data.get("name") or "")
    html_url = data.get("html_url") or RELEASES_PAGE_URL
    release_name = data.get("name") or data.get("tag_name")

    if not tag:
        return UpdateCheckResult(
            current_version=current,
            latest_version=None,
            release_url=html_url,
            release_name=release_name,
            update_available=False,
            message="远程 Release 缺少版本号，无法比较。",
            error="missing_tag",
        )

    if is_remote_newer(current, tag):
        return UpdateCheckResult(
            current_version=current,
            latest_version=tag,
            release_url=html_url,
            release_name=release_name,
            update_available=True,
            message=(
                f"发现新版本：v{tag}（当前 v{current}）。"
                "可前往 GitHub Releases 下载安装包。"
            ),
        )

    return UpdateCheckResult(
        current_version=current,
        latest_version=tag,
        release_url=html_url,
        release_name=release_name,
        update_available=False,
        message=f"已是最新版本（v{current}）。",
    )


class UpdateCheckWorker(QThread):
    """Background worker so the UI stays responsive while checking updates."""

    finished_result = pyqtSignal(object)

    def __init__(self, proxy: str | None = None, parent=None):
        super().__init__(parent)
        self.proxy = proxy

    def run(self):
        result = check_for_update(proxy=self.proxy)
        self.finished_result.emit(result)
