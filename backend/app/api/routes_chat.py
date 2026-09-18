"""Endpoints del chat conversacional."""
from __future__ import annotations

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agent.orchestrator import get_orchestrator
from .schemas import ConfirmarRelacionRequest, PreguntaRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/preguntar")
def preguntar(req: PreguntaRequest) -> dict:
    orquestador = get_orchestrator()
    return orquestador.preguntar(req.pregunta, req.session_id, req.forzar_grafico)


@router.post("/relacion/confirmar")
def confirmar_relacion(req: ConfirmarRelacionRequest) -> dict:
    return get_orchestrator().confirmar_relacion(req.session_id, req.aceptar, req.declarar)


@router.get("/historial/{session_id}")
def historial(session_id: str) -> dict:
    orquestador = get_orchestrator()
    if session_id not in orquestador.sessions:
        raise HTTPException(404, "Sesión no encontrada")
    sesion = orquestador.sessions[session_id]
    return {
        "session_id": session_id,
        "creada": sesion.creada.isoformat(),
        "mensajes": sesion.historial,
        "ultimo_sql": sesion.ultimo_sql,
    }


@router.get("/export/{session_id}.csv")
def exportar_csv(session_id: str) -> StreamingResponse:
    orquestador = get_orchestrator()
    sesion = orquestador.sessions.get(session_id)
    if not sesion or sesion.ultimo_resultado is None:
        raise HTTPException(404, "No hay resultados para exportar en esta sesión")
    buffer = io.StringIO()
    sesion.ultimo_resultado.to_csv(buffer, index=False)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="optimiza_{session_id[:8]}.csv"'},
    )
