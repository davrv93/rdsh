"""Clasificación de intención en español, con varios motores en cadena.

Este módulo es la fachada que usa el resto de la aplicación. La lógica vive en
`clasificacion/`:

    base.py      contrato de un motor y registro de cada intento
    motores.py   edge (local), transformers, llm y reglas
    cadena.py    relevo: si un motor no está, falla o duda, pasa al siguiente

Configuración:

    INTENT_ENGINES=edge,transformers,reglas   orden de la cadena
    INTENT_MIN_CONFIDENCE=0.35                umbral general
    INTENT_MIN_CONFIDENCE_EDGE=0.45           umbral de un motor concreto

Si no se define `INTENT_ENGINES`, la cadena se deriva de `EDGE_CLASSIFIER_BACKEND`
para respetar las configuraciones anteriores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .clasificacion.cadena import CadenaClasificadores
from .clasificacion.motores import MotorReglas
from .intent_data import EVALUACION, INTENCIONES
from .intent_utils import VOCABULARIO_ANALITICO, limpiar_cortesia

__all__ = [
    "IntentResult", "IntentClassifier", "get_classifier", "clasificar_por_reglas",
    "limpiar_cortesia", "INTENCIONES", "VOCABULARIO_ANALITICO",
]


@dataclass
class IntentResult:
    """Resultado de clasificar, con la traza de la cadena de motores."""

    intent: str
    confidence: float
    latency_ms: float
    backend: str
    scores: dict[str, float] = field(default_factory=dict)
    fallback_used: bool = False
    detalles: dict[str, Any] = field(default_factory=dict)
    motor: str = ""
    relevos: int = 0
    intentos: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 4),
            "latency_ms": round(self.latency_ms, 3),
            "backend": self.backend,
            "motor": self.motor,
            "relevos": self.relevos,
            "fallback_used": self.fallback_used,
            "intentos": self.intentos,
            "scores": {k: round(v, 4) for k, v in sorted(
                self.scores.items(), key=lambda kv: kv[1], reverse=True)},
            "detalles": self.detalles,
        }


def clasificar_por_reglas(texto: str) -> tuple[str, float, dict[str, float]]:
    """Clasificación por expresiones regulares, sin pasar por la cadena."""
    prediccion = MotorReglas().clasificar(limpiar_cortesia(texto))
    return prediccion.intent, prediccion.confidence, prediccion.scores


class IntentClassifier:
    """Fachada sobre la cadena de motores."""

    def __init__(self, motores: list[str] | None = None) -> None:
        self.cadena = CadenaClasificadores(motores)

    # ---------------- compatibilidad ----------------
    @property
    def backend(self) -> str:
        """Descripción de la cadena, por ejemplo `edge→reglas`."""
        return "→".join(self.cadena.nombres)

    @property
    def configurado(self) -> list[str]:
        return self.cadena.nombres

    @property
    def info(self) -> dict[str, Any]:
        return self.cadena.info()

    # ---------------- uso ----------------
    def classify(self, texto: str) -> IntentResult:
        resultado = self.cadena.clasificar(texto)
        return IntentResult(
            intent=resultado.intent,
            confidence=resultado.confidence,
            latency_ms=resultado.latency_ms,
            backend=resultado.motor,
            scores=resultado.scores,
            fallback_used=resultado.fallback_used,
            detalles={"cadena": self.cadena.nombres, "detalle": resultado.detalle},
            motor=resultado.motor,
            relevos=resultado.relevos,
            intentos=[i.to_dict() for i in resultado.intentos],
        )

    def evaluate(self, casos: list[tuple[str, str]] | None = None) -> dict[str, Any]:
        evaluacion = self.cadena.evaluar(casos or EVALUACION)
        evaluacion["backend"] = self.backend
        return evaluacion


_classifier: IntentClassifier | None = None


def get_classifier() -> IntentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier


def reset_classifier() -> None:
    """Fuerza la reconstrucción de la cadena tras cambiar la configuración."""
    global _classifier
    _classifier = None
