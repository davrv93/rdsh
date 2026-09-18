"""Canal de WhatsApp sobre Evolution API.

Evolution API expone WhatsApp como una API HTTP: se crea una instancia, se
escanea un QR con el teléfono y a partir de ahí se envían y reciben mensajes.
La aplicación le habla por REST y recibe los mensajes entrantes en un webhook.

Diseño:
  - La conversación de cada número es una sesión del agente (`wa:<número>`),
    así que el historial y la exportación funcionan igual que en la web.
  - Solo responden los números de la lista autorizada. Sin esa lista, cualquiera
    con el número del bot consultaría los datos de la empresa.
  - La respuesta se reescribe para texto plano: WhatsApp no tiene tarjetas,
    tablas ni paneles.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger("optimiza.whatsapp")

EVENTOS_POR_DEFECTO = ["MESSAGES_UPSERT", "CONNECTION_UPDATE", "QRCODE_UPDATED"]
MAX_CARACTERES = 3500
MAX_FILAS_TEXTO = 8


@dataclass
class MensajeEntrante:
    numero: str
    texto: str
    nombre: str = ""
    instancia: str = ""
    id_mensaje: str = ""

    @property
    def session_id(self) -> str:
        return f"wa:{self.numero}"


class EvolutionAPI:
    """Cliente mínimo de Evolution API v2."""

    def __init__(self, url: str | None = None, api_key: str | None = None,
                 instancia: str | None = None) -> None:
        settings = get_settings()
        self.url = (url or settings.evolution_url).rstrip("/")
        self.api_key = api_key or settings.evolution_api_key
        self.instancia = instancia or settings.evolution_instance

    @property
    def configurado(self) -> bool:
        return bool(self.url and self.api_key)

    def _cabeceras(self) -> dict[str, str]:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None,
               timeout: float = 15.0) -> dict[str, Any]:
        if not self.configurado:
            raise RuntimeError(
                "Evolution API no está configurada: define EVOLUTION_URL y EVOLUTION_API_KEY"
            )
        respuesta = httpx.request(
            metodo, f"{self.url}{ruta}", headers=self._cabeceras(), json=cuerpo, timeout=timeout
        )
        if respuesta.status_code >= 400:
            raise RuntimeError(f"Evolution API {respuesta.status_code}: {respuesta.text[:300]}")
        try:
            return respuesta.json()
        except ValueError:
            return {"respuesta": respuesta.text[:300]}

    # ---------------- estado e instancia ----------------
    def info(self) -> dict[str, Any]:
        return self._pedir("GET", "/", timeout=5.0)

    def estado(self) -> dict[str, Any]:
        """Estado de la sesión de WhatsApp: open, connecting o close."""
        return self._pedir("GET", f"/instance/connectionState/{self.instancia}", timeout=8.0)

    def crear_instancia(self) -> dict[str, Any]:
        return self._pedir("POST", "/instance/create", {
            "instanceName": self.instancia,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
        }, timeout=30.0)

    def conectar(self) -> dict[str, Any]:
        """Devuelve un QR nuevo para vincular el teléfono."""
        return self._pedir("GET", f"/instance/connect/{self.instancia}", timeout=30.0)

    def instancias(self) -> Any:
        return self._pedir("GET", "/instance/fetchInstances", timeout=8.0)

    # ---------------- webhook ----------------
    def configurar_webhook(self, url_webhook: str,
                           eventos: list[str] | None = None) -> dict[str, Any]:
        return self._pedir("POST", f"/webhook/set/{self.instancia}", {
            "webhook": {
                "enabled": True,
                "url": url_webhook,
                "webhookByEvents": False,
                "webhookBase64": False,
                "events": eventos or EVENTOS_POR_DEFECTO,
            }
        })

    def ver_webhook(self) -> dict[str, Any]:
        return self._pedir("GET", f"/webhook/find/{self.instancia}", timeout=8.0)

    # ---------------- envío ----------------
    def enviar_texto(self, numero: str, texto: str) -> dict[str, Any]:
        return self._pedir("POST", f"/message/sendText/{self.instancia}", {
            "number": solo_digitos(numero),
            "text": texto[:MAX_CARACTERES],
        }, timeout=20.0)


def solo_digitos(numero: str) -> str:
    """Normaliza el número: Evolution espera solo dígitos con código de país."""
    return re.sub(r"\D", "", str(numero or "")).lstrip("0")


def extraer_mensaje(payload: dict[str, Any]) -> MensajeEntrante | None:
    """Convierte el evento MESSAGES_UPSERT de Evolution en algo manejable.

    Devuelve None cuando el evento no es un mensaje de texto entrante: mensajes
    propios, estados de conexión, audios, imágenes o grupos.
    """
    evento = str(payload.get("event", "")).lower().replace(".", "_")
    if evento and evento != "messages_upsert":
        return None

    datos = payload.get("data") or {}
    if isinstance(datos, list):
        datos = datos[0] if datos else {}

    clave = datos.get("key") or {}
    if clave.get("fromMe"):
        return None

    remitente = str(clave.get("remoteJid") or "")
    if not remitente or "@g.us" in remitente:   # los grupos no se atienden
        return None

    mensaje = datos.get("message") or {}
    texto = (
        mensaje.get("conversation")
        or (mensaje.get("extendedTextMessage") or {}).get("text")
        or (mensaje.get("ephemeralMessage") or {}).get("message", {}).get("conversation")
        or ""
    ).strip()
    if not texto:
        return None

    return MensajeEntrante(
        numero=solo_digitos(remitente.split("@")[0]),
        texto=texto,
        nombre=str(datos.get("pushName") or ""),
        instancia=str(payload.get("instance") or ""),
        id_mensaje=str(clave.get("id") or ""),
    )


def numero_autorizado(numero: str) -> bool:
    """WhatsApp es un canal abierto: solo responden los números en la lista."""
    permitidos = get_settings().whatsapp_autorizados
    if not permitidos:
        return False
    limpio = solo_digitos(numero)
    return any(limpio.endswith(solo_digitos(p)) for p in permitidos)


def formatear_para_whatsapp(respuesta: dict[str, Any],
                            base_publica: str = "") -> str:
    """Reescribe la respuesta del agente como texto plano de WhatsApp.

    WhatsApp no tiene tarjetas ni tablas: se conserva la frase de negocio, se
    listan pocas filas y se ofrece el archivo para el detalle completo.
    """
    partes: list[str] = []

    # El resumen ya viene en lenguaje de negocio; **negrita** se escribe *así*
    texto = respuesta.get("respuesta", "")
    partes.append(re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto).strip())

    filas = respuesta.get("filas") or []
    columnas_meta = {c["nombre"]: c for c in respuesta.get("columnas_meta", [])}
    columnas = [c for c in respuesta.get("columnas", []) if c in columnas_meta]

    if filas and len(columnas) >= 2:
        dimension = next(
            (c for c in columnas if columnas_meta[c]["tipo"] in {"texto", "fecha"}), columnas[0]
        )
        medida = next(
            (c for c in columnas
             if columnas_meta[c]["tipo"] in {"moneda", "entero", "decimal", "porcentaje", "ratio"}),
            columnas[-1],
        )
        partes.append("")
        partes.append(f"*{columnas_meta[medida]['etiqueta']} por {columnas_meta[dimension]['etiqueta'].lower()}*")
        for fila in filas[:MAX_FILAS_TEXTO]:
            partes.append(f"• {fila.get(dimension, '—')}: {_valor(fila.get(medida), columnas_meta[medida]['tipo'], respuesta)}")
        if respuesta.get("total_filas", 0) > MAX_FILAS_TEXTO:
            partes.append(f"…y {respuesta['total_filas'] - MAX_FILAS_TEXTO} más.")

    opciones = respuesta.get("opciones") or []
    if opciones:
        partes.append("")
        partes.append("Responde con el número de la opción:")
        for i, opcion in enumerate(opciones, start=1):
            partes.append(f"{i}. {opcion['texto']}")

    exportacion = respuesta.get("exportacion")
    if exportacion and base_publica:
        partes.append("")
        partes.append(f"Descarga el detalle: {base_publica.rstrip('/')}{exportacion['url']}")

    metricas = respuesta.get("metricas") or {}
    if metricas.get("latencia_total_ms") is not None:
        partes.append("")
        partes.append(f"_Respuesta en {metricas['latencia_total_ms']:.0f} ms_")

    return "\n".join(partes)[:MAX_CARACTERES]


def _valor(valor: Any, tipo: str, respuesta: dict[str, Any]) -> str:
    """Formato de negocio en texto plano, coherente con la interfaz web."""
    moneda = (respuesta.get("metricas") or {}).get("moneda", "")
    if valor is None:
        return "sin dato"
    if tipo == "porcentaje":
        return f"{float(valor) * 100:,.1f} %".replace(",", " ")
    if tipo == "ratio":
        return f"{float(valor):,.2f}x"
    if tipo == "moneda":
        numero = float(valor)
        if abs(numero) >= 1_000_000:
            return f"{moneda} {numero / 1_000_000:,.1f} M".replace(",", " ")
        return f"{moneda} {numero:,.0f}".replace(",", " ")
    if tipo == "entero":
        return f"{int(valor):,}".replace(",", " ")
    if isinstance(valor, float):
        return f"{valor:,.2f}".replace(",", " ")
    return str(valor)


_cliente: EvolutionAPI | None = None


def get_evolution() -> EvolutionAPI:
    global _cliente
    if _cliente is None:
        _cliente = EvolutionAPI()
    return _cliente


def reset_evolution() -> None:
    global _cliente
    _cliente = None
