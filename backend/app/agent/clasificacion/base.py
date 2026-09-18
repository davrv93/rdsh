"""Contrato común de los motores de clasificación de intención.

Un motor traduce texto en español a una de las intenciones del catálogo. Puede
estar disponible o no (un modelo que no se descargó, una API sin credenciales) y
puede devolver poca confianza. La cadena decide qué hacer en cada caso.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Prediccion:
    """Lo que devuelve un motor cuando logra clasificar."""

    intent: str
    confidence: float
    scores: dict[str, float] = field(default_factory=dict)
    detalle: str = ""


@dataclass
class IntentoMotor:
    """Registro de lo que pasó con un motor, se haya usado o no.

    Es lo que permite explicar en el panel de pasos por qué respondió uno y no
    otro, y medir en producción cuántas veces hace falta el respaldo.
    """

    motor: str
    estado: str  # aceptado | baja_confianza | no_disponible | error | no_ejecutado
    intent: str | None = None
    confidence: float = 0.0
    latency_ms: float = 0.0
    detalle: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "motor": self.motor,
            "estado": self.estado,
            "intent": self.intent,
            "confidence": round(self.confidence, 4),
            "latency_ms": round(self.latency_ms, 3),
            "detalle": self.detalle,
        }


class MotorClasificacion(Protocol):
    """Interfaz que implementa cada motor."""

    nombre: str

    def disponible(self) -> bool:
        """False si falta el modelo, la credencial o la dependencia."""

    def clasificar(self, texto: str) -> Prediccion:
        """Clasifica o lanza una excepción; la cadena la captura y sigue."""

    def info(self) -> dict[str, Any]:
        """Datos para el panel de administración."""


class MotorBase:
    """Implementación parcial: mide la latencia y normaliza la información."""

    nombre = "base"
    descripcion = ""

    def disponible(self) -> bool:  # pragma: no cover - lo redefine cada motor
        return True

    def clasificar(self, texto: str) -> Prediccion:  # pragma: no cover
        raise NotImplementedError

    def info(self) -> dict[str, Any]:
        return {"motor": self.nombre, "descripcion": self.descripcion,
                "disponible": self.disponible()}

    def medir(self, texto: str) -> tuple[Prediccion, float]:
        inicio = time.perf_counter()
        prediccion = self.clasificar(texto)
        return prediccion, (time.perf_counter() - inicio) * 1000
