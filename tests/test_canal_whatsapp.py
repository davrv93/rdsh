"""Canal de WhatsApp: extracción de mensajes, autorización y formato de salida."""
from __future__ import annotations

import pytest

from backend.app.canales import whatsapp as wa


def evento(texto="ventas por mes", numero="51999888777", propio=False, jid=None):
    return {
        "event": "messages.upsert",
        "instance": "optimiza",
        "data": {
            "key": {"remoteJid": jid or f"{numero}@s.whatsapp.net", "fromMe": propio, "id": "ID1"},
            "pushName": "David",
            "message": {"conversation": texto},
        },
    }


def test_extrae_un_mensaje_de_texto():
    mensaje = wa.extraer_mensaje(evento())
    assert mensaje is not None
    assert mensaje.numero == "51999888777"
    assert mensaje.texto == "ventas por mes"
    assert mensaje.session_id == "wa:51999888777"


def test_ignora_los_mensajes_propios():
    assert wa.extraer_mensaje(evento(propio=True)) is None


def test_ignora_los_grupos():
    assert wa.extraer_mensaje(evento(jid="12036304@g.us")) is None


def test_ignora_los_eventos_que_no_son_mensajes():
    assert wa.extraer_mensaje({"event": "connection.update", "data": {"state": "open"}}) is None


def test_ignora_los_mensajes_sin_texto():
    payload = evento()
    payload["data"]["message"] = {"imageMessage": {"caption": "una foto"}}
    assert wa.extraer_mensaje(payload) is None


def test_lee_el_texto_extendido():
    payload = evento()
    payload["data"]["message"] = {"extendedTextMessage": {"text": "top 10 clientes"}}
    assert wa.extraer_mensaje(payload).texto == "top 10 clientes"


def test_normaliza_el_numero():
    assert wa.solo_digitos("+51 999 888 777") == "51999888777"
    assert wa.solo_digitos("051999888777") == "51999888777"


def test_sin_lista_de_autorizados_el_canal_no_responde(monkeypatch):
    monkeypatch.setenv("WHATSAPP_AUTORIZADOS", "")
    from backend.app.config import reload_settings

    reload_settings()
    assert wa.numero_autorizado("51999888777") is False


def test_autoriza_solo_a_los_numeros_de_la_lista(monkeypatch):
    monkeypatch.setenv("WHATSAPP_AUTORIZADOS", "51999888777, +51 988 777 666")
    from backend.app.config import reload_settings

    reload_settings()
    assert wa.numero_autorizado("51999888777") is True
    assert wa.numero_autorizado("+51 988 777 666") is True
    assert wa.numero_autorizado("51111222333") is False
    monkeypatch.delenv("WHATSAPP_AUTORIZADOS")
    reload_settings()


RESPUESTA = {
    "respuesta": "Ingreso total: **S/ 121.8 millones**. Lidera **Trujillo**.",
    "columnas": ["region", "ingreso"],
    "columnas_meta": [
        {"nombre": "region", "etiqueta": "Región", "tipo": "texto"},
        {"nombre": "ingreso", "etiqueta": "Ingreso", "tipo": "moneda"},
    ],
    "filas": [{"region": "Trujillo", "ingreso": 21373334}, {"region": "Lima", "ingreso": 16963895}],
    "total_filas": 2,
    "metricas": {"moneda": "S/", "latencia_total_ms": 21.4},
    "exportacion": {"url": "/api/export/wa.csv", "disponible": True},
    "opciones": [],
}


def test_el_formato_de_whatsapp_usa_negritas_de_whatsapp():
    texto = wa.formatear_para_whatsapp(RESPUESTA)
    assert "*S/ 121.8 millones*" in texto
    assert "**" not in texto


def test_el_formato_lista_las_filas_como_viñetas():
    texto = wa.formatear_para_whatsapp(RESPUESTA)
    assert "• Trujillo: S/ 21.4 M" in texto
    assert "• Lima: S/ 17.0 M" in texto


def test_incluye_el_enlace_de_descarga_solo_si_hay_url_publica():
    assert "http" not in wa.formatear_para_whatsapp(RESPUESTA)
    con_url = wa.formatear_para_whatsapp(RESPUESTA, "https://optimiza.example.com")
    assert "https://optimiza.example.com/api/export/wa.csv" in con_url


def test_numera_las_opciones_cuando_el_agente_pide_confirmacion():
    respuesta = dict(RESPUESTA, opciones=[
        {"accion": "separado", "texto": "Mostrar por separado"},
        {"accion": "probar_relacion", "texto": "Probar la relación sugerida"},
    ])
    texto = wa.formatear_para_whatsapp(respuesta)
    assert "1. Mostrar por separado" in texto
    assert "2. Probar la relación sugerida" in texto


def test_el_mensaje_nunca_supera_el_limite_de_whatsapp():
    respuesta = dict(RESPUESTA, respuesta="x" * 9000)
    assert len(wa.formatear_para_whatsapp(respuesta)) <= wa.MAX_CARACTERES


def test_el_webhook_ignora_todo_si_el_canal_esta_apagado(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENABLED", "false")
    from backend.app.config import reload_settings

    reload_settings()
    r = client.post("/api/canales/whatsapp/webhook", json=evento()).json()
    assert r["ok"] is True
    assert r["ignorado"] == "canal deshabilitado"


def test_el_webhook_responde_200_aunque_el_cuerpo_sea_invalido(client):
    respuesta = client.post("/api/canales/whatsapp/webhook", content=b"no es json")
    assert respuesta.status_code == 200


def test_estado_del_canal_reporta_la_configuracion(client):
    estado = client.get("/api/canales/whatsapp/estado").json()
    assert "habilitado" in estado
    assert "instancia" in estado
    assert estado["autorizados"] >= 0


def test_la_previsualizacion_no_envia_nada(client):
    r = client.post("/api/canales/whatsapp/probar",
                    json={"texto": "ventas por mes", "enviar": False}).json()
    assert r["ok"] is True
    assert r["enviado"] is None
    assert r["caracteres"] > 0


def test_enviar_sin_numero_es_un_error_de_peticion(client):
    respuesta = client.post("/api/canales/whatsapp/probar",
                            json={"texto": "ventas por mes", "enviar": True})
    assert respuesta.status_code == 400
