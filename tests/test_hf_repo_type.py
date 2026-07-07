from unittest.mock import MagicMock

from huggingface_hub.errors import RepositoryNotFoundError

from src.hf_repo_validate import hf_repo_type_mismatch_message


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
    assert "is a model, not a dataset" in message
    assert "switch the type to 'Model'" in message


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
