"""Capa de presentación: etiquetas, formatos y resumen en lenguaje de negocio."""
import pandas as pd

from backend.app.agent.presentacion import (
    columnas_meta,
    etiqueta_columna,
    formato_valor,
    intencion_negocio,
    paso_negocio,
    periodo_legible,
    tipo_columna,
)


def test_etiquetas_sin_jerga_tecnica():
    assert etiqueta_columna("variacion_pct") == "Variación %"
    assert etiqueta_columna("ticket_promedio") == "Ticket promedio"
    assert etiqueta_columna("campania") == "Campaña"
    assert etiqueta_columna("columna_desconocida") == "Columna desconocida"


def test_tipos_de_columna():
    df = pd.DataFrame(
        {
            "periodo": pd.to_datetime(["2025-01-01"]),
            "ingreso": [100.0],
            "variacion_pct": [0.12],
            "ranking": [1],
            "cliente": ["Ana"],
        }
    )
    tipos = {c["nombre"]: c["tipo"] for c in columnas_meta(df)}
    assert tipos == {
        "periodo": "fecha", "ingreso": "moneda", "variacion_pct": "porcentaje",
        "ranking": "entero", "cliente": "texto",
    }


def test_columnas_derivadas_heredan_el_formato_de_la_metrica():
    df = pd.DataFrame({"ingreso": [10.0], "variacion": [2.0], "acumulado": [12.0]})
    tipos = {c["nombre"]: c["tipo"] for c in columnas_meta(df, tipo_base="moneda")}
    assert tipos["variacion"] == "moneda"
    assert tipos["acumulado"] == "moneda"


def test_formato_de_valores_en_espanol():
    assert "millones" in formato_valor(121_847_301.0, "moneda")
    assert formato_valor(0.834, "porcentaje").startswith("83.4")
    assert formato_valor(2.5, "ratio") == "2.50x"
    assert periodo_legible("2025-06-01") == "jun 2025"


def test_traduccion_de_intenciones_y_pasos():
    assert intencion_negocio("KPI") == "Indicador"
    assert intencion_negocio("aclaracion") == "Falta contexto"
    titulo, descripcion = paso_negocio("clasificador_edge")
    assert titulo == "Entendí tu pregunta"
    assert "nube" in descripcion


def test_tipo_columna_ignora_booleanos():
    serie = pd.Series([True, False])
    assert tipo_columna("convirtio", serie) == "booleano"
