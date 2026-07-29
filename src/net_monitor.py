"""Network interface traffic sampling and session statistics."""

from __future__ import annotations

import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import psutil

# Interfaces typically not useful for download monitoring.
_SKIP_IFACE_PREFIXES = (
    "lo",
    "lo0",
    "Loopback",
    "awdl",
    "llw",
    "utun",
    "gif",
    "stf",
    "bridge",
    "ap",
    "p2p",
    "anpi",
    "VMware",
    "veth",
    "docker",
    "br-",
    "virbr",
    "tun",
    "tap",
)


def format_bytes(n: float | int) -> str:
    """Human-readable byte size."""
    n = float(n)
    if n < 0:
        n = 0.0
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while n >= 1024.0 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.2f} {units[i]}"


def format_rate(bps: float) -> str:
    """Human-readable bytes/second."""
    return f"{format_bytes(bps)}/s"


def format_rate_compact(bps: float) -> str:
    """Short rate label for chart axes (fits narrow Y margin)."""
    n = max(0.0, float(bps))
    units = ("B", "K", "M", "G", "T")
    i = 0
    while n >= 1024.0 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)}"
    if n >= 100:
        return f"{n:.0f}{units[i]}"
    if n >= 10:
        return f"{n:.1f}{units[i]}"
    return f"{n:.2f}{units[i]}"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def should_skip_iface(name: str) -> bool:
    n = name or ""
    if n.startswith("lo"):
        return True
    lower = n.lower()
    for p in _SKIP_IFACE_PREFIXES:
        if n.startswith(p) or lower.startswith(p.lower()):
            return True
    return False


def list_network_interfaces() -> list[str]:
    """Return usable NIC names (non-loopback / virtual noise filtered)."""
    try:
        counters = psutil.net_io_counters(pernic=True) or {}
    except Exception:
        return []
    names = [n for n in counters if not should_skip_iface(n)]
    return sorted(names)


@dataclass
class NetSnapshot:
    """One sample of interface + disk traffic."""

    timestamp: float
    down_bps: float = 0.0
    up_bps: float = 0.0
    disk_write_bps: float = 0.0
    disk_read_bps: float = 0.0
    bytes_recv: int = 0
    bytes_sent: int = 0
    disk_write_bytes: int = 0
    disk_read_bytes: int = 0


@dataclass
class SessionStats:
    """Aggregated stats since last reset."""

    started_at: float = field(default_factory=time.time)
    total_down: int = 0
    total_up: int = 0
    total_disk_write: int = 0
    peak_down_bps: float = 0.0
    peak_up_bps: float = 0.0
    peak_disk_write_bps: float = 0.0
    sample_count: int = 0
    sum_down_bps: float = 0.0
    sum_up_bps: float = 0.0
    sum_disk_write_bps: float = 0.0

    @property
    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started_at)

    @property
    def avg_down_bps(self) -> float:
        if self.sample_count <= 0:
            return 0.0
        return self.sum_down_bps / self.sample_count

    @property
    def avg_up_bps(self) -> float:
        if self.sample_count <= 0:
            return 0.0
        return self.sum_up_bps / self.sample_count

    @property
    def avg_disk_write_bps(self) -> float:
        if self.sample_count <= 0:
            return 0.0
        return self.sum_disk_write_bps / self.sample_count

    @property
    def overall_avg_down_bps(self) -> float:
        """Total downloaded / wall-clock elapsed (session average)."""
        elapsed = self.elapsed
        if elapsed <= 0:
            return 0.0
        return self.total_down / elapsed

    @property
    def overall_avg_up_bps(self) -> float:
        elapsed = self.elapsed
        if elapsed <= 0:
            return 0.0
        return self.total_up / elapsed

    @property
    def overall_avg_disk_write_bps(self) -> float:
        elapsed = self.elapsed
        if elapsed <= 0:
            return 0.0
        return self.total_disk_write / elapsed


# Cap chart points so 24h windows stay light (UI + memory).
_MAX_HISTORY_POINTS = 900


def _history_maxlen(history_seconds: int, interval_sec: float) -> int:
    raw = int(history_seconds / max(0.2, interval_sec)) + 5
    return max(30, min(_MAX_HISTORY_POINTS, raw))


