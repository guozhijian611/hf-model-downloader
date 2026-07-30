"""Floating side window for network + file progress monitors."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, QThread, QTimer, pyqtSignal
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
from .hfd_error_log_panel import HfdErrorLogPanel
from .net_monitor_panel import NetMonitorPanel
from .progress_tracker import DownloadProgressTracker


class _DirScanThread(QThread):
    """Background incomplete-file scan so UI never freezes."""

    result_ready = pyqtSignal(list)  # list[tuple[str, int]] rel_or_path, size

    def __init__(self, tracker: DownloadProgressTracker, parent=None) -> None:
        super().__init__(parent)
        self._tracker = tracker

    def run(self) -> None:
        try:
            root = self._tracker._resolve_scan_dir()
            if root is None:
                self.result_ready.emit([])
                return
            hits = self._tracker._iter_incomplete_files(root)
            # Serialize as (display_name, size) on worker thread
            payload: list[tuple[str, int]] = []
            for path, size in hits:
                name = self._tracker._rel_name(root, path)
                payload.append((name, size))
            self.result_ready.emit(payload)
        except Exception:
            self.result_ready.emit([])


class MonitorWindow(QMainWindow):
    """Independent monitor window (place to the right of the main app)."""

    closed = pyqtSignal()
    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下载监控")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setMinimumSize(400, 480)
        self.resize(440, 600)
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

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

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

        self.net_panel = NetMonitorPanel()
        self.net_panel.set_expanded(True)
        self.net_panel.toggle_btn.setEnabled(False)
        self.net_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.net_panel)

        self.file_panel = DownloadProgressPanel()
        self.file_panel.set_expanded(True)
        self.file_panel.toggle_btn.setEnabled(False)
        self.file_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.file_panel, stretch=1)

        # aria2/hfd download.log live tail (403 / SSL live view)
        self.hfd_log_panel = HfdErrorLogPanel()
        self.hfd_log_panel.set_expanded(True)
        self.hfd_log_panel.prefs_changed.connect(self.prefs_changed.emit)
        root.addWidget(self.hfd_log_panel)

        # Dir scan: infrequent + background thread
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(5000)
        self._scan_timer.timeout.connect(self._request_scan)
        self._watch_dir: str | None = None
        self._repo_dir: str | None = None
        self._scan_active = False
        self._scan_thread: _DirScanThread | None = None
        self._scan_busy = False

        self.setMinimumSize(400, 620)
        self.resize(460, 720)

    def set_watch_path(self, path: str | None) -> None:
        """Save root or repo directory for net/file monitors."""
        self._watch_dir = (path or "").strip() or None
        self.net_panel.set_watch_path(path)
        self.file_panel.set_scan_root(self._watch_dir)

    def set_repo_dir(self, path: str | None) -> None:
        """Dataset/model folder that contains ``.hfd/download.log``."""
        self._repo_dir = (path or "").strip() or None
        # Prefer explicit repo dir; fall back to watch path.
        self.hfd_log_panel.set_watch_path(self._repo_dir or self._watch_dir)

    def start_session(self, *, reset: bool = True) -> None:
        if reset:
            self.file_panel.reset()
            self.net_panel.mark_download_session()
            self.hfd_log_panel.clear_display()
        self._scan_active = True
        if not self._scan_timer.isActive():
            self._scan_timer.start()
        # First scan after a short delay — never block download start
        QTimer.singleShot(1500, self._request_scan)
        # Live-tail aria2 log from current end (huge historical logs stay off-screen).
        self.hfd_log_panel.set_watch_path(self._repo_dir or self._watch_dir)
        self.hfd_log_panel.start(from_end=True)

    def stop_session(self) -> None:
        self._scan_active = False
        # Keep tailing briefly so final errors still appear; user can clear later.
        # Stop only when monitor fully stops.
        # self.hfd_log_panel.stop()

    def feed_log(self, message: str) -> None:
        self.file_panel.feed_log(message)

    def stop(self) -> None:
        self._scan_timer.stop()
        self._scan_active = False
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.wait(500)
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

    def _request_scan(self) -> None:
        if not self._scan_active or self._scan_busy:
            return
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self._scan_busy = True
        thread = _DirScanThread(self.file_panel.tracker, self)
        thread.result_ready.connect(self._on_scan_result)
        thread.finished.connect(lambda: setattr(self, "_scan_busy", False))
        thread.finished.connect(thread.deleteLater)
        self._scan_thread = thread
        thread.start()

    def _on_scan_result(self, payload: list) -> None:
        if not self._scan_active:
            return
        try:
            self.file_panel.apply_scan_hits(payload)
        except Exception:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self.closed.emit()
