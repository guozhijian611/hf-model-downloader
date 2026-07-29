"""
Utility functions for the Model Downloader
"""

import logging
import os

logger = logging.getLogger("huggingface_hub")
logger.setLevel(logging.INFO)


def cleanup_lock_files(directory):
    """Clean up any .lock files in the directory and its subdirectories."""
    logger.info("正在清理下载锁文件（保留已下载分块以便断点续传）...")
    try:
        for root, _dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".lock"):
                    lock_file = os.path.join(root, file)
                    try:
                        os.remove(lock_file)
                        logger.info(f"已删除锁文件：{lock_file}")
                    except Exception as e:
                        logger.warning(f"无法删除锁文件 {lock_file}：{e!s}")
    except Exception as e:
        logger.warning(f"清理锁文件时出错：{e!s}")


def cleanup_environment():
    """Clean up environment variables."""
    env_vars = ["HF_TOKEN", "HF_HUB_DISABLE_SSL_VERIFICATION"]
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]