def chart_sample_interval(history_seconds: int) -> float:
    """How often to store a chart sample for the given window length."""
    # Aim for ~600–900 points across the window.
    seconds = max(30, int(history_seconds))
    return max(1.0, seconds / float(_MAX_HISTORY_POINTS - 20))


class NetworkTrafficMonitor:
    """Sample NIC counters and keep a rolling history for charting."""

    def __init__(
        self,
        *,
        history_seconds: int = 180,
        interval_sec: float = 1.0,
        interface: str | None = None,
    ) -> None:
        self.history_seconds = max(30, int(history_seconds))
        # Live rate tick interval (UI timer); chart may store less often.
        self.interval_sec = max(0.2, float(interval_sec))
        self.interface: str | None = interface or None
        self._chart_interval = chart_sample_interval(self.history_seconds)
        self._last_chart_t: float | None = None
        maxlen = _history_maxlen(self.history_seconds, self._chart_interval)
        self.history: deque[NetSnapshot] = deque(maxlen=maxlen)
        self.session = SessionStats()
        self._prev_recv: int | None = None
        self._prev_sent: int | None = None
        self._prev_disk_w: int | None = None
        self._prev_disk_r: int | None = None
        self._prev_t: float | None = None
        self._paused = False
        self.last: NetSnapshot | None = None
        self.watch_path: str | None = None
        self.disk_free_bytes: int | None = None
        self.disk_total_bytes: int | None = None

    def set_interface(self, name: str | None) -> None:
        """Switch NIC; resets rate baseline (not session totals)."""
        iface = (name or "").strip() or None
        if iface == self.interface:
            return
        self.interface = iface
        self._reset_baseline()

    def set_watch_path(self, path: str | None) -> None:
        """Path used for free-space display (usually download save dir)."""
        self.watch_path = (path or "").strip() or None
        self._refresh_disk_space()

    def set_history_seconds(self, seconds: int) -> None:
        seconds = max(30, min(int(seconds), 7 * 24 * 3600))  # up to 7 days
        if seconds == self.history_seconds:
            return
        self.history_seconds = seconds
        self._chart_interval = chart_sample_interval(self.history_seconds)
        maxlen = _history_maxlen(self.history_seconds, self._chart_interval)
        # Drop points older than the new window
        cutoff = time.time() - self.history_seconds
        kept = [s for s in self.history if s.timestamp >= cutoff]
        # Downsample if still too dense
        if len(kept) > maxlen:
            step = max(1, len(kept) // maxlen)
            kept = kept[::step][-maxlen:]
        self.history = deque(kept, maxlen=maxlen)
        self._last_chart_t = kept[-1].timestamp if kept else None

    def reset_session(self) -> None:
        """Clear totals / peaks / chart history and re-baseline counters."""
        self.session = SessionStats()
        self.history.clear()
        self._last_chart_t = None
        self._reset_baseline()
        self.last = None
        self._refresh_disk_space()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if self._paused:
            # Drop baseline so next resume doesn't invent a huge spike.
            self._reset_baseline()

    def _reset_baseline(self) -> None:
        self._prev_recv = None
        self._prev_sent = None
        self._prev_disk_w = None
        self._prev_disk_r = None
        self._prev_t = None

    @property
    def paused(self) -> bool:
        return self._paused

    def _read_counters(self) -> tuple[int, int]:
        if self.interface:
            pernic = psutil.net_io_counters(pernic=True) or {}
            c = pernic.get(self.interface)
            if c is None:
                return 0, 0
            return int(c.bytes_recv), int(c.bytes_sent)

        pernic = psutil.net_io_counters(pernic=True) or {}
        recv = sent = 0
        any_usable = False
        for name, c in pernic.items():
            if should_skip_iface(name):
                continue
            any_usable = True
            recv += int(c.bytes_recv)
            sent += int(c.bytes_sent)
        if any_usable:
            return recv, sent
        # Fallback: system totals
        total = psutil.net_io_counters()
        if total is None:
            return 0, 0
        return int(total.bytes_recv), int(total.bytes_sent)

    def _read_disk_counters(self) -> tuple[int, int]:
        """System-wide disk bytes written/read (all disks)."""
        try:
            c = psutil.disk_io_counters()
        except Exception:
            return 0, 0
        if c is None:
            return 0, 0
        return int(getattr(c, "write_bytes", 0) or 0), int(
            getattr(c, "read_bytes", 0) or 0
        )

    def _refresh_disk_space(self) -> None:
        path = self.watch_path
        if not path:
            self.disk_free_bytes = None
            self.disk_total_bytes = None
            return
        try:
            p = Path(path)
            # Use existing parent if path not created yet
            while p and not p.exists() and p != p.parent:
                p = p.parent
            usage = shutil.disk_usage(str(p if p.exists() else path))
            self.disk_free_bytes = int(usage.free)
            self.disk_total_bytes = int(usage.total)
        except Exception:
            self.disk_free_bytes = None
            self.disk_total_bytes = None

    def tick(self) -> NetSnapshot:
        """Take one sample. Safe to call from UI timer."""
        now = time.time()
        if self._paused:
            snap = self.last or NetSnapshot(timestamp=now)
            return snap

        try:
            recv, sent = self._read_counters()
        except Exception:
            recv, sent = self._prev_recv or 0, self._prev_sent or 0
        try:
            disk_w, disk_r = self._read_disk_counters()
        except Exception:
            disk_w = self._prev_disk_w or 0
            disk_r = self._prev_disk_r or 0

        down_bps = up_bps = disk_w_bps = disk_r_bps = 0.0
        if self._prev_recv is not None and self._prev_t is not None:
            dt = max(1e-6, now - self._prev_t)
            d_recv = recv - self._prev_recv
            d_sent = sent - self._prev_sent
            d_dw = disk_w - (self._prev_disk_w or disk_w)
            d_dr = disk_r - (self._prev_disk_r or disk_r)
            # Counter wrap / NIC reset
            if d_recv < 0:
                d_recv = 0
            if d_sent < 0:
                d_sent = 0
            if d_dw < 0:
                d_dw = 0
            if d_dr < 0:
                d_dr = 0
            down_bps = d_recv / dt
            up_bps = d_sent / dt
            disk_w_bps = d_dw / dt
            disk_r_bps = d_dr / dt
            self.session.total_down += d_recv
            self.session.total_up += d_sent
            self.session.total_disk_write += d_dw
            self.session.sample_count += 1
            self.session.sum_down_bps += down_bps
            self.session.sum_up_bps += up_bps
            self.session.sum_disk_write_bps += disk_w_bps
            if down_bps > self.session.peak_down_bps:
                self.session.peak_down_bps = down_bps
            if up_bps > self.session.peak_up_bps:
                self.session.peak_up_bps = up_bps
            if disk_w_bps > self.session.peak_disk_write_bps:
                self.session.peak_disk_write_bps = disk_w_bps

        self._prev_recv = recv
        self._prev_sent = sent
        self._prev_disk_w = disk_w
        self._prev_disk_r = disk_r
        self._prev_t = now

        # Refresh free space every ~5 samples to keep cost low
        if self.session.sample_count % 5 == 0:
            self._refresh_disk_space()

        snap = NetSnapshot(
            timestamp=now,
            down_bps=down_bps,
            up_bps=up_bps,
            disk_write_bps=disk_w_bps,
            disk_read_bps=disk_r_bps,
            bytes_recv=recv,
            bytes_sent=sent,
            disk_write_bytes=disk_w,
            disk_read_bytes=disk_r,
        )
        self.last = snap
        # Store chart samples less often for long windows (hours/days).
        if (
            self._last_chart_t is None
            or (now - self._last_chart_t) >= self._chart_interval - 1e-6
        ):
            self.history.append(snap)
            self._last_chart_t = now
            # Prune points outside the visible window
            cutoff = now - self.history_seconds
            while self.history and self.history[0].timestamp < cutoff:
                self.history.popleft()
        return snap

    def history_series(
        self,
    ) -> tuple[list[float], list[float], list[float], list[float]]:
        """Return (t_rel, down_bps, up_bps, disk_write_bps) for charting."""
        if not self.history:
            return [], [], [], []
        cutoff = time.time() - self.history_seconds
        samples = [s for s in self.history if s.timestamp >= cutoff]
        if not samples:
            return [], [], [], []
        t0 = samples[0].timestamp
        ts = [s.timestamp - t0 for s in samples]
        down = [s.down_bps for s in samples]
        up = [s.up_bps for s in samples]
        disk_w = [s.disk_write_bps for s in samples]
        return ts, down, up, disk_w
