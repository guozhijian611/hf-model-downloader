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

from src.resource_utils import get_asset_path
from src.ui import MainWindow

__version__ = "1.0.0"

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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def setup_multiprocessing():
    """Configure multiprocessing for cross-platform compatibility."""
    try:
        multiprocessing.set_start_method(MULTIPROCESSING_START_METHOD, force=True)
    except RuntimeError as e:
        logger.warning(f"Failed to set multiprocessing method: {e}")

    if getattr(sys, "frozen", False):
        os.environ["PYINSTALLER_HOOKS_DIR"] = "1"
        multiprocessing.freeze_support()


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
            logger.info(f"Application icon loaded from: {icon_path}")
        except Exception as e:
            logger.warning(f"Failed to set application icon: {e}")
    else:
        logger.warning(f"Icon file not found at: {icon_path}")


def main():
    """Main application entry point."""
    try:
        setup_multiprocessing()
        setup_environment()

        app = QApplication(sys.argv)
        setup_application_icon(app)

        window = MainWindow()
        window.show()
        sys.exit(app.exec())

    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
