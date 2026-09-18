"""Selección automática de gráfico y generación de la especificación Vega-Lite.

Reglas (en orden):
  1. Serie temporal -> línea (o área si hay una sola serie y acumulado).
  2. Ranking / dimensión categórica con pocas categorías -> barras.
  3. Comparación de dos periodos -> barras divergentes por variación.
  4. Una sola fila y una sola medida -> tarjeta KPI, sin gráfico.
  5. Dos medidas numéricas sin dimensión temporal -> dispersión.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

TIPOS_NUMERICOS = {"int64", "int32", "float64", "float32", "Int64", "Float64"}


def _es_temporal(serie: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(serie)


def _es_numerica(serie: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(serie) and not pd.api.types.is_bool_dtype(serie)


def elegir_grafico(df: pd.DataFrame, plan_tipo: str, intent: str,
                   metrica_label: str = "") -> dict[str, Any]:
    if df.empty:
        return {"tipo": "ninguno", "motivo": "El resultado no tiene filas."}

    if plan_tipo == "detalle" and intent != "grafico":
        return {"tipo": "tabla", "motivo": "Resultado a nivel de detalle: se muestra como tabla."}

    columnas = list(df.columns)
    temporales = [c for c in columnas if _es_temporal(df[c])]
    numericas = [c for c in columnas if _es_numerica(df[c])]
    categoricas = [c for c in columnas if c not in temporales and c not in numericas]

    if len(df) == 1 and len(numericas) >= 1 and not categoricas:
        return {
            "tipo": "kpi",
            "motivo": "Una sola fila con medidas: se muestra como tarjeta KPI.",
            "campos": {"medidas": numericas},
        }

    if plan_tipo == "comparacion" and "variacion_pct" in columnas and categoricas:
        dim = categoricas[0]
        return _spec_barras(df, dim, "variacion_pct", titulo=f"Variación de {metrica_label}",
                            divergente=True, horizontal=True)

    if temporales and numericas:
        tiempo = temporales[0]
        medida = next((c for c in numericas if c == metrica_label), numericas[0])
        serie = categoricas[0] if categoricas else None
        return _spec_linea(df, tiempo, medida, serie)

    if categoricas and numericas:
        dim = categoricas[0]
        medida = next((c for c in numericas if c == metrica_label), numericas[0])
        horizontal = df[dim].astype(str).str.len().max() > 12 or len(df) > 8
        if len(df) <= 6 and intent != "comparacion" and medida.endswith("pct") is False and len(df) > 1 and df[medida].min() >= 0 and len(categoricas) == 1 and len(numericas) <= 3 and len(df) <= 5:
            return _spec_dona(df, dim, medida)
        return _spec_barras(df, dim, medida, titulo=f"{medida} por {dim}", horizontal=horizontal)

    if len(numericas) >= 2:
        return _spec_dispersion(df, numericas[0], numericas[1], categoricas[0] if categoricas else None)

    return {"tipo": "tabla", "motivo": "El resultado se entiende mejor como tabla."}


def _spec_linea(df: pd.DataFrame, tiempo: str, medida: str, serie: str | None) -> dict[str, Any]:
    encoding: dict[str, Any] = {
        "x": {"field": tiempo, "type": "temporal", "title": tiempo},
        "y": {"field": medida, "type": "quantitative", "title": medida},
        "tooltip": [
            {"field": tiempo, "type": "temporal"},
            {"field": medida, "type": "quantitative", "format": ",.2f"},
        ],
    }
    if serie:
        encoding["color"] = {"field": serie, "type": "nominal", "title": serie}
        encoding["tooltip"].append({"field": serie, "type": "nominal"})
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"Evolución de {medida}",
        "mark": {"type": "line", "point": True, "interpolate": "monotone"},
        "encoding": encoding,
    }
    return {
        "tipo": "linea",
        "motivo": "Hay una dimensión temporal: la serie muestra la evolución.",
        "spec": spec,
        "campos": {"x": tiempo, "y": medida, "serie": serie},
    }


def _spec_barras(df: pd.DataFrame, dimension: str, medida: str, titulo: str = "",
                 divergente: bool = False, horizontal: bool = True) -> dict[str, Any]:
    eje_cat = {"field": dimension, "type": "nominal", "sort": "-x" if horizontal else "-y",
               "title": dimension}
    eje_num = {"field": medida, "type": "quantitative", "title": medida}
    encoding = ({"y": eje_cat, "x": eje_num} if horizontal else {"x": eje_cat, "y": eje_num})
    if divergente:
        encoding["color"] = {
            "field": medida,
            "type": "quantitative",
            "scale": {"range": ["#b42318", "#f3c9c4", "#0f8a5f"], "domainMid": 0},
            "legend": None,
        }
    encoding["tooltip"] = [
        {"field": dimension, "type": "nominal"},
        {"field": medida, "type": "quantitative", "format": ",.2f"},
    ]
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": titulo or f"{medida} por {dimension}",
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": encoding,
    }
    return {
        "tipo": "barras",
        "motivo": "Dimensión categórica con una medida: barras ordenadas.",
        "spec": spec,
        "campos": {"dimension": dimension, "medida": medida, "horizontal": horizontal},
    }


def _spec_dona(df: pd.DataFrame, dimension: str, medida: str) -> dict[str, Any]:
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"Participación de {medida} por {dimension}",
        "mark": {"type": "arc", "innerRadius": 60},
        "encoding": {
            "theta": {"field": medida, "type": "quantitative"},
            "color": {"field": dimension, "type": "nominal"},
            "tooltip": [
                {"field": dimension, "type": "nominal"},
                {"field": medida, "type": "quantitative", "format": ",.2f"},
            ],
        },
    }
    return {
        "tipo": "dona",
        "motivo": "Pocas categorías que suman un total: participación.",
        "spec": spec,
        "campos": {"dimension": dimension, "medida": medida},
    }


def _spec_dispersion(df: pd.DataFrame, x: str, y: str, color: str | None) -> dict[str, Any]:
    encoding: dict[str, Any] = {
        "x": {"field": x, "type": "quantitative"},
        "y": {"field": y, "type": "quantitative"},
        "tooltip": [{"field": x, "type": "quantitative"}, {"field": y, "type": "quantitative"}],
    }
    if color:
        encoding["color"] = {"field": color, "type": "nominal"}
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "description": f"{y} vs {x}",
        "mark": {"type": "point", "filled": True, "size": 90},
        "encoding": encoding,
    }
    return {
        "tipo": "dispersion",
        "motivo": "Dos medidas numéricas: se grafica su relación.",
        "spec": spec,
        "campos": {"x": x, "y": y, "color": color},
    }


def tarjetas_kpi(df: pd.DataFrame, metrica_label: str, formato: str) -> list[dict[str, Any]]:
    """Tarjetas de cabecera, ya con etiquetas y formatos de negocio."""
    from .presentacion import etiqueta_columna, periodo_legible, tipo_columna

    if df.empty:
        return []
    numericas = [c for c in df.columns if _es_numerica(df[c])]
    if metrica_label in numericas:
        principal = metrica_label
    elif numericas:
        principal = numericas[0]
    else:
        return [{"label": "Registros", "valor": len(df), "formato": "entero"}]

    tipo = tipo_columna(principal, df[principal])
    nombre = etiqueta_columna(principal)
    promedia = tipo in {"porcentaje", "ratio"} or principal in {"ticket_promedio", "csat", "csat_promedio"}

    tarjetas: list[dict[str, Any]] = []
    if promedia:
        tarjetas.append({"label": f"{nombre} promedio", "valor": float(df[principal].mean()),
                         "formato": tipo})
    else:
        tarjetas.append({"label": f"{nombre} total", "valor": float(df[principal].sum()),
                         "formato": tipo})
    tarjetas.append({"label": "Registros", "valor": int(len(df)), "formato": "entero"})

    if len(df) > 1:
        categoricas = [c for c in df.columns if not _es_numerica(df[c])]
        temporales = [c for c in df.columns if _es_temporal(df[c])]
        idx = df[principal].idxmax()
        # "Mayor caída" solo en comparaciones entre periodos, no en series temporales
        if "variacion_pct" in df.columns and categoricas and not temporales:
            peor = df.loc[df["variacion_pct"].idxmin()]
            tarjetas.append({"label": "Mayor caída", "valor": str(peor[categoricas[0]]),
                             "detalle": float(peor["variacion_pct"]),
                             "formato": "texto", "formato_detalle": "porcentaje"})
            tarjetas.append({"label": f"{nombre} promedio", "valor": float(df[principal].mean()),
                             "formato": tipo})
            return tarjetas[:4]
        if temporales:
            tarjetas.append({"label": f"Mejor {etiqueta_columna(temporales[0]).lower()}",
                             "valor": periodo_legible(df.loc[idx, temporales[0]]),
                             "detalle": float(df.loc[idx, principal]),
                             "formato": "texto", "formato_detalle": tipo})
        elif categoricas:
            tarjetas.append({"label": f"Mayor {etiqueta_columna(categoricas[0]).lower()}",
                             "valor": str(df.loc[idx, categoricas[0]]),
                             "detalle": float(df.loc[idx, principal]),
                             "formato": "texto", "formato_detalle": tipo})
        if not promedia:
            tarjetas.append({"label": f"{nombre} promedio", "valor": float(df[principal].mean()),
                             "formato": tipo})
    return tarjetas[:4]
