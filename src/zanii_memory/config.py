"""Configuration via ZANII_* environment variables. Zero-config by default:
no LLM/embedding keys -> L0 capture + keyword-only recall still work."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZANII_", env_file=".env", extra="ignore")

    data_dir: Path = Path.home() / ".zanii" / "memory"

    # Storage backend: empty -> SQLite in data_dir; postgresql://... -> Postgres + pgvector.
    database_url: str = ""

    # LLM — powers L1/L3 extraction, conflict resolution, the firewall screen.
    # provider="openai": any OpenAI-compatible /chat/completions endpoint (incl.
    #   Anthropic's compat layer, gateways, Ollama). provider="anthropic": native
    #   Claude Messages API (/v1/messages) — base URL defaults to api.anthropic.com.
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    anthropic_version: str = "2023-06-01"  # sent as anthropic-version header in native mode
    # >0 overrides every LLM call timeout (seconds) — for slow local backends
    # (Ollama on laptop hardware needs 600-1200s for large extraction prompts).
    llm_timeout_s: float = 0

    # Embeddings (OpenAI-compatible) — fall back to the LLM endpoint/key when unset.
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 1536

    # Recall
    recall_strategy: Literal["keyword", "embedding", "hybrid"] = "hybrid"
    recall_max_results: int = 5
    recall_max_total_chars: int = 4000
    recall_timeout_s: float = 5.0
    # Present selected memories oldest->newest (selection stays relevance-ranked).
    # Off by default; not yet benchmark-validated in isolation.
    recall_chronological: bool = False
    # Procedural recall: inject the best-matching learned skill (skills/*.md)
    # into the system context. Fires only on strong matches.
    recall_skills: bool = True

    # Pipeline triggers
    pipeline_every_n_turns: int = 5
    pipeline_warmup: bool = True
    pipeline_idle_timeout_s: int = 600
    pipeline_persona_every_n: int = 50
    pipeline_max_memories: int = 20
    pipeline_skills: bool = True  # distill SOP/skill docs after each persona regeneration

    # Full-text tokenization: "unicode61" (default) or "trigram" (CJK-friendly, SQLite;
    # queries need a contiguous substring of >= 3 characters). Applies at DB creation.
    # Postgres uses a text-search config name instead ("simple", "english", ...).
    fts_tokenizer: Literal["unicode61", "trigram"] = "unicode61"
    pg_text_search_config: str = "simple"

    # Memory Firewall (anti-poisoning). Channels outside the trusted set mark
    # content as third-party (tool outputs, fetched web/email); instructions
    # from untrusted channels are always quarantined. strict=True quarantines
    # EVERY untrusted-channel memory pending review.
    firewall_enabled: bool = True
    firewall_trusted_channels: str = "user,assistant"
    firewall_strict: bool = False
    # LLM screen precision scales with model quality; weak local models
    # over-flag legitimate standing instructions (red-team: phi4 4/8 FP).
    # Disable to keep the precise heuristic + policy layers without the noise.
    firewall_llm_screen: bool = True

    # Conflict resolution & scene synthesis
    supersede_max_distance: float = 0.45  # neighbor distance considered for contradiction check
    scene_condense_chars: int = 3000  # LLM-synthesize scene files above this size; 0 = off

    # Consolidation & retention
    dedup_max_distance: float = 0.08  # cosine distance for near-duplicate merge
    retention_episodic_days: int = 0  # 0 = keep forever
    retention_keep_priority: int = 90  # episodic memories at/above this survive retention

    # Audit log (off by default — one DB write per operation when on)
    audit_enabled: bool = False

    # Exact-request LLM/embedding response cache (SQLite file). Empty = off.
    # Identical requests replay free; any prompt/model/param change is a miss.
    llm_cache_path: str = ""

    # Provable memory (optional): mirror memory mutations as hash-chained
    # zanii.memory receipts on a Zanii transparency ledger. Off unless both
    # ledger_url and ledger_identity_file are set (see provable.py).
    ledger_url: str = ""
    ledger_api_key: str = ""
    ledger_identity_file: str = ""

    # Gateway
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 8520
    gateway_api_key: str = ""
    cors_origins: str = ""  # comma-separated allow-list; empty = no CORS headers

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url
        if self.llm_provider == "anthropic":
            return "https://api.anthropic.com/v1"  # native-mode default
        return ""

    @property
    def llm_enabled(self) -> bool:
        # Native Anthropic mode needs only a key + model (base URL defaults).
        if self.llm_provider == "anthropic":
            return bool(self.llm_api_key and self.llm_model)
        return bool(self.llm_base_url and self.llm_model)

    @property
    def resolved_embedding_base_url(self) -> str:
        # Anthropic has no embeddings API; never fall back to the Anthropic LLM
        # base URL for embeddings — require an explicit embedding endpoint.
        if self.embedding_base_url:
            return self.embedding_base_url
        if self.llm_provider == "anthropic":
            return ""
        return self.llm_base_url

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.llm_api_key

    @property
    def embedding_enabled(self) -> bool:
        return bool(self.resolved_embedding_base_url and self.embedding_model)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def scenes_dir(self) -> Path:
        return self.data_dir / "scenes"

    @property
    def persona_path(self) -> Path:
        return self.data_dir / "persona.md"

    @property
    def skills_dir(self) -> Path:
        return self.data_dir / "skills"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "memory.db"
