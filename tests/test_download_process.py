"""Regression tests for download subprocess exit codes."""

import multiprocessing

from src.unified_downloader import unified_download_model


def _drain_pipe(reader) -> None:
    while reader.poll(0.1):
        try:
            reader.recv()
        except EOFError:
            break


def test_unsupported_platform_exits_nonzero():
    reader, writer = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.get_context("spawn").Process(
        target=unified_download_model,
        args=(
            "invalid-platform",
            "org/model",
            "/tmp",
            None,
            None,
            writer,
            "model",
        ),
    )
    process.start()
    process.join(timeout=15)
    _drain_pipe(reader)
    reader.close()
    writer.close()

    assert process.exitcode not in (0, None)
