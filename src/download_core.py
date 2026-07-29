"""
Qt-free download core used by subprocess workers.

IMPORTANT: This module must NOT import PyQt. Spawned download processes load
this module only — importing Qt in a child of a GUI app can crash the app
(especially frozen PyInstaller builds on Windows/macOS).
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import sys

from tqdm.auto import tqdm

from .hf_hub_env import apply_hf_download_env, resolve_hf_endpoint, xet_available
from .proxy_env import apply_proxy_env, normalize_proxy, proxies_dict

PLATFORM_LABELS = {
    "huggingface": "Hugging Face",
    "modelscope": "ModelScope",
}

PLATFORM_CONFIGS = {
    "huggingface": {
        "token_env": "HF_TOKEN",
        "endpoint_env": "HF_ENDPOINT",
        "logger_name": "huggingface_hub",
        "default_endpoint": "https://huggingface.co",
        "mirror_endpoint": "https://hf-mirror.com",
        "ssl_verification": True,
    },
    "modelscope": {
        "token_env": "MODELSCOPE_API_TOKEN",
        "endpoint_env": "MODELSCOPE_ENDPOINT",
        "logger_name": "modelscope",
        "default_endpoint": "https://modelscope.cn",
        "mirror_endpoint": "https://modelscope.cn",
        "ssl_verification": True,
    },
}


def platform_label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, platform)


def repo_type_label(repo_type: str) -> str:
    return "模型" if repo_type == "model" else "数据集"


def _abort_download(pipe, message: str) -> None:
    if pipe:
        try:
            pipe.send(f"错误：{message}")
        except Exception:
            pass
    print(f"错误：{message}", flush=True)
    sys.exit(1)


class UnifiedProgressBar(tqdm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current = self.n

    def update(self, n):
        super().update(n)
        self._current += n


class SafePipeWriter:
    """Process-safe pipe writer that doesn't hold PyQt references."""

    def __init__(self, pipe):
        if hasattr(pipe, "send"):
            self.pipe = pipe
        else:
            self.pipe = None
        self.buffer = ""
        self.last_progress = ""
        self._closed = False

    def send(self, message):
        if self._closed or not self.pipe:
            return
        try:
            self.pipe.send(str(message))
        except (BrokenPipeError, OSError, EOFError):
            self._closed = True

    def write(self, text):
        if self._closed:
            return

        if "\r" in text:
            self.buffer = text.split("\r")[-1]
            if self.buffer.strip() and self.buffer != self.last_progress:
                self.send(self.buffer)
                self.last_progress = self.buffer
        elif "\n" in text:
            self.buffer += text
            lines = self.buffer.split("\n")
            self.buffer = lines[-1]
            for line in lines[:-1]:
                if line.strip() and line != self.last_progress:
                    self.send(line)
        else:
            self.buffer += text

    def flush(self):
        if (
            not self._closed
            and self.buffer.strip()
            and self.buffer != self.last_progress
        ):
            self.send(self.buffer)
            self.buffer = ""

    def close(self):
        self._closed = True
        self.pipe = None


def _hf_friendly_error(exc: Exception, endpoint: str) -> str:
    msg = str(exc)
    tips: list[str] = [f"Hugging Face 下载失败：{msg}"]
    lower = msg.lower()
    if (
        "cannot find the requested files in the local cache" in lower
        or "error happened while trying to locate the file" in lower
        or "connection" in lower
        or "timed out" in lower
        or "timeout" in lower
        or "max retries" in lower
    ):
        tips.append("可能原因与建议：")
        tips.append(
            f"1) 当前 Endpoint「{endpoint}」连不上或镜像不完整，"
            "可改试 https://huggingface.co（需代理时请启用代理）"
        )
        tips.append("2) 网络不稳定：开启系统/本机代理后重试（支持断点续传）")
        tips.append("3) 私有/门禁仓库：请填写有效 HF Token")
        tips.append("4) 超大仓库文件很多时，可降低并发或换网络环境再试")
    return "\n".join(tips)


