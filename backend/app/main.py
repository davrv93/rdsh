"""Optimiza Conversacional — API y frontend."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import routes_admin, routes_canales, routes_chat, routes_meta
from .config import FRONTEND_DIR, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("optimiza")


def _materializar_al_iniciar() -> None:
    """Primera materialización Redshift → DuckDB en segundo plano.

    Si la caché ya tiene datos, solo trae lo nuevo (incremental).
    """
    from .engines.duckdb_engine import get_duckdb
    from .pipeline import sync

    try:
        vacia = not get_duckdb().tablas_en_cache()
        resultado = sync.sincronizar(incremental=not vacia)
        log.info(
            "Materialización %s: %s filas nuevas en %.0f ms",
            "inicial" if vacia else "incremental",
            sum(t.filas_nuevas for t in resultado.tablas),
            resultado.ms_total,
        )
    except Exception as exc:  # pragma: no cover - depende del entorno
        log.warning("No se pudo materializar al iniciar: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .agent.intent_classifier import get_classifier
    from .agent.orchestrator import get_orchestrator

    settings = get_settings()
    log.info("Modo de fuente: %s", settings.source_mode)
    clasificador = get_classifier()
    log.info("Clasificador edge listo: backend=%s info=%s", clasificador.backend, clasificador.info)
    orquestador = get_orchestrator()
    log.info(
        "Capa semántica: %s documentos (%s). Fuente activa: %s · ruteo: %s",
        orquestador.catalog.store.size,
        orquestador.catalog.store.backend,
        orquestador.fuente_activa,
        settings.query_routing,
    )

    if settings.use_redshift:
        estado = orquestador.redshift.ping()
        log.info("Conexión a Redshift: %s", estado)
        if settings.sync_on_start:
            threading.Thread(target=_materializar_al_iniciar, daemon=True).start()

    yield


app = FastAPI(
    title="Optimiza Conversacional",
    description="Agente IA que consulta Redshift o DuckDB en lenguaje natural.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_chat.router)
app.include_router(routes_admin.router)
app.include_router(routes_meta.router)
app.include_router(routes_canales.router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/admin", include_in_schema=False)
    def admin() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "admin.html")
