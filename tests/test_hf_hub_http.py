"""Tests for modern huggingface_hub httpx proxy wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.hf_hub_env import configure_hf_hub_http


def test_configure_hf_hub_http_sets_env_and_factory(monkeypatch):
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(key, raising=False)

    mock_set = MagicMock()
    mock_set_async = MagicMock()
    mock_close = MagicMock()

    with patch("huggingface_hub.utils._http.set_client_factory", mock_set), patch(
        "huggingface_hub.utils._http.set_async_client_factory", mock_set_async
    ), patch("huggingface_hub.utils._http.close_session", mock_close):
        got = configure_hf_hub_http("http://127.0.0.1:10808")

    assert got == "http://127.0.0.1:10808"
    import os

    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:10808"
    mock_set.assert_called_once()
    mock_set_async.assert_called_once()
    mock_close.assert_called_once()

    # Factory should build a client with proxy=
    factory = mock_set.call_args[0][0]
    client = factory()
    try:
        # httpx stores proxy on the client transport; just ensure construct works
        assert client is not None
    finally:
        client.close()


def test_configure_hf_hub_http_none_clears_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://old:1")
    with patch("huggingface_hub.utils._http.set_client_factory"), patch(
        "huggingface_hub.utils._http.set_async_client_factory"
    ), patch("huggingface_hub.utils._http.close_session"):
        configure_hf_hub_http(None)
    import os

    assert "HTTPS_PROXY" not in os.environ
