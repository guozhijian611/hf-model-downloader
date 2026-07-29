"""Collapsible panel: per-file download progress table."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .net_monitor import format_rate
from .progress_tracker import DownloadProgressTracker, FileProgress


class DownloadProgressPanel(QFrame):
    """Shows overall + per-file progress parsed from download logs / disk."""

    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(
            """
            DownloadProgressPanel {
                background: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
            }
            QTableWidget {
                border: 1px solid #eee;
                border-radius: 4px;
                gridline-color: #f0f0f0;
                background: #fafafa;
            }
            QHeaderView::section {
                background: #f5f5f5;
                padding: 4px 6px;
                border: none;
                border-bottom: 1px solid #e0e0e0;
                font-weight: 600;
            }
            """
        )
        self.tracker = DownloadProgressTracker()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        self.toggle_btn = QPushButton("▼ 文件进度")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: 600; text-align: left; border: none; "
            "font-size: 13px; }"
        )
        self.toggle_btn.toggled.connect(self._on_toggle)
        header.addWidget(self.toggle_btn)

        self.summary_label = QLabel("等待下载…")
        self.summary_label.setStyleSheet("color: #666; font-size: 12px;")
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header.addWidget(self.summary_label, stretch=1)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedWidth(56)
        self.clear_btn.clicked.connect(self.reset)
        header.addWidget(self.clear_btn)
        root.addLayout(header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        self.overall_label = QLabel("总体：—")
        self.overall_label.setStyleSheet("font-weight: 600; font-size: 12px;")
        self.overall_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body_layout.addWidget(self.overall_label)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 1000)
        self.overall_bar.setValue(0)
        self.overall_bar.setTextVisible(True)
        self.overall_bar.setFormat("%p%")
        self.overall_bar.setFixedHeight(18)
        self.overall_bar.setStyleSheet(
            """
            QProgressBar {
                border: 1px solid #ddd;
                border-radius: 4px;
                background: #f0f0f0;
                text-align: center;
                font-size: 11px;
            }
            QProgressBar::chunk {
                background: #43a047;
                border-radius: 3px;
            }
            """
        )
        body_layout.addWidget(self.overall_bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["文件", "进度", "已下 / 总量", "速度", "状态"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(140)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        body_layout.addWidget(self.table)

        self.empty_hint = QLabel(
            "尚无分文件信息。\n"
            "· 总体进度来自日志 incomplete total\n"
            "· 分文件来自日志 或 扫描目录中的 *.incomplete"
        )
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet("color: #999; font-size: 11px; padding: 12px;")
        self.empty_hint.setWordWrap(True)
        body_layout.addWidget(self.empty_hint)

        root.addWidget(self.body)

    def is_expanded(self) -> bool:
        return self.toggle_btn.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_btn.setChecked(bool(expanded))

    def set_scan_root(self, path: str | None, repo_id: str | None = None) -> None:
        self.tracker.set_scan_root(path, repo_id=repo_id)

    def scan_directory(self) -> None:
        if self.tracker.scan_directory():
            self.refresh_view()

    def apply_scan_hits(self, hits: list[tuple[str, int]]) -> None:
        """Apply background scan results: list of (display_name, size)."""
        import time as _time

        from .progress_tracker import FileProgress

        now = _time.time()
        found: set[str] = set()
        changed = False
        for name, size in hits[:40]:
            key = self.tracker._short_name(name)
            found.add(key)
            rate = 0.0
            prev = self.tracker._disk_prev.get(key)
            if prev is not None:
                prev_size, prev_t = prev
                dt = max(1e-3, now - prev_t)
                delta = size - prev_size
                if delta >= 0:
                    rate = delta / dt
            self.tracker._disk_prev[key] = (size, now)
            existing = self.tracker.files.get(key)
            if (
                existing
                and existing.source == "log"
                and (now - existing.updated_at) < 5
            ):
                continue
            fp = existing or FileProgress(name=key, source="disk")
            fp.done_bytes = int(size)
            if rate > 0:
                fp.rate_bps = rate
            fp.status = "下载中"
            fp.updated_at = now
            fp.source = "disk"
            self.tracker.files[key] = fp
            changed = True

        for key, fp in list(self.tracker.files.items()):
            if fp.source != "disk" or key in found:
                continue
            if fp.status == "下载中" and (now - fp.updated_at) > 8:
                fp.status = "完成"
                fp.pct = 100.0
                fp.updated_at = now
                changed = True

        if len(self.tracker.files) > 60:
            self.tracker._prune_stale(now)
        if changed or hits:
            self.refresh_view()

    def reset(self) -> None:
        self.tracker.reset()
        self.table.setRowCount(0)
        self.overall_label.setText("总体：—")
        self.overall_bar.setValue(0)
        self.summary_label.setText("等待下载…")
        self.empty_hint.setVisible(True)

    def feed_log(self, message: str) -> None:
        if self.tracker.feed(message):
            self.refresh_view()

    def refresh_view(self) -> None:
        summary = self.tracker.summary()
        overall: FileProgress | None = summary["overall"]
        if overall:
            rate = format_rate(overall.rate_bps) if overall.rate_bps else "—"
            pct = overall.pct
            if overall.total_bytes > 0 and overall.done_bytes > 0:
                computed = 100.0 * overall.done_bytes / overall.total_bytes
                if pct < 0.05 and computed >= 0.05:
                    pct = computed
            self.overall_label.setText(
                f"总体：{pct:.2f}%  {overall.size_text}  "
                f"速度 {rate}  [{overall.status}]"
            )
            self.overall_bar.setValue(int(min(1000, max(0, pct * 10))))
            self.overall_bar.setFormat(f"{pct:.2f}%")
        else:
            self.overall_label.setText("总体：—（等待 incomplete total 日志）")
            self.overall_bar.setValue(0)
            self.overall_bar.setFormat("%p%")

        expected = summary["expected"]
        exp_txt = f"/{expected}" if expected else ""
        self.summary_label.setText(
            f"活跃 {summary['active']}  "
            f"完成 {summary['completed']}{exp_txt}  "
            f"跟踪 {summary['tracked']}  "
            f"速度 {format_rate(summary['active_rate_bps'])}"
        )

        rows = self.tracker.recent_files(limit=20)
        self.empty_hint.setVisible(len(rows) == 0)
        self.table.setRowCount(len(rows))
        for i, fp in enumerate(rows):
            self._set_row(i, fp)

    def _set_row(self, row: int, fp: FileProgress) -> None:
        pct = fp.pct
        if fp.total_bytes > 0 and fp.done_bytes > 0 and pct < 0.05:
            pct = 100.0 * fp.done_bytes / fp.total_bytes
        items = [
            fp.name,
            f"{pct:.1f}%",
            fp.size_text,
            format_rate(fp.rate_bps) if fp.rate_bps else "—",
            fp.status if not fp.is_overall else "总体",
        ]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            if fp.is_overall:
                item.setForeground(QColor("#1565c0"))
            elif col == 4:
                if fp.status == "完成":
                    item.setForeground(QColor("#2e7d32"))
                else:
                    item.setForeground(QColor("#ef6c00"))
            if col == 0 and fp.source == "disk":
                item.setToolTip("来自磁盘扫描 (*.incomplete)")
            self.table.setItem(row, col, item)

    def _on_toggle(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle_btn.setText("▼ 文件进度" if expanded else "▶ 文件进度")
        self.prefs_changed.emit()
