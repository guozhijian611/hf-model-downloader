from unittest.mock import MagicMock

from huggingface_hub.errors import RepositoryNotFoundError

from src.hf_repo_validate import (
    hf_repo_type_mismatch_message,
    validate_hf_repo_type,
)


def test_no_mismatch_when_selected_type_exists():
    api = MagicMock()
    api.repo_info.return_value = object()

    assert hf_repo_type_mismatch_message(api, "org/model", "model", token=None) is None
    api.repo_info.assert_called_once_with(
        repo_id="org/model",
        repo_type="model",
        token=None,
    )


def test_detect_model_selected_as_dataset():
    api = MagicMock()
    api.repo_info.side_effect = [
        RepositoryNotFoundError("missing", response=MagicMock()),
        object(),
    ]

    message = hf_repo_type_mismatch_message(
        api,
        "MonsterMMORPG/Kohya_Train",
        "dataset",
        token=None,
    )

    assert message is not None
    assert "模型" in message
    assert "数据集" in message
    assert "Model" in message


def test_no_mismatch_when_repo_missing_on_both_types():
    api = MagicMock()
    api.repo_info.side_effect = RepositoryNotFoundError(
        "missing",
        response=MagicMock(),
    )

    assert (
        hf_repo_type_mismatch_message(
            api,
            "definitely/does-not-exist",
            "model",
            token=None,
        )
        is None
    )
    assert api.repo_info.call_count == 2


def test_skips_mismatch_when_hub_probe_is_inconclusive():
    api = MagicMock()
    api.repo_info.side_effect = TimeoutError("hub timeout")

    assert (
        hf_repo_type_mismatch_message(
            api,
            "MonsterMMORPG/Kohya_Train",
            "dataset",
            token=None,
        )
        is None
    )
    api.repo_info.assert_called_once()


def test_validate_hf_repo_type_timeout_returns_warning():
    api = MagicMock()

    def slow_repo_info(**_kwargs):
        import time

        time.sleep(2)
        return object()

    api.repo_info.side_effect = slow_repo_info

    # Force the outer validate timeout by patching the called function path:
    # use a very short timeout around a blocking probe via monkeypatch of
    # hf_repo_type_mismatch_message behavior isn't needed if we make
    # validate call real function that hangs on repo_info.
    # Instead simulate hang with side_effect sleep and tiny timeout.
    mismatch, warning = validate_hf_repo_type(
        api,
        "org/model",
        "model",
        token=None,
        timeout_sec=0.1,
    )
    assert mismatch is None
    assert warning is not None
    assert "超时" in warning
