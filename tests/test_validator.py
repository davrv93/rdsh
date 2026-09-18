"""Validación de SQL: solo lectura, catálogo permitido, límites y full scan."""
import pytest

from backend.app.agent.validator import extraer_tablas, validar_sql

PERMITIDAS = {"ventas", "clientes", "productos"}
ESTIMACIONES = {"ventas": 40000, "clientes": 600, "productos": 120}


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE ventas",
        "DELETE FROM ventas WHERE 1=1",
        "INSERT INTO ventas VALUES (1)",
        "UPDATE ventas SET ingreso = 0",
        "SELECT * FROM read_csv('/etc/passwd')",
    ],
)
def test_rechaza_operaciones_de_escritura(sql):
    assert validar_sql(sql, PERMITIDAS, 100, ESTIMACIONES).ok is False


def test_rechaza_tablas_fuera_del_catalogo():
    resultado = validar_sql("SELECT * FROM finanzas_secretas", PERMITIDAS, 100, ESTIMACIONES)
    assert not resultado.ok
    assert any("catálogo" in e for e in resultado.errores)


def test_inyecta_limite_cuando_falta():
    resultado = validar_sql("SELECT canal, SUM(ingreso) FROM ventas GROUP BY 1",
                            PERMITIDAS, 500, ESTIMACIONES)
    assert resultado.ok
    assert resultado.sql.strip().endswith("LIMIT 500")
    assert resultado.limite_aplicado == 500


def test_reduce_limite_excesivo():
    resultado = validar_sql("SELECT * FROM clientes LIMIT 99999", PERMITIDAS, 1000, ESTIMACIONES)
    assert resultado.limite_aplicado == 1000
    assert "LIMIT 1000" in resultado.sql


def test_marca_riesgo_full_scan():
    resultado = validar_sql("SELECT * FROM ventas", PERMITIDAS, 5000, {"ventas": 400000})
    assert resultado.riesgo_full_scan == "alto"


def test_acepta_cte_y_window_functions():
    sql = """WITH base AS (
        SELECT canal, SUM(ingreso) AS ingreso FROM ventas WHERE fecha >= DATE '2025-01-01' GROUP BY 1
    )
    SELECT canal, ingreso, RANK() OVER (ORDER BY ingreso DESC) AS r FROM base LIMIT 10"""
    resultado = validar_sql(sql, PERMITIDAS, 5000, ESTIMACIONES)
    assert resultado.ok, resultado.errores
    assert resultado.tablas == ["ventas"]


def test_extrae_tablas_ignorando_ctes():
    sql = "WITH t AS (SELECT * FROM ventas) SELECT * FROM t JOIN clientes ON 1=1"
    assert set(extraer_tablas(sql)) == {"ventas", "clientes"}
