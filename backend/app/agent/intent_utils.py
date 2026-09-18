"""Utilidades compartidas por los motores de clasificación de intención.

Viven aparte para que un motor nuevo pueda reutilizar la normalización del
español y la extracción de características sin depender de otro motor.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

from ..semantic.embeddings import tokenizar

DIM = 2048

# Cortesía y saludos que preceden a una pregunta real. Se quitan antes de
# clasificar: sin esto, "hola puedes decirme el margen..." cae en `aclaracion`.
PREFIJOS_CORTESIA = re.compile(
    r"^\s*(?:"
    r"hola|holi|buen[oa]s?\s+(?:d[ií]as?|tardes|noches)|oye|disculpa|perdona|"
    r"por\s*favor|porfa(?:vor)?|gracias|hey|buenas|"
    r"me\s+puedes?\s+(?:decir|dar|mostrar|indicar)|"
    r"puedes?\s+(?:decirme|darme|mostrarme|indicarme)|"
    r"quisiera\s+(?:saber|ver)|quiero\s+saber|necesito\s+saber|"
    r"podr[ií]as?\s+(?:decirme|darme|mostrarme)"
    r")\b[\s,\.:;¿?!¡-]*",
    flags=re.I,
)

# Vocabulario analítico mínimo: si aparece, la pregunta no es una simple
# aclaración aunque venga envuelta en cortesía.
VOCABULARIO_ANALITICO = re.compile(
    r"\b(venta\w*|ingres\w*|margen|margn|meargen|facturaci[oó]n|unidad\w*|ticket|tiket|"
    r"roi|roas|csat|conversi[oó]n|cliente\w*|producto\w*|campa[nñ]a\w*|regi[oó]n|regiones|"
    r"categor[ií]a\w*|segmento\w*|canal\w*|mes|meses|trimestre\w*|a[nñ]o\w*|kpi\w*|"
    r"tabla\w*|columna\w*|top|ranking|total|promedio|csv)\b",
    flags=re.I,
)


def limpiar_cortesia(texto: str) -> str:
    """Quita saludos y fórmulas de cortesía iniciales, hasta dos veces."""
    limpio = texto
    for _ in range(2):
        nuevo = PREFIJOS_CORTESIA.sub("", limpio, count=1)
        if nuevo == limpio:
            break
        limpio = nuevo
    return limpio.strip() or texto.strip()


def caracteristicas(texto: str, dim: int = DIM) -> np.ndarray:
    """Vector disperso denso-izado: palabras, bigramas y n-gramas de carácter."""
    vec = np.zeros(dim, dtype=np.float32)

    def bump(clave: str, peso: float) -> None:
        h = int.from_bytes(hashlib.blake2b(clave.encode(), digest_size=6).digest(), "big")
        vec[h % dim] += peso

    tokens = tokenizar(texto, quitar_stopwords=False)
    for t in tokens:
        bump(f"w::{t}", 1.0)
        bump(f"p::{t[:4]}", 0.5)  # prefijo: cubre flexiones (grafic*, export*)
    for a, b in zip(tokens, tokens[1:]):
        bump(f"b::{a}_{b}", 0.8)
    plano = " " + " ".join(tokens) + " "
    for n in (3, 4):
        for i in range(len(plano) - n + 1):
            bump(f"c{n}::{plano[i:i + n]}", 0.3)
    bump("__bias__", 1.0)
    norma = np.linalg.norm(vec)
    return vec / norma if norma else vec
