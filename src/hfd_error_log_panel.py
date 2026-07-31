"""Real-time tail panel for hfd/aria2 download.log (403/SSL diagnostics)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Keep UI responsive for multi-MB logs.
_MAX_UI_LINES = 800
_READ_CHUNK = 256 * 1024


class HfdErrorLogPanel(QFrame):
    """
    Tails ``{repo}/.hfd/download.log`` written by aria2 under hfd.

    This is the file that contains status=403 / SSL handshake failures —
    not the main window QTextEdit (which only shows hfd stdout summaries).
    """

    prefs_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setStyleSheet(
            """
            HfdErrorLogPanel {
                background: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
            }
            """
        )

        self._log_path: Path | None = None
        self._offset = 0
        self._pending = ""
        self._ui_line_count = 0
        self._sess_err = 0
        self._sess_403 = 0
        self._sess_ssl = 0
        self._active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)

        header = QHBoxLayout()
        self.toggle_btn = QPushButton("▶ aria2 / hfd 错误日志")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(False)
        self.toggle_btn.setStyleSheet(
            "QPushButton { font-weight: 600; text-align: left; border: none; "
            "font-size: 13px; }"
        )
        self.toggle_btn.setToolTip("点击展开/收起 aria2 错误日志")
        self.toggle_btn.toggled.connect(self._on_toggle)
        header.addWidget(self.toggle_btn)

        self.summary_label = QLabel("未绑定下载目录")
        self.summary_label.setStyleSheet("color: #666; font-size: 11px;")
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.summary_label.setWordWrap(True)
        header.addWidget(self.summary_label, stretch=1)
        root.addLayout(header)

        self._content = QWidget()
        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("过滤："))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("全部新行", "all")
        self.filter_combo.addItem("仅 ERROR", "error")
        self.filter_combo.addItem("仅 403 / SSL", "critical")
        self.filter_combo.setToolTip(
            "日志文件：{保存目录}/.hfd/download.log\n"
            "aria2 把 403/SSL 写在这里，主界面默认看不到。"
        )
        self.filter_combo.currentIndexChanged.connect(
            lambda _i: self.prefs_changed.emit()
        )
        tools.addWidget(self.filter_combo)

        self.autoscroll_cb = QCheckBox("自动滚底")
        self.autoscroll_cb.setChecked(True)
        tools.addWidget(self.autoscroll_cb)

        self.clear_btn = QPushButton("清空显示")
        self.clear_btn.setFixedWidth(72)
        self.clear_btn.clicked.connect(self.clear_display)
        tools.addWidget(self.clear_btn)

        self.open_btn = QPushButton("打开文件")
        self.open_btn.setFixedWidth(72)
        self.open_btn.setToolTip("用系统默认程序打开 download.log")
        self.open_btn.clicked.connect(self._open_log_file)
        tools.addWidget(self.open_btn)
        tools.addStretch()
        cl.addLayout(tools)

        self.path_label = QLabel("")
        self.path_label.setStyleSheet("color: #888; font-size: 10px;")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setWordWrap(True)
        cl.addWidget(self.path_label)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(140)
        self.text.setMaximumHeight(280)
        font = QFont("Consolas", 9)
        if not font.exactMatch():
            font = QFont("Courier New", 9)
        self.text.setFont(font)
        self.text.setStyleSheet(
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; "
            "border: 1px solid #333; border-radius: 4px; }"
        )
        cl.addWidget(self.text)
        root.addWidget(self._content)
        # Default collapsed (header stays visible).
        self._content.setVisible(False)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)

    def _on_toggle(self, expanded: bool) -> None:
        self.toggle_btn.setText(
            "▼ aria2 / hfd 错误日志" if expanded else "▶ aria2 / hfd 错误日志"
        )
        self._content.setVisible(expanded)
        self.prefs_changed.emit()

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        self.toggle_btn.blockSignals(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.blockSignals(False)
        self.toggle_btn.setText(
            "▼ aria2 / hfd 错误日志" if expanded else "▶ aria2 / hfd 错误日志"
        )
        self._content.setVisible(expanded)

    def set_watch_path(self, path: str | None) -> None:
        """``path`` is the model/dataset local directory (contains .hfd/)."""
        root = (path or "").strip()
        if not root:
            self._log_path = None
            self.path_label.setText("")
            self.summary_label.setText("未绑定下载目录")
            return
        log = Path(root) / ".hfd" / "download.log"
        self._log_path = log
        self.path_label.setText(f"文件：{log}")
        self.summary_label.setText(f"监视：{log.name}")
        # Next start/poll can jump to end for huge existing logs.
        self._offset = -1
        self._pending = ""

    def start(self, *, from_end: bool = True) -> None:
        self._active = True
        self._sess_err = 0
        self._sess_403 = 0
        self._sess_ssl = 0
        if from_end and self._log_path and self._log_path.is_file():
            try:
                self._offset = self._log_path.stat().st_size
            except OSError:
                self._offset = 0
        elif self._offset < 0:
            self._offset = 0
        self._pending = ""
        if not self._timer.isActive():
            self._timer.start()
        self._poll()

    def stop(self) -> None:
        self._active = False
        self._timer.stop()

    def clear_display(self) -> None:
        self.text.clear()
        self._ui_line_count = 0

    def _filter_mode(self) -> str:
        return str(self.filter_combo.currentData() or "all")

    def _open_log_file(self) -> None:
        if not self._log_path:
            return
        path = self._log_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                path.write_text("", encoding="utf-8")
        except OSError:
            pass
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception:
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            except Exception:
                pass

    def _poll(self) -> None:
        if not self._active or self._log_path is None:
            return
        path = self._log_path
        if not path.is_file():
            self.summary_label.setText("等待 download.log …（hfd/aria2 启动后生成）")
            return

        try:
            size = path.stat().st_size
        except OSError:
            return

        if self._offset < 0:
            self._offset = size

        if size < self._offset:
            self._offset = 0
            self._pending = ""

        if size == self._offset:
            self._update_summary(path, size, new_lines=0)
            return

        try:
            with path.open("rb") as f:
                f.seek(self._offset)
                raw = f.read(_READ_CHUNK)
                self._offset = f.tell()
                if size - self._offset > _READ_CHUNK * 4:
                    self._offset = max(0, size - _READ_CHUNK)
        except OSError:
            return

        if not raw:
            return

        text = self._pending + raw.decode("utf-8", errors="replace")
        last_nl = max(text.rfind("\n"), text.rfind("\r"))
        if last_nl == -1:
            self._pending = text
            self._update_summary(path, size, new_lines=0)
            return
        chunk = text[: last_nl + 1]
        self._pending = text[last_nl + 1 :]

        mode = self._filter_mode()
        added = 0
        for line in chunk.splitlines():
            line = line.rstrip("\r")
            if not line.strip():
                continue
            low = line.lower()
            is_err = "[error]" in low or "exception:" in low
            is_403 = "status=403" in low or " 403" in low
            is_ssl = "ssl/tls" in low or "handshake failure" in low
            if is_err:
                self._sess_err += 1
            if is_403:
                self._sess_403 += 1
            if is_ssl:
                self._sess_ssl += 1

            if mode == "error" and not (is_err or is_403 or is_ssl):
                continue
            if mode == "critical" and not (is_403 or is_ssl):
                continue

            self._append_line(line, is_403=is_403, is_ssl=is_ssl, is_err=is_err)
            added += 1

        self._update_summary(path, size, new_lines=added)

    def _append_line(
        self,
        line: str,
        *,
        is_403: bool,
        is_ssl: bool,
        is_err: bool,
    ) -> None:
        if is_403:
            color = "#f48771"
        elif is_ssl:
            color = "#ce9178"
        elif is_err:
            color = "#dcdcaa"
        else:
            color = "#d4d4d4"

        display = _shorten_line(line)
        html = f'<span style="color:{color}">{_escape(display)}</span>'
        self.text.append(html)
        self._ui_line_count += 1

        if self._ui_line_count > _MAX_UI_LINES:
            cursor = self.text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.KeepAnchor,
                self._ui_line_count - _MAX_UI_LINES,
            )
            cursor.removeSelectedText()
            self._ui_line_count = _MAX_UI_LINES

        if self.autoscroll_cb.isChecked():
            sb = self.text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _update_summary(self, path: Path, size: int, *, new_lines: int) -> None:
        mb = size / (1024 * 1024)
        extra = f"  (+{new_lines})" if new_lines else ""
        self.summary_label.setText(
            f"本次会话 ERROR≈{self._sess_err}  403≈{self._sess_403}  "
            f"SSL≈{self._sess_ssl}  |  文件 {mb:.2f} MB{extra}"
        )


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_LONG_QUERY_RE = re.compile(r"(\?[^ \t]{80})")


def _shorten_line(line: str, max_len: int = 320) -> str:
    line = _LONG_QUERY_RE.sub("?…", line)
    if len(line) > max_len:
        return line[: max_len - 1] + "…"
    return line
