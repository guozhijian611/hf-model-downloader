"""Application version helpers."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Keep in sync with pyproject.toml [project].version when packaging as a frozen app.
FALLBACK_VERSION = "0.6.2"


def _read_pyproject_version() -> str | None:
    """Read version from pyproject.toml near this source tree or frozen bundle."""
    candidates: list[Path] = []
    here = Path(__file__).resolve()
    candidates.append(here.parents[1] / "pyproject.toml")
    if getattr(sys, "frozen", False):
        # PyInstaller onedir/onefile layout may place resources next to executable.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "pyproject.toml")
        candidates.append(Path(sys.executable).resolve().parent / "pyproject.toml")

    for path in candidates:
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
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
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("hf-model-downloader")
        except PackageNotFoundError:
            pass
    except Exception:
        pass

    return _read_pyproject_version() or FALLBACK_VERSION


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
