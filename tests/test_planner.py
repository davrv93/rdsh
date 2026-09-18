"""Planificador determinista: intención, métricas, periodos y ausencia de joins inventados."""
from datetime import date

import pytest

from backend.app.agent.planner import Planner


@pytest.fixture(scope="module")
def planner(catalog):
    return Planner(catalog, date(2025, 9, 30))


def _plan(planner, catalog, pregunta, intent):
    return planner.build(pregunta, intent, catalog.search(pregunta, k=8))


def test_serie_mensual(planner, catalog):
    plan = _plan(planner, catalog, "ventas por mes", "KPI")
    assert plan.grano == "mes"
    assert plan.tipo_resultado == "serie"
    assert "date_trunc('month'" in plan.sql


def test_ranking_con_limite(planner, catalog):
    plan = _plan(planner, catalog, "top 10 clientes por ingreso", "KPI")
    assert plan.limite == 10
    assert plan.dimension[0] == "clientes"
    assert "LIMIT 10" in plan.sql


def test_roi_usa_cte_y_left_join(planner, catalog):
    plan = _plan(planner, catalog, "compara campañas por roi", "comparacion")
    assert plan.metrica == "roi_campania"
    assert "WITH" in plan.sql and "LEFT JOIN" in plan.sql
    assert "inversion" in plan.sql


def test_filtro_de_anio(planner, catalog):
    plan = _plan(planner, catalog, "margen por categoría en 2024", "KPI")
    assert any("2024" in f.expresion for f in plan.filtros)


def test_no_cruza_tablas_huerfanas(planner, catalog):
    plan = _plan(planner, catalog, "ingreso por motivo de ticket", "KPI")
    assert "tickets_soporte" not in plan.sql or "ventas" not in plan.sql


def test_transformacion_siempre_definida(planner, catalog):
    for pregunta, intent in [("ventas por mes", "KPI"), ("top 5 productos por margen", "KPI")]:
        plan = _plan(planner, catalog, pregunta, intent)
        assert plan.transform_sql
        assert "_resultado" in plan.transform_sql


def test_typos_resuelven_metrica_por_similitud(planner, catalog):
    plan = _plan(planner, catalog, "hola puedes decirme el meargen de categorias?", "KPI")
    assert plan.metrica == "margen_total"
    assert plan.dimension[1] == "categoria"


def test_mejores_clientes_usa_ingreso_no_conteo(planner, catalog):
    for pregunta in ["quienes son mis 10 mejores clientes", "top clientes", "mejores productos"]:
        plan = _plan(planner, catalog, pregunta, "KPI")
        assert plan.metrica == "ingreso_total", pregunta


@pytest.mark.parametrize(
    "pregunta,dimension_esperada",
    [
        ("e el ingreso por regino", "region"),
        ("haz un grafico del ingreso por regin", "region"),
        ("ingreso por categoia", "categoria"),
        ("ventas por clietnes", "cliente"),
        ("margen por prodcuto", "producto"),
    ],
)
def test_typos_en_la_dimension_no_pierden_el_agrupamiento(planner, catalog, pregunta,
                                                          dimension_esperada):
    """Regresión: «por regino» devolvía el total en vez del desglose por región."""
    plan = _plan(planner, catalog, pregunta, "KPI")
    assert plan.dimension is not None, pregunta
    assert plan.dimension[2] == dimension_esperada


def test_grafico_sin_dimension_usa_la_serie_mensual(planner, catalog):
    plan = _plan(planner, catalog, "hazme un grafico de ingresos", "grafico")
    assert plan.grano == "mes"
    assert plan.tipo_resultado == "serie"


def test_pedir_tabla_desactiva_el_grafico(planner, catalog):
    plan = _plan(planner, catalog, "tabla de ingreso por region", "KPI")
    assert plan.solo_tabla is True
    assert _plan(planner, catalog, "ingreso por region", "KPI").solo_tabla is False
