"""Almacén vectorial de la capa semántica.

Backend por defecto: `memory` (numpy, coseno exacto). Es suficiente para
metadatos (cientos de documentos) y no necesita servicio externo.
Backend opcional: `qdrant` por HTTP (perfil docker `qdrant`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import get_settings
from .embeddings import cosine, get_embedder, keyword_overlap, tokenizar


@dataclass
class Documento:
    id: str
    tipo: str  # tabla | columna | kpi | relacion | glosario | valor
    texto: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resultado:
    documento: Documento
    score: float
    score_vectorial: float
    score_lexico: float


class VectorStore:
    """Índice híbrido: coseno sobre embeddings + solape léxico."""

    def __init__(self, alpha: float = 0.75) -> None:
        self.embedder = get_embedder()
        self.alpha = alpha
        self._docs: list[Documento] = []
        self._matriz: np.ndarray = np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._remote = None
        settings = get_settings()
        if settings.vector_backend.lower() == "qdrant":
            self._remote = _QdrantBackend(settings.qdrant_url, self.embedder.dim)

    # ---------- escritura ----------
    def reset(self) -> None:
        self._docs = []
        self._matriz = np.zeros((0, self.embedder.dim), dtype=np.float32)
        if self._remote:
            self._remote.reset()

    def add(self, documentos: list[Documento]) -> None:
        if not documentos:
            return
        vectores = self.embedder.encode([d.texto for d in documentos])
        self._docs.extend(documentos)
        self._matriz = np.vstack([self._matriz, vectores]) if self._matriz.size else vectores
        if self._remote:
            self._remote.upsert(documentos, vectores)

    # ---------- lectura ----------
    @property
    def size(self) -> int:
        return len(self._docs)

    @property
    def backend(self) -> str:
        return "qdrant" if self._remote and self._remote.ok else "memory"

    def documentos(self, tipo: str | None = None) -> list[Documento]:
        return [d for d in self._docs if tipo is None or d.tipo == tipo]

    def search(self, consulta: str, k: int = 8, tipos: tuple[str, ...] | None = None) -> list[Resultado]:
        if not self._docs:
            return []
        qvec = self.embedder.encode_one(consulta)
        qtokens = tokenizar(consulta)
        vectorial = cosine(self._matriz, qvec)
        salida: list[Resultado] = []
        for i, doc in enumerate(self._docs):
            if tipos and doc.tipo not in tipos:
                continue
            lexico = keyword_overlap(qtokens, doc.texto)
            score = self.alpha * float(vectorial[i]) + (1 - self.alpha) * lexico
            salida.append(Resultado(doc, score, float(vectorial[i]), lexico))
        salida.sort(key=lambda r: r.score, reverse=True)
        return salida[:k]

    def embedding_preview(self, doc_id: str, dims: int = 12) -> list[float]:
        for i, doc in enumerate(self._docs):
            if doc.id == doc_id:
                return [round(float(x), 4) for x in self._matriz[i][:dims]]
        return []


class _QdrantBackend:  # pragma: no cover - requiere servicio externo
    """Espejo opcional en Qdrant. No bloquea la demo si el servicio no está."""

    COLECCION = "optimiza_semantic"

    def __init__(self, url: str, dim: int) -> None:
        self.url = url.rstrip("/")
        self.dim = dim
        self.ok = False
        try:
            import httpx

            self._httpx = httpx
            httpx.put(
                f"{self.url}/collections/{self.COLECCION}",
                json={"vectors": {"size": dim, "distance": "Cosine"}},
                timeout=3.0,
            )
            self.ok = True
        except Exception:
            self.ok = False

    def reset(self) -> None:
        if not self.ok:
            return
        try:
            self._httpx.delete(f"{self.url}/collections/{self.COLECCION}", timeout=3.0)
            self._httpx.put(
                f"{self.url}/collections/{self.COLECCION}",
                json={"vectors": {"size": self.dim, "distance": "Cosine"}},
                timeout=3.0,
            )
        except Exception:
            self.ok = False

    def upsert(self, documentos: list[Documento], vectores: np.ndarray) -> None:
        if not self.ok:
            return
        points = [
            {
                "id": abs(hash(d.id)) % (10**12),
                "vector": [float(x) for x in vec],
                "payload": {"doc_id": d.id, "tipo": d.tipo, "texto": d.texto, **d.metadata},
            }
            for d, vec in zip(documentos, vectores)
        ]
        try:
            self._httpx.put(
                f"{self.url}/collections/{self.COLECCION}/points",
                json={"points": points},
                timeout=10.0,
            )
        except Exception:
            self.ok = False
