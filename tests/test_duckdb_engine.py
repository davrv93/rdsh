"""DuckDB: ejecución, transformación real y detección de claves compatibles."""
import pandas as pd


def test_vistas_demo_disponibles(duck):
    tablas = duck.tablas()
    for esperada in ["ventas", "clientes", "productos", "campanias", "tickets_soporte"]:
        assert esperada in tablas


def test_transformacion_con_window_function(duck):
    base = duck.execute(
        "SELECT CAST(date_trunc('month', fecha) AS DATE) AS periodo, SUM(ingreso) AS ingreso "
        "FROM ventas GROUP BY 1 ORDER BY 1"
    )
    assert base.rows > 6

    transformado = duck.transform(
        base.dataframe,
        """SELECT periodo, ingreso,
                  ingreso - LAG(ingreso) OVER (ORDER BY periodo) AS variacion,
                  SUM(ingreso) OVER (ORDER BY periodo ROWS UNBOUNDED PRECEDING) AS acumulado
           FROM _resultado ORDER BY periodo""",
    )
    df = transformado.dataframe
    assert {"variacion", "acumulado"} <= set(df.columns)
    assert df["acumulado"].iloc[-1] == pytest_approx(base.dataframe["ingreso"].sum())


def pytest_approx(valor, tol=1.0):
    import pytest

    return pytest.approx(valor, abs=tol)


def test_clave_compatible_detectada(duck):
    prueba = duck.probe_join_key("tickets_soporte", "documento_cliente", "clientes", "documento")
    assert prueba["confiable"] is True
    assert prueba["cardinalidad"] == "many_to_one"
    assert prueba["cobertura_izquierda"] > 0.9


def test_clave_incompatible_rechazada(duck):
    prueba = duck.probe_join_key("web_sessions", "utm_campaign", "productos", "nombre")
    assert prueba["confiable"] is False
    assert prueba["valores_comunes"] == 0


def test_materializacion_de_cache(duck):
    df = pd.DataFrame({"a": [1, 2, 3]})
    duck.materialize(df, "_cache_test")
    assert duck.execute("SELECT SUM(a) AS s FROM _cache_test").dataframe.iloc[0]["s"] == 6
