"""Parse huggingface-hub / tqdm progress log lines into file-level status."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# "name:  12%|...| 1.2G/10G [00:01<00:10, 100MB/s]"
_RE_TQDM = re.compile(
    r"^(?P<name>.+?):\s+(?P<pct>\d+(?:\.\d+)?)%\s*\|"
    r"[^|]*\|?\s*"
    r"(?P<done>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"\s*/\s*"
    r"(?P<total>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"(?:\s*\[(?P<bracket>[^\]]*)\])?",
)

# Fallback without bar: "name: 50% 1G/2G"
_RE_SIMPLE = re.compile(
    r"^(?P<name>.+?):\s+(?P<pct>\d+(?:\.\d+)?)%\s+"
    r"(?P<done>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"\s*/\s*"
    r"(?P<total>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)",
)

_RE_RATE = re.compile(
    r"([\d.,]+)\s*([kKmMgGtTpPeE]?i?)[bB]/s",
    re.IGNORECASE,
)

_RE_FETCHING = re.compile(
    r"Fetching\s+(?P<n>\d+)\s+files",
    re.IGNORECASE,
)


def parse_size_to_bytes(text: str) -> int | None:
    """Parse sizes like 1.59G, 388MB, 1024, 1.2GiB into bytes."""
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    if not s:
        return None
    m = re.match(
        r"^([\d.]+)\s*([kKmMgGtTpPeE]?)(i?)[bB]?$",
        s,
    )
    if not m:
        # pure number
        try:
            return int(float(s))
        except ValueError:
            return None
    value = float(m.group(1))
    unit = (m.group(2) or "").upper()
    binary = bool(m.group(3))
    base = 1024.0 if binary or unit in {"", "K", "M", "G", "T", "P"} else 1000.0
    # tqdm / HF almost always use 1024-based abbreviations (MB, GB)
    base = 1024.0
    mult = {
        "": 1.0,
        "K": base,
        "M": base**2,
        "G": base**3,
        "T": base**4,
        "P": base**5,
        "E": base**6,
    }.get(unit, 1.0)
    return int(value * mult)


def parse_rate_to_bps(text: str) -> float | None:
    if not text:
        return None
    m = _RE_RATE.search(text)
    if not m:
        return None
    size = parse_size_to_bytes(m.group(1) + m.group(2) + "B")
    if size is None:
        return None
    return float(size)


@dataclass
class FileProgress:
    name: str
    pct: float = 0.0
    done_bytes: int = 0
    total_bytes: int = 0
    rate_bps: float = 0.0
    status: str = "下载中"  # 下载中 / 完成 / 总体
    updated_at: float = field(default_factory=time.time)
    is_overall: bool = False

    @property
    def size_text(self) -> str:
        from .net_monitor import format_bytes

        if self.total_bytes > 0:
            return f"{format_bytes(self.done_bytes)} / {format_bytes(self.total_bytes)}"
        if self.done_bytes > 0:
            return f"{format_bytes(self.done_bytes)} / ?"
        return "—"


class DownloadProgressTracker:
    """Track overall + per-file progress parsed from log lines."""

    OVERALL_NAMES = (
        "downloading",
        "incomplete total",
        "fetching",
        "总体",
        "total",
    )

    def __init__(self, *, stale_seconds: float = 90.0) -> None:
        self.stale_seconds = stale_seconds
        self.files: dict[str, FileProgress] = {}
        self.overall: FileProgress | None = None
        self.expected_files: int | None = None
        self.completed_count = 0
        self._seen_complete: set[str] = set()

    def reset(self) -> None:
        self.files.clear()
        self.overall = None
        self.expected_files = None
        self.completed_count = 0
        self._seen_complete.clear()

    def feed(self, message: str) -> bool:
        """Ingest one log/status line. Returns True if state changed."""
        if not message:
            return False
        # strip log prefixes like "12:34:56 [信息] "
        text = message.strip()
        text = re.sub(r"^\d{1,2}:\d{2}:\d{2}\s+\[[^\]]+\]\s*", "", text)
        text = text.strip()
        # tqdm control chars
        text = text.replace("\r", "").strip()
        if not text:
            return False

        changed = False
        m_fetch = _RE_FETCHING.search(text)
        if m_fetch:
            self.expected_files = int(m_fetch.group("n"))
            changed = True

        parsed = self._parse_tqdm(text)
        if not parsed:
            return changed

        name, pct, done, total, rate = parsed
        now = time.time()
        is_overall = self._is_overall_name(name)

        if is_overall:
            fp = self.overall or FileProgress(name=name, is_overall=True)
            fp.name = name
            fp.pct = pct
            fp.done_bytes = done
            fp.total_bytes = total
            if rate is not None:
                fp.rate_bps = rate
            fp.updated_at = now
            fp.status = "完成" if pct >= 100 else "下载中"
            fp.is_overall = True
            self.overall = fp
            return True

        # Per-file
        short = self._short_name(name)
        fp = self.files.get(short) or FileProgress(name=short)
        prev_pct = fp.pct
        fp.pct = pct
        fp.done_bytes = done
        fp.total_bytes = total
        if rate is not None:
            fp.rate_bps = rate
        fp.updated_at = now
        if pct >= 99.9:
            fp.status = "完成"
            fp.pct = 100.0
            if short not in self._seen_complete:
                self._seen_complete.add(short)
                self.completed_count = len(self._seen_complete)
        else:
            fp.status = "下载中"
        self.files[short] = fp
        # drop very stale inactive entries only when many files
        if len(self.files) > 80:
            self._prune_stale(now)
        return True if prev_pct != pct or rate else True

    def active_files(self) -> list[FileProgress]:
        now = time.time()
        active = [
            f
            for f in self.files.values()
            if f.status == "下载中" and (now - f.updated_at) <= self.stale_seconds
        ]
        active.sort(key=lambda x: (-x.rate_bps, x.name))
        return active

    def recent_files(self, limit: int = 40) -> list[FileProgress]:
        """Active first, then recently updated completed."""
        now = time.time()
        items = list(self.files.values())
        items.sort(
            key=lambda f: (
                0 if f.status == "下载中" else 1,
                -(f.updated_at),
            )
        )
        # hide ancient completed
        out = []
        for f in items:
            if f.status == "下载中" or (now - f.updated_at) < 600:
                out.append(f)
            if len(out) >= limit:
                break
        return out

    def summary(self) -> dict:
        active = self.active_files()
        total_rate = sum(f.rate_bps for f in active)
        return {
            "active": len(active),
            "completed": self.completed_count,
            "tracked": len(self.files),
            "expected": self.expected_files,
            "active_rate_bps": total_rate,
            "overall": self.overall,
        }

    def _prune_stale(self, now: float) -> None:
        stale = [
            k
            for k, f in self.files.items()
            if f.status == "完成" and (now - f.updated_at) > self.stale_seconds
        ]
        for k in stale[: max(0, len(self.files) - 60)]:
            self.files.pop(k, None)

    @staticmethod
    def _short_name(name: str) -> str:
        name = name.strip()
        # strip long path, keep last 2 segments
        parts = name.replace("\\", "/").split("/")
        if len(parts) > 2:
            return "/".join(parts[-2:])
        return name

    @classmethod
    def _is_overall_name(cls, name: str) -> bool:
        lower = name.lower()
        return any(k in lower for k in cls.OVERALL_NAMES)

    def _parse_tqdm(
        self, text: str
    ) -> tuple[str, float, int, int, float | None] | None:
        m = _RE_TQDM.search(text) or _RE_SIMPLE.search(text)
        if not m:
            return None
        name = m.group("name").strip()
        # strip emoji / noise prefixes sometimes present
        name = re.sub(r"^[\s\|#]+", "", name)
        try:
            pct = float(m.group("pct"))
        except ValueError:
            return None
        done = parse_size_to_bytes(m.group("done")) or 0
        total = parse_size_to_bytes(m.group("total")) or 0
        rate = None
        if "bracket" in m.groupdict() and m.groupdict().get("bracket"):
            rate = parse_rate_to_bps(m.group("bracket"))
        else:
            rate = parse_rate_to_bps(text)
        return name, pct, done, total, rate
