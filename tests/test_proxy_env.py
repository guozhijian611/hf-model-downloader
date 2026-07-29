"""Unit tests for proxy helpers."""

import os

from src.proxy_env import apply_proxy_env, normalize_proxy, proxies_dict, proxy_env


def test_normalize_proxy_strips_and_empty():
    assert normalize_proxy("  http://127.0.0.1:7890  ") == "http://127.0.0.1:7890"
    assert normalize_proxy("") is None
    assert normalize_proxy(None) is None
    assert normalize_proxy("   ") is None


def test_proxies_dict():
    assert proxies_dict(None) is None
    assert proxies_dict("http://127.0.0.1:7890") == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }


def test_apply_proxy_env_sets_and_clears(monkeypatch):
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(key, raising=False)

    apply_proxy_env("http://127.0.0.1:7890")
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["http_proxy"] == "http://127.0.0.1:7890"

    apply_proxy_env(None)
    assert "HTTPS_PROXY" not in os.environ
    assert "http_proxy" not in os.environ


def test_proxy_env_context_restores(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://old:1")
    with proxy_env("http://new:2"):
        assert os.environ["HTTPS_PROXY"] == "http://new:2"
    assert os.environ["HTTPS_PROXY"] == "http://old:1"
