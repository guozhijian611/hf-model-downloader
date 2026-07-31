"""Floating side window for network/disk stats and hfd error log."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .hfd_error_log_panel import HfdErrorLogPanel
from .net_monitor_panel import NetMonitorPanel


class MonitorWindow(QMainWindow):
    """Independent monitor window (place to the right of the main app)."""

    closed = pyqtSignal()
    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下载监控")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setMinimumSize(380, 360)
        self.resize(420, 520)
        self.setStyleSheet(
            """
            QMainWindow { background: #ffffff; }
            QPushButton {
                padding: 4px 10px;
                border: 1px solid #ddd;
                border-radius: 6px;
                background: #fafafa;
            }
            QPushButton:hover { background: #f0f0f0; }
            QComboBox {
                padding: 3px 6px;
                border: 1px solid #ddd;
                border-radius: 6px;
                background: #fff;
            }
            """
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        central = QWidget()
        scroll.setWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(12)

        toolbar = QHBoxLayout()
        title = QLabel("下载监控")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #1a1a1a;")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.pin_checkbox = QCheckBox("置顶")
        self.pin_checkbox.setToolTip("保持监控窗在最前")
        self.pin_checkbox.toggled.connect(self._on_pin_toggled)
        toolbar.addWidget(self.pin_checkbox)

        self.dock_right_btn = QPushButton("贴右侧")
        self.dock_right_btn.setToolTip("将本窗移到主窗口右边")
        self.dock_right_btn.clicked.connect(self.place_right_of_parent)
        toolbar.addWidget(self.dock_right_btn)
        root.addLayout(toolbar)

        # Network / disk (collapsible)
        self.net_panel = NetMonitorPanel()
        self.net_panel.set_expanded(True)
        self.net_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.net_panel)

        # aria2/hfd error log (collapsible, default collapsed to reduce clutter)
        self.hfd_log_panel = HfdErrorLogPanel()
        self.hfd_log_panel.set_expanded(False)
        self.hfd_log_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.hfd_log_panel)

        root.addStretch(1)

        self._watch_dir: str | None = None
        self._repo_dir: str | None = None

    def set_watch_path(self, path: str | None) -> None:
        """Save root for disk free / write monitoring."""
        self._watch_dir = (path or "").strip() or None
        self.net_panel.set_watch_path(path)

    def set_repo_dir(self, path: str | None) -> None:
        """Dataset/model folder that contains ``.hfd/download.log``."""
        self._repo_dir = (path or "").strip() or None
        self.hfd_log_panel.set_watch_path(self._repo_dir or self._watch_dir)

    def start_session(self, *, reset: bool = True) -> None:
        if reset:
            self.net_panel.mark_download_session()
            self.hfd_log_panel.clear_display()
        self.hfd_log_panel.set_watch_path(self._repo_dir or self._watch_dir)
        self.hfd_log_panel.start(from_end=True)

    def stop_session(self) -> None:
        """Download stopped; keep net chart running, stop is optional for log."""
        return

    def feed_log(self, message: str) -> None:
        """Kept for API compatibility; file progress panel removed."""
        _ = message

    def stop(self) -> None:
        self.net_panel.stop()
        self.hfd_log_panel.stop()

    def place_right_of_parent(self) -> None:
        parent = self.parent()
        if parent is None or not isinstance(parent, QWidget):
            self._ensure_on_screen()
            return
        main: QWidget = parent.window() if parent.window() else parent
        mg = main.frameGeometry()
        self.move(mg.right() + 8, mg.top())
        self._ensure_on_screen()

    def show_and_place(self) -> None:
        self.show()
        self.raise_()
        QTimer.singleShot(30, self.place_right_of_parent)

    def _ensure_on_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail: QRect = screen.availableGeometry()
        geo = self.frameGeometry()
        x = min(max(geo.x(), avail.x()), avail.right() - geo.width() + 1)
        y = min(max(geo.y(), avail.y()), avail.bottom() - geo.height() + 1)
        parent = self.parent()
        if parent is not None and isinstance(parent, QWidget):
            main = parent.window() if parent.window() else parent
            mg = main.frameGeometry()
            if x + geo.width() > avail.right() - 20:
                x = max(avail.x(), mg.left() - geo.width() - 8)
        self.move(QPoint(x, y))

    def _on_pin_toggled(self, pinned: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        self.show()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.closed.emit()
