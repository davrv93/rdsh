"""Motor analítico embebido DuckDB.

Roles en la demo:
  1. Simulador de Redshift (vistas sobre Parquet) cuando no hay credenciales.
  2. Motor de transformación local sobre resultados (CTEs, window functions, PIVOT).
  3. Caché de resultados materializados.
  4. Detector de claves compatibles entre tablas sin relación declarada.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from ..config import DATA_DIR, SEED_DIR, get_settings

TABLAS_DEMO = [
    "ventas", "clientes", "productos", "campanias", "regiones", "dim_fechas",
    "tickets_soporte", "web_sessions",
]


@dataclass
class QueryResult:
    dataframe: pd.DataFrame
    elapsed_ms: float
    rows: int
    truncated: bool = False
    engine: str = "duckdb"

    @property
    def columns(self) -> list[str]:
        return [str(c) for c in self.dataframe.columns]


class DuckDBEngine:
    def __init__(self, database: str | None = None) -> None:
        self._lock = threading.RLock()
        path = database or str(DATA_DIR / "optimiza.duckdb")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(path)
        self.con.execute("SET threads TO 4")
        self._bootstrap_views()

    def _bootstrap_views(self) -> None:
        """Prepara las vistas que consultará el agente.

        - En modo demo: vistas sobre los Parquet generados.
        - En modo Redshift: vistas sobre el esquema `cache`, que llena el
          proceso de materialización (backend/app/pipeline/sync.py).
        """
        with self._lock:
            self.con.execute("CREATE SCHEMA IF NOT EXISTS cache")

        if get_settings().use_redshift:
            self.exponer_cache_como_vistas()
            return

        from ..seed.generate_seed import build_seed

        build_seed()
        with self._lock:
            for tabla in TABLAS_DEMO:
                archivo = SEED_DIR / f"{tabla}.parquet"
                if archivo.exists():
                    self.con.execute(
                        f"CREATE OR REPLACE VIEW {tabla} AS "
                        f"SELECT * FROM read_parquet('{archivo.as_posix()}')"
                    )

    # ---------- caché materializada desde Redshift ----------
    def materializar_cache(self, df: pd.DataFrame, tabla: str, reemplazar: bool = True) -> int:
        """Carga un DataFrame extraído de Redshift en `cache.<tabla>`."""
        with self._lock:
            self.con.register("_tmp_sync", df)
            if reemplazar:
                self.con.execute(
                    f'CREATE OR REPLACE TABLE cache."{tabla}" AS SELECT * FROM _tmp_sync'
                )
            else:
                self.con.execute(
                    f'CREATE TABLE IF NOT EXISTS cache."{tabla}" AS SELECT * FROM _tmp_sync WHERE 1=0'
                )
                self.con.execute(f'INSERT INTO cache."{tabla}" SELECT * FROM _tmp_sync')
            self.con.unregister("_tmp_sync")
            filas = self.con.execute(f'SELECT COUNT(*) FROM cache."{tabla}"').fetchone()[0]
        return int(filas)

    def cache_info(self) -> dict[str, dict[str, Any]]:
        """Tablas materializadas en la caché local y su conteo de filas."""
        with self._lock:
            filas = self.con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'cache' ORDER BY 1"
            ).fetchall()
            salida: dict[str, dict[str, Any]] = {}
            for (tabla,) in filas:
                total = self.con.execute(f'SELECT COUNT(*) FROM cache."{tabla}"').fetchone()[0]
                salida[tabla] = {"filas": int(total)}
        return salida

    def exportar_cache_parquet(self, tabla: str, destino) -> None:
        """Deja también una copia en Parquet, inspeccionable y portable."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            existe = self.con.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'cache' AND table_name = ?", [tabla]
            ).fetchone()[0]
            if existe:
                self.con.execute(
                    f"COPY cache.\"{tabla}\" TO '{destino.as_posix()}' (FORMAT parquet)"
                )

    def exponer_cache_como_vistas(self) -> list[str]:
        """Publica cada tabla de `cache` con su nombre de negocio."""
        expuestas = []
        with self._lock:
            filas = self.con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'cache'"
            ).fetchall()
            for (tabla,) in filas:
                self.con.execute(
                    f'CREATE OR REPLACE VIEW "{tabla}" AS SELECT * FROM cache."{tabla}"'
                )
                expuestas.append(tabla)
        return expuestas

    def tablas_en_cache(self) -> set[str]:
        return set(self.cache_info())

    # ---------- ejecución ----------
    def execute(self, sql: str, max_rows: int | None = None,
                timeout_s: int | None = None) -> QueryResult:
        settings = get_settings()
        max_rows = max_rows or settings.max_rows
        timeout_s = timeout_s or settings.query_timeout_s
        with self._lock:
            cursor = self.con.cursor()
            temporizador = threading.Timer(timeout_s, cursor.interrupt)
            temporizador.start()
            t0 = time.perf_counter()
            try:
                df = cursor.execute(sql).fetch_df()
            except duckdb.InterruptException as exc:  # pragma: no cover
                raise TimeoutError(
                    f"La consulta superó el timeout de {timeout_s}s y fue cancelada"
                ) from exc
            finally:
                temporizador.cancel()
                cursor.close()
            elapsed_ms = (time.perf_counter() - t0) * 1000
        truncated = len(df) > max_rows
        if truncated:
            df = df.head(max_rows)
        return QueryResult(df, elapsed_ms, len(df), truncated, "duckdb")

    def transform(self, df: pd.DataFrame, sql: str, vista: str = "_resultado") -> QueryResult:
        """Aplica una transformación DuckDB sobre un DataFrame ya obtenido.

        Se usa tanto con resultados de DuckDB como con resultados de Redshift.
        """
        with self._lock:
            cursor = self.con.cursor()
            t0 = time.perf_counter()
            try:
                cursor.register(vista, df)
                out = cursor.execute(sql).fetch_df()
            finally:
                try:
                    cursor.unregister(vista)
                except Exception:
                    pass
                cursor.close()
            elapsed_ms = (time.perf_counter() - t0) * 1000
        return QueryResult(out, elapsed_ms, len(out), False, "duckdb-transform")

    def materialize(self, df: pd.DataFrame, nombre: str) -> None:
        """Cachea un resultado como tabla temporal reutilizable."""
        with self._lock:
            self.con.register("_tmp_mat", df)
            self.con.execute(f'CREATE OR REPLACE TABLE "{nombre}" AS SELECT * FROM _tmp_mat')
            self.con.unregister("_tmp_mat")

    # ---------- introspección ----------
    def tablas(self) -> list[str]:
        """Vistas y tablas consultables por el agente (esquema principal)."""
        with self._lock:
            filas = self.con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY 1"
            ).fetchall()
        return [f[0] for f in filas]

    def sample(self, tabla: str, n: int = 5) -> pd.DataFrame:
        return self.execute(f'SELECT * FROM "{tabla}" LIMIT {int(n)}').dataframe

    def profile_column(self, tabla: str, columna: str) -> dict[str, Any]:
        sql = (
            f'SELECT COUNT(*) AS filas, COUNT(DISTINCT "{columna}") AS distintos, '
            f'COUNT("{columna}") AS no_nulos FROM "{tabla}"'
        )
        fila = self.execute(sql).dataframe.iloc[0]
        filas = int(fila["filas"]) or 1
        return {
            "filas": int(fila["filas"]),
            "distintos": int(fila["distintos"]),
            "no_nulos": int(fila["no_nulos"]),
            "unicidad": round(int(fila["distintos"]) / filas, 4),
        }

    def probe_join_key(self, tabla_a: str, col_a: str, tabla_b: str, col_b: str) -> dict[str, Any]:
        """Valida empíricamente una clave candidata entre dos tablas.

        Devuelve solape de valores y cardinalidad estimada. Sirve para explicar
        el join ANTES de ejecutarlo; nunca lo ejecuta por su cuenta.
        """
        sql = f"""
        WITH a AS (SELECT DISTINCT CAST("{col_a}" AS VARCHAR) AS v FROM "{tabla_a}" WHERE "{col_a}" IS NOT NULL),
             b AS (SELECT DISTINCT CAST("{col_b}" AS VARCHAR) AS v FROM "{tabla_b}" WHERE "{col_b}" IS NOT NULL),
             i AS (SELECT v FROM a INTERSECT SELECT v FROM b)
        SELECT (SELECT COUNT(*) FROM a) AS distintos_a,
               (SELECT COUNT(*) FROM b) AS distintos_b,
               (SELECT COUNT(*) FROM i) AS comunes
        """
        fila = self.execute(sql).dataframe.iloc[0]
        da, db, comunes = int(fila["distintos_a"]), int(fila["distintos_b"]), int(fila["comunes"])
        perfil_a = self.profile_column(tabla_a, col_a)
        perfil_b = self.profile_column(tabla_b, col_b)
        cobertura_a = comunes / da if da else 0.0
        cobertura_b = comunes / db if db else 0.0
        if perfil_a["unicidad"] > 0.98 and perfil_b["unicidad"] > 0.98:
            cardinalidad = "one_to_one"
        elif perfil_b["unicidad"] > 0.98:
            cardinalidad = "many_to_one"
        elif perfil_a["unicidad"] > 0.98:
            cardinalidad = "one_to_many"
        else:
            cardinalidad = "many_to_many"
        return {
            "izquierda": f"{tabla_a}.{col_a}",
            "derecha": f"{tabla_b}.{col_b}",
            "distintos_izquierda": da,
            "distintos_derecha": db,
            "valores_comunes": comunes,
            "cobertura_izquierda": round(cobertura_a, 4),
            "cobertura_derecha": round(cobertura_b, 4),
            "cardinalidad": cardinalidad,
            "confiable": cobertura_a >= 0.6 and cardinalidad != "many_to_many",
        }


_engine: DuckDBEngine | None = None


def get_duckdb() -> DuckDBEngine:
    global _engine
    if _engine is None:
        _engine = DuckDBEngine()
    return _engine
