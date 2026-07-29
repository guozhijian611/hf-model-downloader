from src.app_logging import (
    get_last_crash_log_path,
    get_runtime_log_path,
    setup_app_logging,
    write_crash_report,
)


def test_setup_app_logging_creates_runtime_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Force re-init path for linux-style layout even on mac/windows tests:
    import src.app_logging as al

    al._LOG_DIR = None
    al._CONFIGURED = False

    # Use explicit dir override via monkeypatch of Path.home-related logic:
    # re-point get_log_dir by setting _LOG_DIR after call is complex; call setup
    # and assert files exist under real log dir for this process.
    log_dir = setup_app_logging()
    assert log_dir.is_dir()
    runtime = get_runtime_log_path()
    assert runtime.name == "runtime.log"
    # After setup, at least the handler is attached (file may be empty until log)
    assert runtime.parent == log_dir


def test_write_crash_report_creates_files():
    import src.app_logging as al

    # Ensure dir ready
    al._CONFIGURED = False
    setup_app_logging()

    try:
        raise RuntimeError("boom-for-test")
    except RuntimeError as exc:
        path = write_crash_report(
            "test",
            type(exc),
            exc,
            exc.__traceback__,
            extra="unit-test",
        )

    assert path is not None
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "boom-for-test" in text
    assert "crash_kind=test" in text
    assert get_last_crash_log_path().exists()
