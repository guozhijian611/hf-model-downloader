"""Unit tests for network traffic monitor helpers."""

from __future__ import annotations

from src.net_monitor import (
    NetworkTrafficMonitor,
    SessionStats,
    format_bytes,
    format_duration,
    format_rate,
    should_skip_iface,
)


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert "KB" in format_bytes(2048)
    assert "MB" in format_bytes(5 * 1024 * 1024)


def test_format_rate_and_duration():
    assert format_rate(1024).endswith("/s")
    assert format_duration(65) == "01:05"
    assert format_duration(3661) == "1:01:01"


def test_should_skip_iface():
    assert should_skip_iface("lo0")
    assert should_skip_iface("lo")
    assert should_skip_iface("utun3")
    assert not should_skip_iface("en0")
    assert not should_skip_iface("eth0")
    assert not should_skip_iface("Wi-Fi")


def test_session_stats_averages():
    s = SessionStats()
    s.total_down = 10_000
    s.total_up = 1_000
    s.sample_count = 2
    s.sum_down_bps = 200.0
    s.sum_up_bps = 20.0
    assert s.avg_down_bps == 100.0
    assert s.avg_up_bps == 10.0
    # overall depends on elapsed; just ensure non-negative
    assert s.overall_avg_down_bps >= 0


def test_monitor_tick_and_history():
    m = NetworkTrafficMonitor(history_seconds=60, interval_sec=1.0)
    # Two ticks establish a rate baseline
    m.tick()
    m.tick()
    assert m.last is not None
    assert len(m.history) >= 1
    ts, down, up, disk_w = m.history_series()
    assert len(ts) == len(down) == len(up) == len(disk_w)
    m.reset_session()
    assert m.session.total_down == 0
    assert len(m.history) == 0
