"""Hugging Face Hub environment setup for downloads."""

import importlib.util
import os
from contextlib import contextmanager

from huggingface_hub import HfApi

_HF_DOWNLOAD_ENV_VARS = (
    "HF_TOKEN",
    "HF_ENDPOINT",
    "HF_HUB_DISABLE_SSL_VERIFICATION",
    "HF_HUB_DISABLE_XET",
    "HF_HUB_ETAG_TIMEOUT",
    "HF_HUB_DOWNLOAD_TIMEOUT",
)

DEFAULT_HF_MIRROR_ENDPOINT = "https://hf-mirror.com"
DEFAULT_HF_ENDPOINT = "https://huggingface.co"


def resolve_hf_endpoint(endpoint: str | None) -> str:
    endpoint = (endpoint or "").strip()
    return endpoint or DEFAULT_HF_MIRROR_ENDPOINT


def apply_hf_download_env(
    token: str | None = None,
    endpoint: str | None = None,
) -> None:
    if token:
        os.environ["HF_TOKEN"] = token
    else:
        os.environ.pop("HF_TOKEN", None)

    resolved_endpoint = resolve_hf_endpoint(endpoint)
    os.environ["HF_ENDPOINT"] = resolved_endpoint
    # More tolerant timeouts for large repos / mirrors.
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

    if "hf-mirror.com" in resolved_endpoint or "mirror" in resolved_endpoint.lower():
        os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
        # Xet + third-party mirrors is a common failure mode; force classic HTTP.
        os.environ["HF_HUB_DISABLE_XET"] = "1"
    else:
        os.environ.pop("HF_HUB_DISABLE_SSL_VERIFICATION", None)
        # Keep Xet available for official hub unless user disabled it.
        os.environ.pop("HF_HUB_DISABLE_XET", None)


def clear_hf_download_env() -> None:
    for var in _HF_DOWNLOAD_ENV_VARS:
        os.environ.pop(var, None)


def xet_available() -> bool:
    return importlib.util.find_spec("hf_xet") is not None


@contextmanager
def hf_api_client(token: str | None = None, endpoint: str | None = None):
    """Provide an HfApi client with matching download environment variables."""
    apply_hf_download_env(token=token, endpoint=endpoint)
    try:
        yield HfApi(endpoint=resolve_hf_endpoint(endpoint))
    finally:
        clear_hf_download_env()
