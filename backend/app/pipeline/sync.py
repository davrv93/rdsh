"""Materialización Redshift → DuckDB.

Este es el proceso que reemplaza al ETL nocturno: extrae de Redshift en modo
lectura y deja los datos en DuckDB (tablas del esquema `cache` + Parquet),
para que las consultas siguientes se resuelvan localmente en milisegundos.

Modos:
  - completa:    vuelve a traer la tabla entera.
  - incremental: trae solo las filas nuevas según la columna de fecha de la
                 tabla (marca de agua guardada entre corridas).

Se puede ejecutar desde la API (`POST /api/admin/sync`), desde la línea de
comandos (`python -m backend.app.pipeline.sync`) o de forma programada.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd

from ..config import DATA_DIR, get_settings
from ..engines.duckdb_engine import get_duckdb
from ..engines.redshift_adapter import get_redshift
from ..security import audit
from ..semantic.catalog import get_catalog

log = logging.getLogger("optimiza.sync")

ESTADO_FILE = DATA_DIR / "sync_state.json"
CACHE_DIR = DATA_DIR / "cache"
_lock = threading.Lock()


@dataclass
class TablaSincronizada:
    tabla: str
    filas_nuevas: int
    filas_totales: int
    modo: str
    columna_marca: str | None
    marca: str | None
    ms_extraccion: float
    ms_carga: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class ResultadoSync:
    inicio: str
    fin: str
    origen: str
    tablas: list[TablaSincronizada] = field(default_factory=list)

    @property
    def ms_total(self) -> float:
        return sum(t.ms_extraccion + t.ms_carga for t in self.tablas)

    def to_dict(self) -> dict[str, Any]:
        return {
            "inicio": self.inicio,
            "fin": self.fin,
            "origen": self.origen,
            "ms_total": round(self.ms_total, 1),
            "filas_nuevas": sum(t.filas_nuevas for t in self.tablas),
            "tablas": [asdict(t) for t in self.tablas],
        }


def _leer_estado() -> dict[str, Any]:
    if ESTADO_FILE.exists():
        try:
            return json.loads(ESTADO_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _guardar_estado(estado: dict[str, Any]) -> None:
    ESTADO_FILE.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_FILE.write_text(json.dumps(estado, ensure_ascii=False, indent=2, default=str),
                           encoding="utf-8")


def columna_marca(tabla: str) -> str | None:
    """Columna de fecha que sirve como marca de agua para el incremental."""
    catalogo = get_catalog().table(tabla)
    if not catalogo:
        return None
    for columna in catalogo["columns"]:
        if columna.get("role") == "time":
            return columna["name"]
    for preferida in ("fecha", "fecha_alta", "fecha_inicio"):
        if any(c["name"] == preferida for c in catalogo["columns"]):
            return preferida
    return None


def tablas_del_catalogo() -> list[str]:
    return [t["name"] for t in get_catalog().tables]


def estado() -> dict[str, Any]:
    """Estado de la caché: qué hay materializado, cuántas filas y desde cuándo."""
    settings = get_settings()
    guardado = _leer_estado()
    duck = get_duckdb()
    materializadas = duck.cache_info()
    ahora = datetime.now(timezone.utc)
    tablas = []
    for tabla in tablas_del_catalogo():
        info = materializadas.get(tabla, {})
        previo = guardado.get("tablas", {}).get(tabla, {})
        actualizada = previo.get("ultima_sync")
        antiguedad_min = None
        if actualizada:
            try:
                antiguedad_min = round(
                    (ahora - datetime.fromisoformat(actualizada)).total_seconds() / 60, 1
                )
            except ValueError:
                antiguedad_min = None
        tablas.append(
            {
                "tabla": tabla,
                "materializada": bool(info),
                "filas": info.get("filas", 0),
                "ultima_sync": actualizada,
                "antiguedad_min": antiguedad_min,
                "marca": previo.get("marca"),
                "columna_marca": previo.get("columna_marca") or columna_marca(tabla),
                "fresca": antiguedad_min is not None and antiguedad_min <= settings.cache_max_age_min,
            }
        )
    return {
        "origen": "redshift" if settings.use_redshift else "duckdb_demo",
        "routing": settings.query_routing,
        "cache_max_age_min": settings.cache_max_age_min,
        "ultima_corrida": guardado.get("ultima_corrida"),
        "tablas": tablas,
    }


def tablas_frescas(tablas: Iterable[str]) -> bool:
    """True si todas las tablas pedidas están materializadas y dentro de la ventana."""
    detalle = {t["tabla"]: t for t in estado()["tablas"]}
    for tabla in tablas:
        info = detalle.get(tabla)
        if not info or not info["materializada"] or not info["fresca"]:
            return False
    return True


def sincronizar(tablas: list[str] | None = None, incremental: bool = True,
                chunk: int = 50_000) -> ResultadoSync:
    """Extrae de Redshift y materializa en DuckDB. Devuelve el detalle por tabla."""
    settings = get_settings()
    redshift = get_redshift()
    duck = get_duckdb()
    if not (settings.use_redshift and redshift.available):
        raise RuntimeError(
            "La sincronización requiere Redshift configurado "
            "(OPTIMIZA_SOURCE_MODE=redshift y credenciales válidas)."
        )

    objetivo = tablas or tablas_del_catalogo()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    guardado = _leer_estado()
    guardado.setdefault("tablas", {})
    resultado = ResultadoSync(
        inicio=datetime.now(timezone.utc).isoformat(), fin="", origen="redshift"
    )

    with _lock:
        for tabla in objetivo:
            columna = columna_marca(tabla)
            previo = guardado["tablas"].get(tabla, {})
            marca_previa = previo.get("marca") if incremental else None
            modo = "incremental" if (marca_previa and columna) else "completa"

            sql = f"SELECT * FROM {settings.redshift.schema}.{tabla}"
            if modo == "incremental":
                sql += f" WHERE {columna} > '{marca_previa}'"

            t0 = time.perf_counter()
            try:
                bloques = list(redshift.execute_stream(sql, chunk=chunk))
            except Exception as exc:
                log.warning("Fallo extrayendo %s: %s", tabla, exc)
                resultado.tablas.append(
                    TablaSincronizada(tabla, 0, 0, modo, columna, marca_previa, 0.0, 0.0,
                                      str(exc)[:200])
                )
                continue
            ms_extraccion = (time.perf_counter() - t0) * 1000

            df = pd.concat(bloques, ignore_index=True) if bloques else pd.DataFrame()
            t1 = time.perf_counter()
            if modo == "completa":
                duck.materializar_cache(df, tabla, reemplazar=True)
            elif not df.empty:
                duck.materializar_cache(df, tabla, reemplazar=False)
            filas_totales = duck.cache_info().get(tabla, {}).get("filas", len(df))
            duck.exportar_cache_parquet(tabla, CACHE_DIR / f"{tabla}.parquet")
            ms_carga = (time.perf_counter() - t1) * 1000

            marca = marca_previa
            if columna and not df.empty and columna in df.columns:
                nueva = pd.to_datetime(df[columna], errors="coerce").max()
                if pd.notna(nueva):
                    marca = str(pd.Timestamp(nueva).date())

            guardado["tablas"][tabla] = {
                "ultima_sync": datetime.now(timezone.utc).isoformat(),
                "marca": marca,
                "columna_marca": columna,
                "filas": filas_totales,
                "modo": modo,
            }
            resultado.tablas.append(
                TablaSincronizada(tabla, len(df), filas_totales, modo, columna, marca,
                                  ms_extraccion, ms_carga)
            )

        duck.exponer_cache_como_vistas()
        resultado.fin = datetime.now(timezone.utc).isoformat()
        guardado["ultima_corrida"] = resultado.to_dict()
        _guardar_estado(guardado)

    audit.registrar(
        "sincronizacion",
        {
            "tablas": [t.tabla for t in resultado.tablas],
            "filas_nuevas": sum(t.filas_nuevas for t in resultado.tablas),
            "ms_total": round(resultado.ms_total, 1),
            "errores": [t.error for t in resultado.tablas if t.error],
        },
    )
    return resultado


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import sys

    completa = "--completa" in sys.argv
    salida = sincronizar(incremental=not completa)
    print(f"Sincronización {'completa' if completa else 'incremental'} "
          f"en {salida.ms_total:.0f} ms")
    for t in salida.tablas:
        estado_txt = t.error or f"{t.filas_nuevas:>8,} nuevas / {t.filas_totales:>9,} totales"
        print(f"  {t.tabla:18s} {t.modo:12s} {estado_txt}")
