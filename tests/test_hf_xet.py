"""Smoke tests for Hugging Face Xet download support."""

from src.hf_hub_env import xet_available


def test_hf_xet_is_available():
    assert xet_available(), (
        "hf_xet must be installed for Xet Storage downloads. "
        "Run `uv sync` to install huggingface-hub[hf_xet]."
    )
