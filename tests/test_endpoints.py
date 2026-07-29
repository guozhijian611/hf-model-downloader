from src.endpoints import (
    build_endpoint_chain,
    default_endpoint,
    url_from_combo_text,
)


def test_url_from_combo_text():
    assert (
        url_from_combo_text("https://hf-mirror.com  —  HF 镜像（国内推荐）")
        == "https://hf-mirror.com"
    )
    assert url_from_combo_text("https://huggingface.co/") == "https://huggingface.co"
    assert url_from_combo_text("  ") == ""


def test_build_endpoint_chain_failover():
    chain = build_endpoint_chain(
        "https://hf-mirror.com",
        "huggingface",
        failover=True,
    )
    assert chain[0] == "https://hf-mirror.com"
    assert "https://huggingface.co" in chain
    assert len(chain) == len(set(chain))


def test_build_endpoint_chain_no_failover():
    chain = build_endpoint_chain(
        "https://huggingface.co",
        "huggingface",
        failover=False,
    )
    assert chain == ["https://huggingface.co"]


def test_default_endpoints():
    assert default_endpoint("huggingface").startswith("http")
    assert "modelscope" in default_endpoint("modelscope")
