import logging
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .app_logging import get_last_crash_log_path, get_log_dir, get_runtime_log_path
from .app_settings import load_form_settings, save_form_settings
from .endpoints import (
    build_endpoint_chain,
    default_endpoint,
    preset_labels,
    url_from_combo_text,
)
from .hfd_backend import (
    BACKEND_CHOICES,
    BACKEND_HFD,
    BACKEND_HUB,
    can_auto_install_hfd_deps,
    hfd_availability,
    missing_hfd_deps,
    missing_hfd_required_deps,
    run_hfd_deps_install,
)
from .monitor_window import MonitorWindow
from .proxy_env import normalize_proxy
from .resource_utils import get_asset_path
from .unified_downloader import UnifiedDownloadWorker
from .update_check import (
    UpdateApplyWorker,
    UpdateCheckResult,
    UpdateCheckWorker,
    is_frozen_install,
    launch_updater_and_exit,
)
from .version import get_app_version

GITHUB_REPO_URL = "https://github.com/guozhijian611/hf-model-downloader"
AUTHOR_NAME = "guozhijian611"
AUTHOR_GITHUB_URL = "https://github.com/guozhijian611"

logger = logging.getLogger(__name__)


class _HfdDepsInstallWorker(QThread):
    """Background installer for aria2 / bash used by hfd backend."""

    log_line = pyqtSignal(str)
    finished_ok = pyqtSignal(bool, str)

    def run(self) -> None:
        ok, summary = run_hfd_deps_install(log_cb=self.log_line.emit)
        self.finished_ok.emit(ok, summary)


