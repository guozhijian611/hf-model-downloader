"""Runtime and crash logging for the desktop app."""

from __future__ import annotations

import faulthandler
import logging
import os
import platform
import sys
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .version import get_app_version

APP_LOG_DIRNAME = "hf-model-downloader"
RUNTIME_LOG_NAME = "runtime.log"
LAST_CRASH_LOG_NAME = "last_crash.log"

_LOG_DIR: Path | None = None
_FAULT_FILE = None
_CONFIGURED = False


def get_log_dir() -> Path:
    """Return platform-specific writable log directory (created if needed)."""
    global _LOG_DIR
    if _LOG_DIR is not None:
        return _LOG_DIR

    system = platform.system().lower()
    home = Path.home()
    if system == "darwin":
        base = home / "Library" / "Logs" / APP_LOG_DIRNAME
    elif system.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        base = Path(local) / APP_LOG_DIRNAME / "logs"
    else:
        xdg = os.environ.get("XDG_STATE_HOME") or str(home / ".local" / "state")
        base = Path(xdg) / APP_LOG_DIRNAME / "logs"

    base.mkdir(parents=True, exist_ok=True)
    _LOG_DIR = base
    return base


def get_runtime_log_path() -> Path:
    return get_log_dir() / RUNTIME_LOG_NAME


def get_last_crash_log_path() -> Path:
    return get_log_dir() / LAST_CRASH_LOG_NAME


def _format_env_banner() -> str:
    frozen = getattr(sys, "frozen", False)
    exe = sys.executable
    return "\n".join(
        [
            "=" * 72,
            f"time={datetime.now().isoformat(timespec='seconds')}",
            f"version={get_app_version()}",
            f"python={sys.version.replace(chr(10), ' ')}",
            f"platform={platform.platform()}",
            f"machine={platform.machine()}",
            f"frozen={frozen}",
            f"executable={exe}",
            f"cwd={os.getcwd()}",
            f"pid={os.getpid()}",
            "=" * 72,
        ]
    )


def write_crash_report(
    kind: str,
    exc_type=None,
    exc_value=None,
    exc_tb=None,
    extra: str | None = None,
) -> Path | None:
    """Write a crash report file and append a short note to runtime.log."""
    try:
        log_dir = get_log_dir()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        crash_path = log_dir / f"crash-{stamp}.log"
        last_path = get_last_crash_log_path()

        parts = [
            _format_env_banner(),
            f"crash_kind={kind}",
            "",
        ]
        if exc_type is not None:
            parts.append(
                "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            )
        if extra:
            parts.append(extra)
        body = "\n".join(parts).rstrip() + "\n"

        crash_path.write_text(body, encoding="utf-8")
        last_path.write_text(body, encoding="utf-8")

        logging.getLogger("crash").error(
            "崩溃已记录：%s (last=%s)", crash_path, last_path
        )
        return crash_path
    except Exception:
        # Last resort: stderr only
        try:
            traceback.print_exc()
        except Exception:
            pass
        return None


def _excepthook(exc_type, exc_value, exc_tb):
    write_crash_report("sys.excepthook", exc_type, exc_value, exc_tb)
    # Also print default traceback
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _threading_excepthook(args):
    # Python 3.8+ threading.excepthook
    write_crash_report(
        "threading.excepthook",
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
        extra=f"thread_name={getattr(args.thread, 'name', None)}",
    )


def setup_app_logging(level: int = logging.INFO) -> Path:
    """
    Configure console + rotating runtime file logging and crash hooks.

    Returns the log directory path.
    """
    global _CONFIGURED, _FAULT_FILE
    log_dir = get_log_dir()
    if _CONFIGURED:
        return log_dir

    runtime_path = get_runtime_log_path()
    root = logging.getLogger()
    root.setLevel(level)

    # Clear handlers that basicConfig may have attached earlier.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        runtime_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Native crash / fatal signal dumps (best-effort).
    try:
        fault_path = log_dir / "faulthandler.log"
        _FAULT_FILE = open(fault_path, "a", encoding="utf-8")  # noqa: SIM115
        _FAULT_FILE.write("\n" + _format_env_banner() + "\n")
        _FAULT_FILE.flush()
        faulthandler.enable(file=_FAULT_FILE, all_threads=True)
    except Exception as e:
        logging.getLogger(__name__).warning("无法启用 faulthandler：%s", e)

    sys.excepthook = _excepthook
    try:
        import threading

        if hasattr(threading, "excepthook"):
            threading.excepthook = _threading_excepthook
    except Exception:
        pass

    # Qt message handler (installed later when Qt is available).
    logging.getLogger(__name__).info("日志目录：%s", log_dir)
    logging.getLogger(__name__).info("运行日志：%s", runtime_path)
    logging.getLogger(__name__).info("\n%s", _format_env_banner())

    _CONFIGURED = True
    return log_dir


def install_qt_message_handler() -> None:
    """Route Qt internal messages into Python logging / crash file for fatals."""
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception as e:
        logging.getLogger(__name__).warning("无法安装 Qt 日志钩子：%s", e)
        return

    logger = logging.getLogger("qt")

    def _qt_handler(mode, context, message):
        text = str(message)
        where = ""
        try:
            if context is not None:
                cfile = getattr(context, "file", "?")
                cline = getattr(context, "line", "?")
                where = f" ({cfile}:{cline})"
        except Exception:
            pass
        line = text + where
        if mode == QtMsgType.QtFatalMsg:
            logger.critical(line)
            write_crash_report("qt.fatal", extra=line)
        elif mode == QtMsgType.QtCriticalMsg:
            logger.error(line)
        elif mode == QtMsgType.QtWarningMsg:
            logger.warning(line)
        elif mode == QtMsgType.QtInfoMsg:
            logger.info(line)
        else:
            logger.debug(line)

    qInstallMessageHandler(_qt_handler)
    logging.getLogger(__name__).info("已安装 Qt 消息处理器")
