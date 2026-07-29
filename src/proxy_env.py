"""HTTP(S)/SOCKS proxy helpers for downloads."""

from __future__ import annotations

import os
from contextlib import contextmanager

_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def normalize_proxy(proxy: str | None) -> str | None:
    proxy = (proxy or "").strip()
    return proxy or None


def is_socks_proxy(proxy: str | None) -> bool:
    proxy = (proxy or "").lower()
    return (
        proxy.startswith("socks5://")
        or proxy.startswith("socks4://")
        or proxy.startswith("socks://")
    )


def socks_support_available() -> bool:
    try:
        import socks  # noqa: F401  # from PySocks

        return True
    except Exception:
        return False


def proxies_dict(proxy: str | None) -> dict[str, str] | None:
    """Build a requests/huggingface_hub style proxies mapping."""
    proxy = normalize_proxy(proxy)
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def apply_proxy_env(proxy: str | None) -> None:
    """Set or clear process proxy environment variables."""
    proxy = normalize_proxy(proxy)
    if proxy:
        for key in _PROXY_ENV_KEYS:
            os.environ[key] = proxy
    else:
        for key in _PROXY_ENV_KEYS:
            os.environ.pop(key, None)


@contextmanager
def proxy_env(proxy: str | None):
    """Temporarily apply proxy env vars, then restore previous values."""
    previous = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    apply_proxy_env(proxy)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
