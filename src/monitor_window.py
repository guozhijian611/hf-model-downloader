"""Floating side window for network + file progress monitors."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .download_progress_panel import DownloadProgressPanel
from .net_monitor_panel import NetMonitorPanel


class MonitorWindow(QMainWindow):
    """Independent monitor window (place to the right of the main app)."""

    closed = pyqtSignal()
    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        # Parent kept for lifetime; window is independent (not modal).
        super().__init__(parent)
        self.setWindowTitle("下载监控")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setMinimumSize(420, 520)
        self.resize(480, 640)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel("📊 下载监控")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.pin_checkbox = QCheckBox("置顶")
        self.pin_checkbox.setToolTip("保持监控窗在最前")
        self.pin_checkbox.toggled.connect(self._on_pin_toggled)
        toolbar.addWidget(self.pin_checkbox)

        self.dock_right_btn = QPushButton("贴到主窗右侧")
        self.dock_right_btn.setToolTip("将本窗移到主窗口右边")
        self.dock_right_btn.clicked.connect(self.place_right_of_parent)
        toolbar.addWidget(self.dock_right_btn)
        root.addLayout(toolbar)

        self.net_panel = NetMonitorPanel()
        self.net_panel.set_expanded(True)
        # In floating window, collapse chrome is less useful — keep body open.
        self.net_panel.toggle_btn.setEnabled(False)
        self.net_panel.toggle_btn.setText("网络 / 磁盘")
        self.net_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.net_panel)

        self.file_panel = DownloadProgressPanel()
        self.file_panel.set_expanded(True)
        self.file_panel.toggle_btn.setEnabled(False)
        self.file_panel.toggle_btn.setText("文件进度")
        self.file_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.file_panel, stretch=1)

        tip = QLabel(
            "提示：huggingface-hub 日志往往只有总体进度；"
            "分文件列表会结合下载目录扫描 incomplete 文件。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #777; font-size: 11px;")
        root.addWidget(tip)

        # Dir scan timer (complements log parsing)
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(2000)
        self._scan_timer.timeout.connect(self._on_scan_tick)
        self._watch_dir: str | None = None
        self._scan_active = False

    # ----- public API (proxied for MainWindow) -----

    def set_watch_path(self, path: str | None) -> None:
        self._watch_dir = (path or "").strip() or None
        self.net_panel.set_watch_path(path)
        self.file_panel.set_scan_root(self._watch_dir)

    def start_session(self, *, reset: bool = True) -> None:
        if reset:
            self.file_panel.reset()
            self.net_panel.mark_download_session()
        self._scan_active = True
        if not self._scan_timer.isActive():
            self._scan_timer.start()

    def stop_session(self) -> None:
        self._scan_active = False

    def feed_log(self, message: str) -> None:
        self.file_panel.feed_log(message)

    def stop(self) -> None:
        self._scan_timer.stop()
        self.net_panel.stop()

    def place_right_of_parent(self) -> None:
        """Move this window to the right of the parent main window."""
        parent = self.parent()
        if parent is None or not isinstance(parent, QWidget):
            self._ensure_on_screen()
            return
        main: QWidget = parent.window() if parent.window() else parent
        mg = main.frameGeometry()
        # Prefer same top, to the right with a small gap
        x = mg.right() + 8
        y = mg.top()
        self.move(x, y)
        self._ensure_on_screen()

    def show_and_place(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        # Delay place so frameGeometry of main is valid
        QTimer.singleShot(50, self.place_right_of_parent)

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
        # If it would hang mostly off the right edge, put it left of main
        parent = self.parent()
        if parent is not None and isinstance(parent, QWidget):
            main = parent.window() if parent.window() else parent
            mg = main.frameGeometry()
            if x + geo.width() > avail.right() - 20:
                x = max(avail.x(), mg.left() - geo.width() - 8)
        self.move(QPoint(x, y))

    def _on_pin_toggled(self, pinned: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        # Re-show required after changing window flags
        self.show()

    def _on_scan_tick(self) -> None:
        if not self._scan_active:
            return
        self.file_panel.scan_directory()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Hide instead of destroy so MainWindow can reopen quickly
        event.ignore()
        self.hide()
        self.closed.emit()
