from unittest.mock import MagicMock, patch

from src.update_check import (
    check_for_update,
    pick_release_asset,
    preferred_asset_name,
)


def test_preferred_asset_name_windows():
    assert (
        preferred_asset_name("Windows", "AMD64")
        == "hf-model-downloader-windows-x86_64.zip"
    )


def test_preferred_asset_name_macos_arm():
    assert preferred_asset_name("Darwin", "arm64") == "hf-model-downloader-arm64.dmg"


def test_pick_release_asset_exact_match():
    assets = [
        {
            "name": "hf-model-downloader-arm64.dmg",
            "browser_download_url": "https://example.com/a.dmg",
            "size": 1,
        },
        {
            "name": "hf-model-downloader-windows-x86_64.zip",
            "browser_download_url": "https://example.com/w.zip",
            "size": 2,
        },
    ]
    with patch("src.update_check.preferred_asset_name", return_value=assets[1]["name"]):
        picked = pick_release_asset(assets)
    assert picked is not None
    assert picked.name.endswith(".zip")
    assert picked.download_url.endswith("w.zip")


@patch("src.update_check.get_app_version", return_value="0.8.0")
@patch("src.update_check._http_get")
def test_check_for_update_finds_newer_release_with_asset(mock_get, _mock_version):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "tag_name": "v0.8.2",
        "name": "v0.8.2",
        "html_url": "https://github.com/guozhijian611/hf-model-downloader/releases/tag/v0.8.2",
        "assets": [
            {
                "name": "hf-model-downloader-windows-x86_64.zip",
                "browser_download_url": "https://example.com/app.zip",
                "size": 10,
            }
        ],
    }
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    with patch(
        "src.update_check.preferred_asset_name",
        return_value="hf-model-downloader-windows-x86_64.zip",
    ):
        result = check_for_update()
    assert result.update_available is True
    assert result.latest_version == "0.8.2"
    assert result.asset is not None
    assert result.asset.name.endswith(".zip")
    assert "自动下载" in result.message


@patch("src.update_check.get_app_version", return_value="0.8.2")
@patch("src.update_check._http_get")
def test_check_for_update_already_latest(mock_get, _mock_version):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "tag_name": "v0.8.2",
        "name": "v0.8.2",
        "html_url": "https://github.com/example/releases/tag/v0.8.2",
        "assets": [],
    }
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    result = check_for_update()
    assert result.update_available is False
    assert "已是最新版本" in result.message


@patch("src.update_check.get_app_version", return_value="0.8.0")
@patch("src.update_check._http_get")
def test_check_for_update_network_error(mock_get, _mock_version):
    import requests

    mock_get.side_effect = requests.ConnectionError("offline")
    result = check_for_update()
    assert result.update_available is False
    assert result.error is not None
    assert "检查更新失败" in result.message
