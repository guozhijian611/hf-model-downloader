"""
Qt download worker.

Heavy download work runs in a subprocess via download_core (no PyQt imports),
so spawn/frozen builds do not re-enter the GUI stack and crash.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import threading
import time
import weakref

from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QThread, pyqtSignal

# Re-export for backward compatibility / tests
from .download_core import (  # noqa: F401
    PLATFORM_CONFIGS,
    SafePipeWriter,
    UnifiedProgressBar,
    download_huggingface,
    download_modelscope,
    isolated_download_main,
    platform_label,
    repo_type_label,
    unified_download_model,
)
from .hf_hub_env import clear_hf_download_env, configure_hf_hub_http, hf_api_client
from .hf_repo_validate import DEFAULT_VALIDATE_TIMEOUT_SEC, validate_hf_repo_type
from .proxy_env import normalize_proxy
from .utils import (
    cleanup_environment,
    cleanup_lock_files,
    kill_hfd_related_processes,
    kill_process_tree,
)


class LoggerManager:
    """Unified logger handler management to prevent memory leaks."""

    _instance = None
    _handlers = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_handler(self, signal):
        handler_id = id(signal)
        if handler_id not in self._handlers:
            self._handlers[handler_id] = LogHandler(signal)
        return self._handlers[handler_id]

    def cleanup_handler(self, signal):
        handler_id = id(signal)
        if handler_id not in self._handlers:
            return
        handler = self._handlers.pop(handler_id)
        for config in PLATFORM_CONFIGS.values():
            target_logger = logging.getLogger(config["logger_name"])
            if handler in target_logger.handlers:
                target_logger.removeHandler(handler)
        for logger_name in ["UnifiedDownloadWorker", "PyQt6"]:
            target_logger = logging.getLogger(logger_name)
            if handler in target_logger.handlers:
                target_logger.removeHandler(handler)


class LogHandler(logging.Handler):
    _LEVEL_CN = {
        "DEBUG": "调试",
        "INFO": "信息",
        "WARNING": "警告",
        "ERROR": "错误",
        "CRITICAL": "严重",
    }

    def __init__(self, log_signal):
        super().__init__()
        self.log_signal = log_signal
        # formatTime lives on Formatter, not Handler.
        self._time_formatter = logging.Formatter()

    def emit(self, record):
        try:
            level = self._LEVEL_CN.get(record.levelname, record.levelname)
            stamp = self._time_formatter.formatTime(record, datefmt="%H:%M:%S")
            msg = f"{stamp} [{level}] {record.getMessage()}"
            self.log_signal.emit(msg)
        except Exception:
            # Never let logging failures abort the download thread.
            self.handleError(record)


class ThreadSafeSignalEmitter(QObject):
    """Thread-safe signal emitter with object lifecycle management."""

    # Do NOT name these finished/error — would shadow QThread.finished.
    download_finished = pyqtSignal()
    download_error = pyqtSignal(str)
    download_status = pyqtSignal(str)
    download_log = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._is_valid = True
        self._parent_ref = weakref.ref(parent) if parent else None

    def safe_emit(self, signal_name: str, *args):
        with QMutexLocker(self._mutex):
            if not self._is_valid:
                return False

            if self._parent_ref:
                parent = self._parent_ref()
                if (
                    parent is None
                    or not hasattr(parent, "isRunning")
                    or not parent.isRunning()
                ):
                    return False

            try:
                signal = getattr(self, signal_name, None)
                if signal is not None:
                    signal.emit(*args)
                    return True
            except (RuntimeError, AttributeError):
                self._is_valid = False
                return False
        return False

    def invalidate(self):
        with QMutexLocker(self._mutex):
            self._is_valid = False


class UnifiedDownloadWorker(QThread):
    """QThread wrapper that validates then spawns a Qt-free download process."""

    def __init__(
        self,
        platform,
        model_id,
        save_path,
        token=None,
        endpoint=None,
        repo_type="model",
        proxy=None,
        skip_validation=False,
        endpoints=None,
        backend="huggingface-hub",
        max_workers=None,
        hfd_threads=None,
        hfd_jobs=None,
    ):
        super().__init__()

        if platform not in PLATFORM_CONFIGS:
            raise ValueError(
                f"Unsupported platform, Only Supported: {list(PLATFORM_CONFIGS.keys())}"
            )

        self.platform = platform
        self.model_id = model_id
        self.save_path = save_path
        self.token = token
        self.repo_type = repo_type
        self.proxy = normalize_proxy(proxy)
        self.skip_validation = bool(skip_validation)
        self.backend = (backend or "huggingface-hub").strip()
        self.max_workers = max_workers
        self.hfd_threads = hfd_threads
        self.hfd_jobs = hfd_jobs

        self._config = PLATFORM_CONFIGS[platform]
        # Prefer multi-endpoint chain; fall back to single endpoint.
        chain: list[str] = []
        if endpoints:
            for item in endpoints:
                url = (item or "").strip().rstrip("/")
                if url and url not in chain:
                    chain.append(url)
        single = (endpoint or "").strip().rstrip("/")
        if single and single not in chain:
            chain.insert(0, single)
        if not chain:
            chain = [self._config["default_endpoint"]]
        self.endpoints = chain
        self.endpoint = chain[0]

        # Emitter lives in the main thread (created here with QThread parent).
        self._signal_emitter = ThreadSafeSignalEmitter(self)

        # Public aliases used by the UI (not QThread.finished).
        self.download_finished = self._signal_emitter.download_finished
        self.download_error = self._signal_emitter.download_error
        self.download_status = self._signal_emitter.download_status
        self.download_log = self._signal_emitter.download_log
        # Backward-compatible aliases
        self.error = self.download_error
        self.status = self.download_status
        self.log = self.download_log
        # NOTE: do not assign self.finished — that shadows QThread.finished.

        self._logger = logging.getLogger("UnifiedDownloadWorker")
        self._logger.setLevel(logging.DEBUG)

        self.logger_manager = LoggerManager()
        self.log_handler = self.logger_manager.get_handler(self.download_log)
        self.log_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self.log_handler.setLevel(logging.INFO)

        platform_logger = logging.getLogger(self._config["logger_name"])
        platform_logger.addHandler(self.log_handler)
        self._logger.addHandler(self.log_handler)

        self.repo_name = self.model_id.split("/")[-1]
        self.repo_dir = os.path.join(self.save_path, self.repo_name)

        self._cancel_event = threading.Event()
        # Sticky across endpoint failover; Event alone is cleared/replaced and races.
        self._user_cancel_requested = False
        self._download_process = None
        self._pipe_reader = None
        self._pipe_writer = None
        self._output_thread = None
        self._is_running = False

    def _safe_emit(self, signal_name: str, *args):
        return self._signal_emitter.safe_emit(signal_name, *args)

    def _is_cancel_requested(self) -> bool:
        """True when user (or stall) asked to stop — sticky, not just the Event."""
        if getattr(self, "_user_cancel_requested", False):
            return True
        try:
            if self._cancel_event.is_set():
                return True
        except Exception:
            pass
        try:
            if self.isInterruptionRequested():
                return True
        except Exception:
            pass
        return False

    def run(self):
        try:
            self._is_running = True
            self._user_cancel_requested = False
            self._cancel_event.clear()
            self._run()
        except Exception as e:
            # Last-resort: never let exceptions kill the whole GUI process.
            try:
                self._safe_emit("download_error", f"下载线程异常：{e}")
            except Exception:
                pass
        finally:
            self._is_running = False

    def _stop_download_process(self, *, reason: str = "cancel") -> None:
        """
        Stop the spawn download worker and its whole process tree.

        hfd runs bash → aria2c as grandchildren; a plain Process.terminate()
        leaves them orphaned on Windows.
        """
        proc = self._download_process
        if proc is None:
            # Still sweep residual hfd/aria2 for this repo (prior orphans).
            if getattr(self, "backend", "") == "hfd":
                kill_hfd_related_processes(getattr(self, "repo_dir", None))
            return

        pid = getattr(proc, "pid", None)
        try:
            alive = False
            try:
                alive = proc.is_alive()
            except (ValueError, AssertionError, OSError):
                alive = False

            if alive or pid:
                self._logger.info(
                    "终止下载进程树（%s）pid=%s backend=%s",
                    reason,
                    pid,
                    getattr(self, "backend", ""),
                )
                kill_process_tree(pid, grace_sec=2.0)
                try:
                    proc.join(timeout=2.0)
                except Exception:
                    pass
                try:
                    if proc.is_alive():
                        proc.kill()
                        kill_process_tree(pid, grace_sec=1.0)
                        proc.join(timeout=1.0)
                except (ValueError, AssertionError, OSError, ProcessLookupError):
                    pass
        except Exception as e:
            self._logger.error("终止下载进程失败：%s", e)
        finally:
            # hfd safety net: orphans from incomplete trees or prior runs.
            if getattr(self, "backend", "") == "hfd":
                try:
                    kill_hfd_related_processes(getattr(self, "repo_dir", None))
                except Exception as e:
                    self._logger.warning("清理 hfd 残留进程失败：%s", e)

    def cancel_download(self):
        # Sticky cancel first so the endpoint loop cannot "failover" after kill.
        self._user_cancel_requested = True
        try:
            self._cancel_event.set()
        except Exception:
            pass
        try:
            self.requestInterruption()
        except Exception:
            pass

        if not self.isRunning():
            # Even if the QThread finished, sweep orphaned hfd/aria2 workers.
            if getattr(self, "backend", "") == "hfd":
                kill_hfd_related_processes(getattr(self, "repo_dir", None))
            return

        self._stop_download_process(reason="user_cancel")

        # Do NOT cleanup()/close pipes here — the worker thread still owns them.
        # Closing early causes WinError 6 (invalid handle) in the pipe reader and
        # can race with endpoint failover logic. Final cleanup is in _run.finally.
        try:
            self.quit()
        except Exception:
            pass

    def _run(self):
        platform_cn = platform_label(self.platform)
        repo_type_cn = repo_type_label(self.repo_type)
        try:
            self._logger.info(f"开始 {platform_cn} 下载任务")
            cleanup_lock_files(self.repo_dir)

            if self.platform == "huggingface" and not self.skip_validation:
                timeout_sec = DEFAULT_VALIDATE_TIMEOUT_SEC
                self._safe_emit(
                    "download_status",
                    (
                        f"正在校验仓库类型（连接 {self.endpoint}，"
                        f"最长 {timeout_sec} 秒）..."
                    ),
                )
                self._safe_emit("download_log", f"仓库 ID：{self.model_id}")
                self._safe_emit("download_log", f"选择类型：{repo_type_cn}")
                self._safe_emit("download_log", f"Endpoint：{self.endpoint}")
                if self.proxy:
                    self._safe_emit("download_log", f"代理：{self.proxy}")
                else:
                    self._safe_emit("download_log", "代理：未启用")

                configure_hf_hub_http(self.proxy)
                with hf_api_client(token=self.token, endpoint=self.endpoint) as api:
                    mismatch, warning = validate_hf_repo_type(
                        api,
                        self.model_id,
                        self.repo_type,
                        self.token,
                        timeout_sec=timeout_sec,
                    )
                if mismatch:
                    raise Exception(mismatch)
                if warning:
                    self._safe_emit("download_status", warning)
                    self._safe_emit("download_log", f"提示：{warning}")
                else:
                    self._safe_emit("download_status", "仓库校验通过，开始下载...")
                    self._safe_emit("download_log", "仓库类型校验通过")
            elif self.platform == "huggingface" and self.skip_validation:
                self._safe_emit(
                    "download_log", "重试模式：跳过仓库类型校验，直接续传下载"
                )

            self._safe_emit(
                "download_status",
                f"正在从 {platform_cn} 下载{repo_type_cn}到 {self.repo_dir} ...",
            )
            self._safe_emit(
                "download_log",
                f"开始下载 {self.model_id} → {self.repo_dir}",
            )
            if self.proxy:
                self._safe_emit("download_log", f"已启用代理：{self.proxy}")
            if len(self.endpoints) > 1:
                self._safe_emit(
                    "download_log",
                    "Endpoint 尝试顺序：" + " → ".join(self.endpoints),
                )

            download_completed = False
            user_cancelled = False
            self._last_process_errors: list[str] = []
            last_exitcode = None

            for ep_index, endpoint in enumerate(self.endpoints):
                # Always re-check sticky cancel (UI may kill the process from
                # another thread; exitcode alone must not trigger failover).
                if self._is_cancel_requested():
                    user_cancelled = True
                    self._logger.info("取消已请求，跳过后续 Endpoint")
                    break

                self.endpoint = endpoint
                total_eps = len(self.endpoints)
                self._safe_emit(
                    "download_status",
                    f"使用 Endpoint（{ep_index + 1}/{total_eps}）：{endpoint}",
                )
                self._safe_emit("download_log", f"当前 Endpoint：{endpoint}")

                # Only clear the Event between endpoints when NOT cancelling.
                # Never clear sticky _user_cancel_requested here.
                if not self._is_cancel_requested():
                    try:
                        self._cancel_event.clear()
                    except Exception:
                        pass

                self._pipe_reader, self._pipe_writer = multiprocessing.Pipe(
                    duplex=False
                )
                self._output_thread = threading.Thread(
                    target=self._process_pipe_output, daemon=True
                )
                self._output_thread.start()

                self._download_process = multiprocessing.get_context("spawn").Process(
                    target=isolated_download_main,
                    args=(
                        self.platform,
                        self.model_id,
                        self.save_path,
                        self.token,
                        endpoint,
                        self._pipe_writer,
                        self.repo_type,
                        self.proxy,
                        self.backend,
                        self.max_workers,
                        self.hfd_threads,
                        self.hfd_jobs,
                    ),
                )
                self._download_process.start()
                self._safe_emit("download_log", "下载进程已启动，等待数据传输...")

                while True:
                    if self._is_cancel_requested():
                        user_cancelled = True
                        self._logger.info("检测到取消请求，正在终止下载进程")
                        self._stop_download_process(reason="cancel_loop")
                        break
                    proc = self._download_process
                    if proc is None:
                        break
                    try:
                        if not proc.is_alive():
                            break
                    except (ValueError, AssertionError, OSError):
                        break
                    try:
                        proc.join(timeout=0.1)
                    except Exception:
                        time.sleep(0.1)

                # If UI killed the process first, is_alive became false without
                # entering the cancel branch — still treat as user cancel.
                if self._is_cancel_requested():
                    user_cancelled = True

                proc = self._download_process
                try:
                    last_exitcode = proc.exitcode if proc is not None else last_exitcode
                except Exception:
                    pass
                # Ensure tree is dead after cancel (and clear residual hfd workers).
                if user_cancelled or self._is_cancel_requested():
                    user_cancelled = True
                    self._stop_download_process(reason="post_cancel")
                try:
                    self._cancel_event.set()
                except Exception:
                    pass
                if self._output_thread:
                    self._output_thread.join(timeout=2.0)
                self._output_thread = None
                # Close pipes after reader stops (avoid WinError 6 races).
                try:
                    if self._pipe_reader is not None:
                        self._pipe_reader.close()
                except Exception:
                    pass
                try:
                    if self._pipe_writer is not None:
                        self._pipe_writer.close()
                except Exception:
                    pass
                self._pipe_reader = None
                self._pipe_writer = None
                self._download_process = None

                if user_cancelled or self._is_cancel_requested():
                    user_cancelled = True
                    self._logger.info(
                        "%s Endpoint %s 因取消结束（退出码：%s）",
                        platform_cn,
                        endpoint,
                        last_exitcode,
                    )
                    break

                if last_exitcode == 0:
                    download_completed = True
                    break

                self._logger.info(
                    f"{platform_cn} Endpoint {endpoint} 退出码：{last_exitcode}"
                )
                if ep_index + 1 < len(self.endpoints):
                    if self._is_cancel_requested():
                        user_cancelled = True
                        break
                    self._safe_emit(
                        "download_log",
                        f"Endpoint 失败，切换下一个：{self.endpoints[ep_index + 1]}",
                    )
                    # Fresh Event for next attempt only (sticky cancel stays).
                    if not self._is_cancel_requested():
                        self._cancel_event = threading.Event()

            if download_completed:
                cleanup_lock_files(self.repo_dir)
                self._safe_emit(
                    "download_log",
                    f"{platform_cn}{repo_type_cn}已下载到：{self.repo_dir}",
                )
                self._logger.info(f"{platform_cn} 下载成功")
                self._safe_emit("download_finished")
            elif user_cancelled or self._is_cancel_requested():
                raise Exception("用户已取消下载")
            else:
                detail = ""
                if self._last_process_errors:
                    detail = self._last_process_errors[-1]
                if detail:
                    raise Exception(detail)
                raise Exception(
                    f"{platform_cn} 下载进程失败"
                    f"（退出码 {last_exitcode}）。"
                    "请检查网络、代理、Token 或 Endpoint。"
                )

        except Exception as e:
            error_msg = str(e)
            self._logger.error(f"{platform_cn} 下载失败：{error_msg}")
            self._safe_emit("download_log", f"错误：{error_msg}")
            self._safe_emit("download_error", error_msg)
        finally:
            self._logger.info(f"{platform_cn} 下载任务结束")
            self._is_running = False
            if hasattr(self, "_cancel_event"):
                self._cancel_event.set()
            if (
                hasattr(self, "_output_thread")
                and self._output_thread
                and self._output_thread.is_alive()
            ):
                self._output_thread.join(timeout=1.0)
            self.cleanup()

    def _process_pipe_output(self):
        while not self._is_cancel_requested():
            reader = self._pipe_reader
            if reader is None:
                break
            try:
                if reader.poll(0.01):
                    try:
                        output = reader.recv()
                        if output == "DOWNLOAD_COMPLETE":
                            break
                        text = str(output)
                        # Capture child-process error lines for the final UI message.
                        if text.startswith("错误：") or text.startswith("Error:"):
                            if not hasattr(self, "_last_process_errors"):
                                self._last_process_errors = []
                            self._last_process_errors.append(text)
                        self._safe_emit("download_log", text)
                    except EOFError:
                        break
                    except (OSError, BrokenPipeError, ValueError) as e:
                        # WinError 6 invalid handle after cancel closes the pipe.
                        if self._is_cancel_requested():
                            break
                        self._logger.debug("管道读取结束：%s", e)
                        break
                    except Exception as e:
                        if self._is_cancel_requested():
                            break
                        self._logger.error(f"处理下载输出失败：{e}")
                        continue
            except (OSError, BrokenPipeError, ValueError) as e:
                if not self._is_cancel_requested():
                    self._logger.debug("读取下载输出管道结束：%s", e)
                break
            except Exception as e:
                if self._is_cancel_requested():
                    break
                self._logger.error(f"读取下载输出管道失败：{e}")
                break

    def cleanup(self):
        cleanup_errors = []
        try:
            current_endpoint = os.environ.get(self._config["endpoint_env"])
            try:
                cleanup_environment()
                os.environ.pop(self._config["token_env"], None)
                os.environ.pop(self._config["endpoint_env"], None)
                if self.platform == "huggingface":
                    clear_hf_download_env()
            except Exception as e:
                cleanup_errors.append(f"环境清理失败：{e}")

            if current_endpoint:
                os.environ[self._config["endpoint_env"]] = current_endpoint

            try:
                if getattr(self, "_pipe_reader", None):
                    self._pipe_reader.close()
                if getattr(self, "_pipe_writer", None):
                    self._pipe_writer.close()
            except Exception as e:
                cleanup_errors.append(f"管道清理失败：{e}")

            try:
                if hasattr(self, "logger_manager"):
                    self.logger_manager.cleanup_handler(self.download_log)
            except Exception as e:
                cleanup_errors.append(f"日志清理失败：{e}")

            try:
                cleanup_lock_files(self.repo_dir)
            except Exception as e:
                cleanup_errors.append(f"锁文件清理失败：{e}")

            try:
                if hasattr(self, "_signal_emitter"):
                    self._signal_emitter.invalidate()
            except Exception as e:
                cleanup_errors.append(f"信号清理失败：{e}")

            if cleanup_errors:
                self._logger.warning(f"清理完成但有问题：{'; '.join(cleanup_errors)}")
        except Exception as e:
            self._logger.exception(f"清理时发生严重错误：{e}")