class MainWindow(QMainWindow):
    # Background stall-hook command finished (msg, is_error)
    stall_hook_finished = pyqtSignal(str, bool)

    def __init__(self):
        super().__init__()
        self.app_version = get_app_version()
        self.setWindowTitle(f"HF Model Downloader v{self.app_version}")
        logger.info("MainWindow init, version=%s", self.app_version)

        # Set window icon based on platform
        system = platform.system().lower()
        if system == "darwin":
            icon_path = get_asset_path("icon.icns")
        elif system == "windows":
            icon_path = get_asset_path("icon.ico")
        else:
            icon_path = get_asset_path("icon.png")

        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        main_widget = QWidget()
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        standard_button_height = 32

        icon_layout = QHBoxLayout()
        icon_layout.setContentsMargins(10, 10, 10, 0)

        self.platform_button_group = QButtonGroup()
        self.platform_button_group.setExclusive(True)

        self.hf_button = QPushButton()
        hf_icon_path = get_asset_path("huggingface_logo.png")
        if os.path.exists(hf_icon_path):
            self.hf_button.setIcon(QIcon(hf_icon_path))
            self.hf_button.setIconSize(QSize(32, 32))
        self.hf_button.setCheckable(True)
        self.hf_button.setChecked(True)
        self.hf_button.setStyleSheet("""
            QPushButton {
                border: 2px solid #ddd;
                border-radius: 6px;
                padding: 8px;
                background-color: white;
            }
            QPushButton:hover {
                border-color: #FFD21E;
                background-color: #fffbf0;
            }
            QPushButton:checked {
                border-color: #FFD21E;
                background-color: #fff8e1;
            }
        """)
        self.platform_button_group.addButton(self.hf_button, 0)

        self.ms_button = QPushButton()
        ms_icon_path = get_asset_path("modelscope_logo.png")
        if os.path.exists(ms_icon_path):
            self.ms_button.setIcon(QIcon(ms_icon_path))
            self.ms_button.setIconSize(QSize(32, 32))
        self.ms_button.setCheckable(True)
        self.ms_button.setStyleSheet("""
            QPushButton {
                border: 2px solid #ddd;
                border-radius: 6px;
                padding: 8px;
                background-color: white;
            }
            QPushButton:hover {
                border-color: #1677FF;
                background-color: #f0f8ff;
            }
            QPushButton:checked {
                border-color: #1677FF;
                background-color: #e6f3ff;
            }
        """)
        self.platform_button_group.addButton(self.ms_button, 1)

        self.platform_button_group.idClicked.connect(self.on_platform_icon_changed)

        icon_layout.addWidget(self.hf_button)
        icon_layout.addWidget(self.ms_button)
        icon_layout.addStretch()

        layout.addLayout(icon_layout)

        help_frame = QFrame()
        help_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        help_layout = QVBoxLayout(help_frame)

        help_title = QLabel("📖 快速指南")
        help_title.setStyleSheet("font-weight: bold; font-size: 12px;")
        help_layout.addWidget(help_title)

        guide_content_layout = QHBoxLayout()

        help_text = QLabel(
            "1. 选择平台（Hugging Face / ModelScope）\n"
            "2. 填写模型或数据集 ID\n"
            "3. 选择保存目录\n"
            "4. 可选：Token / 代理 / Endpoint\n"
            "5. 下载方式可选 huggingface-hub 或 hfd/aria2\n"
            "6. 可勾选失败自动重试 / 卡住无速度自动重启\n"
            "7. 点击下载（会记住上次输入）\n"
        )
        help_text.setWordWrap(True)
        help_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        guide_content_layout.addWidget(help_text)

        links_layout = QVBoxLayout()
        links_layout.addStretch()
        self.browse_models_btn = QPushButton("🔍 浏览模型")
        self.browse_models_btn.setMaximumWidth(150)
        self.browse_models_btn.setFixedHeight(standard_button_height)
        self.browse_models_btn.clicked.connect(self.open_models_page)
        self.browse_datasets_btn = QPushButton("📊 浏览数据集")
        self.browse_datasets_btn.setMaximumWidth(150)
        self.browse_datasets_btn.setFixedHeight(standard_button_height)
        self.browse_datasets_btn.clicked.connect(self.open_datasets_page)
        self.get_token_btn = QPushButton("🔑 获取 Token")
        self.get_token_btn.setMaximumWidth(150)
        self.get_token_btn.setFixedHeight(standard_button_height)
        self.get_token_btn.clicked.connect(self.open_token_page)
        self.check_update_btn = QPushButton("🔄 检查更新")
        self.check_update_btn.setMaximumWidth(150)
        self.check_update_btn.setFixedHeight(standard_button_height)
        self.check_update_btn.setToolTip("从 GitHub Releases 检查是否有新版本")
        self.check_update_btn.clicked.connect(self.check_for_updates)
        self.open_logs_btn = QPushButton("📋 打开日志")
        self.open_logs_btn.setMaximumWidth(150)
        self.open_logs_btn.setFixedHeight(standard_button_height)
        self.open_logs_btn.setToolTip("打开运行日志 / 崩溃日志目录")
        self.open_logs_btn.clicked.connect(self.open_log_folder)
        self.monitor_btn = QPushButton("📊 监控面板")
        self.monitor_btn.setMaximumWidth(150)
        self.monitor_btn.setFixedHeight(standard_button_height)
        self.monitor_btn.setToolTip("打开右侧悬浮监控窗（网速 / 磁盘 / 文件进度）")
        self.monitor_btn.clicked.connect(self.toggle_monitor_window)

        links_layout.addWidget(self.browse_models_btn)
        links_layout.addWidget(self.browse_datasets_btn)
        links_layout.addWidget(self.get_token_btn)
        links_layout.addWidget(self.check_update_btn)
        links_layout.addWidget(self.open_logs_btn)
        links_layout.addWidget(self.monitor_btn)
        links_layout.addStretch()

        guide_content_layout.addLayout(links_layout)
        help_layout.addLayout(guide_content_layout)

        layout.addWidget(help_frame)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["Hugging Face", "ModelScope"])
        self.platform_combo.setCurrentText("Hugging Face")
        self.platform_combo.currentTextChanged.connect(self.on_platform_changed)
        self.platform_combo.hide()

        type_layout = QHBoxLayout()
        type_label = QLabel("类型:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Model", "Dataset"])
        self.type_combo.setCurrentText("Model")
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        self.skip_validate_checkbox = QCheckBox("跳过类型校验")
        self.skip_validate_checkbox.setChecked(False)
        self.skip_validate_checkbox.setToolTip(
            "跳过开始下载前连接 Hugging Face 校验仓库是 Model 还是 Dataset。\n"
            "网络慢/代理不稳时校验常超时（约 20 秒）；勾选后立即进入下载。\n"
            "请自行确认「类型」选择正确，否则可能下错或失败。"
        )
        type_layout.addWidget(type_label)
        type_layout.addWidget(self.type_combo)
        type_layout.addWidget(self.skip_validate_checkbox)
        type_layout.addStretch()
        layout.addLayout(type_layout)

        backend_layout = QHBoxLayout()
        backend_label = QLabel("下载方式:")
        self.backend_combo = QComboBox()
        for key, label in BACKEND_CHOICES:
            self.backend_combo.addItem(label, key)
        self.backend_combo.setCurrentIndex(0)
        self.backend_combo.setToolTip(
            "huggingface-hub：内置 Python SDK\n"
            "hfd：内置 padeoe/hfd.sh + aria2c 多线程（仅 Hugging Face）\n"
            "脚本来源：https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f"
        )
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.backend_status = QLabel("")
        self.backend_status.setStyleSheet("color: #666; font-size: 11px;")
        self.backend_status.setWordWrap(True)
        self.hfd_install_btn = QPushButton("一键安装 hfd 依赖")
        self.hfd_install_btn.setToolTip(
            "自动安装 aria2c（及 Windows 上的 Git Bash，如缺失）。\n"
            "使用 brew / winget / choco / scoop / apt 等，需本机已有对应包管理器。\n"
            "安装后建议重启本程序以刷新 PATH。"
        )
        self.hfd_install_btn.setVisible(False)
        self.hfd_install_btn.clicked.connect(self.install_hfd_dependencies)
        backend_layout.addWidget(backend_label)
        backend_layout.addWidget(self.backend_combo)
        backend_layout.addWidget(self.backend_status, stretch=1)
        backend_layout.addWidget(self.hfd_install_btn)
        layout.addLayout(backend_layout)
        self._hfd_install_worker = None
        self._refresh_backend_status()

        repo_layout = QHBoxLayout()
        self.repo_label = QLabel("模型 ID:")
        self.repo_input = QLineEdit()
        self.repo_input.setPlaceholderText("例如：qwen/Qwen2.5-Coder-1.5B-Instruct")
        repo_layout.addWidget(self.repo_label)
        repo_layout.addWidget(self.repo_input)
        layout.addLayout(repo_layout)

        path_layout = QHBoxLayout()
        path_label = QLabel("保存路径:")
        self.path_input = QLineEdit()
        browse_button = QPushButton("浏览")
        browse_button.clicked.connect(self.browse_path)
        path_layout.addWidget(path_label)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_button)
        layout.addLayout(path_layout)

        token_layout = QHBoxLayout()
        token_label = QLabel("Token:")
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("可选：私有仓库或提高限流额度")
        token_layout.addWidget(token_label)
        token_layout.addWidget(self.token_input)
        layout.addLayout(token_layout)

        endpoint_layout = QHBoxLayout()
        endpoint_label = QLabel("Endpoint:")
        self.endpoint_combo = QComboBox()
        self.endpoint_combo.setEditable(True)
        self.endpoint_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.endpoint_combo.setMinimumWidth(360)
        self.endpoint_combo.setToolTip(
            "可下拉选择预设，也可直接输入自定义 Endpoint URL"
        )
        self.endpoint_failover = QCheckBox("失败自动切换")
        self.endpoint_failover.setChecked(True)
        self.endpoint_failover.setToolTip(
            "当前 Endpoint 失败时，按预设顺序自动尝试其他 Endpoint（断点续传）"
        )
        endpoint_layout.addWidget(endpoint_label)
        endpoint_layout.addWidget(self.endpoint_combo, stretch=1)
        endpoint_layout.addWidget(self.endpoint_failover)
        layout.addLayout(endpoint_layout)
        self._refill_endpoint_combo("Hugging Face")

        proxy_layout = QHBoxLayout()
        proxy_label = QLabel("代理:")
        self.proxy_enabled = QCheckBox("启用")
        self.proxy_enabled.setChecked(False)
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText(
            "例如：http://127.0.0.1:7890 或 socks5://127.0.0.1:1080"
        )
        self.proxy_input.setEnabled(False)
        self.proxy_enabled.toggled.connect(self.proxy_input.setEnabled)
        proxy_layout.addWidget(proxy_label)
        proxy_layout.addWidget(self.proxy_enabled)
        proxy_layout.addWidget(self.proxy_input)
        layout.addLayout(proxy_layout)

        retry_layout = QHBoxLayout()
        self.auto_retry_checkbox = QCheckBox("失败自动重试直至完成")
        self.auto_retry_checkbox.setChecked(True)
        self.auto_retry_checkbox.setToolTip(
            "下载中断或失败时自动重试，已下载部分会断点续传；"
            "点击「停止」可结束重试循环。"
        )
        self.stall_restart_checkbox = QCheckBox("卡住无速度自动重启")
        self.stall_restart_checkbox.setChecked(True)
        self.stall_restart_checkbox.setToolTip(
            "下载过程中若长时间没有进度日志/速度，自动停止并重新开始（断点续传）。"
            "可同时配置下方「卡住时执行」命令（例如重启 v2ray 内核）。"
        )
        stall_timeout_label = QLabel("卡住超时(秒):")
        self.stall_timeout_spin = QSpinBox()
        self.stall_timeout_spin.setRange(10, 600)
        self.stall_timeout_spin.setSingleStep(10)
        self.stall_timeout_spin.setValue(120)
        self.stall_timeout_spin.setToolTip("超过该秒数无进度则视为卡住（默认 120 秒）")
        retry_wait_label = QLabel("重试等待(秒):")
        self.retry_wait_spin = QSpinBox()
        self.retry_wait_spin.setRange(0, 600)
        self.retry_wait_spin.setSingleStep(1)
        self.retry_wait_spin.setValue(5)
        self.retry_wait_spin.setToolTip(
            "失败自动重试 / 卡住重启后，等待多少秒再继续下载。\n"
            "0 表示几乎立即重试；若配置了卡住关联命令，可适当加大以便代理内核恢复。"
        )
        retry_layout.addWidget(self.auto_retry_checkbox)
        retry_layout.addWidget(self.stall_restart_checkbox)
        retry_layout.addWidget(stall_timeout_label)
        retry_layout.addWidget(self.stall_timeout_spin)
        retry_layout.addWidget(retry_wait_label)
        retry_layout.addWidget(self.retry_wait_spin)
        retry_layout.addStretch()
        layout.addLayout(retry_layout)

        stall_cmd_layout = QHBoxLayout()
        stall_cmd_label = QLabel("卡住时执行:")
        stall_cmd_label.setToolTip(
            "检测到卡住并自动重启前，在后台执行的系统命令/脚本。\n"
            "常用于重启卡死的代理内核（v2ray/xray 等）。\n"
            "留空则只重启下载，不跑额外命令。"
        )
        self.stall_cmd_input = QLineEdit()
        self.stall_cmd_input.setPlaceholderText(
            "可选：卡住时执行的命令，如 killall xray 或 taskkill /F /IM xray.exe"
        )
        self.stall_cmd_input.setToolTip(
            "shell 命令（macOS/Linux 走 sh，Windows 走 cmd）。\n"
            "示例：\n"
            "  macOS: killall xray; sleep 2; open -a v2rayN\n"
            '  Windows: taskkill /F /IM xray.exe & timeout /t 2 & start "" '
            '"C:\\Path\\to\\v2rayN.exe"\n'
            "  或直接写脚本路径：/path/to/restart-proxy.sh\n"
            "命令在后台执行，不阻塞界面；完成后日志会提示结果。"
        )
        self.stall_restart_checkbox.toggled.connect(self._on_stall_restart_toggled)
        self._on_stall_restart_toggled(self.stall_restart_checkbox.isChecked())
        stall_cmd_layout.addWidget(stall_cmd_label)
        stall_cmd_layout.addWidget(self.stall_cmd_input)
        layout.addLayout(stall_cmd_layout)

        concurrency_layout = QHBoxLayout()
        concurrency_layout.addWidget(QLabel("并发:"))
        concurrency_layout.addWidget(QLabel("hub文件"))
        self.hub_workers_spin = QSpinBox()
        self.hub_workers_spin.setRange(1, 32)
        self.hub_workers_spin.setValue(8)
        self.hub_workers_spin.setToolTip(
            "huggingface-hub 并行下载的文件数（max_workers）\n"
            "越大越吃带宽/CPU；镜像不稳时可降到 2～4"
        )
        concurrency_layout.addWidget(self.hub_workers_spin)
        concurrency_layout.addWidget(QLabel("hfd连接-x"))
        self.hfd_threads_spin = QSpinBox()
        self.hfd_threads_spin.setRange(1, 16)
        self.hfd_threads_spin.setValue(8)
        self.hfd_threads_spin.setToolTip(
            "hfd/aria2 单文件分片连接数（-x，最大 10 由 hfd 限制）\n"
            "提高有助于单文件吃满带宽"
        )
        concurrency_layout.addWidget(self.hfd_threads_spin)
        concurrency_layout.addWidget(QLabel("hfd任务-j"))
        self.hfd_jobs_spin = QSpinBox()
        self.hfd_jobs_spin.setRange(1, 16)
        self.hfd_jobs_spin.setValue(5)
        self.hfd_jobs_spin.setToolTip(
            "hfd/aria2 同时下载的文件数（-j，最大 10 由 hfd 限制）\n"
            "多文件仓库可适当提高；配合代理 LB 更有效"
        )
        concurrency_layout.addWidget(self.hfd_jobs_spin)
        concurrency_layout.addStretch()
        layout.addLayout(concurrency_layout)

        button_layout = QHBoxLayout()
        self.download_button = QPushButton("下载")
        self.download_button.setFixedHeight(standard_button_height)
        self.download_button.clicked.connect(self.start_download)
        self.stop_button = QPushButton("停止")
        self.stop_button.setFixedHeight(standard_button_height)
        self.stop_button.clicked.connect(self.stop_download)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.download_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        # Monitors live in a floating side window (not embedded — keeps main UI clean).
        self._monitor_window = MonitorWindow(self)
        self._monitor_window.prefs_changed.connect(self._save_settings)
        self._monitor_window.closed.connect(self._on_monitor_window_closed)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(100)
        layout.addWidget(self.log_text)

        footer_frame = QFrame()
        footer_layout = QHBoxLayout(footer_frame)

        version_label = QLabel(f"v{self.app_version}")
        version_label.setStyleSheet("font-size: 12px; color: #666;")
        footer_layout.addWidget(version_label)

        footer_layout.addStretch()

        github_btn = QPushButton("在 GitHub 查看")
        github_btn.setFlat(True)
        github_btn.setStyleSheet(
            "QPushButton { "
            "font-size: 12px; color: #666; border: none; text-decoration: underline; "
            "}"
        )
        github_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_REPO_URL))
        )
        footer_layout.addWidget(github_btn)

        author_btn = QPushButton(f"作者 {AUTHOR_NAME}")
        author_btn.setFlat(True)
        author_btn.setStyleSheet(
            "QPushButton { "
            "font-size: 12px; color: #666; border: none; text-decoration: underline; "
            "}"
        )
        author_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(AUTHOR_GITHUB_URL))
        )
        footer_layout.addWidget(author_btn)

        footer_layout.addStretch()

        layout.addWidget(footer_frame)

        self._set_dynamic_minimum_height()

        self.download_worker = None
        self._update_worker = None
        self._update_apply_worker = None
        self._pending_update_result = None
        self._user_stopped = False
        self._retry_attempt = 0
        self._download_params = None
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._on_retry_timer)
        # Stall (no progress) watchdog
        self._last_download_activity = 0.0
        self._download_watch_started = 0.0
        self._pending_stall_restart = False
        self._stall_hook_thread: threading.Thread | None = None
        self._stall_watch_timer = QTimer(self)
        self._stall_watch_timer.setInterval(5000)
        self._stall_watch_timer.timeout.connect(self._check_download_stall)
        self.stall_hook_finished.connect(self._on_stall_hook_finished)
        self._load_settings()

    def _set_dynamic_minimum_height(self):
        platform_icons_height = 40
        help_section_height = 220
        form_fields_height = 270
        buttons_height = 40
        log_minimum_height = 120
        footer_height = 40
        margins_spacing = 40

        total_height = (
            platform_icons_height
            + help_section_height
            + form_fields_height
            + buttons_height
            + log_minimum_height
            + footer_height
            + margins_spacing
        )

        self.setMinimumHeight(total_height)
        self.setMinimumWidth(800)

    def _load_settings(self):
        """Restore last-used form values."""
        data = load_form_settings()
        platform = data["platform"]
        if platform not in ("Hugging Face", "ModelScope"):
            platform = "Hugging Face"

        self.platform_combo.blockSignals(True)
        self.platform_combo.setCurrentText(platform)
        self.platform_combo.blockSignals(False)

        if platform == "ModelScope":
            self.ms_button.setChecked(True)
        else:
            self.hf_button.setChecked(True)

        repo_type = data["repo_type"]
        if repo_type not in ("Model", "Dataset"):
            repo_type = "Model"
        self.type_combo.blockSignals(True)
        self.type_combo.setCurrentText(repo_type)
        self.type_combo.blockSignals(False)
        self.on_type_changed(repo_type)

        if data["repo_id"]:
            self.repo_input.setText(data["repo_id"])
        if data["save_path"]:
            self.path_input.setText(data["save_path"])
        if data["token"]:
            self.token_input.setText(data["token"])

        self._refill_endpoint_combo(platform)
        endpoint = data.get("endpoint") or default_endpoint(
            "modelscope" if platform == "ModelScope" else "huggingface"
        )
        self._set_endpoint_combo_url(endpoint)
        self.endpoint_failover.setChecked(bool(data.get("endpoint_failover", True)))
        self.skip_validate_checkbox.setChecked(
            bool(data.get("skip_repo_validate", False))
        )

        self.proxy_enabled.setChecked(bool(data["proxy_enabled"]))
        self.proxy_input.setText(data["proxy"] or "")
        self.proxy_input.setEnabled(self.proxy_enabled.isChecked())
        self.auto_retry_checkbox.setChecked(bool(data.get("auto_retry", True)))
        self.stall_restart_checkbox.setChecked(bool(data.get("stall_restart", True)))
        stall_sec = int(data.get("stall_timeout_sec") or 120)
        self.stall_timeout_spin.setValue(max(10, min(600, stall_sec)))
        raw_wait = data.get("retry_wait_sec")
        retry_wait = 5 if raw_wait is None else int(raw_wait)
        self.retry_wait_spin.setValue(max(0, min(600, retry_wait)))
        self.stall_cmd_input.setText(str(data.get("stall_restart_command") or ""))
        self._on_stall_restart_toggled(self.stall_restart_checkbox.isChecked())
        self.hub_workers_spin.setValue(
            max(1, min(32, int(data.get("hub_max_workers") or 8)))
        )
        self.hfd_threads_spin.setValue(
            max(1, min(16, int(data.get("hfd_threads") or 8)))
        )
        self.hfd_jobs_spin.setValue(max(1, min(16, int(data.get("hfd_jobs") or 5))))

        backend = data.get("download_backend") or BACKEND_HUB
        idx = self.backend_combo.findData(backend)
        if idx < 0:
            idx = 0
        self.backend_combo.setCurrentIndex(idx)
        self._refresh_backend_status()

        hist = int(data.get("net_monitor_history_sec") or 180)
        mw = self._monitor_window
        # Allow up to 3 days (matches monitor window options)
        mw.net_panel.set_history_seconds(max(60, min(3 * 24 * 3600, hist)))
        mw.net_panel.set_selected_interface(str(data.get("net_monitor_iface") or ""))
        mw.net_panel.set_expanded(True)
        mw.file_panel.set_expanded(True)
        if data.get("monitor_window_open"):
            # Defer so main geometry is ready
            QTimer.singleShot(200, self.show_monitor_window)

    def _platform_key(self) -> str:
        return (
            "modelscope"
            if self.platform_combo.currentText() == "ModelScope"
            else "huggingface"
        )

    def _refill_endpoint_combo(self, platform_text: str | None = None):
        """Reload endpoint presets for the selected platform."""
        if platform_text is None:
            platform_text = self.platform_combo.currentText()
        key = "modelscope" if platform_text == "ModelScope" else "huggingface"
        current = url_from_combo_text(self.endpoint_combo.currentText())
        self.endpoint_combo.blockSignals(True)
        self.endpoint_combo.clear()
        self.endpoint_combo.addItems(preset_labels(key))
        self.endpoint_combo.blockSignals(False)
        if current:
            self._set_endpoint_combo_url(current)
        else:
            self._set_endpoint_combo_url(default_endpoint(key))

    def _set_endpoint_combo_url(self, url: str):
        url = url_from_combo_text(url)
        if not url:
            return
        # Prefer matching a preset row; otherwise put raw URL in edit field.
        for i in range(self.endpoint_combo.count()):
            if url_from_combo_text(self.endpoint_combo.itemText(i)) == url:
                self.endpoint_combo.setCurrentIndex(i)
                return
        self.endpoint_combo.setEditText(url)

    def _current_endpoint_url(self) -> str:
        return url_from_combo_text(self.endpoint_combo.currentText())

    def _current_backend(self) -> str:
        data = self.backend_combo.currentData()
        return data if isinstance(data, str) else BACKEND_HUB

    def _refresh_backend_status(self):
        backend = self._current_backend()
        if backend == BACKEND_HFD:
            ok, msg = hfd_availability()
            # jq optional — still show install if only jq is missing
            need_install = bool(missing_hfd_deps())
            color = (
                "#2e7d32"
                if ok and not any(m.startswith("jq") for m in missing_hfd_deps())
                else ("#c62828" if not ok else "#ef6c00")
            )
            self.backend_status.setStyleSheet(f"color: {color}; font-size: 11px;")
            self.backend_status.setText(msg)
            show_install = need_install
            self.hfd_install_btn.setVisible(show_install)
            if show_install:
                if can_auto_install_hfd_deps():
                    self.hfd_install_btn.setText("一键安装 hfd 依赖")
                    self.hfd_install_btn.setEnabled(
                        self._hfd_install_worker is None
                        or not self._hfd_install_worker.isRunning()
                    )
                else:
                    self.hfd_install_btn.setText("查看安装说明")
                    self.hfd_install_btn.setEnabled(True)
        else:
            self.backend_status.setStyleSheet("color: #666; font-size: 11px;")
            self.backend_status.setText(
                "使用 Python huggingface-hub（可随时改 hfd，同目录可续传）"
            )
            self.hfd_install_btn.setVisible(False)

    def _on_backend_changed(self, _index: int = 0):
        self._refresh_backend_status()
        backend = self._current_backend()
        if backend == BACKEND_HFD:
            ok, msg = hfd_availability()
            if ok:
                self.update_status(
                    "已切换 hfd：下次点「下载」将用 aria2；"
                    "与 hub 使用相同保存目录时可续传已下完的文件。"
                )
            else:
                self.update_status(f"hfd 当前不可用：{msg}", error=True)

    def install_hfd_dependencies(self) -> None:
        """One-click install aria2/bash for hfd backend."""
        missing = missing_hfd_deps()
        if not missing:
            self._refresh_backend_status()
            QMessageBox.information(self, "hfd 依赖", "依赖已齐全，可直接使用 hfd。")
            return

        if not can_auto_install_hfd_deps():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("手动安装 hfd 依赖")
            box.setText("缺少：" + "、".join(missing))
            box.setInformativeText(
                "Windows 无 winget 时：\n"
                "· aria2：一键安装会下载官方便携包到\n"
                "  %LOCALAPPDATA%\\hf-model-downloader\\tools\n"
                "· bash：需手动装 Git for Windows\n"
                "  https://git-scm.com/download/win\n\n"
                "装好后请重启本程序。"
            )
            open_git = box.addButton(
                "打开 Git 下载页", QMessageBox.ButtonRole.ActionRole
            )
            box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_git:
                QDesktopServices.openUrl(QUrl("https://git-scm.com/download/win"))
            return

        reply = QMessageBox.question(
            self,
            "安装 hfd 依赖",
            "将尝试自动安装：\n· " + "\n· ".join(missing) + "\n\n"
            "Windows：优先 winget；没有则下载官方便携 aria2\n"
            "（%LOCALAPPDATA%\\hf-model-downloader\\tools，无需管理员）。\n"
            "bash 若仍缺，需手动安装 Git for Windows。\n"
            "macOS/Linux：brew / apt 等。\n\n"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._hfd_install_worker and self._hfd_install_worker.isRunning():
            self.update_status("正在安装 hfd 依赖，请稍候…")
            return

        self.hfd_install_btn.setEnabled(False)
        self.update_status("正在安装 hfd 依赖（aria2 / bash）…")

        worker = _HfdDepsInstallWorker(self)
        self._hfd_install_worker = worker
        worker.log_line.connect(self.update_status)
        worker.finished_ok.connect(self._on_hfd_install_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_hfd_install_finished(self, ok: bool, summary: str) -> None:
        self._hfd_install_worker = None
        self._refresh_backend_status()
        self.update_status(summary, error=not ok)
        if ok:
            QMessageBox.information(self, "安装完成", summary)
        else:
            QMessageBox.warning(self, "安装未完全成功", summary)

    def _save_settings(self):
        """Persist current form values for next launch."""
        save_form_settings(
            platform=self.platform_combo.currentText(),
            repo_type=self.type_combo.currentText(),
            repo_id=self.repo_input.text().strip(),
            save_path=self.path_input.text().strip(),
            token=self.token_input.text().strip(),
            endpoint=self._current_endpoint_url(),
            endpoint_failover=self.endpoint_failover.isChecked(),
            skip_repo_validate=self.skip_validate_checkbox.isChecked(),
            proxy=self.proxy_input.text().strip(),
            proxy_enabled=self.proxy_enabled.isChecked(),
            auto_retry=self.auto_retry_checkbox.isChecked(),
            retry_wait_sec=self.retry_wait_spin.value(),
            download_backend=self._current_backend(),
            stall_restart=self.stall_restart_checkbox.isChecked(),
            stall_timeout_sec=self.stall_timeout_spin.value(),
            stall_restart_command=self.stall_cmd_input.text().strip(),
            hub_max_workers=self.hub_workers_spin.value(),
            hfd_threads=self.hfd_threads_spin.value(),
            hfd_jobs=self.hfd_jobs_spin.value(),
            net_monitor_expanded=True,
            net_monitor_iface=self._monitor_window.net_panel.selected_interface(),
            net_monitor_history_sec=self._monitor_window.net_panel.history_seconds(),
            file_progress_expanded=True,
            monitor_window_open=self._monitor_window.isVisible(),
        )

    def show_monitor_window(self) -> None:
        self._monitor_window.show_and_place()
        self.monitor_btn.setText("📊 监控面板 ✓")

    def toggle_monitor_window(self) -> None:
        if self._monitor_window.isVisible():
            self._monitor_window.hide()
            self.monitor_btn.setText("📊 监控面板")
        else:
            self.show_monitor_window()

    def _on_monitor_window_closed(self) -> None:
        self.monitor_btn.setText("📊 监控面板")
        self._save_settings()

    def closeEvent(self, event):
        self._save_settings()
        self._user_stopped = True
        self._pending_stall_restart = False
        self._retry_timer.stop()
        self._stall_watch_timer.stop()
        try:
            self._monitor_window.stop()
            self._monitor_window.hide()
        except Exception:
            pass
        if self._update_worker and self._update_worker.isRunning():
            self._update_worker.wait(3000)
        if self.download_worker and self.download_worker.isRunning():
            try:
                self.download_worker.download_finished.disconnect()
                self.download_worker.download_error.disconnect()
                self.download_worker.download_status.disconnect()
                self.download_worker.download_log.disconnect()
            except TypeError:
                pass

            self.download_worker.cancel_download()
            if not self.download_worker.wait(5000):
                self.download_worker.terminate()
                self.download_worker.wait()
        event.accept()

    def on_platform_icon_changed(self, button_id):
        if button_id == 0:
            platform_text = "Hugging Face"
        else:
            platform_text = "ModelScope"

        self.platform_combo.setCurrentText(platform_text)

    def on_platform_changed(self, platform_text):
        self._refill_endpoint_combo(platform_text)
        # hfd is HF-only; keep selection but warn via status label.
        self._refresh_backend_status()

    def open_models_page(self):
        """Open the models page for the current platform"""
        platform = self.platform_combo.currentText()
        if platform == "ModelScope":
            QDesktopServices.openUrl(QUrl("https://modelscope.cn/models"))
        else:
            QDesktopServices.openUrl(QUrl("https://huggingface.co/models"))

    def open_datasets_page(self):
        platform = self.platform_combo.currentText()
        if platform == "ModelScope":
            QDesktopServices.openUrl(QUrl("https://modelscope.cn/datasets"))
        else:
            QDesktopServices.openUrl(QUrl("https://huggingface.co/datasets"))

    def open_token_page(self):
        platform = self.platform_combo.currentText()
        if platform == "ModelScope":
            QDesktopServices.openUrl(QUrl("https://modelscope.cn/my/myaccesstoken"))
        else:
            QDesktopServices.openUrl(QUrl("https://huggingface.co/settings/tokens"))

    def _current_proxy_for_network(self) -> str | None:
        if self.proxy_enabled.isChecked():
            return normalize_proxy(self.proxy_input.text())
        return None

    def open_log_folder(self):
        """Open the directory that stores runtime.log and crash reports."""
        try:
            log_dir = get_log_dir()
            runtime = get_runtime_log_path()
            crash = get_last_crash_log_path()
            self.update_status(f"日志目录：{log_dir}")
            self.update_status(f"运行日志：{runtime}")
            if crash.exists():
                self.update_status(f"最近崩溃：{crash}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        except Exception as exc:
            self.update_status(f"打开日志目录失败：{exc}", error=True)
            QMessageBox.warning(self, "打开日志", f"打开日志目录失败：\n{exc}")

    def check_for_updates(self):
        """Check GitHub Releases for a newer app version (async)."""
        if self._update_worker and self._update_worker.isRunning():
            self.update_status("正在检查更新，请稍候...")
            return
        if self._update_apply_worker and self._update_apply_worker.isRunning():
            self.update_status("正在下载并安装更新，请稍候...")
            return

        proxy = self._current_proxy_for_network()
        self.check_update_btn.setEnabled(False)
        self.update_status(
            f"正在检查更新（当前 v{self.app_version}"
            + (f"，代理 {proxy}" if proxy else "")
            + "）..."
        )

        self._update_worker = UpdateCheckWorker(proxy=proxy, parent=self)
        self._update_worker.finished_result.connect(
            self._on_update_check_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._update_worker.finished.connect(
            self._on_update_worker_done,
            Qt.ConnectionType.QueuedConnection,
        )
        self._update_worker.start()

    def _on_update_worker_done(self):
        # Keep button disabled if apply worker is running.
        if not (self._update_apply_worker and self._update_apply_worker.isRunning()):
            self.check_update_btn.setEnabled(True)
        if self._update_worker:
            self._update_worker.deleteLater()
            self._update_worker = None

    def _on_update_check_finished(self, result: UpdateCheckResult):
        self.update_status(result.message)
        self._pending_update_result = result

        if result.error:
            QMessageBox.warning(self, "检查更新", result.message)
            return

        if not result.update_available:
            QMessageBox.information(self, "检查更新", result.message)
            return

        can_auto = bool(result.asset) and is_frozen_install()
        if can_auto:
            reply = QMessageBox.question(
                self,
                "发现新版本",
                (
                    f"{result.message}\n\n"
                    f"最新版本：v{result.latest_version}\n"
                    f"当前版本：v{result.current_version}\n"
                    f"安装包：{result.asset.name}\n\n"
                    "是否立即下载、解压并替换当前程序？\n"
                    "（完成后会自动重启）"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._start_auto_update(result)
            return

        # Dev mode or no matching asset: open releases page.
        detail = result.message
        if not is_frozen_install():
            detail += (
                "\n\n当前为开发模式，无法自动替换安装包。可打开 Releases 页面手动下载。"
            )
        elif not result.asset:
            detail += "\n\n未找到适合本机系统的安装包。"
        reply = QMessageBox.question(
            self,
            "发现新版本",
            f"{detail}\n\n是否打开下载页面？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(result.release_url))

    def _start_auto_update(self, result: UpdateCheckResult):
        if not result.asset:
            QMessageBox.warning(self, "自动更新", "没有可下载的安装包。")
            return
        if self.download_worker and self.download_worker.isRunning():
            QMessageBox.warning(
                self,
                "自动更新",
                "当前正在下载模型，请先停止后再更新程序。",
            )
            return

        proxy = self._current_proxy_for_network()
        self.check_update_btn.setEnabled(False)
        self.update_status(
            f"开始自动更新到 v{result.latest_version}（{result.asset.name}）..."
        )
        self._update_apply_worker = UpdateApplyWorker(
            result.asset, proxy=proxy, parent=self
        )
        self._update_apply_worker.progress.connect(
            self.update_status, Qt.ConnectionType.QueuedConnection
        )
        self._update_apply_worker.finished_ok.connect(
            self._on_update_apply_ok, Qt.ConnectionType.QueuedConnection
        )
        self._update_apply_worker.failed.connect(
            self._on_update_apply_failed, Qt.ConnectionType.QueuedConnection
        )
        self._update_apply_worker.finished.connect(
            self._on_update_apply_worker_done,
            Qt.ConnectionType.QueuedConnection,
        )
        self._update_apply_worker.start()

    def _on_update_apply_worker_done(self):
        self.check_update_btn.setEnabled(True)
        if self._update_apply_worker:
            self._update_apply_worker.deleteLater()
            self._update_apply_worker = None

    def _on_update_apply_ok(self, script_path: str):
        self.update_status("更新包已就绪，即将退出并替换程序...")
        logger.info("Update package ready, script=%s", script_path)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("准备安装更新")
        box.setText(
            "更新文件已下载并解压完成。\n\n"
            "点击「立即安装并重启」后程序会退出，后台自动替换文件并重新启动。\n"
            "请勿手动删除原安装目录。"
        )
        install_btn = box.addButton("立即安装并重启", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(install_btn)
        box.exec()
        if box.clickedButton() is not install_btn:
            self.update_status("已取消自动安装（安装包仍在临时目录）。")
            logger.info("User cancelled in-place update install")
            return

        try:
            launch_updater_and_exit(Path(script_path))
            self.update_status("已启动更新程序，正在退出…")
            logger.info("Updater launched, forcing application exit")
        except Exception as exc:
            logger.exception("Failed to launch updater: %s", exc)
            QMessageBox.critical(
                self,
                "自动更新失败",
                (
                    f"无法启动更新脚本：\n{exc}\n\n"
                    "可点击「打开日志」查看 runtime.log / update.log，"
                    "或手动到 GitHub Releases 下载安装包覆盖。"
                ),
            )
            return

        # Ensure workers don't block quit; force-exit shortly after.
        try:
            if self.download_worker and self.download_worker.isRunning():
                self.download_worker.cancel_download()
        except Exception:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()
        # Hard exit so Windows can overwrite the running onedir files.
        QTimer.singleShot(300, lambda: os._exit(0))

    def _on_update_apply_failed(self, error_msg: str):
        self.update_status(f"自动更新失败：{error_msg}", error=True)
        result = self._pending_update_result
        buttons = QMessageBox.StandardButton.Ok
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("自动更新失败")
        box.setText(f"自动下载/安装失败：\n{error_msg}")
        if result and result.release_url:
            box.setInformativeText("可以改为打开 Releases 页面手动下载。")
            box.setStandardButtons(
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Open)
            if box.exec() == QMessageBox.StandardButton.Open:
                QDesktopServices.openUrl(QUrl(result.release_url))
        else:
            box.setStandardButtons(buttons)
            box.exec()

    def on_type_changed(self, type_text):
        if type_text == "Dataset":
            self.repo_label.setText("数据集 ID:")
            self.repo_input.setPlaceholderText("例如：baicai003/Llama3-Chinese-dataset")
        else:
            self.repo_label.setText("模型 ID:")
            self.repo_input.setPlaceholderText("例如：deepseek-ai/DeepSeek-R1")

    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录")
        if path:
            self.path_input.setText(path)

    def _retry_delay_seconds(self, attempt: int = 1) -> int:
        """Seconds to wait before auto-retry / stall restart (user-configured)."""
        try:
            wait = int(self.retry_wait_spin.value())
        except Exception:
            wait = 5
        return max(0, min(600, wait))

    def _set_downloading_ui(self, active: bool):
        self.download_button.setEnabled(not active)
        self.stop_button.setEnabled(active)
        if active:
            self.stop_button.setStyleSheet(
                "QPushButton { background-color: #ff4444; color: white; }"
            )
        else:
            self.stop_button.setStyleSheet("")

    def start_download(self):
        repo_id = self.repo_input.text().strip()
        save_path = self.path_input.text().strip()
        token = self.token_input.text().strip() or None
        repo_type = self.type_combo.currentText().lower()
        platform = self.platform_combo.currentText()
        proxy = None
        if self.proxy_enabled.isChecked():
            proxy = normalize_proxy(self.proxy_input.text())
            if not proxy:
                self.update_status("错误：已启用代理，但代理地址为空", error=True)
                return

        platform_key = "modelscope" if platform == "ModelScope" else "huggingface"
        backend = self._current_backend()
        if backend == BACKEND_HFD and platform_key != "huggingface":
            self.update_status(
                "错误：hfd 仅支持 Hugging Face，请切换平台或下载方式",
                error=True,
            )
            return
        if backend == BACKEND_HFD:
            ok, reason = hfd_availability()
            # Allow start when only jq is missing (optional), but nudge install.
            req = missing_hfd_required_deps()
            if ok and any(m.startswith("jq") for m in missing_hfd_deps()):
                self.update_status(
                    "提示：未安装 jq，大仓库列文件较慢，建议先点「一键安装 hfd 依赖」。"
                )
            if (not ok) or req:
                self.update_status(
                    f"错误：hfd 不可用 — {reason or '、'.join(req)}",
                    error=True,
                )
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("hfd 不可用")
                box.setText(reason if not ok else "、".join(req))
                box.setInformativeText(
                    "可一键安装依赖（aria2 / bash / jq），或改回 huggingface-hub。\n"
                    "jq 可显著加快大仓库列文件；无 winget 时会下便携包。"
                )
                install_btn = None
                if can_auto_install_hfd_deps() or missing_hfd_deps():
                    install_btn = box.addButton(
                        "一键安装依赖", QMessageBox.ButtonRole.AcceptRole
                    )
                box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if install_btn is not None and box.clickedButton() is install_btn:
                    self.install_hfd_dependencies()
                return

        endpoint = self._current_endpoint_url() or default_endpoint(platform_key)
        endpoints = build_endpoint_chain(
            endpoint,
            platform_key,
            failover=self.endpoint_failover.isChecked(),
        )

        if not repo_id:
            repo_type_text = "模型 ID" if repo_type == "model" else "数据集 ID"
            self.update_status(f"错误：请填写{repo_type_text}", error=True)
            return

        if not save_path:
            self.update_status("错误：请选择保存路径", error=True)
            return

        self._save_settings()
        self._user_stopped = False
        self._pending_stall_restart = False
        self._retry_attempt = 0
        self._retry_timer.stop()
        self._download_params = {
            "platform": platform_key,
            "repo_id": repo_id,
            "save_path": save_path,
            "token": token,
            "endpoint": endpoints[0],
            "endpoints": endpoints,
            "repo_type": repo_type,
            "proxy": proxy,
            "backend": backend,
            "max_workers": self.hub_workers_spin.value(),
            "hfd_threads": self.hfd_threads_spin.value(),
            "hfd_jobs": self.hfd_jobs_spin.value(),
        }
        logger.info(
            "Start download platform=%s backend=%s repo=%s type=%s "
            "path=%s endpoints=%s proxy=%s",
            platform_key,
            backend,
            repo_id,
            repo_type,
            save_path,
            endpoints,
            bool(proxy),
        )
        skip_val = self.skip_validate_checkbox.isChecked()
        self._start_download_job(clear_log=True, skip_validation=skip_val)

    def _start_download_job(self, *, clear_log: bool, skip_validation: bool):
        if not self._download_params:
            return
        if self.download_worker and self.download_worker.isRunning():
            return

        params = self._download_params
        self._set_downloading_ui(True)
        self._touch_download_activity()
        self._download_watch_started = time.monotonic()
        if self.stall_restart_checkbox.isChecked():
            self._stall_watch_timer.start()

        # Prepare monitors AFTER UI updates — never block download start.
        # (Full-dir incomplete scans used to freeze the UI on large datasets.)
        def _prep_monitor() -> None:
            try:
                save_path = params.get("save_path")
                repo_id = params.get("repo_id") or ""
                repo_name = repo_id.split("/")[-1] if repo_id else ""
                repo_dir = (
                    os.path.join(save_path, repo_name)
                    if save_path and repo_name
                    else save_path
                )
                self._monitor_window.set_watch_path(save_path)
                self._monitor_window.set_repo_dir(repo_dir)
                self._monitor_window.file_panel.set_scan_root(
                    save_path, repo_id=repo_id
                )
                # Only auto-open if user already had it open / wants it
                if self._monitor_window.isVisible():
                    self._monitor_window.start_session(reset=bool(clear_log))
                else:
                    # Soft-start session stats without forcing window open
                    self._monitor_window.start_session(reset=bool(clear_log))
            except Exception:
                logger.exception("Failed to prepare monitor window")

        QTimer.singleShot(0, _prep_monitor)

        if clear_log:
            self.log_text.clear()
            self.update_status("正在初始化下载...")
            if params["proxy"]:
                self.update_status(f"使用代理：{params['proxy']}")
            eps = params.get("endpoints") or [params["endpoint"]]
            backend = params.get("backend") or BACKEND_HUB
            if backend == BACKEND_HFD:
                self.update_status(
                    "下载方式：hfd / aria2"
                    "（https://gist.github.com/padeoe/697678ab8e528b85a2a7bddafea1fa4f）"
                )
            else:
                self.update_status("下载方式：huggingface-hub（内置）")
            if skip_validation:
                self.update_status("已跳过仓库类型校验（按界面所选类型直接下载）")
            if len(eps) > 1:
                self.update_status("Endpoint 顺序：" + " → ".join(eps))
            else:
                self.update_status(f"Endpoint：{eps[0]}")
            if self.auto_retry_checkbox.isChecked():
                self.update_status(
                    "已开启「失败自动重试直至完成」：中断后会自动续传重试"
                )
            if self.stall_restart_checkbox.isChecked():
                self.update_status(
                    f"已开启「卡住无速度自动重启」："
                    f"{self.stall_timeout_spin.value()} 秒无进度将重启"
                )
            self.update_status(
                f"并发：hub文件={params.get('max_workers')} "
                f"hfd连接-x={params.get('hfd_threads')} "
                f"hfd任务-j={params.get('hfd_jobs')}"
            )
        elif self._retry_attempt > 0:
            self.update_status(
                f"正在进行第 {self._retry_attempt} 次自动重试（断点续传）..."
            )

        try:
            self.download_worker = UnifiedDownloadWorker(
                params["platform"],
                params["repo_id"],
                params["save_path"],
                params["token"],
                params["endpoint"],
                params["repo_type"],
                proxy=params["proxy"],
                skip_validation=skip_validation,
                endpoints=params.get("endpoints"),
                backend=params.get("backend") or BACKEND_HUB,
                max_workers=params.get("max_workers"),
                hfd_threads=params.get("hfd_threads"),
                hfd_jobs=params.get("hfd_jobs"),
            )
        except Exception as exc:
            logger.exception("Failed to create download worker: %s", exc)
            self._set_downloading_ui(False)
            self.update_status(f"无法启动下载：{exc}", error=True)
            QMessageBox.critical(self, "下载失败", f"无法启动下载：\n{exc}")
            return

        # Use download_* signals — never QThread.finished (that means thread exit).
        self.download_worker.download_finished.connect(
            self.download_finished, Qt.ConnectionType.QueuedConnection
        )
        self.download_worker.download_error.connect(
            self.download_error, Qt.ConnectionType.QueuedConnection
        )
        self.download_worker.download_status.connect(
            self.update_status, Qt.ConnectionType.QueuedConnection
        )
        self.download_worker.download_log.connect(
            self.update_log, Qt.ConnectionType.QueuedConnection
        )
        self.download_worker.download_finished.connect(
            self._on_worker_finished, Qt.ConnectionType.QueuedConnection
        )
        self.download_worker.download_error.connect(
            self._on_worker_finished, Qt.ConnectionType.QueuedConnection
        )
        try:
            self.download_worker.start()
            logger.info("Download worker thread started")
        except Exception as exc:
            logger.exception("Failed to start download worker: %s", exc)
            self._set_downloading_ui(False)
            self.update_status(f"启动下载线程失败：{exc}", error=True)
            QMessageBox.critical(self, "下载失败", f"启动下载线程失败：\n{exc}")

    def stop_download(self):
        self._user_stopped = True
        self._pending_stall_restart = False
        self._retry_timer.stop()
        self._stall_watch_timer.stop()
        try:
            self._monitor_window.stop_session()
        except Exception:
            pass
        self.update_status("正在停止下载（并取消自动重试）...")
        if self.download_worker and self.download_worker.isRunning():
            self.stop_button.setEnabled(False)
            self.download_worker.cancel_download()
        else:
            self._set_downloading_ui(False)
            self.update_status("⏹️ 已停止下载")

    def _touch_download_activity(self, message: str = "") -> None:
        """Record that the download produced some output/progress."""
        now = time.monotonic()
        self._last_download_activity = now
        # Any log line counts; extra keywords for clarity / future filters.
        if message and (
            re.search(r"\d+%", message)
            or re.search(r"\d+(\.\d+)?\s*[kKmMgGtT]?B", message)
            or "Downloading" in message
            or "Fetching" in message
            or "Resuming" in message
            or "Listed" in message
            or "Listing" in message
            or "scanned" in message.lower()
            or "Repository size" in message
            or "metadata" in message.lower()
            or "files" in message.lower()
            or "aria2" in message.lower()
            or "hfd" in message.lower()
        ):
            self._last_download_activity = now

    def _check_download_stall(self) -> None:
        if not self.stall_restart_checkbox.isChecked():
            return
        if self._user_stopped or self._pending_stall_restart:
            return
        if not self.download_worker or not self.download_worker.isRunning():
            return
        if self._retry_timer.isActive():
            return

        timeout = int(self.stall_timeout_spin.value())
        # Grace: hfd listing 10k+ files (esp. without jq) can take minutes.

        backend = (
            (self._download_params or {}).get("backend")
            if self._download_params
            else None
        )
        if backend == BACKEND_HFD:
            grace = max(180, timeout * 3, 300)
            # During listing, also require longer idle before stall.
            timeout = max(timeout, 120)
        else:
            grace = max(45, min(timeout, 90))
        if self._download_watch_started and (
            time.monotonic() - self._download_watch_started < grace
        ):
            return

        idle = time.monotonic() - (self._last_download_activity or 0)
        if idle < timeout:
            return

        logger.warning("Download stall detected: idle=%.0fs timeout=%ss", idle, timeout)
        self._pending_stall_restart = True
        self._user_stopped = False
        self.update_status(
            f"⚠️ 已 {int(idle)} 秒无进度，判定卡住，自动停止并重新开始…",
            error=True,
        )
        # Run associated command first (e.g. restart frozen v2ray core).
        self._run_stall_hook_command()
        try:
            self.download_worker.cancel_download()
        except Exception as exc:
            logger.exception("Stall cancel failed: %s", exc)
            self._pending_stall_restart = False
            return
        # cancel() may invalidate signals so error might not fire — poll until stop.
        QTimer.singleShot(800, self._after_stall_cancel)

    def _on_stall_restart_toggled(self, enabled: bool) -> None:
        self.stall_timeout_spin.setEnabled(enabled)
        self.stall_cmd_input.setEnabled(enabled)

    def _run_stall_hook_command(self) -> None:
        """Fire the user-configured stall hook in a background thread."""
        cmd = self.stall_cmd_input.text().strip()
        if not cmd:
            return
        if self._stall_hook_thread and self._stall_hook_thread.is_alive():
            logger.warning("Previous stall hook still running; skip new run")
            self.update_status("⚠️ 上一次卡住关联命令仍在执行，跳过本次")
            return

        self.update_status(f"🔧 执行卡住关联命令：{cmd}")
        logger.info("Starting stall hook command: %s", cmd)

        def worker() -> None:
            try:
                # shell=True so users can write pipelines / compound commands.
                run_kwargs: dict = {
                    "shell": True,
                    "capture_output": True,
                    "text": True,
                    "timeout": 120,
                }
                if platform.system().lower() == "windows":
                    run_kwargs["creationflags"] = getattr(
                        subprocess, "CREATE_NO_WINDOW", 0
                    )
                completed = subprocess.run(cmd, **run_kwargs)
                out = (completed.stdout or "").strip()
                err = (completed.stderr or "").strip()
                detail_parts = []
                if out:
                    detail_parts.append(out[:400])
                if err:
                    detail_parts.append(err[:400])
                detail = " | ".join(detail_parts)
                if completed.returncode == 0:
                    msg = "卡住关联命令已完成"
                    if detail:
                        msg = f"{msg}：{detail}"
                    self.stall_hook_finished.emit(msg, False)
                else:
                    msg = f"卡住关联命令退出码 {completed.returncode}"
                    if detail:
                        msg = f"{msg}：{detail}"
                    self.stall_hook_finished.emit(msg, True)
            except subprocess.TimeoutExpired:
                self.stall_hook_finished.emit(
                    "卡住关联命令超时（120 秒），已放弃等待", True
                )
            except Exception as exc:
                logger.exception("Stall hook command failed: %s", exc)
                self.stall_hook_finished.emit(f"卡住关联命令执行失败：{exc}", True)

        self._stall_hook_thread = threading.Thread(
            target=worker, name="stall-hook", daemon=True
        )
        self._stall_hook_thread.start()

    def _on_stall_hook_finished(self, message: str, is_error: bool) -> None:
        logger.info("Stall hook finished: error=%s msg=%s", is_error, message)
        self.update_status(message, error=is_error)

    def _after_stall_cancel(self) -> None:
        if self._user_stopped:
            self._pending_stall_restart = False
            return
        if not self._pending_stall_restart:
            return
        if self.download_worker and self.download_worker.isRunning():
            QTimer.singleShot(800, self._after_stall_cancel)
            return
        self._pending_stall_restart = False
        self.download_worker = None
        self._schedule_stall_or_error_restart(
            "因卡住无进度已中断，准备重新开始（断点续传）"
        )

    def _schedule_stall_or_error_restart(self, reason: str) -> None:
        """Shared path for stall / error restart (delay from user setting)."""
        self._stall_watch_timer.stop()
        self._retry_attempt += 1
        delay = self._retry_delay_seconds(self._retry_attempt)
        self._set_downloading_ui(True)
        self.update_status(reason, error=True)
        if delay <= 0:
            self.update_status(
                f"立即自动重新开始（第 {self._retry_attempt} 次，断点续传）。"
                "点「停止」可取消。"
            )
            # Tiny delay so cancel/cleanup can finish before restart.
            self._retry_timer.start(200)
        else:
            self.update_status(
                f"将在 {delay} 秒后自动重新开始"
                f"（第 {self._retry_attempt} 次，断点续传）。"
                "点「停止」可取消。"
            )
            self._retry_timer.start(delay * 1000)

    def update_status(self, message, error=False):
        # Worker status counts as activity (unless it's our own stall notice).
        if self.download_worker and self.download_worker.isRunning():
            if "无进度" not in message and "卡住" not in message:
                self._touch_download_activity(message)
        if error:
            self.log_text.append(f"❌ {message}")
        else:
            self.log_text.append(f"ℹ️ {message}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def update_log(self, message):
        text = str(message)
        if self.download_worker and self.download_worker.isRunning():
            self._touch_download_activity(text)
        try:
            self._monitor_window.feed_log(text)
        except Exception:
            pass
        # Structured ticks go to the monitor panel only (avoid log flood).
        if text.startswith("[HF_FILE]") or text.startswith("[HF_META]"):
            return
        # hfd overall progress is already mirrored as "Downloading (hfd total...)";
        # keep a readable copy in the main log as well.
        self.log_text.append(text)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    @staticmethod
    def _is_non_retryable_error(error_msg: str) -> bool:
        """True when retrying cannot fix the error (input / type / deps)."""
        markers = (
            "该仓库实际是",
            "请将类型切换",
            "请填写",
            "请选择保存",
            "代理地址为空",
            "不支持的平台",
            "failed to import",
            "未安装",
            "library not installed",
        )
        return any(marker in error_msg for marker in markers)

    def download_finished(self):
        self._retry_timer.stop()
        self._stall_watch_timer.stop()
        self._pending_stall_restart = False
        try:
            self._monitor_window.stop_session()
        except Exception:
            pass
        attempts = self._retry_attempt
        self._retry_attempt = 0
        self._set_downloading_ui(False)
        if attempts > 0:
            self.update_status(f"✅ 下载完成！（期间自动重试 {attempts} 次）")
        else:
            self.update_status("✅ 下载完成！")
        self.log_text.append("✅ 下载完成！")

    def download_error(self, error_msg):
        lowered = error_msg.lower()
        is_cancel = (
            self._user_stopped
            or "cancelled by user" in lowered
            or "用户已取消" in error_msg
        )

        # Stall watchdog forced a cancel → restart, not user stop.
        if self._pending_stall_restart and not self._user_stopped:
            self._pending_stall_restart = False
            self._schedule_stall_or_error_restart(f"因卡住无进度已中断：{error_msg}")
            return

        if is_cancel:
            self._retry_timer.stop()
            self._stall_watch_timer.stop()
            self._pending_stall_restart = False
            try:
                self._monitor_window.stop_session()
            except Exception:
                pass
            self._set_downloading_ui(False)
            self.update_status("⏹️ 已停止下载")
            self.log_text.append("⏹️ 已停止下载")
            return

        can_retry = (
            self.auto_retry_checkbox.isChecked()
            and not self._user_stopped
            and not self._is_non_retryable_error(error_msg)
        )
        if can_retry:
            self._schedule_stall_or_error_restart(f"下载中断：{error_msg}")
            return

        self._retry_timer.stop()
        self._stall_watch_timer.stop()
        self._pending_stall_restart = False
        self._set_downloading_ui(False)
        self.update_status(f"错误：{error_msg}", error=True)
        self.log_text.append(f"❌ 错误：{error_msg}")

    def _on_retry_timer(self):
        if self._user_stopped:
            self._set_downloading_ui(False)
            return
        if self.download_worker and self.download_worker.isRunning():
            # Wait for previous worker to fully exit, then retry.
            self._retry_timer.start(500)
            return
        self._start_download_job(clear_log=False, skip_validation=True)

    def _on_worker_finished(self):
        if hasattr(self, "download_worker") and self.download_worker:
            # Wait for thread to fully stop before cleanup
            if self.download_worker.isRunning():
                self.download_worker.wait(5000)

            # Clear the worker reference
            self.download_worker = None
