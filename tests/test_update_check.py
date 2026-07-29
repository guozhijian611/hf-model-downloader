from unittest.mock import MagicMock, patch

from src.update_check import check_for_update


@patch("src.update_check.get_app_version", return_value="0.6.2")
@patch("src.update_check.requests.get")
def test_check_for_update_finds_newer_release(mock_get, _mock_version):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "tag_name": "v0.7.0",
        "name": "v0.7.0",
        "html_url": "https://github.com/guozhijian611/hf-model-downloader/releases/tag/v0.7.0",
    }
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    result = check_for_update()
    assert result.update_available is True
    assert result.latest_version == "0.7.0"
    assert "发现新版本" in result.message


@patch("src.update_check.get_app_version", return_value="0.6.2")
@patch("src.update_check.requests.get")
def test_check_for_update_already_latest(mock_get, _mock_version):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "tag_name": "v0.6.2",
        "name": "v0.6.2",
        "html_url": "https://github.com/example/releases/tag/v0.6.2",
    }
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    result = check_for_update()
    assert result.update_available is False
    assert "已是最新版本" in result.message


@patch("src.update_check.get_app_version", return_value="0.6.2")
@patch("src.update_check.requests.get")
def test_check_for_update_network_error(mock_get, _mock_version):
    import requests

    mock_get.side_effect = requests.ConnectionError("offline")
    result = check_for_update()
    assert result.update_available is False
    assert result.error is not None
    assert "检查更新失败" in result.message
