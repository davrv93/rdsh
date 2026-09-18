"""Adaptador Redshift estrictamente de solo lectura.

Reglas de seguridad aplicadas aquí (además del validador SQL):
  - Conexión con usuario read-only tomado de variables de entorno.
  - `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` en cada sesión.
  - `statement_timeout` a nivel de sesión.
  - Corte de filas del lado del cliente con `fetchmany`.
Si no hay credenciales, `available` es False y el orquestador usa DuckDB.
"""
from __future__ import annotations

import time
from typing import Any

import pandas as pd

from ..config import get_settings
from .duckdb_engine import QueryResult


class RedshiftAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cfg = self.settings.redshift
        self._driver = None
        self.error: str | None = None
        if self.cfg.configured:
            try:
                import psycopg2  # noqa: F401

                self._driver = psycopg2
            except ImportError as exc:
                self.error = (
                    "psycopg2 no está instalado. Usa: pip install -r requirements-redshift.txt"
                    f" ({exc})"
                )

    @property
    def available(self) -> bool:
        return self._driver is not None and self.cfg.configured

    def _connect(self, statement_timeout_ms: int | None = None, autocommit: bool = True):
        """Sesión de solo lectura, con timeout y search_path al esquema del catálogo."""
        timeout = statement_timeout_ms or self.cfg.statement_timeout_ms
        opciones = f"-c statement_timeout={timeout} -c search_path={self.cfg.schema},public"
        conn = self._driver.connect(
            host=self.cfg.host,
            port=self.cfg.port,
            dbname=self.cfg.database,
            user=self.cfg.user,
            password=self.cfg.password,
            connect_timeout=8,
            options=opciones,
        )
        conn.set_session(readonly=True, autocommit=autocommit)
        return conn

    def ping(self) -> dict[str, Any]:
        if not self.available:
            return {"ok": False, "motivo": self.error or "Sin credenciales de Redshift"}
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT current_user, version()")
                usuario, version = cur.fetchone()
            return {"ok": True, "usuario": usuario, "version": version[:80]}
        except Exception as exc:  # pragma: no cover - depende del entorno
            return {"ok": False, "motivo": str(exc)[:300]}

    def execute(self, sql: str, max_rows: int | None = None) -> QueryResult:
        if not self.available:
            raise RuntimeError(self.error or "Redshift no está configurado")
        max_rows = max_rows or self.settings.max_rows
        t0 = time.perf_counter()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
            cur.execute(sql)
            columnas = [c.name for c in cur.description]
            filas = cur.fetchmany(max_rows + 1)
        truncated = len(filas) > max_rows
        df = pd.DataFrame(filas[:max_rows], columns=columnas)
        return QueryResult(df, (time.perf_counter() - t0) * 1000, len(df), truncated, "redshift")

    def execute_stream(self, sql: str, chunk: int = 50_000,
                       statement_timeout_ms: int | None = None):
        """Itera el resultado por bloques, sin el límite de filas de la API.

        Lo usa el proceso de materialización hacia DuckDB, que sí necesita
        extraer tablas completas.
        """
        if not self.available:
            raise RuntimeError(self.error or "Redshift no está configurado")
        # Un cursor con nombre (server-side) necesita transacción: sin autocommit.
        with self._connect(statement_timeout_ms or 600_000, autocommit=False) as conn:
            with conn.cursor(name="optimiza_stream") as cur:
                cur.itersize = chunk
                cur.execute(sql)
                # Con cursor del servidor, `description` recién está disponible
                # después del primer fetch.
                filas = cur.fetchmany(chunk)
                if not filas:
                    return
                columnas = [c.name for c in cur.description]
                while filas:
                    yield pd.DataFrame(filas, columns=columnas)
                    filas = cur.fetchmany(chunk)

    def scalar(self, sql: str):
        """Devuelve el primer valor de la primera fila (marcas de agua, conteos)."""
        if not self.available:
            raise RuntimeError(self.error or "Redshift no está configurado")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            fila = cur.fetchone()
        return fila[0] if fila else None

    def introspect(self) -> list[dict[str, Any]]:  # pragma: no cover - requiere cluster
        """Lee el catálogo real para alimentar la capa semántica."""
        sql = """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (self.cfg.schema,))
            filas = cur.fetchall()
        tablas: dict[str, dict[str, Any]] = {}
        for tabla, columna, tipo in filas:
            entry = tablas.setdefault(
                tabla, {"name": tabla, "kind": "unknown", "description": "", "columns": []}
            )
            entry["columns"].append({"name": columna, "type": tipo, "description": ""})
        return list(tablas.values())


_adapter: RedshiftAdapter | None = None


def get_redshift() -> RedshiftAdapter:
    global _adapter
    if _adapter is None:
        _adapter = RedshiftAdapter()
    return _adapter
