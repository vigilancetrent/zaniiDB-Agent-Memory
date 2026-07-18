import pytest

from zanii_memory.config import Settings


@pytest.fixture
def cfg(tmp_path) -> Settings:
    """Isolated config: tmp data dir, LLM/embeddings disabled, env ignored."""
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "memory",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
        embedding_base_url="",
        embedding_api_key="",
        embedding_model="",
        gateway_api_key="",
        cors_origins="",
    )
