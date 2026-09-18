"""Capa semántica: catálogo de metadatos + índice vectorial.

Indexa tablas, columnas, KPIs, relaciones, valores categóricos y glosario.
Las relaciones virtuales declaradas por el admin se persisten en disco.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Iterable

from ..config import DATA_DIR, BASE_DIR
from .vector_store import Documento, Resultado, VectorStore

METADATA_FILE = BASE_DIR / "seed" / "metadata.json"
VIRTUAL_RELATIONS_FILE = DATA_DIR / "virtual_relations.json"


class Catalog:
    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        self.metadata: dict[str, Any] = metadata or self._load_metadata()
        self.metadata.setdefault("virtual_relations", [])
        self.metadata["virtual_relations"] = self._load_virtual_relations()
        self.store = VectorStore()
        self.reindex()

    # ---------- carga ----------
    @staticmethod
    def _load_metadata() -> dict[str, Any]:
        return json.loads(METADATA_FILE.read_text(encoding="utf-8"))

    @staticmethod
    def _load_virtual_relations() -> list[dict[str, Any]]:
        if VIRTUAL_RELATIONS_FILE.exists():
            try:
                return json.loads(VIRTUAL_RELATIONS_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
        return []

    def _save_virtual_relations(self) -> None:
        VIRTUAL_RELATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        VIRTUAL_RELATIONS_FILE.write_text(
            json.dumps(self.metadata["virtual_relations"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---------- accesores ----------
    @property
    def tables(self) -> list[dict[str, Any]]:
        return self.metadata["tables"]

    @property
    def kpis(self) -> list[dict[str, Any]]:
        return self.metadata["kpis"]

    @property
    def relations(self) -> list[dict[str, Any]]:
        return list(self.metadata["relations"]) + list(self.metadata["virtual_relations"])

    def table(self, nombre: str) -> dict[str, Any] | None:
        return next((t for t in self.tables if t["name"] == nombre), None)

    def column(self, tabla: str, columna: str) -> dict[str, Any] | None:
        t = self.table(tabla)
        if not t:
            return None
        return next((c for c in t["columns"] if c["name"] == columna), None)

    def kpi(self, nombre: str) -> dict[str, Any] | None:
        return next((k for k in self.kpis if k["name"] == nombre), None)

    def pii_columns(self) -> set[str]:
        return {
            f"{t['name']}.{c['name']}"
            for t in self.tables
            for c in t["columns"]
            if c.get("pii")
        }

    def relation_between(self, a: str, b: str) -> dict[str, Any] | None:
        for rel in self.relations:
            lt, rt = rel["left"].split(".")[0], rel["right"].split(".")[0]
            if {lt, rt} == {a, b}:
                return rel
        return None

    def join_path(self, tablas: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Devuelve (relaciones usables, tablas que quedaron sin conectar)."""
        pendientes = [t for t in tablas]
        if len(pendientes) <= 1:
            return [], []
        base = pendientes[0]
        conectadas = {base}
        usadas: list[dict[str, Any]] = []
        sin_conectar: list[str] = []
        for t in pendientes[1:]:
            rel = None
            for c in list(conectadas):
                rel = self.relation_between(c, t)
                if rel:
                    break
            if rel:
                usadas.append(rel)
                conectadas.add(t)
            else:
                sin_conectar.append(t)
        return usadas, sin_conectar

    # ---------- índice vectorial ----------
    def _documentos(self) -> list[Documento]:
        docs: list[Documento] = []
        for t in self.tables:
            sin = " ".join(t.get("sinonimos", []))
            docs.append(
                Documento(
                    id=f"tabla::{t['name']}",
                    tipo="tabla",
                    texto=f"tabla {t['name']} {sin} {t['description']}",
                    metadata={"tabla": t["name"], "kind": t.get("kind"), "orphan": t.get("orphan", False)},
                )
            )
            for c in t["columns"]:
                cats = " ".join(str(v) for v in c.get("categorias", []))
                docs.append(
                    Documento(
                        id=f"columna::{t['name']}.{c['name']}",
                        tipo="columna",
                        texto=f"columna {c['name']} de {t['name']} {c['description']} {cats}",
                        metadata={
                            "tabla": t["name"],
                            "columna": c["name"],
                            "role": c.get("role"),
                            "type": c.get("type"),
                            "pii": bool(c.get("pii")),
                        },
                    )
                )
                for valor in c.get("categorias", []):
                    docs.append(
                        Documento(
                            id=f"valor::{t['name']}.{c['name']}::{valor}",
                            tipo="valor",
                            texto=f"valor {valor} de la columna {c['name']} en {t['name']}",
                            metadata={"tabla": t["name"], "columna": c["name"], "valor": valor},
                        )
                    )
        for k in self.kpis:
            sin = " ".join(k.get("sinonimos", []))
            docs.append(
                Documento(
                    id=f"kpi::{k['name']}",
                    tipo="kpi",
                    texto=f"kpi {k['label']} {sin} {k['description']} {k['expression']}",
                    metadata={"kpi": k["name"], "expression": k["expression"], "format": k.get("format")},
                )
            )
        for r in self.relations:
            docs.append(
                Documento(
                    id=f"relacion::{r['left']}->{r['right']}",
                    tipo="relacion",
                    texto=f"relacion {r['left']} con {r['right']} tipo {r['type']}",
                    metadata=dict(r),
                )
            )
        for g in self.metadata.get("glosario", []):
            docs.append(
                Documento(
                    id=f"glosario::{g['termino']}",
                    tipo="glosario",
                    texto=f"{g['termino']} {g['definicion']}",
                    metadata=dict(g),
                )
            )
        return docs

    def reindex(self) -> int:
        with self._lock:
            self.store.reset()
            self.store.add(self._documentos())
            return self.store.size

    def search(self, consulta: str, k: int = 10, tipos: tuple[str, ...] | None = None) -> list[Resultado]:
        return self.store.search(consulta, k=k, tipos=tipos)

    # ---------- administración ----------
    def add_virtual_relation(self, left: str, right: str, tipo: str = "many_to_one",
                             nota: str = "") -> dict[str, Any]:
        for ref in (left, right):
            tabla, _, columna = ref.partition(".")
            if not self.column(tabla, columna):
                raise ValueError(f"Columna inexistente en el catálogo: {ref}")
        rel = {
            "left": left,
            "right": right,
            "type": tipo,
            "declared": False,
            "virtual": True,
            "nota": nota,
        }
        with self._lock:
            self.metadata["virtual_relations"].append(rel)
            self._save_virtual_relations()
            self.reindex()
        return rel

    def remove_virtual_relation(self, left: str, right: str) -> bool:
        with self._lock:
            antes = len(self.metadata["virtual_relations"])
            self.metadata["virtual_relations"] = [
                r for r in self.metadata["virtual_relations"]
                if not (r["left"] == left and r["right"] == right)
            ]
            if len(self.metadata["virtual_relations"]) != antes:
                self._save_virtual_relations()
                self.reindex()
                return True
            return False

    def upsert_metadata(self, nuevo: dict[str, Any]) -> int:
        """Reemplaza el catálogo (panel admin: cargar metadata)."""
        if "tables" not in nuevo:
            raise ValueError("El metadata debe incluir la clave 'tables'")
        with self._lock:
            nuevo.setdefault("relations", [])
            nuevo.setdefault("kpis", [])
            nuevo.setdefault("glosario", [])
            nuevo["virtual_relations"] = self.metadata.get("virtual_relations", [])
            self.metadata = nuevo
            return self.reindex()


_catalog: Catalog | None = None


def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog()
    return _catalog
