"""Preset Hub endpoints and failover helpers."""

from __future__ import annotations

# (url, short label for UI)
HF_ENDPOINT_PRESETS: list[tuple[str, str]] = [
    ("https://hf-mirror.com", "HF 镜像（国内推荐）"),
    ("https://huggingface.co", "Hugging Face 官方"),
]

MS_ENDPOINT_PRESETS: list[tuple[str, str]] = [
    ("https://modelscope.cn", "ModelScope 官方"),
    ("https://www.modelscope.cn", "ModelScope www"),
]


def preset_urls(platform: str) -> list[str]:
    if platform == "modelscope":
        return [url for url, _ in MS_ENDPOINT_PRESETS]
    return [url for url, _ in HF_ENDPOINT_PRESETS]


def preset_labels(platform: str) -> list[str]:
    """Labels shown in the combo (url — label)."""
    presets = MS_ENDPOINT_PRESETS if platform == "modelscope" else HF_ENDPOINT_PRESETS
    return [f"{url}  —  {label}" for url, label in presets]


def url_from_combo_text(text: str) -> str:
    """Extract bare URL from combo display text or raw user input."""
    text = (text or "").strip()
    if not text:
        return ""
    # "https://x  —  label" → https://x
    if "  —  " in text:
        text = text.split("  —  ", 1)[0].strip()
    elif " — " in text:
        text = text.split(" — ", 1)[0].strip()
    return text.rstrip("/")


def default_endpoint(platform: str) -> str:
    urls = preset_urls(platform)
    return urls[0] if urls else ""


def build_endpoint_chain(
    selected: str | None,
    platform: str,
    *,
    failover: bool,
) -> list[str]:
    """
    Build ordered unique endpoint list.

    Selected first; if failover, append remaining presets for the platform.
    """
    selected = url_from_combo_text(selected or "")
    presets = preset_urls(platform)
    chain: list[str] = []

    def _add(url: str) -> None:
        url = (url or "").strip().rstrip("/")
        if url and url not in chain:
            chain.append(url)

    if selected:
        _add(selected)
    elif presets:
        _add(presets[0])

    if failover:
        for url in presets:
            _add(url)

    return chain or [default_endpoint(platform)]
