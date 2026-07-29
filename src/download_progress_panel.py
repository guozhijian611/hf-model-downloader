"""Collapsible panel: per-file download progress table."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .net_monitor import format_rate
from .progress_tracker import DownloadProgressTracker, FileProgress


class DownloadProgressPanel(QFrame):
    """Shows overall + per-file progress parsed from download logs."""

    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(
            "DownloadProgressPanel { background: #fafafa; border: 1px solid #ddd; "
            "border-radius: 6px; }"
        )
        self.tracker = DownloadProgressTracker()
        self._dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(4)

        header = QHBoxLayout()
        self.toggle_btn = QPushButton("▼ 文件进度")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: bold; text-align: left; border: none; }"
        )
        self.toggle_btn.toggled.connect(self._on_toggle)
        header.addWidget(self.toggle_btn)

        self.summary_label = QLabel("等待下载日志…")
        self.summary_label.setStyleSheet("color: #555; font-size: 12px;")
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
        body_layout.setSpacing(4)

        self.overall_label = QLabel("总体：—")
        self.overall_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self.overall_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body_layout.addWidget(self.overall_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["文件", "进度", "已下 / 总量", "速度", "状态"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(180)
        self.table.setMinimumHeight(100)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        body_layout.addWidget(self.table)
        root.addWidget(self.body)

    def is_expanded(self) -> bool:
        return self.toggle_btn.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_btn.setChecked(bool(expanded))

    def reset(self) -> None:
        self.tracker.reset()
        self.table.setRowCount(0)
        self.overall_label.setText("总体：—")
        self.summary_label.setText("等待下载日志…")

    def feed_log(self, message: str) -> None:
        if self.tracker.feed(message):
            self._dirty = True
            self.refresh_view()

    def refresh_view(self) -> None:
        summary = self.tracker.summary()
        overall: FileProgress | None = summary["overall"]
        if overall:
            rate = format_rate(overall.rate_bps) if overall.rate_bps else "—"
            self.overall_label.setText(
                f"总体：{overall.pct:.1f}%  "
                f"{overall.size_text}  "
                f"速度 {rate}  "
                f"[{overall.status}]"
            )
        else:
            self.overall_label.setText("总体：—（尚未解析到 incomplete total 行）")

        expected = summary["expected"]
        exp_txt = f"/{expected}" if expected else ""
        self.summary_label.setText(
            f"活跃 {summary['active']}  "
            f"已完成 {summary['completed']}{exp_txt}  "
            f"跟踪 {summary['tracked']}  "
            f"活跃合计 {format_rate(summary['active_rate_bps'])}"
        )

        rows = self.tracker.recent_files(limit=50)
        if overall:
            # put overall-like synthetic only in label; table is files
            pass
        self.table.setRowCount(len(rows))
        for i, fp in enumerate(rows):
            self._set_row(i, fp)
        self._dirty = False

    def _set_row(self, row: int, fp: FileProgress) -> None:
        items = [
            fp.name,
            f"{fp.pct:.1f}%",
            fp.size_text,
            format_rate(fp.rate_bps) if fp.rate_bps else "—",
            fp.status,
        ]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            if col == 4:
                if fp.status == "完成":
                    item.setForeground(Qt.GlobalColor.darkGreen)
                else:
                    item.setForeground(Qt.GlobalColor.darkBlue)
            self.table.setItem(row, col, item)

    def _on_toggle(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle_btn.setText("▼ 文件进度" if expanded else "▶ 文件进度")
        self.prefs_changed.emit()
