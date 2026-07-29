"""Tests for tqdm / HF progress line parsing."""

from __future__ import annotations

from src.progress_tracker import (
    DownloadProgressTracker,
    parse_rate_to_bps,
    parse_size_to_bytes,
)


def test_parse_size():
    assert parse_size_to_bytes("512") == 512
    assert parse_size_to_bytes("1.5K") == int(1.5 * 1024)
    assert parse_size_to_bytes("388MB") == 388 * 1024 * 1024
    assert parse_size_to_bytes("1.59G") == int(1.59 * 1024**3)
    assert parse_size_to_bytes("77.6G") == int(77.6 * 1024**3)


def test_parse_rate():
    bps = parse_rate_to_bps("00:56<03:16, 388MB/s")
    assert bps is not None
    assert abs(bps - 388 * 1024 * 1024) < 1


def test_overall_incomplete_total():
    t = DownloadProgressTracker()
    line = (
        "Downloading (incomplete total...):  2%|█| 1.59G/77.6G [00:56<03:16, 388MB/s]"
    )
    assert t.feed(line)
    assert t.overall is not None
    assert t.overall.is_overall
    assert 1.9 < t.overall.pct < 2.1
    assert t.overall.done_bytes > 0
    assert t.overall.total_bytes > 0
    assert t.overall.rate_bps > 0


def test_per_file_and_fetching():
    t = DownloadProgressTracker()
    assert t.feed("Fetching 50 files:  10%|█| 5/50")
    assert t.expected_files == 50
    line = "data/shard-00001.parquet:  45%|████| 450M/1.00G [00:10<00:12, 45.0MB/s]"
    assert t.feed(line)
    assert "shard-00001.parquet" in list(t.files.keys())[0] or any(
        "shard" in k for k in t.files
    )
    fp = next(iter(t.files.values()))
    assert fp.status == "下载中"
    assert fp.pct == 45.0

    done_line = (
        "data/shard-00001.parquet: 100%|████| 1.00G/1.00G [00:22<00:00, 45.0MB/s]"
    )
    t.feed(done_line)
    fp = next(iter(t.files.values()))
    assert fp.status == "完成"
    assert t.completed_count == 1


def test_log_prefix_stripped():
    t = DownloadProgressTracker()
    line = (
        "12:34:56 [信息] Downloading (incomplete total...):  "
        "3%| | 2.02G/77.6G [00:58<04:26, 284MB/s]"
    )
    assert t.feed(line)
    assert t.overall is not None
    assert t.overall.pct == 3.0
