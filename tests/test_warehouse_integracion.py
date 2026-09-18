"""Integración real contra el almacén (docker compose).

Se salta automáticamente si el almacén no está levantado, para que la suite
siga corriendo en cualquier máquina:

    docker compose up -d warehouse warehouse-loader
    OPTIMIZA_SOURCE_MODE=redshift REDSHIFT_HOST=localhost REDSHIFT_PORT=5439 \
      .venv/bin/python -m pytest tests/test_warehouse_integracion.py -v
"""
from __future__ import annotations

import os

import pytest

from backend.app.config import get_settings

pytestmark = pytest.mark.integracion


def _almacen_disponible() -> bool:
    if os.getenv("OPTIMIZA_SOURCE_MODE", "demo") != "redshift":
        return False
    from backend.app.engines.redshift_adapter import get_redshift

    return get_redshift().ping().get("ok", False)


requiere_almacen = pytest.mark.skipif(
    not _almacen_disponible(), reason="El almacén no está disponible en este entorno"
)


@requiere_almacen
def test_conexion_de_solo_lectura():
    from backend.app.engines.redshift_adapter import get_redshift

    estado = get_redshift().ping()
    assert estado["ok"] is True
    assert estado["usuario"] == get_settings().redshift.user


@requiere_almacen
def test_escritura_rechazada_por_el_almacen():
    import psycopg2

    from backend.app.engines.redshift_adapter import get_redshift

    adaptador = get_redshift()
    with pytest.raises(psycopg2.Error):
        adaptador.execute("DELETE FROM ventas WHERE venta_id = 1")


@requiere_almacen
def test_consulta_real_y_materializacion():
    from backend.app.engines.duckdb_engine import get_duckdb
    from backend.app.engines.redshift_adapter import get_redshift
    from backend.app.pipeline import sync

    filas = get_redshift().execute("SELECT COUNT(*) AS n FROM ventas").dataframe
    assert int(filas.iloc[0]["n"]) > 1000

    resultado = sync.sincronizar(tablas=["regiones"], incremental=False)
    assert resultado.tablas[0].ok
    assert get_duckdb().cache_info()["regiones"]["filas"] == 7


@requiere_almacen
def test_ruteo_usa_la_copia_local_cuando_esta_fresca():
    from backend.app.agent.orchestrator import get_orchestrator
    from backend.app.pipeline import sync

    sync.sincronizar(tablas=["ventas"], incremental=False)
    ruta, motivo = get_orchestrator().decidir_ruta(["ventas"])
    assert ruta == "duckdb_cache"
    assert "vigente" in motivo
