from src.hfd_backend import (
    BACKEND_HFD,
    BACKEND_HUB,
    find_hfd_script,
    hfd_availability,
)


def test_bundled_hfd_script_exists():
    script = find_hfd_script()
    assert script is not None
    assert script.is_file()
    text = script.read_text(encoding="utf-8", errors="ignore")
    assert text.startswith("#!")
    assert "aria2c" in text
    assert "padeoe" in text or "REPO_ID" in text


def test_backend_constants():
    assert BACKEND_HUB == "huggingface-hub"
    assert BACKEND_HFD == "hfd"


def test_hfd_availability_shape():
    ok, msg = hfd_availability()
    assert isinstance(ok, bool)
    assert isinstance(msg, str)
    assert msg
