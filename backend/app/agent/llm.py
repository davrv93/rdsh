"""Cliente LLM opcional (Anthropic Messages API).

Reglas de privacidad:
  - Al LLM solo se envían metadatos: nombres de tablas, columnas, descripciones,
    KPIs, relaciones y valores categóricos NO sensibles.
  - Nunca se envían filas de datos ni columnas marcadas como PII.
Si no hay API key, el orquestador usa el planificador determinista.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings

SYSTEM_PROMPT = """Eres el generador SQL de Optimiza Conversacional.
Devuelves SIEMPRE un único objeto JSON con esta forma exacta:
{"sql": "<una sola consulta SELECT o WITH>", "explicacion": "<2 frases en español>", "grafico_sugerido": "linea|barras|dona|dispersion|tabla|kpi"}

Reglas obligatorias:
- Solo SELECT o WITH. Prohibido INSERT, UPDATE, DELETE, DDL o SET.
- Usa exclusivamente las tablas y columnas del catálogo entregado.
- No inventes relaciones: usa solo las relaciones declaradas. Si la pregunta
  necesita una relación inexistente, responde con SQL sobre una sola tabla y
  explícalo.
- Dialecto compatible con Redshift y DuckDB: usa date_trunc, CAST, CTEs y
  window functions estándar. No uses funciones propietarias.
- Incluye siempre un LIMIT razonable.
- Nunca proyectes columnas marcadas como PII."""


@dataclass
class LLMResult:
    ok: bool
    sql: str = ""
    explicacion: str = ""
    grafico_sugerido: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    modelo: str = ""
    error: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def construir_contexto(catalog, resultados) -> str:
    """Serializa SOLO metadatos relevantes (sin datos de filas)."""
    pii = catalog.pii_columns()
    tablas_relevantes = {r.documento.metadata.get("tabla") for r in resultados}
    tablas_relevantes.discard(None)
    lineas: list[str] = []
    for tabla in catalog.tables:
        if tablas_relevantes and tabla["name"] not in tablas_relevantes:
            continue
        lineas.append(f"TABLA {tabla['name']}: {tabla['description']}")
        for col in tabla["columns"]:
            ref = f"{tabla['name']}.{col['name']}"
            marca = " [PII - NO PROYECTAR]" if ref in pii else ""
            cats = col.get("categorias")
            valores = f" valores: {', '.join(map(str, cats))}" if cats else ""
            lineas.append(f"  - {col['name']} {col['type']}: {col['description']}{valores}{marca}")
    lineas.append("RELACIONES DECLARADAS:")
    for rel in catalog.relations:
        virtual = " (virtual, declarada por admin)" if rel.get("virtual") else ""
        lineas.append(f"  - {rel['left']} = {rel['right']} [{rel['type']}]{virtual}")
    lineas.append("KPIs:")
    for kpi in catalog.kpis:
        lineas.append(f"  - {kpi['name']}: {kpi['expression']} ({kpi['description']})")
    return "\n".join(lineas)


def _extraer_json(texto: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", texto, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def generar_sql(pregunta: str, intent: str, contexto: str,
                historial: list[dict[str, str]] | None = None) -> LLMResult:
    settings = get_settings()
    if not settings.llm_enabled:
        return LLMResult(ok=False, error="LLM deshabilitado (LLM_PROVIDER=none)")

    import httpx

    mensajes: list[dict[str, Any]] = []
    for turno in (historial or [])[-4:]:
        mensajes.append({"role": turno["role"], "content": turno["content"]})
    mensajes.append(
        {
            "role": "user",
            "content": (
                f"Intención detectada por el clasificador edge: {intent}\n\n"
                f"CATÁLOGO DISPONIBLE:\n{contexto}\n\n"
                f"PREGUNTA DEL USUARIO: {pregunta}\n\n"
                "Responde solo con el JSON pedido."
            ),
        }
    )

    t0 = time.perf_counter()
    try:
        respuesta = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": settings.llm_max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": mensajes,
            },
            timeout=45.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        if respuesta.status_code >= 400:
            return LLMResult(ok=False, error=f"HTTP {respuesta.status_code}: {respuesta.text[:200]}",
                             latency_ms=latency_ms)
        cuerpo = respuesta.json()
        texto = "".join(bloque.get("text", "") for bloque in cuerpo.get("content", []))
        datos = _extraer_json(texto)
        if not datos or not datos.get("sql"):
            return LLMResult(ok=False, error="El LLM no devolvió un JSON con SQL",
                             latency_ms=latency_ms)
        uso = cuerpo.get("usage", {})
        return LLMResult(
            ok=True,
            sql=datos["sql"].strip(),
            explicacion=datos.get("explicacion", ""),
            grafico_sugerido=datos.get("grafico_sugerido", ""),
            latency_ms=latency_ms,
            input_tokens=int(uso.get("input_tokens", 0)),
            output_tokens=int(uso.get("output_tokens", 0)),
            modelo=settings.anthropic_model,
            payload=datos,
        )
    except Exception as exc:
        return LLMResult(ok=False, error=str(exc)[:300],
                         latency_ms=(time.perf_counter() - t0) * 1000)


def estimar_costo(input_tokens: int, output_tokens: int) -> float:
    settings = get_settings()
    return round(
        input_tokens / 1_000_000 * settings.cost_input_usd_per_mtok
        + output_tokens / 1_000_000 * settings.cost_output_usd_per_mtok,
        6,
    )
