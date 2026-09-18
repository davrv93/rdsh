"""Log de auditoría append-only en JSONL."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from ..config import DATA_DIR

AUDIT_FILE = DATA_DIR / "audit.jsonl"
_lock = threading.Lock()


def registrar(evento: str, payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    linea = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "evento": evento,
        **payload,
    }
    with _lock:
        with AUDIT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(linea, ensure_ascii=False, default=str) + "\n")


def leer(limite: int = 100) -> list[dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    with _lock:
        lineas = AUDIT_FILE.read_text(encoding="utf-8").strip().splitlines()
    salida = []
    for linea in lineas[-limite:]:
        try:
            salida.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return list(reversed(salida))
