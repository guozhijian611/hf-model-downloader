"""Application version helpers."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Last-resort fallback when no other version source is available.
FALLBACK_VERSION = "0.13.0"


def _read_version_data_module() -> str | None:
    try:
        from .version_data import __version__

        value = (__version__ or "").strip()
        return value or None
    except Exception:
        return None


def _candidate_resource_roots() -> list[Path]:
    roots: list[Path] = []
    here = Path(__file__).resolve()
    roots.append(here.parents[1])  # project root in dev
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        exe_dir = Path(sys.executable).resolve().parent
        roots.append(exe_dir)
        # macOS .app: Contents/MacOS -> Contents/Resources sometimes used
        roots.append(exe_dir.parent / "Resources")
    return roots


def _read_version_file() -> str | None:
    for root in _candidate_resource_roots():
        for name in ("VERSION", "pyproject.toml"):
            path = root / name
            try:
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                if name == "VERSION":
                    value = text.strip().splitlines()[0].strip() if text.strip() else ""
                    if value:
                        return value.lstrip("vV")
                else:
                    match = re.search(
                        r'(?m)^version\s*=\s*["\']([^"\']+)["\']',
                        text,
                    )
                    if match:
                        return match.group(1).strip()
            except OSError:
                continue
    return None


def get_app_version() -> str:
    """Return the running app version string (without leading 'v')."""
    for reader in (
        _read_version_data_module,
        _read_version_file,
    ):
        value = reader()
        if value:
            return normalize_version(value)

    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return normalize_version(version("hf-model-downloader"))
        except PackageNotFoundError:
            pass
    except Exception:
        pass

    return FALLBACK_VERSION


def normalize_version(version: str | None) -> str:
    """Strip leading 'v' and whitespace."""
    return (version or "").strip().lstrip("vV")


def parse_version_tuple(version: str | None) -> tuple[int, ...]:
    """Parse a loose semver-like string into an int tuple for comparison."""
    cleaned = normalize_version(version)
    if not cleaned:
        return (0, 0, 0)

    parts: list[int] = []
    for chunk in cleaned.split("."):
        match = re.match(r"(\d+)", chunk)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_remote_newer(local: str, remote: str) -> bool:
    """Return True when remote version is strictly newer than local."""
    return parse_version_tuple(remote) > parse_version_tuple(local)
