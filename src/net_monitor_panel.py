"""Collapsible network traffic monitor panel with history line chart."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .net_monitor import (
    NetworkTrafficMonitor,
    format_bytes,
    format_duration,
    format_rate,
    format_rate_compact,
    list_network_interfaces,
)


class SpeedChartWidget(QWidget):
    """Lightweight line chart: download / upload / disk write."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._down: list[float] = []
        self._up: list[float] = []
        self._disk_w: list[float] = []
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(130)
        self.setToolTip(
            "绿=下载  橙=上传  蓝=磁盘写\n"
            "下载长期明显高于磁盘写 → 可能先堆内存再掉速"
        )

    def set_series(
        self,
        down: list[float],
        up: list[float],
        disk_w: list[float] | None = None,
    ) -> None:
        self._down = list(down)
        self._up = list(up)
        self._disk_w = list(disk_w or [])
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin_l, margin_r, margin_t, margin_b = 40, 8, 6, 16
        plot_x = margin_l
        plot_y = margin_t
        plot_w = max(1, w - margin_l - margin_r)
        plot_h = max(1, h - margin_t - margin_b)

        painter.fillRect(0, 0, w, h, QColor("#1a1d23"))
        painter.fillRect(plot_x, plot_y, plot_w, plot_h, QColor("#22262e"))

        n = max(len(self._down), len(self._up), len(self._disk_w), 1)
        max_v = 0.0
        for values in (self._down, self._up, self._disk_w):
            for v in values:
                if v > max_v:
                    max_v = v
        if max_v <= 0:
            max_v = 1024.0
        max_v *= 1.12

        font = QFont()
        font.setPixelSize(10)
        painter.setFont(font)
        for i in range(4):
            y = plot_y + plot_h * i / 3
            painter.setPen(QPen(QColor("#333842"), 1))
            painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))
            val = max_v * (1 - i / 3)
            painter.setPen(QColor("#8b929e"))
            # Center label on grid line; avoid clipping
            painter.drawText(
                2,
                int(y - 7),
                margin_l - 6,
                14,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_rate_compact(val),
            )

        painter.setPen(QPen(QColor("#3d4450"), 1))
        painter.drawRect(plot_x, plot_y, plot_w - 1, plot_h - 1)

        def draw_line(values: list[float], color: QColor, width: int = 2) -> None:
            if len(values) < 2:
                return
            path = QPainterPath()
            for i, v in enumerate(values):
                x = plot_x + (plot_w * i / max(1, n - 1))
                y = plot_y + plot_h * (1.0 - min(1.0, max(0.0, v / max_v)))
                if i == 0:
                    path.moveTo(QPointF(x, y))
                else:
                    path.lineTo(QPointF(x, y))
            painter.setPen(QPen(color, width))
            painter.drawPath(path)

        draw_line(self._down, QColor("#4caf50"))
        draw_line(self._up, QColor("#ff9800"))
        draw_line(self._disk_w, QColor("#42a5f5"))

        painter.setPen(QColor("#4caf50"))
        painter.drawText(plot_x + 6, plot_y + 12, "↓")
        painter.setPen(QColor("#ff9800"))
        painter.drawText(plot_x + 22, plot_y + 12, "↑")
        painter.setPen(QColor("#42a5f5"))
        painter.drawText(plot_x + 38, plot_y + 12, "盘")


def _stat_card(title: str, color: str) -> tuple[QFrame, QLabel]:
    card = QFrame()
    card.setStyleSheet(
        """
        QFrame {
            background: #f7f8fa;
            border: 1px solid #e6e8ec;
            border-radius: 8px;
        }
        """
    )
    lay = QVBoxLayout(card)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(
        "color: #888; font-size: 11px; border: none; background: transparent;"
    )
    v = QLabel("—")
    v.setStyleSheet(
        f"color: {color}; font-size: 16px; font-weight: 700; border: none; "
        "background: transparent;"
    )
    v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lay.addWidget(t)
    lay.addWidget(v)
    return card, v


