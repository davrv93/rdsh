"""Capa de presentación para usuarios de negocio.

Traduce el resultado técnico (columnas, plan, métricas) a etiquetas, formatos y
frases en lenguaje de negocio. El detalle técnico se conserva aparte para el
equipo de datos.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ..config import get_settings

MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

ETIQUETAS = {
    "periodo": "Periodo",
    "anio_mes": "Periodo",
    "fecha": "Fecha",
    "ingreso": "Ingreso",
    "ingreso_actual": "Ingreso actual",
    "ingreso_anterior": "Ingreso anterior",
    "margen": "Margen",
    "margen_actual": "Margen actual",
    "margen_anterior": "Margen anterior",
    "margen_pct": "Margen %",
    "costo": "Costo",
    "inversion": "Inversión",
    "unidades": "Unidades",
    "unidades_actual": "Unidades actuales",
    "unidades_anterior": "Unidades anteriores",
    "ticket_promedio": "Ticket promedio",
    "clientes_activos": "Clientes activos",
    "csat_promedio": "Satisfacción (CSAT)",
    "tasa_conversion": "Tasa de conversión",
    "roi": "ROI",
    "roi_pct": "ROI %",
    "roi_promedio": "ROI promedio",
    "brecha_vs_promedio": "Diferencia vs promedio",
    "variacion": "Variación",
    "variacion_pct": "Variación %",
    "variacion_periodo": "Variación vs periodo anterior",
    "acumulado": "Acumulado",
    "media_movil_3": "Promedio de 3 periodos",
    "participacion": "Participación",
    "participacion_periodo": "Participación del periodo",
    "participacion_acumulada": "Participación acumulada",
    "ranking": "Posición",
    "ranking_caida": "Posición por caída",
    "tendencia": "Tendencia",
    "ventas_contadas": "N.º de ventas",
    "ventas_atribuidas": "Ventas atribuidas",
    "cliente": "Cliente",
    "producto": "Producto",
    "categoria": "Categoría",
    "subcategoria": "Subcategoría",
    "campania": "Campaña",
    "region": "Región",
    "pais": "País",
    "canal": "Canal",
    "canal_contacto": "Canal de contacto",
    "segmento": "Segmento",
    "motivo": "Motivo",
    "dispositivo": "Dispositivo",
    "estado": "Estado",
    "nombre": "Nombre",
    "csat": "Satisfacción",
    "tiempo_resolucion_h": "Horas de resolución",
    "duracion_s": "Duración (s)",
    "paginas_vistas": "Páginas vistas",
    "convirtio": "Convirtió",
    "precio_unitario": "Precio unitario",
    "costo_unitario": "Costo unitario",
    "precio_lista": "Precio de lista",
    "descuento": "Descuento",
    "venta_id": "N.º de venta",
    "ticket_id": "N.º de ticket",
    "session_id": "N.º de sesión",
}

MONEDA = re.compile(r"(ingreso|margen(?!_pct)|costo|inversion|ticket_promedio|precio|venta_total|facturacion)", re.I)
PORCENTAJE = re.compile(r"(_pct$|^participacion|conversion|descuento|margen_pct|tasa)", re.I)
ENTERO = re.compile(r"(^ranking|_id$|^unidades|ventas_contadas|ventas_atribuidas|clientes_activos|paginas|filas|posicion)", re.I)

# Nombre técnico de la intención -> nombre para el usuario final
INTENCIONES_NEGOCIO = {
    "KPI": "Indicador",
    "exploracion": "Exploración de datos",
    "comparacion": "Comparación",
    "detalle": "Detalle",
    "grafico": "Gráfico",
    "exportacion": "Descarga",
    "aclaracion": "Falta contexto",
}

# Paso técnico -> qué contarle al usuario de negocio
PASOS_NEGOCIO = {
    "clasificador_edge": ("Entendí tu pregunta", "Reconocí qué tipo de respuesta necesitas, en tu propio equipo, sin enviar nada a la nube."),
    "retriever_vectorial": ("Busqué en el catálogo", "Encontré las tablas, columnas e indicadores que corresponden a tu pregunta."),
    "generacion_sql": ("Armé la consulta", "Traduje la pregunta a una consulta sobre la base de datos."),
    "generacion_sql_llm": ("Armé la consulta con IA", "Un modelo de lenguaje escribió la consulta a partir del catálogo."),
    "guardia_join": ("Revisé si las tablas se pueden cruzar", "Comprobé si existe una relación confiable entre las tablas involucradas."),
    "validacion_sql": ("Revisé que fuera segura", "Verifiqué que solo se lea información y que no se consulte de más."),
    "ejecucion_duckdb": ("Consulté los datos", "Obtuve la información desde la base de datos."),
    "ejecucion_redshift": ("Consulté el almacén", "Obtuve la información directamente de Redshift, en modo solo lectura."),
    "ejecucion_cache": ("Consulté la copia local", "Usé la copia de los datos que ya se había traído del almacén, sin volver a molestarlo."),
    "sincronizacion": ("Actualicé la copia local", "Traje del almacén las filas nuevas y las dejé listas para consultas rápidas."),
    "transformacion_duckdb": ("Calculé totales y variaciones", "Agregué acumulados, participaciones y comparaciones contra el periodo anterior."),
    "enmascaramiento_pii": ("Protegí los datos personales", "Oculté correos, documentos y nombres completos."),
    "visualizacion": ("Elegí el gráfico", "Seleccioné la visualización que mejor representa el resultado."),
    "analisis_relaciones": ("Analicé las relaciones entre tablas", "Medí cuántos valores coinciden entre las tablas antes de proponer un cruce."),
    "preparacion_csv": ("Preparé el archivo", "Dejé el resultado listo para descargar en Excel."),
}


def etiqueta_columna(nombre: str) -> str:
    clave = str(nombre).lower()
    if clave in ETIQUETAS:
        return ETIQUETAS[clave]
    return str(nombre).replace("_", " ").capitalize()


def tipo_columna(nombre: str, serie: pd.Series) -> str:
    clave = str(nombre).lower()
    if pd.api.types.is_datetime64_any_dtype(serie):
        return "fecha"
    if pd.api.types.is_bool_dtype(serie):
        return "booleano"
    if not pd.api.types.is_numeric_dtype(serie):
        return "texto"
    if PORCENTAJE.search(clave):
        return "porcentaje"
    if clave in {"roi", "roi_promedio"}:
        return "ratio"
    if MONEDA.search(clave):
        return "moneda"
    if ENTERO.search(clave):
        return "entero"
    return "decimal"


DERIVADAS = re.compile(r"^(variacion(?!_pct)|acumulado|media_movil|brecha)", re.I)


def columnas_meta(df: pd.DataFrame, tipo_base: str | None = None) -> list[dict[str, str]]:
    """Etiqueta y tipo de cada columna. `tipo_base` es el tipo de la métrica
    principal: las columnas derivadas (variación, acumulado, media móvil) heredan
    su formato, para que una diferencia de ingresos también se vea como dinero."""
    salida = []
    for c in df.columns:
        tipo = tipo_columna(c, df[c])
        if tipo_base and tipo == "decimal" and DERIVADAS.search(str(c)):
            tipo = tipo_base
        salida.append({"nombre": str(c), "etiqueta": etiqueta_columna(c), "tipo": tipo})
    return salida


def formato_valor(valor: Any, tipo: str) -> str:
    """Formato legible en español para textos generados en el servidor."""
    simbolo = get_settings().currency_symbol
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "sin dato"
    if tipo == "moneda":
        return f"{simbolo} {_magnitud(float(valor))}"
    if tipo == "porcentaje":
        return f"{float(valor) * 100:,.1f} %".replace(",", " ")
    if tipo == "ratio":
        return f"{float(valor):,.2f}x"
    if tipo == "entero":
        return f"{int(valor):,}".replace(",", " ")
    if tipo == "fecha":
        return periodo_legible(valor)
    if isinstance(valor, float):
        return f"{valor:,.2f}".replace(",", " ")
    return str(valor)


def _magnitud(valor: float) -> str:
    absoluto = abs(valor)
    if absoluto >= 1_000_000_000:
        return f"{valor / 1_000_000_000:,.1f} mil millones".replace(",", " ")
    if absoluto >= 1_000_000:
        return f"{valor / 1_000_000:,.1f} millones".replace(",", " ")
    if absoluto >= 10_000:
        return f"{valor:,.0f}".replace(",", " ")
    return f"{valor:,.2f}".replace(",", " ")


def periodo_legible(valor: Any) -> str:
    try:
        fecha = pd.Timestamp(valor)
    except Exception:
        return str(valor)
    if pd.isna(fecha):
        return "sin fecha"
    return f"{MESES_ES[fecha.month - 1]} {fecha.year}"


def intencion_negocio(intent: str) -> str:
    return INTENCIONES_NEGOCIO.get(intent, intent)


def paso_negocio(nombre: str) -> tuple[str, str]:
    return PASOS_NEGOCIO.get(nombre, (nombre.replace("_", " ").capitalize(), ""))


def resumen_ejecutivo(plan, df: pd.DataFrame, visual: dict[str, Any] | None) -> list[str]:
    """Dos o tres frases de negocio, sin SQL ni nombres de columnas técnicos."""
    if df.empty:
        return ["La consulta no devolvió resultados para ese periodo o esos filtros."]

    meta = {c["nombre"]: c for c in columnas_meta(df)}
    numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
                 and meta[str(c)]["tipo"] in {"moneda", "decimal", "entero", "porcentaje", "ratio"}]
    principal = plan.metrica_label if plan.metrica_label in numericas else (
        numericas[0] if numericas else None
    )
    if principal is None:
        return [f"Encontré {len(df)} registros que responden a tu pregunta."]

    tipo = meta[str(principal)]["tipo"]
    etiqueta = meta[str(principal)]["etiqueta"]
    frases: list[str] = []

    if plan.tipo_resultado == "serie":
        total = df[principal].sum()
        idx_max = df[principal].idxmax()
        etiqueta_max = periodo_legible(df.loc[idx_max, "periodo"]) if "periodo" in df.columns else ""
        frases.append(f"{etiqueta} total del periodo: **{formato_valor(total, tipo)}**.")
        if etiqueta_max:
            frases.append(
                f"El mejor mes fue **{etiqueta_max}** con {formato_valor(df.loc[idx_max, principal], tipo)}."
            )
        if "variacion_pct" in df.columns and len(df) > 1:
            ultima = df["variacion_pct"].dropna()
            if len(ultima):
                cambio = float(ultima.iloc[-1])
                direccion = "subió" if cambio >= 0 else "bajó"
                frases.append(f"El último periodo {direccion} {abs(cambio) * 100:.1f} % frente al anterior.")
    elif plan.tipo_resultado == "ranking":
        categoricas = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        promedia = tipo in {"ratio", "porcentaje"}
        total = df[principal].sum()
        if categoricas:
            top = df.iloc[0]
            participacion = (
                f", el {top[principal] / total:.1%} del total mostrado."
                if total and not promedia else "."
            )
            frases.append(
                f"Lidera **{top[categoricas[0]]}** con {formato_valor(top[principal], tipo)}{participacion}"
            )
            if not promedia and "participacion_acumulada" in df.columns and len(df) >= 3:
                acumulado_3 = float(df["participacion_acumulada"].iloc[min(2, len(df) - 1)])
                frases.append(f"Los tres primeros concentran el {acumulado_3:.1%} del total.")
        if promedia:
            frases.insert(
                0, f"{etiqueta} promedio de los {len(df)} mostrados: "
                   f"**{formato_valor(df[principal].mean(), tipo)}**."
            )
        else:
            frases.insert(
                0, f"{etiqueta} total de los {len(df)} primeros: **{formato_valor(total, tipo)}**."
            )
    elif plan.tipo_resultado == "comparacion" and "variacion_pct" in df.columns:
        caidas = df[df["variacion_pct"] < 0]
        categoricas = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        frases.append(f"**{len(caidas)} de {len(df)}** cayeron frente al periodo anterior.")
        if len(caidas) and categoricas:
            peor = caidas.iloc[0]
            frases.append(
                f"La mayor caída es **{peor[categoricas[0]]}**, con {abs(float(peor['variacion_pct'])) * 100:.1f} % menos."
            )
    elif plan.tipo_resultado == "detalle":
        frases.append(f"Te muestro **{len(df)} registros** con su detalle.")
    else:
        frases.append(f"{etiqueta}: **{formato_valor(df[principal].iloc[0], tipo)}**.")

    return frases


def titulo_resultado(plan) -> str:
    """Título corto del panel de resultados, en lenguaje de negocio."""
    if plan is None:
        return "Resultado"
    etiqueta = etiqueta_columna(plan.metrica_label)
    if plan.dimension:
        return f"{etiqueta} por {etiqueta_columna(plan.dimension[2]).lower()}"
    if plan.grano:
        return f"{etiqueta} por {plan.grano.replace('anio', 'año')}"
    return etiqueta
