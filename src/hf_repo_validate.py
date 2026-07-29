"""Hugging Face Hub repository validation helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

from huggingface_hub import HfApi
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

# Network probe can hang forever without a hard ceiling (proxy/mirror/DNS issues).
DEFAULT_VALIDATE_TIMEOUT_SEC = 20


def _hf_repo_probe(
    api: HfApi,
    repo_id: str,
    repo_type: str,
    token: str | None,
) -> bool | None:
    """Return True when the repo exists, False when absent, None when inconclusive."""
    try:
        api.repo_info(repo_id=repo_id, repo_type=repo_type, token=token)
        return True
    except GatedRepoError:
        return True
    except RepositoryNotFoundError:
        return False
    except Exception:
        return None


def hf_repo_type_mismatch_message(
    api: HfApi,
    repo_id: str,
    selected_repo_type: str,
    token: str | None = None,
) -> str | None:
    """Return a user-facing hint when the selected repo type does not match the Hub."""
    selected_state = _hf_repo_probe(api, repo_id, selected_repo_type, token)
    if selected_state is not False:
        return None

    actual_repo_type = "dataset" if selected_repo_type == "model" else "model"
    actual_state = _hf_repo_probe(api, repo_id, actual_repo_type, token)
    if actual_state is not True:
        return None

    type_cn = {"model": "模型", "dataset": "数据集"}
    selected_cn = type_cn.get(selected_repo_type, selected_repo_type)
    actual_cn = type_cn.get(actual_repo_type, actual_repo_type)
    actual_ui = "Model" if actual_repo_type == "model" else "Dataset"
    return (
        f"该仓库实际是「{actual_cn}」，不是「{selected_cn}」。"
        f"请将类型切换为「{actual_ui}」后重试。"
    )


def validate_hf_repo_type(
    api: HfApi,
    repo_id: str,
    selected_repo_type: str,
    token: str | None = None,
    timeout_sec: float = DEFAULT_VALIDATE_TIMEOUT_SEC,
) -> tuple[str | None, str | None]:
    """Validate repo type with a hard timeout.

    Returns:
        (mismatch_message, warning_message)
        - mismatch_message: hard error when type is wrong
        - warning_message: soft warning when validation timed out / failed network-wise
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            hf_repo_type_mismatch_message,
            api,
            repo_id,
            selected_repo_type,
            token,
        )
        try:
            mismatch = future.result(timeout=timeout_sec)
            return mismatch, None
        except FuturesTimeoutError:
            future.cancel()
            seconds = int(timeout_sec)
            return None, (
                f"仓库校验超时（超过 {seconds} 秒），"
                "已跳过类型检查并继续下载。"
                "若后续仍长时间无进度，请检查网络、代理或 Endpoint。"
            )
        except Exception as exc:
            return None, f"仓库校验失败（{exc}），已跳过类型检查并继续下载。"
