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
    list_network_interfaces,
)


class SpeedChartWidget(QWidget):
    """Lightweight dual-series line chart (download / upload)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._down: list[float] = []
        self._up: list[float] = []
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(140)
        self.setToolTip("绿色 = 下载速度，橙色 = 上传速度")

    def set_series(self, down: list[float], up: list[float]) -> None:
        self._down = list(down)
        self._up = list(up)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin_l, margin_r, margin_t, margin_b = 48, 8, 8, 18
        plot_x = margin_l
        plot_y = margin_t
        plot_w = max(1, w - margin_l - margin_r)
        plot_h = max(1, h - margin_t - margin_b)

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e1e"))
        painter.fillRect(plot_x, plot_y, plot_w, plot_h, QColor("#252526"))

        series = self._down or self._up
        n = max(len(self._down), len(self._up), 1)
        max_v = 0.0
        for v in self._down:
            if v > max_v:
                max_v = v
        for v in self._up:
            if v > max_v:
                max_v = v
        if max_v <= 0:
            max_v = 1024.0  # 1 KB/s floor so empty chart isn't flat weird scale
        # Headroom
        max_v *= 1.15

        # Grid + Y labels
        painter.setPen(QPen(QColor("#3c3c3c"), 1))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        for i in range(5):
            y = plot_y + plot_h * i / 4
            painter.drawLine(int(plot_x), int(y), int(plot_x + plot_w), int(y))
            val = max_v * (1 - i / 4)
            painter.setPen(QColor("#9e9e9e"))
            painter.drawText(
                2,
                int(y + 4),
                margin_l - 6,
                14,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_rate(val) if series else "0",
            )
            painter.setPen(QPen(QColor("#3c3c3c"), 1))

        # Border
        painter.setPen(QPen(QColor("#555"), 1))
        painter.drawRect(plot_x, plot_y, plot_w, plot_h)

        def draw_line(values: list[float], color: QColor) -> None:
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
            painter.setPen(QPen(color, 2))
            painter.drawPath(path)

        draw_line(self._down, QColor("#4caf50"))
        draw_line(self._up, QColor("#ff9800"))

        # Legend
        painter.setPen(QColor("#4caf50"))
        painter.drawText(plot_x + 6, plot_y + 14, "↓ 下载")
        painter.setPen(QColor("#ff9800"))
        painter.drawText(plot_x + 64, plot_y + 14, "↑ 上传")

        # X axis hint
        painter.setPen(QColor("#9e9e9e"))
        painter.drawText(
            plot_x,
            h - 4,
            plot_w,
            14,
            Qt.AlignmentFlag.AlignCenter,
            "时间 →（历史窗口）",
        )


class NetMonitorPanel(QFrame):
    """Full monitor panel: controls + chart + metrics."""

    # Emitted when user changes persisted preferences
    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(
            "NetMonitorPanel { background: #fafafa; border: 1px solid #ddd; "
            "border-radius: 6px; }"
        )

        self._monitor = NetworkTrafficMonitor(history_seconds=180, interval_sec=1.0)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # Header / toolbar
        header = QHBoxLayout()
        self.toggle_btn = QPushButton("▼ 网络监控")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: bold; text-align: left; border: none; }"
        )
        self.toggle_btn.toggled.connect(self._on_toggle_body)
        header.addWidget(self.toggle_btn)

        header.addWidget(QLabel("网卡:"))
        self.iface_combo = QComboBox()
        self.iface_combo.setMinimumWidth(160)
        self.iface_combo.setToolTip("选择网卡；「全部(非回环)」汇总主要接口")
        self._refill_ifaces()
        self.iface_combo.currentIndexChanged.connect(self._on_iface_changed)
        header.addWidget(self.iface_combo)

        header.addWidget(QLabel("窗口:"))
        self.window_combo = QComboBox()
        self.window_combo.addItem("1 分钟", 60)
        self.window_combo.addItem("3 分钟", 180)
        self.window_combo.addItem("5 分钟", 300)
        self.window_combo.addItem("10 分钟", 600)
        self.window_combo.setCurrentIndex(1)
        self.window_combo.setToolTip("折线图保留的历史时长")
        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        header.addWidget(self.window_combo)

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setFixedWidth(64)
        self.pause_btn.toggled.connect(self._on_pause_toggled)
        header.addWidget(self.pause_btn)

        self.reset_btn = QPushButton("重置会话")
        self.reset_btn.setFixedWidth(80)
        self.reset_btn.setToolTip("清空总流量 / 峰值 / 平均 / 曲线")
        self.reset_btn.clicked.connect(self._on_reset)
        header.addWidget(self.reset_btn)

        self.refresh_ifaces_btn = QPushButton("刷新网卡")
        self.refresh_ifaces_btn.setFixedWidth(80)
        self.refresh_ifaces_btn.clicked.connect(self._refill_ifaces)
        header.addWidget(self.refresh_ifaces_btn)

        header.addStretch()
        root.addLayout(header)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        self.chart = SpeedChartWidget()
        body_layout.addWidget(self.chart)

        # Metrics grid
        metrics = QGridLayout()
        metrics.setHorizontalSpacing(16)
        metrics.setVerticalSpacing(4)

        def _metric_label(title: str) -> tuple[QLabel, QLabel]:
            t = QLabel(title)
            t.setStyleSheet("color: #666; font-size: 11px;")
            v = QLabel("—")
            v.setStyleSheet("font-weight: bold; font-size: 13px;")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return t, v

        self._lbl_live_down_t, self.lbl_live_down = _metric_label("实时下载")
        self._lbl_live_up_t, self.lbl_live_up = _metric_label("实时上传")
        self._lbl_peak_down_t, self.lbl_peak_down = _metric_label("峰值下载")
        self._lbl_peak_up_t, self.lbl_peak_up = _metric_label("峰值上传")
        self._lbl_total_down_t, self.lbl_total_down = _metric_label("会话总下载")
        self._lbl_total_up_t, self.lbl_total_up = _metric_label("会话总上传")
        self._lbl_avg_down_t, self.lbl_avg_down = _metric_label("平均下载")
        self._lbl_avg_up_t, self.lbl_avg_up = _metric_label("平均上传")
        self._lbl_elapsed_t, self.lbl_elapsed = _metric_label("会话时长")
        self._lbl_samples_t, self.lbl_samples = _metric_label("采样点数")

        rows = [
            (
                self._lbl_live_down_t,
                self.lbl_live_down,
                self._lbl_live_up_t,
                self.lbl_live_up,
            ),
            (
                self._lbl_peak_down_t,
                self.lbl_peak_down,
                self._lbl_peak_up_t,
                self.lbl_peak_up,
            ),
            (
                self._lbl_total_down_t,
                self.lbl_total_down,
                self._lbl_total_up_t,
                self.lbl_total_up,
            ),
            (
                self._lbl_avg_down_t,
                self.lbl_avg_down,
                self._lbl_avg_up_t,
                self.lbl_avg_up,
            ),
            (
                self._lbl_elapsed_t,
                self.lbl_elapsed,
                self._lbl_samples_t,
                self.lbl_samples,
            ),
        ]
        for r, (t1, v1, t2, v2) in enumerate(rows):
            metrics.addWidget(t1, r, 0)
            metrics.addWidget(v1, r, 1)
            metrics.addWidget(t2, r, 2)
            metrics.addWidget(v2, r, 3)

        self.lbl_live_down.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #2e7d32;"
        )
        self.lbl_live_up.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #ef6c00;"
        )

        body_layout.addLayout(metrics)
        root.addWidget(self.body)

        # First sample quickly so UI isn't empty
        self._on_tick()
        self._timer.start()

    # ----- public API for MainWindow settings -----

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

    # ----- internals -----

    def _refill_ifaces(self) -> None:
        current = self.selected_interface() if self.iface_combo.count() else ""
        self.iface_combo.blockSignals(True)
        self.iface_combo.clear()
        self.iface_combo.addItem("全部(非回环)", "")
        for name in list_network_interfaces():
            self.iface_combo.addItem(name, name)
        idx = self.iface_combo.findData(current)
        self.iface_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.iface_combo.blockSignals(False)
        self._monitor.set_interface(self.selected_interface() or None)

    def _on_toggle_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle_btn.setText("▼ 网络监控" if expanded else "▶ 网络监控")
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
        self.chart.set_series([], [])
        self._update_labels()

    def _on_tick(self) -> None:
        self._monitor.tick()
        _, down, up = self._monitor.history_series()
        self.chart.set_series(down, up)
        self._update_labels()

    def _update_labels(self) -> None:
        m = self._monitor
        last = m.last
        s = m.session
        if last is None:
            return
        self.lbl_live_down.setText(format_rate(last.down_bps))
        self.lbl_live_up.setText(format_rate(last.up_bps))
        self.lbl_peak_down.setText(format_rate(s.peak_down_bps))
        self.lbl_peak_up.setText(format_rate(s.peak_up_bps))
        self.lbl_total_down.setText(format_bytes(s.total_down))
        self.lbl_total_up.setText(format_bytes(s.total_up))
        # Wall-clock average is more intuitive for "平均流量"
        self.lbl_avg_down.setText(format_rate(s.overall_avg_down_bps))
        self.lbl_avg_up.setText(format_rate(s.overall_avg_up_bps))
        self.lbl_elapsed.setText(format_duration(s.elapsed))
        self.lbl_samples.setText(str(s.sample_count))