class NetMonitorPanel(QFrame):
    """Full monitor panel: controls + chart + metrics."""

    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setStyleSheet("NetMonitorPanel { background: transparent; border: none; }")

        self._monitor = NetworkTrafficMonitor(history_seconds=180, interval_sec=1.0)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # Header / toolbar
        header = QHBoxLayout()
        self.toggle_btn = QPushButton("网络 / 磁盘")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: 600; text-align: left; border: none; "
            "font-size: 13px; color: #222; }"
        )
        self.toggle_btn.toggled.connect(self._on_toggle_body)
        header.addWidget(self.toggle_btn)

        self.iface_combo = QComboBox()
        self.iface_combo.setMinimumWidth(120)
        self.iface_combo.setToolTip("选择网卡；「全部」汇总主要接口")
        self._refill_ifaces()
        self.iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        header.addWidget(self.iface_combo)

        self.window_combo = QComboBox()
        self.window_combo.addItem("1分", 60)
        self.window_combo.addItem("3分", 180)
        self.window_combo.addItem("5分", 300)
        self.window_combo.addItem("10分", 600)
        self.window_combo.setCurrentIndex(1)
        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        header.addWidget(self.window_combo)

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setFixedWidth(52)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        header.addWidget(self.pause_btn)

        self.reset_btn = QPushButton("重置")
        self.reset_btn.setFixedWidth(48)
        self.reset_btn.setToolTip("清空会话统计与曲线")
        self.reset_btn.clicked.connect(self._on_reset)
        header.addWidget(self.reset_btn)

        self.refresh_ifaces_btn = QPushButton("网卡")
        self.refresh_ifaces_btn.setFixedWidth(44)
        self.refresh_ifaces_btn.setToolTip("刷新网卡列表")
        self.refresh_ifaces_btn.clicked.connect(self._refill_ifaces)
        header.addWidget(self.refresh_ifaces_btn)
        header.addStretch()
        root.addLayout(header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        # Big live stats
        cards = QHBoxLayout()
        cards.setSpacing(8)
        c1, self.lbl_live_down = _stat_card("实时下载", "#2e7d32")
        c2, self.lbl_disk_w = _stat_card("磁盘写入", "#1565c0")
        c3, self.lbl_avg_down = _stat_card("平均下载", "#5d4037")
        c4, self.lbl_peak_down = _stat_card("峰值下载", "#6a1b9a")
        for c in (c1, c2, c3, c4):
            cards.addWidget(c, 1)
        body_layout.addLayout(cards)

        self.chart = SpeedChartWidget()
        body_layout.addWidget(self.chart)

        # Secondary row
        sub = QGridLayout()
        sub.setHorizontalSpacing(12)
        sub.setVerticalSpacing(2)

        def _mini(title: str) -> tuple[QLabel, QLabel]:
            t = QLabel(title)
            t.setStyleSheet("color: #999; font-size: 11px;")
            v = QLabel("—")
            v.setStyleSheet("color: #444; font-size: 12px; font-weight: 600;")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return t, v

        self._t1, self.lbl_total_down = _mini("会话下载")
        self._t2, self.lbl_total_disk = _mini("会话写入")
        self._t3, self.lbl_elapsed = _mini("时长")
        self._t4, self.lbl_free = _mini("磁盘剩余")
        self._t5, self.lbl_live_up = _mini("上传")
        self._t6, self.lbl_peak_disk = _mini("峰值写盘")
        pairs = [
            (self._t1, self.lbl_total_down),
            (self._t2, self.lbl_total_disk),
            (self._t3, self.lbl_elapsed),
            (self._t4, self.lbl_free),
            (self._t5, self.lbl_live_up),
            (self._t6, self.lbl_peak_disk),
        ]
        for i, (t, v) in enumerate(pairs):
            sub.addWidget(t, 0 if i < 3 else 1, (i % 3) * 2)
            sub.addWidget(v, 0 if i < 3 else 1, (i % 3) * 2 + 1)
        body_layout.addLayout(sub)

        root.addWidget(self.body)

        self._on_tick()
        self._timer.start()

    def is_expanded(self) -> bool:
        return self.toggle_btn.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_btn.setChecked(bool(expanded))

    def selected_interface(self) -> str:
        data = self.iface_combo.currentData()
        return data if isinstance(data, str) else ""

    def set_selected_interface(self, name: str) -> None:
        name = name or ""
        idx = self.iface_combo.findData(name)
        if idx < 0:
            idx = 0
        self.iface_combo.blockSignals(True)
        self.iface_combo.setCurrentIndex(idx)
        self.iface_combo.blockSignals(False)
        self._monitor.set_interface(name or None)

    def history_seconds(self) -> int:
        data = self.window_combo.currentData()
        return int(data) if data else 180

    def set_history_seconds(self, seconds: int) -> None:
        for i in range(self.window_combo.count()):
            if int(self.window_combo.itemData(i) or 0) == int(seconds):
                self.window_combo.blockSignals(True)
                self.window_combo.setCurrentIndex(i)
                self.window_combo.blockSignals(False)
                self._monitor.set_history_seconds(int(seconds))
                return
        self._monitor.set_history_seconds(int(seconds))

    def stop(self) -> None:
        self._timer.stop()

    def set_watch_path(self, path: str | None) -> None:
        self._monitor.set_watch_path(path)

    def mark_download_session(self) -> None:
        self._monitor.reset_session()
        self.chart.set_series([], [], [])
        self._update_labels()

    def _refill_ifaces(self) -> None:
        current = self.selected_interface() if self.iface_combo.count() else ""
        self.iface_combo.blockSignals(True)
        self.iface_combo.clear()
        self.iface_combo.addItem("全部", "")
        for name in list_network_interfaces():
            self.iface_combo.addItem(name, name)
        idx = self.iface_combo.findData(current)
        self.iface_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.iface_combo.blockSignals(False)
        self._monitor.set_interface(self.selected_interface() or None)

    def _on_toggle_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.prefs_changed.emit()

    def _on_iface_changed(self, _index: int = 0) -> None:
        self._monitor.set_interface(self.selected_interface() or None)
        self.prefs_changed.emit()

    def _on_window_changed(self, _index: int = 0) -> None:
        self._monitor.set_history_seconds(self.history_seconds())
        self.prefs_changed.emit()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._monitor.set_paused(paused)
        self.pause_btn.setText("继续" if paused else "暂停")

    def _on_reset(self) -> None:
        self._monitor.reset_session()
        self.chart.set_series([], [], [])
        self._update_labels()

    def _on_tick(self) -> None:
        self._monitor.tick()
        _, down, up, disk_w = self._monitor.history_series()
        self.chart.set_series(down, up, disk_w)
        self._update_labels()

    def _update_labels(self) -> None:
        m = self._monitor
        last = m.last
        s = m.session
        if last is None:
            return
        self.lbl_live_down.setText(format_rate(last.down_bps))
        self.lbl_disk_w.setText(format_rate(last.disk_write_bps))
        self.lbl_avg_down.setText(format_rate(s.overall_avg_down_bps))
        self.lbl_peak_down.setText(format_rate(s.peak_down_bps))
        self.lbl_total_down.setText(format_bytes(s.total_down))
        self.lbl_total_disk.setText(format_bytes(s.total_disk_write))
        self.lbl_elapsed.setText(format_duration(s.elapsed))
        self.lbl_live_up.setText(format_rate(last.up_bps))
        self.lbl_peak_disk.setText(format_rate(s.peak_disk_write_bps))
        if m.disk_free_bytes is not None and m.disk_total_bytes:
            free_pct = 100.0 * m.disk_free_bytes / max(1, m.disk_total_bytes)
            free_txt = format_bytes(m.disk_free_bytes)
            self.lbl_free.setText(f"{free_txt} ({free_pct:.0f}%)")
        else:
            self.lbl_free.setText("—")
