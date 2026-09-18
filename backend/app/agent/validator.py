"""Validador de SQL previo a la ejecución.

Comprueba: una sola sentencia, solo lectura, tablas permitidas, límite de filas
y riesgo de full scan. Devuelve el SQL saneado (con LIMIT inyectado si falta).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PALABRAS_PROHIBIDAS = {
    "insert", "update", "delete", "drop", "create", "alter", "truncate", "grant",
    "revoke", "merge", "call", "copy", "unload", "vacuum", "attach", "detach",
    "install", "load", "export", "import", "pragma", "set", "reset", "begin",
    "commit", "rollback", "analyze", "replace",
}

# CREATE/REPLACE se permiten solo dentro del motor de transformación interno,
# nunca en el SQL generado a partir de lenguaje natural.

FUNCIONES_PELIGROSAS = {"read_csv", "read_parquet", "read_json", "system", "shell", "getenv"}


@dataclass
class ValidationResult:
    ok: bool
    sql: str
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    tablas: list[str] = field(default_factory=list)
    limite_aplicado: int | None = None
    riesgo_full_scan: str = "bajo"
    filas_estimadas: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errores": self.errores,
            "advertencias": self.advertencias,
            "tablas": self.tablas,
            "limite_aplicado": self.limite_aplicado,
            "riesgo_full_scan": self.riesgo_full_scan,
            "filas_estimadas": self.filas_estimadas,
        }


def _sin_comentarios(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return sql


def _sin_literales(sql: str) -> str:
    return re.sub(r"'[^']*'", "''", sql)


def extraer_tablas(sql: str) -> list[str]:
    plano = _sin_literales(_sin_comentarios(sql))
    referencias = re.findall(r"\b(?:from|join)\s+([a-zA-Z_][\w\.\"]*)", plano, flags=re.I)
    ctes = {c.lower() for c in re.findall(r"\b([a-zA-Z_]\w*)\s+as\s*\(", plano, flags=re.I)}
    tablas = []
    for ref in referencias:
        nombre = ref.replace('"', "").split(".")[-1].lower()
        if nombre in ctes or nombre in tablas:
            continue
        tablas.append(nombre)
    return tablas


def validar_sql(
    sql: str,
    tablas_permitidas: set[str],
    max_rows: int = 5000,
    estimaciones: dict[str, int] | None = None,
) -> ValidationResult:
    estimaciones = estimaciones or {}
    original = sql.strip().rstrip(";").strip()
    plano = _sin_literales(_sin_comentarios(original)).strip()
    errores: list[str] = []
    advertencias: list[str] = []

    if not plano:
        return ValidationResult(False, original, ["SQL vacío"])

    if ";" in plano.strip().rstrip(";"):
        errores.append("Se detectó más de una sentencia SQL. Solo se permite una.")

    primera = plano.lstrip("( ").split(None, 1)[0].lower()
    if primera not in {"select", "with"}:
        errores.append(f"Solo se permiten consultas SELECT/WITH (se recibió '{primera}').")

    tokens = set(re.findall(r"[a-zA-Z_]+", plano.lower()))
    prohibidas = sorted(tokens & PALABRAS_PROHIBIDAS)
    if prohibidas:
        errores.append(f"Palabras no permitidas en modo lectura: {', '.join(prohibidas)}")

    peligrosas = sorted(tokens & FUNCIONES_PELIGROSAS)
    if peligrosas:
        errores.append(f"Funciones de acceso a archivos no permitidas: {', '.join(peligrosas)}")

    tablas = extraer_tablas(original)
    desconocidas = [t for t in tablas if t not in tablas_permitidas]
    if desconocidas:
        errores.append(
            f"Tablas fuera del catálogo permitido: {', '.join(sorted(set(desconocidas)))}"
        )

    # Límite de filas
    limite_aplicado = None
    sql_final = original
    match_limit = re.search(r"\blimit\s+(\d+)\s*$", plano, flags=re.I)
    if match_limit:
        limite = int(match_limit.group(1))
        if limite > max_rows:
            sql_final = re.sub(r"\blimit\s+\d+\s*$", f"LIMIT {max_rows}", sql_final, flags=re.I)
            limite_aplicado = max_rows
            advertencias.append(f"LIMIT reducido de {limite} a {max_rows} por política.")
        else:
            limite_aplicado = limite
    else:
        sql_final = f"{sql_final}\nLIMIT {max_rows}"
        limite_aplicado = max_rows
        advertencias.append(f"Se agregó LIMIT {max_rows} automáticamente.")

    # Riesgo de full scan
    tiene_filtro = bool(re.search(r"\bwhere\b", plano, flags=re.I))
    tiene_agregacion = bool(
        re.search(r"\b(group\s+by|sum|count|avg|min|max|median)\b", plano, flags=re.I)
    )
    filas_estimadas = sum(estimaciones.get(t, 0) for t in set(tablas))
    riesgo = "bajo"
    if filas_estimadas > 100_000 and not tiene_filtro and not tiene_agregacion:
        riesgo = "alto"
        advertencias.append(
            "Riesgo alto de full scan: consulta sin filtros ni agregación sobre tablas grandes."
        )
    elif filas_estimadas > 20_000 and not tiene_filtro:
        riesgo = "medio"
        advertencias.append("Escaneo completo de una tabla de hechos sin filtro de fecha.")

    if re.search(r"select\s+\*", plano, flags=re.I) and filas_estimadas > 20_000:
        advertencias.append("SELECT * sobre una tabla grande: se recomienda proyectar columnas.")

    return ValidationResult(
        ok=not errores,
        sql=sql_final,
        errores=errores,
        advertencias=advertencias,
        tablas=sorted(set(tablas)),
        limite_aplicado=limite_aplicado,
        riesgo_full_scan=riesgo,
        filas_estimadas=filas_estimadas,
    )
