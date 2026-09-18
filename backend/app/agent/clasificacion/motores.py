"""Motores concretos de clasificación de intención.

Cada uno resuelve el mismo problema con un compromiso distinto entre latencia,
precisión y dependencias:

  edge         modelo entrenado en proceso. Microsegundos, sin red ni GPU.
  transformers modelo HuggingFace local. Más preciso, arranque más lento.
  llm          modelo remoto. El más flexible, el más caro y el único con red.
  reglas       expresiones regulares. Siempre disponible, es el último recurso.
"""
from __future__ import annotations

import re
import time
from typing import Any

import numpy as np

from ...config import get_settings
from ...semantic.embeddings import normalizar
from ..intent_data import ENTRENAMIENTO, INTENCIONES
from ..intent_utils import DIM, VOCABULARIO_ANALITICO, caracteristicas, limpiar_cortesia
from .base import MotorBase, Prediccion

# ---------------------------------------------------------------- reglas
REGLAS: list[tuple[str, str]] = [
    (r"\b(export\w*|descarg\w*|csv|excel|baja[rt]|archivo)\b", "exportacion"),
    (r"\b(gr[aá]fic\w*|chart|plot\w*|visualiz\w*|grafica|diagrama|curva|barras|pastel|l[ií]neas)\b", "grafico"),
    (r"\b(compar\w*|versus|\bvs\b|contra|diferencia|crecimiento|vari[aá]\w*|cay[oó]|cayeron|subi[oó]|respecto)\b", "comparacion"),
    (r"\b(qu[eé] tablas|qu[eé] columnas|cat[aá]logo|metadata|modelo de datos|qu[eé] datos|qu[eé] m[eé]tricas|explor\w*|listar tablas|qu[eé] campos|glosario)\b", "exploracion"),
    (r"\b(detalle|filas?|registros?|listado|listar|desglose|fila por fila|datos crudos|[uú]ltimas?)\b", "detalle"),
    (r"\b(total|suma|promedio|ticket promedio|kpi|ingreso|ventas|margen|roi|top \d+|ranking|cu[aá]nto|cu[aá]ntos|tasa|porcentaje)\b", "KPI"),
]

PRIORIDAD_REGLAS = ("exportacion", "grafico", "comparacion", "exploracion", "detalle", "KPI")


class MotorReglas(MotorBase):
    """Expresiones regulares sobre el texto normalizado. Nunca falla."""

    nombre = "reglas"
    descripcion = "Expresiones regulares en español. Sin dependencias, siempre disponible."

    def disponible(self) -> bool:
        return True

    def clasificar(self, texto: str) -> Prediccion:
        plano = normalizar(texto)
        aciertos: dict[str, float] = {}
        for patron, intent in REGLAS:
            if re.search(patron, plano):
                aciertos[intent] = aciertos.get(intent, 0.0) + 1.0

        if not aciertos:
            if len(plano.split()) <= 2:
                return Prediccion("aclaracion", 0.6, {"aclaracion": 0.6}, "texto muy corto")
            return Prediccion("aclaracion", 0.4, {"aclaracion": 0.4}, "sin palabras reconocidas")

        total = sum(aciertos.values())
        for preferida in PRIORIDAD_REGLAS:
            if preferida in aciertos:
                confianza = min(0.95, 0.55 + aciertos[preferida] / (total + 1))
                return Prediccion(preferida, confianza, aciertos, "coincidencia por reglas")
        intent = max(aciertos, key=aciertos.get)
        return Prediccion(intent, 0.6, aciertos, "coincidencia por reglas")


# ---------------------------------------------------------------- edge
class MotorEdge(MotorBase):
    """Regresión logística softmax entrenada en proceso al arrancar.

    Ocupa ~14 000 parámetros, entrena en unos 20 ms y clasifica en microsegundos.
    Corre en CPU, sin red y sin GPU: es el motor por defecto.
    """

    nombre = "edge"
    descripcion = "Modelo local entrenado en proceso (numpy, CPU, sin red)."

    def __init__(self, epochs: int = 260, lr: float = 0.9, l2: float = 1e-4) -> None:
        self.labels = list(INTENCIONES)
        X = np.vstack([caracteristicas(f) for lbl in self.labels for f in ENTRENAMIENTO[lbl]])
        y = np.array([self.labels.index(lbl) for lbl in self.labels for _ in ENTRENAMIENTO[lbl]])
        Y = np.zeros((len(y), len(self.labels)), dtype=np.float32)
        Y[np.arange(len(y)), y] = 1.0
        rng = np.random.default_rng(7)
        W = rng.normal(0, 0.01, size=(DIM, len(self.labels))).astype(np.float32)
        inicio = time.perf_counter()
        for _ in range(epochs):
            logits = X @ W
            logits -= logits.max(axis=1, keepdims=True)
            p = np.exp(logits)
            p /= p.sum(axis=1, keepdims=True)
            grad = X.T @ (p - Y) / len(X) + l2 * W
            W -= lr * grad
        self.W = W
        self.train_ms = (time.perf_counter() - inicio) * 1000
        self.train_accuracy = float((np.argmax(X @ W, axis=1) == y).mean())

    def disponible(self) -> bool:
        return True

    def clasificar(self, texto: str) -> Prediccion:
        logits = caracteristicas(texto) @ self.W
        logits = logits - logits.max()
        p = np.exp(logits)
        p /= p.sum()
        idx = int(np.argmax(p))
        return Prediccion(
            self.labels[idx], float(p[idx]),
            {l: float(s) for l, s in zip(self.labels, p)},
            "softmax local",
        )

    def info(self) -> dict[str, Any]:
        return {
            **super().info(),
            "train_ms": round(self.train_ms, 1),
            "train_accuracy": round(self.train_accuracy, 4),
            "params": int(self.W.size),
        }


