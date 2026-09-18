"""Cadena de motores de clasificación con relevo.

La idea: no depender de un solo clasificador. Se prueban en orden y, antes de
dar por perdido a uno, se pasa al siguiente. Un motor cede el turno cuando:

  - no está disponible (falta el modelo, la credencial o la dependencia),
  - falla al ejecutarse,
  - o responde con menos confianza que su umbral.

El último motor de la cadena siempre acepta, para que el sistema nunca se quede
sin respuesta. Cada intento queda registrado, así que el panel de pasos puede
explicar quién respondió y por qué los anteriores cedieron.

Configuración (variables de entorno):

    INTENT_ENGINES=edge,transformers,reglas     orden de la cadena
    INTENT_MIN_CONFIDENCE=0.35                  umbral general
    INTENT_MIN_CONFIDENCE_EDGE=0.45             umbral de un motor concreto
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ...config import get_settings
from ..intent_data import INTENCIONES
from ..intent_utils import VOCABULARIO_ANALITICO, limpiar_cortesia
from .base import IntentoMotor, Prediccion
from .motores import MotorReglas, construir_motor

MOTOR_DE_ULTIMA_INSTANCIA = "reglas"


@dataclass
class ResultadoCadena:
    """Resultado final más la traza de todos los motores consultados."""

    intent: str
    confidence: float
    motor: str
    latency_ms: float
    scores: dict[str, float] = field(default_factory=dict)
    intentos: list[IntentoMotor] = field(default_factory=list)
    fallback_used: bool = False
    detalle: str = ""

    @property
    def relevos(self) -> int:
        """Cuántos motores cedieron el turno antes del que respondió."""
        return sum(1 for i in self.intentos if i.estado in {"baja_confianza", "error", "no_disponible"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 4),
            "motor": self.motor,
            "latency_ms": round(self.latency_ms, 3),
            "relevos": self.relevos,
            "fallback_used": self.fallback_used,
            "detalle": self.detalle,
            "intentos": [i.to_dict() for i in self.intentos],
            "scores": {k: round(v, 4) for k, v in sorted(
                self.scores.items(), key=lambda kv: kv[1], reverse=True)},
        }


class CadenaClasificadores:
    """Orquesta varios motores de clasificación con relevo y umbral por motor."""

    def __init__(self, nombres: list[str] | None = None,
                 umbral_general: float | None = None,
                 umbrales: dict[str, float] | None = None) -> None:
        settings = get_settings()
        self.umbral_general = (
            umbral_general if umbral_general is not None else settings.intent_min_confidence
        )
        self.umbrales = dict(umbrales or settings.intent_umbrales)
        self.errores_de_construccion: dict[str, str] = {}

        pedidos = nombres if nombres is not None else settings.intent_engines
        self.motores = []
        vistos: set[str] = set()
        for nombre in pedidos:
            try:
                motor = construir_motor(nombre)
            except Exception as exc:
                self.errores_de_construccion[nombre] = str(exc)[:200]
                continue
            if motor.nombre in vistos:
                continue
            vistos.add(motor.nombre)
            self.motores.append(motor)

        # Garantía de respuesta: las reglas cierran la cadena siempre.
        if MOTOR_DE_ULTIMA_INSTANCIA not in vistos:
            self.motores.append(MotorReglas())

    # ---------------- consulta ----------------
    @property
    def nombres(self) -> list[str]:
        return [m.nombre for m in self.motores]

    def umbral_de(self, motor: str) -> float:
        return self.umbrales.get(motor, self.umbral_general)

    def info(self) -> dict[str, Any]:
        return {
            "cadena": self.nombres,
            "umbral_general": self.umbral_general,
            "umbrales": self.umbrales,
            "motores": [
                {**m.info(), "umbral": self.umbral_de(m.nombre),
                 "ultima_instancia": m.nombre == MOTOR_DE_ULTIMA_INSTANCIA
                                     and m is self.motores[-1]}
                for m in self.motores
            ],
            "errores_de_construccion": self.errores_de_construccion,
        }

    # ---------------- ejecución ----------------
    def clasificar(self, texto: str) -> ResultadoCadena:
        inicio = time.perf_counter()
        limpio = limpiar_cortesia(texto)
        intentos: list[IntentoMotor] = []

        for posicion, motor in enumerate(self.motores):
            ultimo = posicion == len(self.motores) - 1

            try:
                if not motor.disponible():
                    intentos.append(IntentoMotor(motor.nombre, "no_disponible",
                                                 detalle="el motor no está listo en este entorno"))
                    continue
            except Exception as exc:
                intentos.append(IntentoMotor(motor.nombre, "error", detalle=str(exc)[:160]))
                continue

            try:
                prediccion, ms = motor.medir(limpio)
            except Exception as exc:
                intentos.append(IntentoMotor(motor.nombre, "error", detalle=str(exc)[:160]))
                continue

            umbral = self.umbral_de(motor.nombre)
            if prediccion.confidence < umbral and not ultimo:
                intentos.append(IntentoMotor(
                    motor.nombre, "baja_confianza", prediccion.intent, prediccion.confidence, ms,
                    f"confianza {prediccion.confidence:.2f} < umbral {umbral:.2f}",
                ))
                continue

            intentos.append(IntentoMotor(
                motor.nombre, "aceptado", prediccion.intent, prediccion.confidence, ms,
                prediccion.detalle,
            ))
            resultado = ResultadoCadena(
                intent=prediccion.intent,
                confidence=prediccion.confidence,
                motor=motor.nombre,
                latency_ms=(time.perf_counter() - inicio) * 1000,
                scores=prediccion.scores,
                intentos=intentos,
                fallback_used=posicion > 0,
                detalle=prediccion.detalle,
            )
            return self._guardia_aclaracion(resultado, limpio)

        # Ningún motor respondió: no debería ocurrir porque las reglas cierran la
        # cadena, pero si alguien la reconfigura mal, se responde con seguridad.
        return ResultadoCadena(
            intent="aclaracion", confidence=0.0, motor="ninguno",
            latency_ms=(time.perf_counter() - inicio) * 1000,
            intentos=intentos, fallback_used=True,
            detalle="ningún motor de la cadena pudo clasificar",
        )

    def _guardia_aclaracion(self, resultado: ResultadoCadena, texto: str) -> ResultadoCadena:
        """Una pregunta con vocabulario analítico no es una aclaración.

        Protege contra el caso "hola puedes decirme el meargen de categorias":
        cortesía más errores de tipeo empujaban la predicción hacia `aclaracion`.
        """
        if resultado.intent != "aclaracion":
            return resultado
        if len(texto.split()) < 3 or not VOCABULARIO_ANALITICO.search(texto):
            return resultado

        reglas = MotorReglas().clasificar(texto)
        if reglas.intent != "aclaracion":
            resultado.intent = reglas.intent
            resultado.confidence = max(resultado.confidence, reglas.confidence)
            resultado.scores = reglas.scores
        else:
            resultado.intent = "KPI"
            resultado.confidence = max(resultado.confidence, 0.5)
        resultado.motor = f"{resultado.motor}+guardia"
        resultado.fallback_used = True
        resultado.detalle = "la pregunta tiene vocabulario analítico: no es una aclaración"
        resultado.intentos.append(IntentoMotor(
            "guardia_analitica", "aceptado", resultado.intent, resultado.confidence, 0.0,
            "corrige una aclaración con vocabulario de negocio",
        ))
        return resultado

    def evaluar(self, casos: list[tuple[str, str]]) -> dict[str, Any]:
        """Corre un set de evaluación y resume acierto, latencia y uso de relevos."""
        resultados = []
        for texto, esperado in casos:
            r = self.clasificar(texto)
            resultados.append({
                "texto": texto, "esperado": esperado, "obtenido": r.intent,
                "ok": r.intent == esperado, "motor": r.motor,
                "latency_ms": round(r.latency_ms, 3), "relevos": r.relevos,
            })
        aciertos = sum(1 for r in resultados if r["ok"])
        por_motor: dict[str, int] = {}
        for r in resultados:
            por_motor[r["motor"]] = por_motor.get(r["motor"], 0) + 1
        return {
            "cadena": self.nombres,
            "accuracy": round(aciertos / len(resultados), 4) if resultados else 0.0,
            "latencia_media_ms": round(
                sum(r["latency_ms"] for r in resultados) / len(resultados), 3
            ) if resultados else 0.0,
            "resueltas_por_motor": por_motor,
            "intenciones_correctas": sorted({r["esperado"] for r in resultados if r["ok"]}),
            "casos": resultados,
        }


__all__ = ["CadenaClasificadores", "ResultadoCadena", "INTENCIONES", "Prediccion"]
