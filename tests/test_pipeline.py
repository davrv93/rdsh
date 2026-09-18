"""Materialización Redshift → DuckDB y ruteo de consultas."""
from __future__ import annotations

import pandas as pd
import pytest

from backend.app.config import get_settings, reload_settings
from backend.app.pipeline import sync


def test_columna_marca_por_tabla(catalog):
    assert sync.columna_marca("ventas") == "fecha"
    assert sync.columna_marca("tickets_soporte") == "fecha"
    assert sync.columna_marca("regiones") is None


def test_estado_lista_todas_las_tablas_del_catalogo(catalog):
    estado = sync.estado()
    tablas = {t["tabla"] for t in estado["tablas"]}
    assert {"ventas", "clientes", "productos"} <= tablas
    assert estado["routing"] in {"auto", "redshift", "cache"}


def test_sincronizar_exige_redshift():
    with pytest.raises(RuntimeError, match="Redshift"):
        sync.sincronizar()


def test_materializacion_en_duckdb(duck):
    df = pd.DataFrame({"id": [1, 2, 3], "fecha": pd.to_datetime(["2025-01-01"] * 3)})
    duck.materializar_cache(df, "tabla_prueba", reemplazar=True)
    assert duck.cache_info()["tabla_prueba"]["filas"] == 3

    # Incremental: agrega sin borrar lo anterior
    duck.materializar_cache(df, "tabla_prueba", reemplazar=False)
    assert duck.cache_info()["tabla_prueba"]["filas"] == 6

    assert "tabla_prueba" in duck.exponer_cache_como_vistas()
    assert duck.execute("SELECT COUNT(*) AS n FROM tabla_prueba").dataframe.iloc[0]["n"] == 6

    duck.con.execute("DROP VIEW IF EXISTS tabla_prueba")
    duck.con.execute("DROP TABLE IF EXISTS cache.tabla_prueba")


def test_exportacion_a_parquet(duck, tmp_path):
    duck.materializar_cache(pd.DataFrame({"a": [1, 2]}), "parquet_prueba")
    destino = tmp_path / "parquet_prueba.parquet"
    duck.exportar_cache_parquet("parquet_prueba", destino)
    assert destino.exists()
    assert len(pd.read_parquet(destino)) == 2
    duck.con.execute("DROP TABLE IF EXISTS cache.parquet_prueba")


def test_ruteo_en_modo_demo():
    from backend.app.agent.orchestrator import get_orchestrator

    ruta, motivo = get_orchestrator().decidir_ruta(["ventas"])
    assert ruta == "duckdb_demo"
    assert "demo" in motivo


def test_routing_configurable(monkeypatch):
    monkeypatch.setenv("QUERY_ROUTING", "cache")
    reload_settings()
    assert get_settings().query_routing == "cache"
    monkeypatch.setenv("QUERY_ROUTING", "auto")
    reload_settings()
    assert get_settings().query_routing == "auto"
