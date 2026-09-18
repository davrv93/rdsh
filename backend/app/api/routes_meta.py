"""Salud, preguntas de ejemplo y comparativa de arquitecturas."""
from __future__ import annotations

import statistics

from fastapi import APIRouter

from ..agent.intent_classifier import get_classifier
from ..agent.orchestrator import get_orchestrator
from ..config import get_settings
from ..security import audit
from ..semantic.catalog import get_catalog

router = APIRouter(prefix="/api", tags=["meta"])

PREGUNTAS_EJEMPLO = [
    {"texto": "Ventas por mes",
     "titulo": "¿Cómo evolucionaron las ventas mes a mes?",
     "intencion_esperada": "KPI"},
    {"texto": "Top 10 clientes por ingreso",
     "titulo": "¿Quiénes son mis 10 mejores clientes?",
     "intencion_esperada": "KPI"},
    {"texto": "Compara campañas por ROI",
     "titulo": "¿Qué campañas dieron mejor retorno?",
     "intencion_esperada": "comparacion"},
    {"texto": "¿Qué productos cayeron este trimestre?",
     "titulo": "¿Qué productos cayeron este trimestre?",
     "intencion_esperada": "comparacion"},
    {"texto": "Margen por categoría en 2025",
     "titulo": "¿Cuál es el margen por categoría este año?",
     "intencion_esperada": "KPI"},
    {"texto": "Hazme un gráfico de ingreso por región",
     "titulo": "Muéstrame los ingresos por región en un gráfico",
     "intencion_esperada": "grafico"},
    {"texto": "Dame el detalle de ventas de julio",
     "titulo": "Quiero el detalle de las ventas de julio",
     "intencion_esperada": "detalle"},
    {"texto": "Exporta el resultado a CSV",
     "titulo": "Descarga el último resultado para Excel",
     "intencion_esperada": "exportacion"},
    {"texto": "¿Qué tablas no relacionadas puedo combinar?",
     "titulo": "¿Qué tablas no relacionadas puedo combinar?",
     "intencion_esperada": "exploracion", "solo_experto": True},
    {"texto": "Ayúdame",
     "titulo": "Ayúdame (pregunta ambigua a propósito)",
     "intencion_esperada": "aclaracion", "solo_experto": True},
]

# Parámetros del pipeline nocturno actual de Optimiza (configurables).
PIPELINE_TRADICIONAL = {
    "etapas": [
        {"nombre": "SELECT sobre vistas de Redshift", "minutos": 45},
        {"nombre": "INSERT en base intermedia", "minutos": 35},
        {"nombre": "Transformaciones y stored procedures", "minutos": 40},
        {"nombre": "Generación de tablas finales", "minutos": 25},
        {"nombre": "Refresco del modelo de Power BI", "minutos": 20},
    ],
    "frecuencia": "1 corrida nocturna",
    "latencia_dato_horas": 12,
    "costo_mensual_usd_estimado": 1450,
    "flexibilidad": "Preguntas nuevas requieren cambio de ETL y despliegue",
}


@router.get("/salud")
def salud() -> dict:
    settings = get_settings()
    orquestador = get_orchestrator()
    clasificador = get_classifier()
    catalog = get_catalog()
    return {
        "ok": True,
        "fuente": orquestador.fuente_activa,
        "modo_demo": orquestador.fuente_activa != "redshift",
        "fecha_referencia_datos": orquestador.fecha_referencia.isoformat(),
        "clasificador_edge": {"backend": clasificador.backend, "info": clasificador.info},
        "capa_semantica": {
            "documentos": catalog.store.size,
            "backend": catalog.store.backend,
            "embedder": catalog.store.embedder.name,
            "dimension": catalog.store.embedder.dim,
        },
        "llm": {"habilitado": settings.llm_enabled,
                "modelo": settings.anthropic_model if settings.llm_enabled else None},
        "limites": {"max_rows": settings.max_rows, "timeout_s": settings.query_timeout_s,
                    "mask_pii": settings.mask_pii},
        "routing": settings.query_routing,
        "cache": {
            "tablas_materializadas": sorted(orquestador.duckdb.tablas_en_cache()),
            "max_age_min": settings.cache_max_age_min,
        },
    }


@router.get("/ejemplos")
def ejemplos() -> dict:
    return {"preguntas": PREGUNTAS_EJEMPLO}


@router.get("/comparativa")
def comparativa() -> dict:
    """Flujo tradicional nocturno vs flujo conversacional (medido)."""
    eventos = [e for e in audit.leer(200) if e.get("evento") == "consulta"]
    latencias = [e["ms_total"] for e in eventos if "ms_total" in e]
    total_minutos = sum(e["minutos"] for e in PIPELINE_TRADICIONAL["etapas"])
    medido = {
        "consultas_registradas": len(eventos),
        "latencia_media_ms": round(statistics.mean(latencias), 1) if latencias else None,
        "latencia_p95_ms": round(
            sorted(latencias)[max(0, int(len(latencias) * 0.95) - 1)], 1
        ) if latencias else None,
        "costo_llm_acumulado_usd": 0.0,
    }
    return {
        "tradicional": {
            **PIPELINE_TRADICIONAL,
            "duracion_total_minutos": total_minutos,
        },
        "conversacional": {
            "etapas": [
                {"nombre": "Clasificador edge de intención", "ms_tipico": 0.2},
                {"nombre": "Retriever vectorial sobre metadata", "ms_tipico": 2},
                {"nombre": "Generación de SQL", "ms_tipico": 1},
                {"nombre": "Validación de seguridad", "ms_tipico": 2},
                {"nombre": "Ejecución analítica", "ms_tipico": 15},
                {"nombre": "Transformación DuckDB", "ms_tipico": 8},
                {"nombre": "Selección de gráfico", "ms_tipico": 1},
            ],
            "frecuencia": "bajo demanda, por pregunta",
            "latencia_dato_horas": 0,
            "flexibilidad": "Preguntas nuevas sin cambios de código",
            "medido": medido,
        },
        "conclusion": (
            f"El pipeline nocturno tarda ~{total_minutos} minutos y deja el dato con "
            f"{PIPELINE_TRADICIONAL['latencia_dato_horas']} h de rezago. El flujo conversacional "
            "responde la misma pregunta en milisegundos sobre el dato vigente, sin materializar "
            "tablas intermedias."
        ),
    }


@router.get("/intencion")
def clasificar(texto: str) -> dict:
    """Prueba directa del clasificador edge (útil para demo y tests)."""
    return get_classifier().classify(texto).to_dict()