# ---------------------------------------------------------------- transformers
MAPA_ETIQUETAS_EXTERNAS = {
    "query": "KPI", "question": "KPI", "information_request": "KPI", "search": "exploracion",
    "explore": "exploracion", "compare": "comparacion", "comparison": "comparacion",
    "detail": "detalle", "list": "detalle", "chart": "grafico", "visualization": "grafico",
    "export": "exportacion", "download": "exportacion", "clarification": "aclaracion",
    "greeting": "aclaracion", "chitchat": "aclaracion", "unknown": "aclaracion",
    "out_of_scope": "aclaracion", "smalltalk": "aclaracion",
}


class MotorTransformers(MotorBase):
    """Modelo HuggingFace local, por ejemplo luigicfilho/intento-v1-edge."""

    nombre = "transformers"
    descripcion = "Modelo HuggingFace local en CPU. Requiere el paquete y el modelo descargado."

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or get_settings().edge_model_name
        self._pipe = None
        self.error: str | None = None

    def _cargar(self):
        if self._pipe is None and self.error is None:
            try:
                from transformers import pipeline

                self._pipe = pipeline(
                    "text-classification", model=self.model_name, device=-1, top_k=None
                )
            except Exception as exc:  # pragma: no cover - depende del entorno
                self.error = str(exc)[:200]
        return self._pipe

    def disponible(self) -> bool:
        return self._cargar() is not None

    def clasificar(self, texto: str) -> Prediccion:  # pragma: no cover - requiere modelo
        pipe = self._cargar()
        if pipe is None:
            raise RuntimeError(self.error or "modelo no disponible")
        salida = pipe(texto)[0]
        scores: dict[str, float] = {}
        for item in salida:
            etiqueta = MAPA_ETIQUETAS_EXTERNAS.get(str(item["label"]).lower(), str(item["label"]))
            scores[etiqueta] = max(scores.get(etiqueta, 0.0), float(item["score"]))
        intent = max(scores, key=scores.get) if scores else "aclaracion"
        if intent not in INTENCIONES:
            intent = "aclaracion"
        return Prediccion(intent, scores.get(intent, 0.0), scores, self.model_name)

    def info(self) -> dict[str, Any]:
        return {**super().info(), "modelo": self.model_name, "error": self.error}


# ---------------------------------------------------------------- LLM
class MotorLLM(MotorBase):
    """Clasificación con el LLM configurado. Solo se usa si hay credenciales.

    Es el motor más flexible y el único que sale a la red, así que va después de
    los locales: se paga solo cuando los demás no alcanzan.
    """

    nombre = "llm"
    descripcion = "Modelo de lenguaje remoto. Flexible, con costo y latencia de red."

    def disponible(self) -> bool:
        return get_settings().llm_enabled

    def clasificar(self, texto: str) -> Prediccion:  # pragma: no cover - requiere API
        import json

        import httpx

        settings = get_settings()
        instruccion = (
            "Clasifica la intención de la pregunta en una de estas categorías: "
            + ", ".join(INTENCIONES)
            + '. Responde solo con JSON: {"intent": "...", "confianza": 0.0}'
        )
        respuesta = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": 64,
                "system": instruccion,
                "messages": [{"role": "user", "content": texto}],
            },
            timeout=10.0,
        )
        respuesta.raise_for_status()
        cuerpo = respuesta.json()
        texto_salida = "".join(b.get("text", "") for b in cuerpo.get("content", []))
        datos = json.loads(re.search(r"\{.*\}", texto_salida, re.S).group())
        intent = datos.get("intent", "aclaracion")
        if intent not in INTENCIONES:
            intent = "aclaracion"
        confianza = float(datos.get("confianza", 0.7))
        return Prediccion(intent, confianza, {intent: confianza}, settings.anthropic_model)


# ---------------------------------------------------------------- registro
REGISTRO: dict[str, type] = {
    "edge": MotorEdge,
    "reglas": MotorReglas,
    "rules": MotorReglas,   # alias en inglés, por compatibilidad con la configuración previa
    "transformers": MotorTransformers,
    "llm": MotorLLM,
}


def construir_motor(nombre: str):
    clave = nombre.strip().lower()
    if clave not in REGISTRO:
        raise ValueError(
            f"Motor de clasificación desconocido: '{nombre}'. "
            f"Disponibles: {', '.join(sorted(set(REGISTRO)))}"
        )
    return REGISTRO[clave]()


__all__ = [
    "MotorEdge", "MotorReglas", "MotorTransformers", "MotorLLM",
    "REGISTRO", "construir_motor", "VOCABULARIO_ANALITICO", "limpiar_cortesia",
]
