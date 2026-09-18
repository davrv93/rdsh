"""Configuración central de Optimiza Conversacional.

Toda la configuración se lee de variables de entorno (ver .env.example).
Nunca se hardcodean credenciales.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:  # pragma: no cover - dotenv es opcional en runtime docker
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
DATA_DIR = Path(os.getenv("OPTIMIZA_DATA_DIR", BASE_DIR / "data"))
SEED_DIR = DATA_DIR / "parquet"
FRONTEND_DIR = Path(os.getenv("OPTIMIZA_FRONTEND_DIR", PROJECT_ROOT / "frontend" / "static"))


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "si", "sí", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class RedshiftSettings:
    host: str = field(default_factory=lambda: os.getenv("REDSHIFT_HOST", ""))
    port: int = field(default_factory=lambda: _int("REDSHIFT_PORT", 5439))
    database: str = field(default_factory=lambda: os.getenv("REDSHIFT_DB", "analytics"))
    user: str = field(default_factory=lambda: os.getenv("REDSHIFT_USER", ""))
    password: str = field(default_factory=lambda: os.getenv("REDSHIFT_PASSWORD", ""))
    schema: str = field(default_factory=lambda: os.getenv("REDSHIFT_SCHEMA", "public"))
    statement_timeout_ms: int = field(
        default_factory=lambda: _int("REDSHIFT_STATEMENT_TIMEOUT_MS", 15000)
    )

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)


@dataclass
class Settings:
    source_mode: str = field(default_factory=lambda: os.getenv("OPTIMIZA_SOURCE_MODE", "demo"))
    max_rows: int = field(default_factory=lambda: _int("MAX_ROWS", 5000))
    query_timeout_s: int = field(default_factory=lambda: _int("QUERY_TIMEOUT_S", 15))
    mask_pii: bool = field(default_factory=lambda: _bool("MASK_PII", True))

    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "none"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"))
    llm_max_tokens: int = field(default_factory=lambda: _int("LLM_MAX_TOKENS", 1200))

    edge_backend: str = field(default_factory=lambda: os.getenv("EDGE_CLASSIFIER_BACKEND", "edge"))
    edge_model_name: str = field(
        default_factory=lambda: os.getenv("EDGE_MODEL_NAME", "luigicfilho/intento-v1-edge")
    )

    embedding_backend: str = field(default_factory=lambda: os.getenv("EMBEDDING_BACKEND", "hashing"))
    embedding_dim: int = field(default_factory=lambda: _int("EMBEDDING_DIM", 512))
    st_model_name: str = field(
        default_factory=lambda: os.getenv(
            "ST_MODEL_NAME", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )

    vector_backend: str = field(default_factory=lambda: os.getenv("VECTOR_BACKEND", "memory"))
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))

    # Ruteo de consultas: auto | redshift | cache
    query_routing: str = field(default_factory=lambda: os.getenv("QUERY_ROUTING", "auto"))
    cache_max_age_min: int = field(default_factory=lambda: _int("CACHE_MAX_AGE_MIN", 720))
    # Materializa Redshift -> DuckDB al arrancar si la caché está vacía
    sync_on_start: bool = field(default_factory=lambda: _bool("SYNC_ON_START", True))

    currency_symbol: str = field(default_factory=lambda: os.getenv("CURRENCY_SYMBOL", "S/"))

    cost_input_usd_per_mtok: float = field(
        default_factory=lambda: _float("COST_INPUT_USD_PER_MTOK", 3.0)
    )
    cost_output_usd_per_mtok: float = field(
        default_factory=lambda: _float("COST_OUTPUT_USD_PER_MTOK", 15.0)
    )

    redshift: RedshiftSettings = field(default_factory=RedshiftSettings)

    @property
    def use_redshift(self) -> bool:
        """Solo usa Redshift si se pidió explícitamente y hay credenciales."""
        return self.source_mode.lower() == "redshift" and self.redshift.configured

    @property
    def active_source(self) -> str:
        return "redshift" if self.use_redshift else "duckdb_demo"

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider.lower() == "anthropic" and bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