def download_huggingface(
    model_id: str,
    save_path: str,
    token: str = None,
    endpoint: str = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str = None,
):
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        _abort_download(pipe, f"无法导入 huggingface_hub：{exc}")

    resolved_endpoint = resolve_hf_endpoint(endpoint)
    apply_hf_download_env(token=token, endpoint=resolved_endpoint)
    apply_proxy_env(proxy)
    proxy_map = proxies_dict(proxy)

    repo_dir = os.path.join(save_path, model_id.split("/")[-1])
    using_mirror = "mirror" in resolved_endpoint.lower()

    if pipe:
        if using_mirror:
            pipe.send("提示：镜像站已禁用 Xet 传输，改用标准 HTTP（兼容性更好）。")
        elif not xet_available():
            pipe.send(
                "警告：未检测到 hf_xet，"
                "大文件可能回退为普通 HTTP 下载（速度可能较慢）。"
            )
        if proxy_map:
            pipe.send(f"Hugging Face 下载使用代理：{normalize_proxy(proxy)}")
        pipe.send(f"开始从 Hugging Face 下载：{model_id}")
        pipe.send(f"仓库类型：{repo_type}")
        pipe.send(f"保存目录：{repo_dir}")
        pipe.send(f"Endpoint：{resolved_endpoint}")

    # Large multi-file repos are more stable with moderate concurrency.
    cpu_count = multiprocessing.cpu_count()
    max_workers = min(cpu_count, 4) if using_mirror else min(cpu_count + 2, 8)

    # Datasets often need many file types; only skip junk / VCS noise for them.
    if repo_type == "dataset":
        ignore_patterns = [".*", "__pycache__/*"]
    else:
        ignore_patterns = [
            "*.h5",
            "*.ot",
            "*.msgpack",
            "*.bin",
            "*.pkl",
            "*.onnx",
            ".*",
        ]

    try:
        result = snapshot_download(
            repo_id=model_id,
            repo_type=repo_type,
            local_dir=repo_dir,
            token=token,
            force_download=False,
            max_workers=max_workers,
            tqdm_class=UnifiedProgressBar,
            ignore_patterns=ignore_patterns,
            local_files_only=False,
            etag_timeout=60,
            proxies=proxy_map,
            endpoint=resolved_endpoint,
        )
    except Exception as exc:
        _abort_download(pipe, _hf_friendly_error(exc, resolved_endpoint))

    if pipe:
        pipe.send(f"Hugging Face 下载完成：{result}")


def download_modelscope(
    model_id: str,
    save_path: str,
    token: str = None,
    endpoint: str = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str = None,
):
    try:
        from modelscope import HubApi, MsDataset
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError:
        _abort_download(pipe, "未安装 ModelScope 库。")

    apply_proxy_env(proxy)

    if token:
        try:
            api = HubApi()
            api.login(token)
            if pipe:
                pipe.send("ModelScope 登录成功")
        except Exception as e:
            if pipe:
                pipe.send(f"ModelScope 登录失败：{e!s}")

    if endpoint:
        os.environ["MODELSCOPE_ENDPOINT"] = endpoint

    repo_name = model_id.split("/")[-1]
    repo_dir = os.path.join(save_path, repo_name)

    if pipe:
        if normalize_proxy(proxy):
            pipe.send(f"ModelScope 下载使用代理：{normalize_proxy(proxy)}")
        pipe.send(f"开始从 ModelScope 下载：{model_id}")
        if repo_type == "dataset":
            pipe.send(f"正在下载数据集到：{repo_dir}")
        else:
            pipe.send(f"正在下载模型到：{repo_dir}")

    try:
        if repo_type == "dataset":
            if pipe:
                pipe.send("使用 MsDataset 下载数据集...")

            os.makedirs(repo_dir, exist_ok=True)

            MsDataset.load(
                dataset_name=model_id,
                cache_dir=repo_dir,
            )

            if pipe:
                pipe.send(f"ModelScope 数据集已缓存到：{repo_dir}")

            result = repo_dir
        else:
            result = snapshot_download(
                model_id=model_id,
                local_dir=repo_dir,
                revision="master",
                ignore_patterns=[
                    "*.h5",
                    "*.ot",
                    "*.msgpack",
                    "*.bin",
                    "*.pkl",
                    "*.onnx",
                    ".*",
                ],
            )

        if pipe:
            pipe.send(f"ModelScope 下载完成：{result}")

    except Exception as exc:
        _abort_download(pipe, f"ModelScope 下载失败：{exc}")


