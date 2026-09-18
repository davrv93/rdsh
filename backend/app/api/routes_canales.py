"""Canales de conversación además de la web. Hoy: WhatsApp vía Evolution API."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ..agent.orchestrator import get_orchestrator
from ..canales import whatsapp as wa
from ..config import get_settings, reload_settings
from ..security import audit
from .schemas import WhatsAppConfigRequest, WhatsAppPruebaRequest

log = logging.getLogger("optimiza.canales")

router = APIRouter(prefix="/api/canales", tags=["canales"])

MENSAJE_NO_AUTORIZADO = (
    "Este asistente responde solo a números autorizados. "
    "Si necesitas acceso, escribe al equipo de datos de Optimiza."
)


def _responder_en_segundo_plano(mensaje: wa.MensajeEntrante) -> None:
    """Consulta al agente y devuelve la respuesta por WhatsApp.

    Corre fuera del ciclo del webhook: Evolution reintenta si no recibe un 200
    rápido, y una consulta puede tardar más que ese margen.
    """
    settings = get_settings()
    cliente = wa.get_evolution()
    try:
        if not wa.numero_autorizado(mensaje.numero):
            audit.registrar("whatsapp_no_autorizado", {"numero": mensaje.numero[-4:]})
            cliente.enviar_texto(mensaje.numero, MENSAJE_NO_AUTORIZADO)
            return

        respuesta = get_orchestrator().preguntar(mensaje.texto, mensaje.session_id)
        texto = wa.formatear_para_whatsapp(respuesta, settings.public_base_url)
        cliente.enviar_texto(mensaje.numero, texto)
        audit.registrar("whatsapp_respondido", {
            "numero": mensaje.numero[-4:],
            "intent": respuesta["intencion"]["intent"],
            "filas": respuesta["total_filas"],
            "ms": respuesta["metricas"]["latencia_total_ms"],
        })
    except Exception as exc:  # pragma: no cover - depende del servicio externo
        log.warning("No se pudo responder por WhatsApp: %s", exc)
        audit.registrar("whatsapp_error", {"numero": mensaje.numero[-4:], "error": str(exc)[:200]})


@router.post("/whatsapp/webhook")
async def webhook(request: Request, tareas: BackgroundTasks) -> dict:
    """Recibe los eventos de Evolution API.

    Siempre responde 200: un error aquí haría que Evolution reintente el mismo
    mensaje una y otra vez.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True, "ignorado": "cuerpo no es JSON"}

    if not get_settings().whatsapp_enabled:
        return {"ok": True, "ignorado": "canal deshabilitado"}

    mensaje = wa.extraer_mensaje(payload)
    if mensaje is None:
        return {"ok": True, "ignorado": str(payload.get("event", "evento sin texto"))}

    audit.registrar("whatsapp_recibido", {
        "numero": mensaje.numero[-4:], "instancia": mensaje.instancia,
        "caracteres": len(mensaje.texto),
    })
    tareas.add_task(_responder_en_segundo_plano, mensaje)
    return {"ok": True, "encolado": mensaje.id_mensaje}


@router.get("/whatsapp/estado")
def estado() -> dict:
    """Estado del canal para el panel de configuración."""
    settings = get_settings()
    cliente = wa.get_evolution()
    salida: dict = {
        "habilitado": settings.whatsapp_enabled,
        "configurado": cliente.configurado,
        "url": cliente.url,
        "instancia": cliente.instancia,
        "autorizados": len(settings.whatsapp_autorizados),
        "base_publica": settings.public_base_url,
    }
    if not cliente.configurado:
        salida["motivo"] = "Falta EVOLUTION_URL o EVOLUTION_API_KEY"
        return salida
    try:
        salida["servicio"] = cliente.info()
    except Exception as exc:
        salida["servicio"] = {"error": str(exc)[:200]}
        return salida
    try:
        salida["sesion"] = cliente.estado().get("instance", {})
    except Exception as exc:
        salida["sesion"] = {"error": str(exc)[:200]}
    try:
        salida["webhook"] = cliente.ver_webhook()
    except Exception as exc:
        salida["webhook"] = {"error": str(exc)[:200]}
    return salida


@router.post("/whatsapp/instancia")
def crear_instancia() -> dict:
    """Crea la instancia si no existe y devuelve el QR para vincular el teléfono."""
    cliente = wa.get_evolution()
    try:
        try:
            datos = cliente.crear_instancia()
        except RuntimeError as exc:
            if "403" not in str(exc) and "already in use" not in str(exc):
                raise
            datos = cliente.conectar()   # la instancia ya existía
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

    qr = datos.get("qrcode") or datos
    audit.registrar("whatsapp_instancia", {"instancia": cliente.instancia})
    return {
        "ok": True,
        "instancia": cliente.instancia,
        "qr_base64": qr.get("base64"),
        "codigo": qr.get("code"),
        "estado": (datos.get("instance") or {}).get("status", "connecting"),
    }


@router.post("/whatsapp/configurar")
def configurar(req: WhatsAppConfigRequest) -> dict:
    """Aplica la configuración del canal sin reiniciar el servicio."""
    if req.url is not None:
        os.environ["EVOLUTION_URL"] = req.url
    if req.api_key:
        os.environ["EVOLUTION_API_KEY"] = req.api_key
    if req.instancia is not None:
        os.environ["EVOLUTION_INSTANCE"] = req.instancia
    if req.autorizados is not None:
        os.environ["WHATSAPP_AUTORIZADOS"] = ",".join(req.autorizados)
    if req.base_publica is not None:
        os.environ["PUBLIC_BASE_URL"] = req.base_publica
    if req.habilitado is not None:
        os.environ["WHATSAPP_ENABLED"] = "true" if req.habilitado else "false"

    reload_settings()
    wa.reset_evolution()
    cliente = wa.get_evolution()

    webhook_aplicado = None
    if req.url_webhook and cliente.configurado:
        try:
            webhook_aplicado = cliente.configurar_webhook(req.url_webhook)
        except RuntimeError as exc:
            webhook_aplicado = {"error": str(exc)[:200]}

    audit.registrar("whatsapp_configurado", {
        "instancia": cliente.instancia,
        "autorizados": len(get_settings().whatsapp_autorizados),
        "habilitado": get_settings().whatsapp_enabled,
    })
    return {"ok": True, "estado": estado(), "webhook": webhook_aplicado}


@router.post("/whatsapp/probar")
def probar(req: WhatsAppPruebaRequest) -> dict:
    """Ensaya el flujo completo sin depender de un teléfono vinculado.

    Con `enviar=false` (por defecto) devuelve el texto tal como saldría por
    WhatsApp; con `enviar=true` lo manda de verdad al número indicado.
    """
    settings = get_settings()
    respuesta = get_orchestrator().preguntar(req.texto, f"wa-prueba:{req.numero or 'demo'}")
    texto = wa.formatear_para_whatsapp(respuesta, settings.public_base_url)

    enviado = None
    if req.enviar:
        if not req.numero:
            raise HTTPException(400, "Para enviar de verdad hace falta un número")
        try:
            enviado = wa.get_evolution().enviar_texto(req.numero, texto)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    return {
        "ok": True,
        "texto": texto,
        "caracteres": len(texto),
        "intencion": respuesta["intencion"]["intent"],
        "filas": respuesta["total_filas"],
        "autorizado": wa.numero_autorizado(req.numero) if req.numero else None,
        "enviado": enviado,
    }
