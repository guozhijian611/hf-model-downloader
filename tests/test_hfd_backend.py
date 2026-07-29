from src.hfd_backend import (
    BACKEND_HFD,
    BACKEND_HUB,
    find_hfd_script,
    hfd_availability,
    hfd_install_plan,
    missing_hfd_deps,
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


def test_missing_deps_and_install_plan_shape():
    missing = missing_hfd_deps()
    assert isinstance(missing, list)
    cmds, tips = hfd_install_plan()
    assert isinstance(cmds, list)
    assert isinstance(tips, list)
    # If aria2c already present, plan may be empty — still valid
    for cmd in cmds:
        assert isinstance(cmd, list) and cmd


def test_tools_bin_dir_and_portable_marker():
    from src.hfd_backend import _PORTABLE_ARIA2_CMD, tools_bin_dir

    d = tools_bin_dir()
    assert d.name == "tools" or d.as_posix().endswith("tools")
    assert _PORTABLE_ARIA2_CMD[0].startswith("__portable")


def test_hfd_progress_line_parsing():
    from src.hfd_backend import _hfd_progress_messages, _normalize_hfd_output_line

    raw = (
        "\r\033[K\033[0;32m[ 14%]\033[0m  400/10755 files | "
        "5.56G/39.9G | 10.7M/s | ETA 05:12"
    )
    line = _normalize_hfd_output_line(raw)
    assert "14%" in line
    msgs = _hfd_progress_messages(line)
    assert any(m.startswith("[HF_META]\tfiles\t10755") for m in msgs)
    assert any(m.startswith("[HF_META]\tdone_files\t400") for m in msgs)
    assert any("hfd total" in m for m in msgs)

    listed = _normalize_hfd_output_line("Listed 10755 files (49.6G)")
    assert _hfd_progress_messages(listed) == ["[HF_META]\tfiles\t10755"]