def unified_download_model(
    platform: str,
    model_id: str,
    save_path: str,
    token: str = None,
    endpoint: str = None,
    pipe=None,
    repo_type: str = "model",
    proxy: str = None,
    backend: str = "huggingface-hub",
):
    """Download entry used by subprocess workers (no Qt)."""
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected = False
    try:
        if platform not in PLATFORM_CONFIGS:
            _abort_download(pipe, f"不支持的平台「{platform}」")

        print(f"\n=== {platform.title()} Download Process Debug Info ===")
        print("Process ID:", os.getpid())
        print("Parent Process ID:", os.getppid())
        print("Current Working Directory:", os.getcwd())
        print("Python Executable:", sys.executable)
        print("Download Backend:", backend or "huggingface-hub")
        try:
            print("Process Start Method:", multiprocessing.get_start_method())
        except RuntimeError:
            print("Process Start Method: (not set)")
        print("=== End Debug Info ===\n")

        if pipe:
            sys.stdout = pipe
            sys.stderr = pipe
            redirected = True

        def signal_handler(signum, frame):
            if pipe:
                try:
                    pipe.send("下载被系统信号中断")
                except Exception:
                    pass
            sys.exit(1)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        try:
            if platform == "huggingface":
                from .hfd_backend import BACKEND_HFD, download_with_hfd

                if (backend or "").strip() == BACKEND_HFD:
                    download_with_hfd(
                        model_id,
                        save_path,
                        token,
                        endpoint,
                        pipe,
                        repo_type,
                        proxy,
                    )
                else:
                    download_huggingface(
                        model_id,
                        save_path,
                        token,
                        endpoint,
                        pipe,
                        repo_type,
                        proxy,
                    )
            elif platform == "modelscope":
                if (backend or "").strip() == "hfd":
                    _abort_download(
                        pipe,
                        "hfd 仅支持 Hugging Face，请切换平台或改用 huggingface-hub。",
                    )
                download_modelscope(
                    model_id, save_path, token, endpoint, pipe, repo_type, proxy
                )
            else:
                _abort_download(pipe, f"不支持的平台「{platform}」")
        except KeyboardInterrupt:
            _abort_download(pipe, "用户已取消下载")

    except SystemExit:
        raise
    except Exception as exc:
        _abort_download(pipe, f"{platform_label(platform)} 下载出错：{exc}")
    finally:
        if redirected:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        if pipe:
            try:
                pipe.send("DOWNLOAD_COMPLETE")
            except (BrokenPipeError, OSError, EOFError):
                pass


def isolated_download_main(
    platform,
    model_id,
    save_path,
    token,
    endpoint,
    pipe,
    repo_type,
    proxy=None,
    backend="huggingface-hub",
):
    """
    Top-level process entry point (must stay free of PyQt imports).

    Used as multiprocessing.Process(target=isolated_download_main, ...).
    """
    try:
        safe_pipe = SafePipeWriter(pipe)
        unified_download_model(
            platform,
            model_id,
            save_path,
            token,
            endpoint,
            safe_pipe,
            repo_type,
            proxy,
            backend=backend,
        )
        safe_pipe.close()
    except SystemExit:
        raise
    except Exception as e:
        if pipe:
            try:
                pipe.send(f"下载进程错误：{e!s}")
            except (BrokenPipeError, OSError, EOFError):
                pass
        sys.exit(1)


# Keep logger quiet in child unless configured by parent.
logging.getLogger("download_core").addHandler(logging.NullHandler())
