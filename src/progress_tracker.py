"""Parse huggingface-hub / tqdm progress + scan local incomplete files."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

# "name:  12%|...| 1.2G/10G [00:01<00:10, 100MB/s]"
# Bar chars may be ascii or unicode blocks; make the middle optional.
_RE_TQDM = re.compile(
    r"^(?P<name>.+?):\s+(?P<pct>\d+(?:\.\d+)?)%\s*"
    r"(?:\|[^|]*\|)?\s*"
    r"(?P<done>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"\s*/\s*"
    r"(?P<total>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"(?:\s*\[(?P<bracket>[^\]]*)\])?",
    re.IGNORECASE,
)

# Fallback without bar: "name: 50% 1G/2G"
_RE_SIMPLE = re.compile(
    r"^(?P<name>.+?):\s+(?P<pct>\d+(?:\.\d+)?)%\s+"
    r"(?P<done>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"\s*/\s*"
    r"(?P<total>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)",
    re.IGNORECASE,
)

# Bare incomplete-total without requiring colon name carefully
_RE_LOOSE_PROGRESS = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)%\s*"
    r"(?:\|[^|]*\|)?\s*"
    r"(?P<done>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"\s*/\s*"
    r"(?P<total>[\d.,]+\s*[kKmMgGtTpPeE]?i?[bB]?)"
    r"(?:\s*\[(?P<bracket>[^\]]*)\])?",
    re.IGNORECASE,
)

_RE_RATE = re.compile(
    r"([\d.,]+)\s*([kKmMgGtTpPeE]?i?)[bB]?/s",
    re.IGNORECASE,
)

_RE_FETCHING = re.compile(
    r"Fetching\s+(?P<n>\d+)\s+files",
    re.IGNORECASE,
)

# "Fetching 50 files:  20%|..| 10/50"
_RE_FETCHING_COUNT = re.compile(
    r"Fetching\s+(?P<total>\d+)\s+files:\s*"
    r"(?P<pct>\d+(?:\.\d+)?)%\s*"
    r"(?:\|[^|]*\|\s*)?"
    r"(?P<done>\d+)\s*/\s*(?P<total2>\d+)",
    re.IGNORECASE,
)

_SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
}


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
        try:
            return int(float(s))
        except ValueError:
            return None
    value = float(m.group(1))
    unit = (m.group(2) or "").upper()
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
    source: str = "log"  # log | disk

    @property
    def size_text(self) -> str:
        from .net_monitor import format_bytes

        if self.total_bytes > 0:
            return f"{format_bytes(self.done_bytes)} / {format_bytes(self.total_bytes)}"
        if self.done_bytes > 0:
            return f"{format_bytes(self.done_bytes)} / ?"
        return "—"


class DownloadProgressTracker:
    """Track overall + per-file progress from logs and disk scan."""

    OVERALL_NAMES = (
        "downloading",
        "incomplete total",
        "fetching",
        "总体",
        "total",
        "files",
    )

    def __init__(self, *, stale_seconds: float = 120.0) -> None:
        self.stale_seconds = stale_seconds
        self.files: dict[str, FileProgress] = {}
        self.overall: FileProgress | None = None
        self.expected_files: int | None = None
        self.completed_count = 0
        self._seen_complete: set[str] = set()
        self._disk_prev: dict[str, tuple[int, float]] = {}
        self.scan_root: str | None = None
        self.repo_subdir: str | None = None  # optional model folder name

    def reset(self) -> None:
        self.files.clear()
        self.overall = None
        self.expected_files = None
        self.completed_count = 0
        self._seen_complete.clear()
        self._disk_prev.clear()

    def set_scan_root(self, path: str | None, repo_id: str | None = None) -> None:
        self.scan_root = (path or "").strip() or None
        if repo_id:
            # download_core saves under save_path / last_segment
            self.repo_subdir = repo_id.strip().split("/")[-1]
        else:
            self.repo_subdir = None

    def feed(self, message: str) -> bool:
        """Ingest one log/status line. Returns True if state changed."""
        if not message:
            return False
        text = message.strip()
        # strip log prefixes like "12:34:56 [信息] "
        text = re.sub(r"^\d{1,2}:\d{2}:\d{2}\s+\[[^\]]+\]\s*", "", text)
        # strip leading icons / info markers
        text = re.sub(r"^[ℹ️❌⏹️✅⚠️🔧\s]+", "", text)
        text = text.replace("\r", "").strip()
        if not text:
            return False

        changed = False

        # Structured per-file lines from parallel hub download:
        # [HF_FILE]\tname\tn\ttotal\tstatus
        if text.startswith("[HF_FILE]\t"):
            parts = text.split("\t")
            if len(parts) >= 4:
                name = parts[1]
                try:
                    done = int(parts[2])
                    total = int(parts[3])
                except ValueError:
                    return False
                status = parts[4] if len(parts) > 4 else "downloading"
                short = self._short_name(name)
                fp = self.files.get(short) or FileProgress(name=short, source="log")
                fp.done_bytes = done
                fp.total_bytes = total
                if total > 0:
                    fp.pct = min(100.0, 100.0 * done / total)
                prev = self._disk_prev.get(short)
                now = time.time()
                if prev is not None:
                    prev_n, prev_t = prev
                    dt = max(1e-3, now - prev_t)
                    delta = done - prev_n
                    if delta >= 0:
                        fp.rate_bps = delta / dt
                self._disk_prev[short] = (done, now)
                fp.updated_at = now
                fp.source = "log"
                if status == "done" or (total > 0 and done >= total):
                    fp.status = "完成"
                    fp.pct = 100.0
                    if short not in self._seen_complete:
                        self._seen_complete.add(short)
                        self.completed_count = max(
                            self.completed_count, len(self._seen_complete)
                        )
                else:
                    fp.status = "下载中"
                self.files[short] = fp
                # overall from sum of tracked files (approx for active set)
                self._recompute_overall_from_files()
                return True
            return False

        if text.startswith("[HF_META]\t"):
            parts = text.split("\t")
            if len(parts) >= 3 and parts[1] == "files":
                try:
                    self.expected_files = int(parts[2])
                    return True
                except ValueError:
                    return False
            if len(parts) >= 3 and parts[1] == "done_files":
                try:
                    self.completed_count = max(self.completed_count, int(parts[2]))
                    return True
                except ValueError:
                    return False

        m_fetch = _RE_FETCHING.search(text)
        if m_fetch:
            self.expected_files = int(m_fetch.group("n"))
            changed = True

        m_fc = _RE_FETCHING_COUNT.search(text)
        if m_fc:
            try:
                self.expected_files = int(m_fc.group("total"))
                done_n = int(m_fc.group("done"))
                self.completed_count = max(self.completed_count, done_n)
                changed = True
            except ValueError:
                pass
            # "Fetching N files: x%| | a/b" is file-count progress, not byte sizes.
            return changed

        # Pure "Fetching N files" without counts — don't parse as tqdm sizes.
        if re.match(r"^Fetching\s+\d+\s+files\s*$", text, re.I):
            return changed

        parsed = self._parse_tqdm(text)
        if not parsed:
            # Last resort: if line mentions incomplete total / Downloading
            if re.search(r"incomplete\s*total|Downloading", text, re.I):
                loose = _RE_LOOSE_PROGRESS.search(text)
                if loose:
                    try:
                        pct = float(loose.group("pct"))
                    except ValueError:
                        return changed
                    done = parse_size_to_bytes(loose.group("done")) or 0
                    total = parse_size_to_bytes(loose.group("total")) or 0
                    rate = parse_rate_to_bps(loose.group("bracket") or text)
                    self._set_overall(
                        "Downloading (incomplete total…)",
                        pct,
                        done,
                        total,
                        rate,
                    )
                    return True
            return changed

        name, pct, done, total, rate = parsed
        now = time.time()
        is_overall = self._is_overall_name(name)

        if is_overall:
            self._set_overall(name, pct, done, total, rate)
            return True

        # Per-file from log
        short = self._short_name(name)
        fp = self.files.get(short) or FileProgress(name=short, source="log")
        fp.pct = pct
        fp.done_bytes = done
        fp.total_bytes = total
        if rate is not None:
            fp.rate_bps = rate
        fp.updated_at = now
        fp.source = "log"
        if pct >= 99.9 or (total > 0 and done >= total):
            fp.status = "完成"
            fp.pct = 100.0
            if short not in self._seen_complete:
                self._seen_complete.add(short)
                self.completed_count = max(
                    self.completed_count, len(self._seen_complete)
                )
        else:
            fp.status = "下载中"
        self.files[short] = fp
        if len(self.files) > 100:
            self._prune_stale(now)
        return True

    def scan_directory(self) -> bool:
        """Scan save dir for .incomplete / active partial files."""
        root = self._resolve_scan_dir()
        if root is None or not root.is_dir():
            return False

        now = time.time()
        found_keys: set[str] = set()
        changed = False
        try:
            candidates = self._iter_incomplete_files(root)
        except OSError:
            return False

        for path, done_bytes in candidates:
            rel = self._rel_name(root, path)
            key = self._short_name(rel)
            found_keys.add(key)

            # Estimate rate from size deltas
            rate = 0.0
            prev = self._disk_prev.get(key)
            if prev is not None:
                prev_size, prev_t = prev
                dt = max(1e-3, now - prev_t)
                delta = done_bytes - prev_size
                if delta >= 0:
                    rate = delta / dt
            self._disk_prev[key] = (done_bytes, now)

            # Prefer not to overwrite fresher log entries with lower info
            existing = self.files.get(key)
            if (
                existing
                and existing.source == "log"
                and (now - existing.updated_at) < 5
            ):
                continue

            fp = existing or FileProgress(name=key, source="disk")
            fp.done_bytes = done_bytes
            # unknown total for incomplete unless name has size — leave 0
            if fp.total_bytes > 0:
                fp.pct = min(99.9, 100.0 * done_bytes / max(1, fp.total_bytes))
            else:
                fp.pct = 0.0
            if rate > 0:
                fp.rate_bps = rate
            fp.status = "下载中"
            fp.updated_at = now
            fp.source = "disk"
            self.files[key] = fp
            changed = True

        # Mark disk-sourced files that disappeared as completed
        for key, fp in list(self.files.items()):
            if fp.source != "disk":
                continue
            if key in found_keys:
                continue
            if fp.status == "下载中" and (now - fp.updated_at) > 3:
                # file left incomplete state — likely finished rename
                fp.status = "完成"
                fp.pct = 100.0
                fp.updated_at = now
                if key not in self._seen_complete:
                    self._seen_complete.add(key)
                    self.completed_count = max(
                        self.completed_count, len(self._seen_complete)
                    )
                changed = True

        if len(self.files) > 100:
            self._prune_stale(now)
        return changed

    def active_files(self) -> list[FileProgress]:
        now = time.time()
        active = [
            f
            for f in self.files.values()
            if f.status == "下载中" and (now - f.updated_at) <= self.stale_seconds
        ]
        active.sort(key=lambda x: (-x.rate_bps, -x.done_bytes, x.name))
        return active

    def recent_files(self, limit: int = 50) -> list[FileProgress]:
        """Active first, then recently updated. Include overall as first row."""
        now = time.time()
        items = list(self.files.values())
        items.sort(
            key=lambda f: (
                0 if f.status == "下载中" else 1,
                -f.updated_at,
            )
        )
        out: list[FileProgress] = []
        # Always surface overall as a synthetic first row when present
        if self.overall:
            o = FileProgress(
                name="【总体】" + (self.overall.name[:40] if self.overall.name else ""),
                pct=self.overall.pct,
                done_bytes=self.overall.done_bytes,
                total_bytes=self.overall.total_bytes,
                rate_bps=self.overall.rate_bps,
                status=self.overall.status,
                updated_at=self.overall.updated_at,
                is_overall=True,
                source="log",
            )
            # Prefer computed pct if tqdm rounded to 0
            if o.total_bytes > 0 and o.done_bytes > 0:
                computed = 100.0 * o.done_bytes / o.total_bytes
                if o.pct < 0.05 and computed >= 0.05:
                    o.pct = computed
            out.append(o)

        for f in items:
            if f.status == "下载中" or (now - f.updated_at) < 600:
                out.append(f)
            if len(out) >= limit:
                break
        return out

    def summary(self) -> dict:
        active = self.active_files()
        total_rate = sum(f.rate_bps for f in active)
        if self.overall and self.overall.rate_bps and not total_rate:
            total_rate = self.overall.rate_bps
        return {
            "active": len(active),
            "completed": self.completed_count,
            "tracked": len(self.files),
            "expected": self.expected_files,
            "active_rate_bps": total_rate,
            "overall": self.overall,
        }

    # ----- internals -----

    def _recompute_overall_from_files(self) -> None:
        """Build a rough overall bar from known file rows + expected count."""
        if not self.files:
            return
        done = sum(f.done_bytes for f in self.files.values())
        total = sum(f.total_bytes for f in self.files.values() if f.total_bytes > 0)
        rate = sum(f.rate_bps for f in self.files.values() if f.status == "下载中")
        pct = 0.0
        if total > 0:
            pct = 100.0 * done / total
        elif self.expected_files and self.completed_count:
            pct = 100.0 * self.completed_count / max(1, self.expected_files)
        self._set_overall("并发文件合计（近似）", pct, done, total, rate)

    def _set_overall(
        self,
        name: str,
        pct: float,
        done: int,
        total: int,
        rate: float | None,
    ) -> None:
        now = time.time()
        fp = self.overall or FileProgress(name=name, is_overall=True)
        fp.name = name
        # Recompute pct if tqdm shows 0% but bytes say otherwise
        if total > 0 and done > 0:
            computed = 100.0 * done / total
            if pct < 0.05 and computed >= 0.05:
                pct = computed
        fp.pct = pct
        fp.done_bytes = done
        fp.total_bytes = total
        if rate is not None:
            fp.rate_bps = rate
        fp.updated_at = now
        fp.status = "完成" if pct >= 100 else "下载中"
        fp.is_overall = True
        self.overall = fp

    def _resolve_scan_dir(self) -> Path | None:
        if not self.scan_root:
            return None
        root = Path(self.scan_root)
        if self.repo_subdir:
            candidate = root / self.repo_subdir
            if candidate.is_dir():
                return candidate
        return root if root.is_dir() else None

    def _iter_incomplete_files(self, root: Path) -> list[tuple[Path, int]]:
        """Find incomplete files quickly — prefer HF cache, hard budget."""
        import os
        import time as _time

        out: list[tuple[Path, int]] = []
        deadline = _time.monotonic() + 0.35  # hard cap so UI never freezes
        max_hits = 40
        max_stat = 800  # max files we even look at

        # Prefer known HF/aria2 hotspots first (cheap, high signal).
        priority_dirs: list[Path] = []
        for rel in (
            Path(".cache") / "huggingface" / "download",
            Path(".cache") / "huggingface",
            Path(".cache"),
        ):
            p = root / rel
            if p.is_dir():
                priority_dirs.append(p)
        priority_dirs.append(root)

        seen_dirs: set[str] = set()
        stats = 0

        def _consider(path: Path) -> None:
            nonlocal stats
            if len(out) >= max_hits or _time.monotonic() > deadline:
                return
            stats += 1
            if stats > max_stat:
                return
            try:
                size = path.stat().st_size
            except OSError:
                return
            if size > 0:
                out.append((path, size))

        for base in priority_dirs:
            key = str(base.resolve()) if base.exists() else str(base)
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            if _time.monotonic() > deadline or len(out) >= max_hits:
                break

            # Shallow-first walk with aggressive pruning.
            for dirpath, dirnames, filenames in os.walk(base):
                if _time.monotonic() > deadline or len(out) >= max_hits:
                    break
                if dirpath != str(base):
                    depth = Path(dirpath).relative_to(base).parts
                else:
                    depth = ()
                # Don't recurse forever into huge shard trees.
                if len(depth) > 4:
                    dirnames[:] = []
                    continue
                # Prune junk; keep .cache only at top
                pruned = []
                for d in dirnames:
                    if d in _SKIP_DIR_NAMES:
                        continue
                    if d.startswith(".") and d != ".cache":
                        continue
                    pruned.append(d)
                dirnames[:] = pruned

                for name in filenames:
                    if _time.monotonic() > deadline or len(out) >= max_hits:
                        break
                    lower = name.lower()
                    if not (
                        lower.endswith(".incomplete")
                        or lower.endswith(".aria2")
                        or lower.endswith(".part")
                        or ".incomplete." in lower
                    ):
                        continue
                    _consider(Path(dirpath) / name)

                # Only full-walk the first priority cache dir deeply;
                # for repo root, stop after one level of incomplete hits.
                if base == root and len(depth) >= 1 and len(out) >= 8:
                    dirnames[:] = []

        out.sort(key=lambda x: -x[1])
        return out[:max_hits]

    @staticmethod
    def _rel_name(root: Path, path: Path) -> str:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        # strip incomplete suffix for display
        for suf in (".incomplete", ".aria2", ".tmp", ".part"):
            if rel.lower().endswith(suf):
                rel = rel[: -len(suf)]
                break
        # Hash-like cache blobs: show short tail
        parts = rel.replace("\\", "/").split("/")
        name = parts[-1]
        if len(name) > 28 and not any(
            name.endswith(ext)
            for ext in (
                ".parquet",
                ".safetensors",
                ".bin",
                ".gguf",
                ".json",
                ".txt",
                ".arrow",
            )
        ):
            # e.g. shards/000/<hash> → shards/000/<hash[:10]…>
            short = name[:10] + "…" + name[-4:] if len(name) > 16 else name
            if len(parts) >= 2:
                return f"{parts[-2]}/{short}"
            return short
        if len(parts) > 2:
            return "/".join(parts[-2:])
        return rel.replace("\\", "/")

    def _prune_stale(self, now: float) -> None:
        stale = [
            k
            for k, f in self.files.items()
            if f.status == "完成" and (now - f.updated_at) > self.stale_seconds
        ]
        for k in stale[: max(0, len(self.files) - 60)]:
            self.files.pop(k, None)
            self._disk_prev.pop(k, None)

    @staticmethod
    def _short_name(name: str) -> str:
        name = name.strip()
        parts = name.replace("\\", "/").split("/")
        if len(parts) > 3:
            return "/".join(parts[-3:])
        return name

    @classmethod
    def _is_overall_name(cls, name: str) -> bool:
        lower = name.lower()
        if any(k in lower for k in cls.OVERALL_NAMES):
            return True
        # "Fetching 12 files" style already handled; bare "Files"
        return lower.startswith("download")

    def _parse_tqdm(
        self, text: str
    ) -> tuple[str, float, int, int, float | None] | None:
        m = _RE_TQDM.search(text) or _RE_SIMPLE.search(text)
        if not m:
            return None
        name = m.group("name").strip()
        name = re.sub(r"^[\s\|#ℹ️]+", "", name)
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
