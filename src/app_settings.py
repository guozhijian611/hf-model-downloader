"""Persist and restore last-used GUI settings."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

ORG_NAME = "guozhijian611"
APP_NAME = "hf-model-downloader"

# Keys stored in QSettings
KEY_PLATFORM = "platform"
KEY_REPO_TYPE = "repo_type"
KEY_REPO_ID = "repo_id"
KEY_SAVE_PATH = "save_path"
KEY_TOKEN = "token"
KEY_ENDPOINT = "endpoint"
KEY_ENDPOINT_FAILOVER = "endpoint_failover"
KEY_PROXY = "proxy"
KEY_PROXY_ENABLED = "proxy_enabled"
KEY_AUTO_RETRY = "auto_retry"
KEY_RETRY_WAIT_SEC = "retry_wait_sec"
KEY_DOWNLOAD_BACKEND = "download_backend"
KEY_STALL_RESTART = "stall_restart"
KEY_STALL_TIMEOUT_SEC = "stall_timeout_sec"
KEY_STALL_RESTART_CMD = "stall_restart_command"
KEY_HUB_MAX_WORKERS = "hub_max_workers"
KEY_HFD_THREADS = "hfd_threads"
KEY_HFD_JOBS = "hfd_jobs"
KEY_NET_MONITOR_EXPANDED = "net_monitor_expanded"
KEY_NET_MONITOR_IFACE = "net_monitor_iface"
KEY_NET_MONITOR_HISTORY = "net_monitor_history_sec"
KEY_FILE_PROGRESS_EXPANDED = "file_progress_expanded"
KEY_MONITOR_WINDOW_OPEN = "monitor_window_open"


def get_settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def load_form_settings() -> dict:
    """Load last form values. Missing keys use sensible defaults."""
    s = get_settings()
    return {
        KEY_PLATFORM: s.value(KEY_PLATFORM, "Hugging Face", type=str),
        KEY_REPO_TYPE: s.value(KEY_REPO_TYPE, "Model", type=str),
        KEY_REPO_ID: s.value(KEY_REPO_ID, "", type=str),
        KEY_SAVE_PATH: s.value(KEY_SAVE_PATH, "", type=str),
        KEY_TOKEN: s.value(KEY_TOKEN, "", type=str),
        KEY_ENDPOINT: s.value(KEY_ENDPOINT, "https://hf-mirror.com", type=str),
        KEY_ENDPOINT_FAILOVER: s.value(KEY_ENDPOINT_FAILOVER, True, type=bool),
        KEY_PROXY: s.value(KEY_PROXY, "", type=str),
        KEY_PROXY_ENABLED: s.value(KEY_PROXY_ENABLED, False, type=bool),
        KEY_AUTO_RETRY: s.value(KEY_AUTO_RETRY, True, type=bool),
        KEY_RETRY_WAIT_SEC: s.value(KEY_RETRY_WAIT_SEC, 5, type=int),
        KEY_DOWNLOAD_BACKEND: s.value(
            KEY_DOWNLOAD_BACKEND, "huggingface-hub", type=str
        ),
        KEY_STALL_RESTART: s.value(KEY_STALL_RESTART, True, type=bool),
        KEY_STALL_TIMEOUT_SEC: s.value(KEY_STALL_TIMEOUT_SEC, 120, type=int),
        KEY_STALL_RESTART_CMD: s.value(KEY_STALL_RESTART_CMD, "", type=str),
        KEY_HUB_MAX_WORKERS: s.value(KEY_HUB_MAX_WORKERS, 8, type=int),
        KEY_HFD_THREADS: s.value(KEY_HFD_THREADS, 8, type=int),
        KEY_HFD_JOBS: s.value(KEY_HFD_JOBS, 5, type=int),
        KEY_NET_MONITOR_EXPANDED: s.value(KEY_NET_MONITOR_EXPANDED, True, type=bool),
        KEY_NET_MONITOR_IFACE: s.value(KEY_NET_MONITOR_IFACE, "", type=str),
        KEY_NET_MONITOR_HISTORY: s.value(KEY_NET_MONITOR_HISTORY, 180, type=int),
        KEY_FILE_PROGRESS_EXPANDED: s.value(
            KEY_FILE_PROGRESS_EXPANDED, True, type=bool
        ),
        KEY_MONITOR_WINDOW_OPEN: s.value(KEY_MONITOR_WINDOW_OPEN, False, type=bool),
    }


def save_form_settings(
    *,
    platform: str,
    repo_type: str,
    repo_id: str,
    save_path: str,
    token: str,
    endpoint: str,
    proxy: str,
    proxy_enabled: bool,
    auto_retry: bool = True,
    retry_wait_sec: int = 5,
    endpoint_failover: bool = True,
    download_backend: str = "huggingface-hub",
    stall_restart: bool = True,
    stall_timeout_sec: int = 120,
    stall_restart_command: str = "",
    hub_max_workers: int = 8,
    hfd_threads: int = 8,
    hfd_jobs: int = 5,
    net_monitor_expanded: bool = True,
    net_monitor_iface: str = "",
    net_monitor_history_sec: int = 180,
    file_progress_expanded: bool = True,
    monitor_window_open: bool = False,
) -> None:
    s = get_settings()
    s.setValue(KEY_PLATFORM, platform)
    s.setValue(KEY_REPO_TYPE, repo_type)
    s.setValue(KEY_REPO_ID, repo_id)
    s.setValue(KEY_SAVE_PATH, save_path)
    s.setValue(KEY_TOKEN, token)
    s.setValue(KEY_ENDPOINT, endpoint)
    s.setValue(KEY_ENDPOINT_FAILOVER, endpoint_failover)
    s.setValue(KEY_PROXY, proxy)
    s.setValue(KEY_PROXY_ENABLED, proxy_enabled)
    s.setValue(KEY_AUTO_RETRY, auto_retry)
    s.setValue(KEY_RETRY_WAIT_SEC, int(retry_wait_sec))
    s.setValue(KEY_DOWNLOAD_BACKEND, download_backend)
    s.setValue(KEY_STALL_RESTART, stall_restart)
    s.setValue(KEY_STALL_TIMEOUT_SEC, int(stall_timeout_sec))
    s.setValue(KEY_STALL_RESTART_CMD, stall_restart_command or "")
    s.setValue(KEY_HUB_MAX_WORKERS, int(hub_max_workers))
    s.setValue(KEY_HFD_THREADS, int(hfd_threads))
    s.setValue(KEY_HFD_JOBS, int(hfd_jobs))
    s.setValue(KEY_NET_MONITOR_EXPANDED, bool(net_monitor_expanded))
    s.setValue(KEY_NET_MONITOR_IFACE, net_monitor_iface or "")
    s.setValue(KEY_NET_MONITOR_HISTORY, int(net_monitor_history_sec))
    s.setValue(KEY_FILE_PROGRESS_EXPANDED, bool(file_progress_expanded))
    s.setValue(KEY_MONITOR_WINDOW_OPEN, bool(monitor_window_open))
    s.sync()
