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
    # Cadena de motores de clasificación, en orden de preferencia
    intent_engines_raw: str = field(default_factory=lambda: os.getenv("INTENT_ENGINES", ""))
    intent_min_confidence: float = field(
        default_factory=lambda: _float("INTENT_MIN_CONFIDENCE", 0.35)
    )
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

    # ---------- Canal de WhatsApp (Evolution API) ----------
    whatsapp_enabled: bool = field(default_factory=lambda: _bool("WHATSAPP_ENABLED", False))
    evolution_url: str = field(default_factory=lambda: os.getenv("EVOLUTION_URL", "http://evolution-api:8080"))
    evolution_api_key: str = field(default_factory=lambda: os.getenv("EVOLUTION_API_KEY", ""))
    evolution_instance: str = field(default_factory=lambda: os.getenv("EVOLUTION_INSTANCE", "optimiza"))
    whatsapp_autorizados_raw: str = field(default_factory=lambda: os.getenv("WHATSAPP_AUTORIZADOS", ""))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", ""))

    currency_symbol: str = field(default_factory=lambda: os.getenv("CURRENCY_SYMBOL", "S/"))

    cost_input_usd_per_mtok: float = field(
        default_factory=lambda: _float("COST_INPUT_USD_PER_MTOK", 3.0)
    )
    cost_output_usd_per_mtok: float = field(
        default_factory=lambda: _float("COST_OUTPUT_USD_PER_MTOK", 15.0)
    )

    redshift: RedshiftSettings = field(default_factory=RedshiftSettings)

    @property
    def whatsapp_autorizados(self) -> list[str]:
        """Números que pueden usar el canal. Vacío significa canal cerrado."""
        return [n.strip() for n in self.whatsapp_autorizados_raw.split(",") if n.strip()]

    @property
    def intent_engines(self) -> list[str]:
        """Orden de la cadena de clasificación.

        `INTENT_ENGINES` manda. Si no está, se deriva de `EDGE_CLASSIFIER_BACKEND`
        para no romper configuraciones anteriores.
        """
        if self.intent_engines_raw.strip():
            return [m.strip() for m in self.intent_engines_raw.split(",") if m.strip()]
        configurado = self.edge_backend.lower()
        if configurado in {"rules", "reglas"}:
            return ["reglas"]
        if configurado == "transformers":
            return ["transformers", "edge", "reglas"]
        return ["edge", "reglas"]

    @property
    def intent_umbrales(self) -> dict[str, float]:
        """Umbrales por motor: INTENT_MIN_CONFIDENCE_<MOTOR>."""
        umbrales: dict[str, float] = {}
        for clave, valor in os.environ.items():
            if clave.startswith("INTENT_MIN_CONFIDENCE_"):
                motor = clave[len("INTENT_MIN_CONFIDENCE_"):].lower()
                try:
                    umbrales[motor] = float(valor)
                except ValueError:
                    continue
        return umbrales

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
