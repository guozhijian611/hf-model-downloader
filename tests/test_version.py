from src.version import is_remote_newer, normalize_version, parse_version_tuple


def test_normalize_version():
    assert normalize_version("v0.6.2") == "0.6.2"
    assert normalize_version("  V1.2.3  ") == "1.2.3"


def test_parse_version_tuple():
    assert parse_version_tuple("0.6.2") == (0, 6, 2)
    assert parse_version_tuple("v1.0") == (1, 0, 0)
    assert parse_version_tuple("2.1.0-beta") == (2, 1, 0)


def test_is_remote_newer():
    assert is_remote_newer("0.6.2", "0.6.3") is True
    assert is_remote_newer("0.6.2", "v0.7.0") is True
    assert is_remote_newer("0.6.2", "0.6.2") is False
    assert is_remote_newer("0.7.0", "0.6.9") is False
