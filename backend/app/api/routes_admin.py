"""Panel de administración: metadata, embeddings, relaciones y fuentes."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from ..agent.intent_classifier import get_classifier
from ..agent.orchestrator import get_orchestrator
from ..config import get_settings, reload_settings
from ..engines.duckdb_engine import get_duckdb
from ..engines.redshift_adapter import get_redshift
from ..security import audit
from ..semantic.catalog import get_catalog
from .schemas import (
    BusquedaSemanticaRequest,
    MetadataRequest,
    RelacionVirtualRequest,
    RoutingRequest,
    SyncRequest,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/metadata")
def obtener_metadata() -> dict:
    catalog = get_catalog()
    return {
        "metadata": catalog.metadata,
        "documentos_indexados": catalog.store.size,
        "backend_vectorial": catalog.store.backend,
    }


@router.post("/metadata")
def cargar_metadata(req: MetadataRequest) -> dict:
    catalog = get_catalog()
    try:
        total = catalog.upsert_metadata(req.metadata)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.registrar("metadata_actualizada", {"documentos": total})
    return {"ok": True, "documentos_indexados": total}


@router.post("/reindexar")
def reindexar() -> dict:
    total = get_catalog().reindex()
    return {"ok": True, "documentos_indexados": total}


@router.get("/embeddings")
def listar_embeddings(tipo: str | None = None, limite: int = 60) -> dict:
    catalog = get_catalog()
    docs = catalog.store.documentos(tipo)
    return {
        "backend": catalog.store.backend,
        "embedder": catalog.store.embedder.name,
        "dimension": catalog.store.embedder.dim,
        "total": len(docs),
        "documentos": [
            {
                "id": d.id,
                "tipo": d.tipo,
                "texto": d.texto[:180],
                "metadata": d.metadata,
                "vector_preview": catalog.store.embedding_preview(d.id),
            }
            for d in docs[:limite]
        ],
    }


@router.post("/buscar")
def buscar(req: BusquedaSemanticaRequest) -> dict:
    catalog = get_catalog()
    tipos = tuple(req.tipos) if req.tipos else None
    resultados = catalog.search(req.consulta, k=req.k, tipos=tipos)
    return {
        "consulta": req.consulta,
        "resultados": [
            {
                "id": r.documento.id,
                "tipo": r.documento.tipo,
                "texto": r.documento.texto[:200],
                "score": round(r.score, 4),
                "score_vectorial": round(r.score_vectorial, 4),
                "score_lexico": round(r.score_lexico, 4),
                "metadata": r.documento.metadata,
            }
            for r in resultados
        ],
    }


@router.get("/relaciones")
def listar_relaciones() -> dict:
    catalog = get_catalog()
    return {
        "declaradas": catalog.metadata["relations"],
        "virtuales": catalog.metadata["virtual_relations"],
        "candidatas": get_orchestrator().analizar_tablas_sin_relacion(),
    }


@router.post("/relaciones")
def crear_relacion(req: RelacionVirtualRequest) -> dict:
    try:
        rel = get_catalog().add_virtual_relation(req.left, req.right, req.tipo, req.nota)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.registrar("relacion_virtual_creada", dict(rel))
    return {"ok": True, "relacion": rel}


@router.delete("/relaciones")
def borrar_relacion(left: str, right: str) -> dict:
    ok = get_catalog().remove_virtual_relation(left, right)
    if not ok:
        raise HTTPException(404, "Relación virtual no encontrada")
    return {"ok": True}


@router.get("/fuentes")
def fuentes() -> dict:
    settings = get_settings()
    redshift = get_redshift()
    duckdb = get_duckdb()
    return {
        "modo": settings.source_mode,
        "fuente_activa": get_orchestrator().fuente_activa,
        "routing": settings.query_routing,
        "cache_max_age_min": settings.cache_max_age_min,
        "redshift": {
            "configurado": settings.redshift.configured,
            "driver_disponible": redshift.available,
            "host": settings.redshift.host or None,
            "schema": settings.redshift.schema,
            "error": redshift.error,
        },
        "duckdb": {"tablas": duckdb.tablas(), "cache": sorted(duckdb.tablas_en_cache())},
        "limites": {
            "max_rows": settings.max_rows,
            "timeout_s": settings.query_timeout_s,
            "mask_pii": settings.mask_pii,
        },
        "llm": {"habilitado": settings.llm_enabled, "modelo": settings.anthropic_model
                if settings.llm_enabled else None},
    }


@router.post("/fuentes/probar")
def probar_fuente() -> dict:
    reload_settings()
    return {"redshift": get_redshift().ping(), "duckdb": {"ok": True,
            "tablas": len(get_duckdb().tablas())}}


@router.get("/sync")
def estado_sync() -> dict:
    """Estado de la copia materializada Redshift → DuckDB."""
    from ..pipeline import sync

    return sync.estado()


@router.post("/sync")
def ejecutar_sync(req: SyncRequest) -> dict:
    """Ejecuta la materialización desde Redshift hacia DuckDB."""
    from ..pipeline import sync

    try:
        resultado = sync.sincronizar(req.tablas, req.incremental)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "resultado": resultado.to_dict(), "estado": sync.estado()}


@router.post("/routing")
def cambiar_routing(req: RoutingRequest) -> dict:
    """Cambia en caliente dónde se ejecutan las consultas."""
    os.environ["QUERY_ROUTING"] = req.routing
    reload_settings()
    audit.registrar("routing_cambiado", {"routing": req.routing})
    return {"ok": True, "routing": get_settings().query_routing}


@router.post("/metadata/introspectar")
def introspectar() -> dict:
    """Genera la metadata a partir del catálogo real de Redshift.

    Conserva descripciones, sinónimos y KPIs ya definidos para las tablas
    que sigan existiendo.
    """
    redshift = get_redshift()
    if not redshift.available:
        raise HTTPException(409, "Redshift no está configurado")
    catalog = get_catalog()
    try:
        tablas_reales = redshift.introspect()
    except Exception as exc:
        raise HTTPException(502, f"No se pudo leer el catálogo: {exc}") from exc

    previas = {t["name"]: t for t in catalog.tables}
    fusionadas = []
    for tabla in tablas_reales:
        anterior = previas.get(tabla["name"], {})
        columnas_previas = {c["name"]: c for c in anterior.get("columns", [])}
        tabla["description"] = anterior.get("description", "")
        tabla["sinonimos"] = anterior.get("sinonimos", [])
        tabla["kind"] = anterior.get("kind", "unknown")
        tabla["orphan"] = anterior.get("orphan", False)
        tabla["row_estimate"] = anterior.get("row_estimate", 0)
        for columna in tabla["columns"]:
            previa = columnas_previas.get(columna["name"], {})
            columna["description"] = previa.get("description", "")
            columna["role"] = previa.get("role", "dimension")
            if previa.get("pii"):
                columna["pii"] = True
            if previa.get("categorias"):
                columna["categorias"] = previa["categorias"]
        fusionadas.append(tabla)

    nuevo = dict(catalog.metadata)
    nuevo["tables"] = fusionadas
    total = catalog.upsert_metadata(nuevo)
    audit.registrar("metadata_introspectada", {"tablas": len(fusionadas)})
    return {"ok": True, "tablas": len(fusionadas), "documentos_indexados": total}


@router.get("/clasificador")
def estado_clasificador() -> dict:
    clasificador = get_classifier()
    return {
        "backend": clasificador.backend,
        "configurado": clasificador.configurado,
        "info": clasificador.info,
        "evaluacion": clasificador.evaluate(),
    }


@router.get("/auditoria")
def auditoria(limite: int = 50) -> dict:
    return {"eventos": audit.leer(limite)}


@router.get("/muestra/{tabla}")
def muestra(tabla: str, n: int = 5) -> dict:
    catalog = get_catalog()
    if not catalog.table(tabla):
        raise HTTPException(404, f"Tabla '{tabla}' fuera del catálogo")
    from ..agent.orchestrator import _json_safe

    df = get_duckdb().sample(tabla, n)
    orquestador = get_orchestrator()
    df, enmascaradas = orquestador._enmascarar(df)
    return {"tabla": tabla, "columnas": [str(c) for c in df.columns],
            "filas": _json_safe(df), "pii_enmascarada": enmascaradas}
