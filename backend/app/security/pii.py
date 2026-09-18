"""Enmascaramiento de PII.

Se aplica en dos puntos:
  1. Antes de enviar cualquier muestra al LLM (nunca salen datos crudos).
  2. Antes de devolver resultados al frontend, si MASK_PII=true.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

PATRONES = {
    "email": re.compile(r"[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+"),
    "documento": re.compile(r"\b\d{8,11}\b"),
    "telefono": re.compile(r"\b(?:\+?51)?\s?9\d{8}\b"),
    "tarjeta": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
}

NOMBRES_SENSIBLES = {
    "email", "correo", "documento", "dni", "ruc", "telefono", "celular",
    "nombre", "direccion", "tarjeta", "documento_cliente",
}


def enmascarar_valor(valor: Any) -> Any:
    if not isinstance(valor, str):
        return valor
    texto = valor
    texto = PATRONES["email"].sub(lambda m: _mask_email(m.group()), texto)
    texto = PATRONES["documento"].sub(lambda m: m.group()[:2] + "*" * (len(m.group()) - 4) + m.group()[-2:], texto)
    return texto


def _mask_email(valor: str) -> str:
    usuario, _, dominio = valor.partition("@")
    visible = usuario[:2]
    return f"{visible}{'*' * max(3, len(usuario) - 2)}@{dominio}"


def enmascarar_nombre(valor: Any) -> Any:
    if not isinstance(valor, str) or not valor.strip():
        return valor
    partes = valor.split()
    return " ".join(p[0] + "." if i else p for i, p in enumerate(partes))


def columnas_pii(columnas: list[str], declaradas: set[str]) -> list[str]:
    """Une la marca del catálogo con una heurística por nombre."""
    salida = []
    for c in columnas:
        corto = c.split(".")[-1].lower()
        if corto in NOMBRES_SENSIBLES or any(d.split(".")[-1] == corto for d in declaradas):
            salida.append(c)
    return salida


def enmascarar_dataframe(df: pd.DataFrame, columnas: list[str]) -> tuple[pd.DataFrame, list[str]]:
    if df.empty or not columnas:
        return df, []
    out = df.copy()
    aplicadas = []
    for c in columnas:
        if c not in out.columns:
            continue
        corto = c.split(".")[-1].lower()
        if corto in {"nombre", "razon_social", "cliente", "nombre_cliente"}:
            out[c] = out[c].map(enmascarar_nombre)
        else:
            out[c] = out[c].map(enmascarar_valor)
        aplicadas.append(c)
    return out, aplicadas
