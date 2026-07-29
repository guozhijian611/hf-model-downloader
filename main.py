"""
Main entry point for the Model Downloader application
"""

import logging
import multiprocessing
import os
import platform
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from src.app_logging import (
    get_log_dir,
    install_qt_message_handler,
    setup_app_logging,
    write_crash_report,
)
from src.resource_utils import get_asset_path
from src.ui import MainWindow
from src.version import get_app_version

__version__ = get_app_version()

# Configuration constants
MULTIPROCESSING_START_METHOD = "spawn"
QT_ENV_VARS = {
    "QT_AUTO_SCREEN_SCALE_FACTOR": "1",
    "QT_ENABLE_HIGHDPI_SCALING": "1",
}

ICON_PATHS = {
    "darwin": "icon.icns",
    "windows": "icon.ico",
    "default": "icon.png",
}

logger = logging.getLogger(__name__)


def setup_multiprocessing():
    """Configure multiprocessing for cross-platform compatibility."""
    # Always safe; required for frozen Windows/macOS child processes.
    multiprocessing.freeze_support()
    if getattr(sys, "frozen", False):
        os.environ["PYINSTALLER_HOOKS_DIR"] = "1"
    try:
        multiprocessing.set_start_method(MULTIPROCESSING_START_METHOD, force=True)
    except RuntimeError as e:
        logger.warning("Failed to set multiprocessing method: %s", e)


def setup_environment():
    """Configure environment variables for Qt."""
    for key, value in QT_ENV_VARS.items():
        os.environ[key] = value


def get_icon_path():
    """Get the appropriate icon path based on platform."""
    system = platform.system().lower()
    icon_name = ICON_PATHS.get(system, ICON_PATHS["default"])
    return get_asset_path(icon_name)


def setup_application_icon(app):
    """Set application icon based on platform availability."""
    icon_path = get_icon_path()
    if os.path.exists(icon_path):
        try:
            app.setWindowIcon(QIcon(icon_path))
            logger.info("Application icon loaded from: %s", icon_path)
        except Exception as e:
            logger.warning("Failed to set application icon: %s", e)
    else:
        logger.warning("Icon file not found at: %s", icon_path)


def main():
    """Main application entry point."""
    # File logging + crash hooks as early as possible.
    log_dir = setup_app_logging()
    logger.info("HF Model Downloader v%s starting", get_app_version())
    logger.info("Log directory: %s", log_dir)

    try:
        setup_multiprocessing()
        setup_environment()

        app = QApplication(sys.argv)
        install_qt_message_handler()
        setup_application_icon(app)

        window = MainWindow()
        window.show()
        logger.info("Main window shown")
        code = app.exec()
        logger.info("Application exiting with code %s", code)
        sys.exit(code)

    except Exception as e:
        logger.error("Application error: %s", e, exc_info=True)
        crash_path = write_crash_report(
            "main.exception",
            type(e),
            e,
            e.__traceback__,
        )
        if crash_path:
            logger.error("Crash report written to %s", crash_path)
            logger.error("Log directory: %s", get_log_dir())
        sys.exit(1)


if __name__ == "__main__":
    # freeze_support must run before any GUI/multiprocessing work in frozen builds.
    multiprocessing.freeze_support()
    main()
