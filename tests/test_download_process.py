"""Regression tests for download subprocess exit codes."""

import multiprocessing

from src.download_core import isolated_download_main


def _drain_pipe(reader) -> None:
    while reader.poll(0.1):
        try:
            reader.recv()
        except EOFError:
            break


def test_unsupported_platform_exits_nonzero():
    reader, writer = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=isolated_download_main,
        args=(
            "invalid-platform",
            "org/model",
            "/tmp",
            None,
            None,
            writer,
            "model",
            None,
        ),
    )
    process.start()
    process.join(timeout=15)
    _drain_pipe(reader)
    reader.close()
    writer.close()

    assert process.exitcode not in (0, None)


def test_download_core_has_no_pyqt_import():
    """Spawned workers must not pull Qt (causes GUI crashes on Windows/macOS)."""
    import re
    from pathlib import Path

    import src.download_core as dc

    text = Path(dc.__file__).read_text(encoding="utf-8")
    # Allow mentioning Qt in comments/docstrings, but forbid imports.
    assert re.search(r"^\s*(from|import)\s+PyQt", text, re.M) is None
    assert re.search(r"^\s*(from|import)\s+PySide", text, re.M) is None
