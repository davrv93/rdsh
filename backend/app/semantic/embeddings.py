"""Embeddings locales para la capa semántica.

Backend por defecto: `hashing`. Es un embedding determinista basado en
hashing de n-gramas de palabra y de carácter, normalizado con IDF aproximado.
Corre en CPU, sin GPU, sin red y sin descargar modelos: suficiente para
recuperar metadatos en español y reproducible en cualquier máquina.

Backend opcional: `st` (sentence-transformers) si el paquete está instalado.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable, Sequence

import numpy as np

from ..config import get_settings

_TOKEN_RE = re.compile(r"[a-z0-9ñ]+")

STOPWORDS_ES = {
    "de", "la", "el", "los", "las", "un", "una", "y", "o", "en", "por", "para",
    "con", "del", "al", "que", "se", "su", "sus", "lo", "es", "son", "como",
    "mas", "muy", "me", "mi", "cual", "cuales", "sobre",
}


def normalizar(texto: str) -> str:
    """Minúsculas sin acentos (la ñ se conserva)."""
    texto = texto.lower().replace("ñ", "\x00")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.replace("\x00", "ñ")


def tokenizar(texto: str, quitar_stopwords: bool = True) -> list[str]:
    tokens = _TOKEN_RE.findall(normalizar(texto))
    if quitar_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS_ES]
    return tokens


def _hash(item: str, dim: int) -> int:
    return int.from_bytes(hashlib.blake2b(item.encode("utf-8"), digest_size=8).digest(), "big") % dim


class HashingEmbedder:
    """Embedding determinista: palabras + n-gramas de carácter (3,4,5)."""

    name = "hashing-local"

    def __init__(self, dim: int | None = None) -> None:
        settings = get_settings()
        self.dim = dim or settings.embedding_dim

    def encode_one(self, texto: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenizar(texto)
        for tok in tokens:
            vec[_hash(f"w::{tok}", self.dim)] += 1.0
        # bigramas de palabra: capturan "ticket promedio", "top clientes"
        for a, b in zip(tokens, tokens[1:]):
            vec[_hash(f"b::{a}_{b}", self.dim)] += 0.8
        # n-gramas de carácter: tolerancia a plurales y errores de tipeo
        plano = " " + " ".join(tokens) + " "
        for n in (3, 4, 5):
            for i in range(len(plano) - n + 1):
                vec[_hash(f"c{n}::{plano[i:i + n]}", self.dim)] += 0.35
        norma = np.linalg.norm(vec)
        return vec / norma if norma else vec

    def encode(self, textos: Sequence[str]) -> np.ndarray:
        if not textos:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self.encode_one(t) for t in textos])


class SentenceTransformerEmbedder:  # pragma: no cover - requiere paquete extra
    name = "sentence-transformers"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        self._model = SentenceTransformer(settings.st_model_name, device="cpu")
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def encode_one(self, texto: str) -> np.ndarray:
        return self.encode([texto])[0]

    def encode(self, textos: Sequence[str]) -> np.ndarray:
        return np.asarray(
            self._model.encode(list(textos), normalize_embeddings=True), dtype=np.float32
        )


def get_embedder() -> HashingEmbedder | "SentenceTransformerEmbedder":
    settings = get_settings()
    if settings.embedding_backend.lower() in {"st", "sentence-transformers"}:
        try:
            return SentenceTransformerEmbedder()
        except Exception:
            pass  # sin el paquete o sin red: degradar al embedder local
    return HashingEmbedder()


def cosine(matriz: np.ndarray, vector: np.ndarray) -> np.ndarray:
    if matriz.size == 0:
        return np.zeros(0, dtype=np.float32)
    return matriz @ vector


def keyword_overlap(consulta: Iterable[str], texto: str) -> float:
    """Señal léxica que complementa el coseno (BM25 simplificado)."""
    doc = set(tokenizar(texto))
    q = [t for t in consulta if t]
    if not q or not doc:
        return 0.0
    return sum(1.0 for t in q if t in doc) / len(q)
