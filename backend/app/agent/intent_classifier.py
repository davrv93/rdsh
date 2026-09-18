"""Clasificador edge de intención en español.

Requisitos: CPU, sin GPU, sin llamadas de red, latencia de milisegundos.

Backends:
  - `edge` (por defecto): regresión logística softmax sobre features hasheadas
    (palabra + n-gramas de carácter). Se entrena en proceso al arrancar
    (~50 ms) y clasifica en microsegundos. Pesos ~40 kB en memoria.
  - `transformers`: usa un modelo HuggingFace local (por ejemplo
    luigicfilho/intento-v1-edge o prudant/es_intent_classification) mapeando
    sus etiquetas al taxonomía de Optimiza. Si el modelo no está disponible
    localmente, degrada a `edge`.
  - `rules`: fallback por expresiones regulares, siempre disponible.

Todas las rutas devuelven la latencia medida para el panel de pasos.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..config import get_settings
from ..semantic.embeddings import normalizar, tokenizar
from .intent_data import ENTRENAMIENTO, EVALUACION, INTENCIONES

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


REGLAS: list[tuple[str, str]] = [
    (r"\b(export\w*|descarg\w*|csv|excel|baja[rt]|archivo)\b", "exportacion"),
    (r"\b(gr[aá]fic\w*|chart|plot\w*|visualiz\w*|grafica|diagrama|curva|barras|pastel|l[ií]neas)\b", "grafico"),
    (r"\b(compar\w*|versus|\bvs\b|contra|diferencia|crecimiento|vari[aá]\w*|cay[oó]|cayeron|subi[oó]|respecto)\b", "comparacion"),
    (r"\b(qu[eé] tablas|qu[eé] columnas|cat[aá]logo|metadata|modelo de datos|qu[eé] datos|qu[eé] m[eé]tricas|explor\w*|listar tablas|qu[eé] campos|glosario)\b", "exploracion"),
    (r"\b(detalle|filas?|registros?|listado|listar|desglose|fila por fila|datos crudos|[uú]ltimas?)\b", "detalle"),
    (r"\b(total|suma|promedio|ticket promedio|kpi|ingreso|ventas|margen|roi|top \d+|ranking|cu[aá]nto|cu[aá]ntos|tasa|porcentaje)\b", "KPI"),
]

MAPA_ETIQUETAS_EXTERNAS = {
    "query": "KPI", "question": "KPI", "information_request": "KPI", "search": "exploracion",
    "explore": "exploracion", "compare": "comparacion", "comparison": "comparacion",
    "detail": "detalle", "list": "detalle", "chart": "grafico", "visualization": "grafico",
    "export": "exportacion", "download": "exportacion", "clarification": "aclaracion",
    "greeting": "aclaracion", "chitchat": "aclaracion", "unknown": "aclaracion",
    "out_of_scope": "aclaracion", "smalltalk": "aclaracion",
}


@dataclass
class IntentResult:
    intent: str
    confidence: float
    latency_ms: float
    backend: str
    scores: dict[str, float] = field(default_factory=dict)
    fallback_used: bool = False
    detalles: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 4),
            "latency_ms": round(self.latency_ms, 3),
            "backend": self.backend,
            "fallback_used": self.fallback_used,
            "scores": {k: round(v, 4) for k, v in sorted(
                self.scores.items(), key=lambda kv: kv[1], reverse=True)},
            "detalles": self.detalles,
        }


def _features(texto: str, dim: int = DIM) -> np.ndarray:
    """Vector disperso denso-izado: palabras, bigramas y n-gramas de carácter."""
    import hashlib

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


class EdgeIntentModel:
    """Softmax entrenado con descenso de gradiente. CPU puro, sin GPU."""

    backend = "edge-logreg-es"

    def __init__(self, epochs: int = 260, lr: float = 0.9, l2: float = 1e-4) -> None:
        self.labels = list(INTENCIONES)
        X = np.vstack([_features(f) for lbl in self.labels for f in ENTRENAMIENTO[lbl]])
        y = np.array(
            [self.labels.index(lbl) for lbl in self.labels for _ in ENTRENAMIENTO[lbl]]
        )
        Y = np.zeros((len(y), len(self.labels)), dtype=np.float32)
        Y[np.arange(len(y)), y] = 1.0
        rng = np.random.default_rng(7)
        W = rng.normal(0, 0.01, size=(DIM, len(self.labels))).astype(np.float32)
        t0 = time.perf_counter()
        for _ in range(epochs):
            logits = X @ W
            logits -= logits.max(axis=1, keepdims=True)
            p = np.exp(logits)
            p /= p.sum(axis=1, keepdims=True)
            grad = X.T @ (p - Y) / len(X) + l2 * W
            W -= lr * grad
        self.W = W
        self.train_ms = (time.perf_counter() - t0) * 1000
        self.train_accuracy = float((np.argmax(X @ W, axis=1) == y).mean())

    def predict(self, texto: str) -> tuple[str, float, dict[str, float]]:
        logits = _features(texto) @ self.W
        logits = logits - logits.max()
        p = np.exp(logits)
        p /= p.sum()
        idx = int(np.argmax(p))
        return self.labels[idx], float(p[idx]), {l: float(s) for l, s in zip(self.labels, p)}


def clasificar_por_reglas(texto: str) -> tuple[str, float, dict[str, float]]:
    plano = normalizar(texto)
    aciertos: dict[str, float] = {}
    for patron, intent in REGLAS:
        if re.search(patron, plano):
            aciertos[intent] = aciertos.get(intent, 0.0) + 1.0
    if len(plano.split()) <= 2 and not aciertos:
        return "aclaracion", 0.6, {"aclaracion": 0.6}
    if not aciertos:
        return "aclaracion", 0.4, {"aclaracion": 0.4}
    # Prioridad: exportación y gráfico ganan porque cambian el flujo de salida
    for preferida in ("exportacion", "grafico", "comparacion", "exploracion", "detalle", "KPI"):
        if preferida in aciertos:
            total = sum(aciertos.values())
            return preferida, min(0.95, 0.55 + aciertos[preferida] / (total + 1)), aciertos
    intent = max(aciertos, key=aciertos.get)
    return intent, 0.6, aciertos


class TransformersIntentModel:  # pragma: no cover - requiere modelo local
    def __init__(self, model_name: str) -> None:
        from transformers import pipeline

        self.backend = f"transformers::{model_name}"
        self._pipe = pipeline(
            "text-classification", model=model_name, device=-1, top_k=None
        )

    def predict(self, texto: str) -> tuple[str, float, dict[str, float]]:
        salida = self._pipe(texto)[0]
        scores: dict[str, float] = {}
        for item in salida:
            etiqueta = MAPA_ETIQUETAS_EXTERNAS.get(
                str(item["label"]).lower(), str(item["label"])
            )
            scores[etiqueta] = max(scores.get(etiqueta, 0.0), float(item["score"]))
        intent = max(scores, key=scores.get)
        if intent not in INTENCIONES:
            intent = "aclaracion"
        return intent, scores.get(intent, 0.0), scores


class IntentClassifier:
    """Fachada: elige backend, mide latencia y aplica el fallback por reglas."""

    UMBRAL_CONFIANZA = 0.22

    def __init__(self) -> None:
        settings = get_settings()
        self.configurado = settings.edge_backend.lower()
        self.model: Any = None
        self.backend = "rules"
        self.info: dict[str, Any] = {}
        if self.configurado == "transformers":
            try:
                self.model = TransformersIntentModel(settings.edge_model_name)
                self.backend = self.model.backend
            except Exception as exc:
                self.info["transformers_error"] = str(exc)[:200]
        if self.model is None and self.configurado in {"edge", "transformers"}:
            modelo = EdgeIntentModel()
            self.model = modelo
            self.backend = modelo.backend
            self.info.update(
                {
                    "train_ms": round(modelo.train_ms, 1),
                    "train_accuracy": round(modelo.train_accuracy, 4),
                    "params": int(modelo.W.size),
                }
            )

    def classify(self, texto: str) -> IntentResult:
        t0 = time.perf_counter()
        fallback = False
        limpio = limpiar_cortesia(texto)
        if self.model is None:
            intent, conf, scores = clasificar_por_reglas(limpio)
            backend = "rules"
            fallback = True
        else:
            try:
                intent, conf, scores = self.model.predict(limpio)
                backend = self.backend
                if conf < self.UMBRAL_CONFIANZA:
                    intent, conf, scores = clasificar_por_reglas(limpio)
                    backend = f"{self.backend}+rules"
                    fallback = True
            except Exception:
                intent, conf, scores = clasificar_por_reglas(limpio)
                backend = "rules"
                fallback = True

        # Guardia anti-aclaración: una pregunta con vocabulario analítico y
        # varias palabras no es una aclaración, aunque venga con saludo o typos.
        if intent == "aclaracion" and len(limpio.split()) >= 3 and VOCABULARIO_ANALITICO.search(limpio):
            intent_reglas, conf_reglas, scores_reglas = clasificar_por_reglas(limpio)
            if intent_reglas != "aclaracion":
                intent, conf, scores = intent_reglas, conf_reglas, scores_reglas
            else:
                intent, conf = "KPI", max(conf, 0.5)
            backend = f"{backend}+guardia"
            fallback = True

        latency_ms = (time.perf_counter() - t0) * 1000
        return IntentResult(
            intent=intent,
            confidence=conf,
            latency_ms=latency_ms,
            backend=backend,
            scores=scores,
            fallback_used=fallback,
            detalles={**self.info, "texto_normalizado": limpio} if limpio != texto.strip() else self.info,
        )

    def evaluate(self) -> dict[str, Any]:
        """Evalúa el clasificador contra el set independiente."""
        resultados = []
        for texto, esperado in EVALUACION:
            r = self.classify(texto)
            resultados.append(
                {
                    "texto": texto,
                    "esperado": esperado,
                    "obtenido": r.intent,
                    "ok": r.intent == esperado,
                    "latency_ms": round(r.latency_ms, 3),
                }
            )
        ok = sum(1 for r in resultados if r["ok"])
        return {
            "backend": self.backend,
            "accuracy": round(ok / len(resultados), 4),
            "intenciones_correctas": sorted({r["esperado"] for r in resultados if r["ok"]}),
            "latencia_media_ms": round(
                sum(r["latency_ms"] for r in resultados) / len(resultados), 3
            ),
            "casos": resultados,
        }


_classifier: IntentClassifier | None = None


def get_classifier() -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier
