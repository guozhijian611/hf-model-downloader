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
KEY_PROXY = "proxy"
KEY_PROXY_ENABLED = "proxy_enabled"
KEY_AUTO_RETRY = "auto_retry"


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
        KEY_PROXY: s.value(KEY_PROXY, "", type=str),
        KEY_PROXY_ENABLED: s.value(KEY_PROXY_ENABLED, False, type=bool),
        KEY_AUTO_RETRY: s.value(KEY_AUTO_RETRY, True, type=bool),
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
) -> None:
    s = get_settings()
    s.setValue(KEY_PLATFORM, platform)
    s.setValue(KEY_REPO_TYPE, repo_type)
    s.setValue(KEY_REPO_ID, repo_id)
    s.setValue(KEY_SAVE_PATH, save_path)
    s.setValue(KEY_TOKEN, token)
    s.setValue(KEY_ENDPOINT, endpoint)
    s.setValue(KEY_PROXY, proxy)
    s.setValue(KEY_PROXY_ENABLED, proxy_enabled)
    s.setValue(KEY_AUTO_RETRY, auto_retry)
    s.sync()
