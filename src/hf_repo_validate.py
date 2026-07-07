"""Hugging Face Hub repository validation helpers."""

from huggingface_hub import HfApi
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError


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

    return (
        f"This repository is a {actual_repo_type}, not a {selected_repo_type}. "
        f"Please switch the type to '{actual_repo_type.title()}' and try again."
    )
