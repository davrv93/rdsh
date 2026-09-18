"""Modelos de entrada/salida de la API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PreguntaRequest(BaseModel):
    pregunta: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    forzar_grafico: bool = False


class ConfirmarRelacionRequest(BaseModel):
    session_id: str
    aceptar: bool = True
    declarar: bool = False


class RelacionVirtualRequest(BaseModel):
    left: str
    right: str
    tipo: str = "many_to_one"
    nota: str = ""


class MetadataRequest(BaseModel):
    metadata: dict[str, Any]


class SyncRequest(BaseModel):
    tablas: list[str] | None = None
    incremental: bool = True


class RoutingRequest(BaseModel):
    routing: str = Field("auto", pattern="^(auto|redshift|cache)$")


class CadenaClasificacionRequest(BaseModel):
    motores: list[str] = Field(..., min_length=1)
    umbral: float | None = Field(None, ge=0.0, le=1.0)


class WhatsAppConfigRequest(BaseModel):
    url: str | None = None
    api_key: str | None = None
    instancia: str | None = None
    autorizados: list[str] | None = None
    base_publica: str | None = None
    url_webhook: str | None = None
    habilitado: bool | None = None


class WhatsAppPruebaRequest(BaseModel):
    texto: str = Field(..., min_length=1, max_length=2000)
    numero: str | None = None
    enviar: bool = False


class BusquedaSemanticaRequest(BaseModel):
    consulta: str
    k: int = 10
    tipos: list[str] | None = None
