"""Clasificador edge en español: precisión, cobertura de intenciones y latencia."""
from backend.app.agent.intent_classifier import (
    IntentClassifier,
    clasificar_por_reglas,
    get_classifier,
)
from backend.app.agent.intent_data import INTENCIONES


def test_evaluacion_alcanza_precision_alta():
    evaluacion = get_classifier().evaluate()
    assert evaluacion["accuracy"] >= 0.75


def test_detecta_al_menos_cinco_intenciones_distintas():
    clasificador = get_classifier()
    frases = [
        "top 10 clientes por ingreso",
        "qué tablas tengo disponibles",
        "compara campañas por roi",
        "dame el detalle de las ventas de julio",
        "hazme un gráfico de ingreso por región",
        "exporta el resultado a csv",
        "hola",
    ]
    detectadas = {clasificador.classify(f).intent for f in frases}
    assert len(detectadas) >= 5
    assert detectadas <= set(INTENCIONES)


def test_latencia_edge_es_milisegundos():
    resultado = get_classifier().classify("ventas por mes")
    assert resultado.latency_ms < 50
    assert resultado.latency_ms > 0


def test_fallback_por_reglas_siempre_responde():
    intent, confianza, _ = clasificar_por_reglas("exporta esto a csv")
    assert intent == "exportacion"
    assert 0 < confianza <= 1


def test_configuracion_previa_de_un_solo_motor_sigue_funcionando(monkeypatch):
    """`EDGE_CLASSIFIER_BACKEND=rules` arma una cadena de un solo motor.

    Solo aplica cuando INTENT_ENGINES no está definido: esa variable manda.
    """
    monkeypatch.delenv("INTENT_ENGINES", raising=False)
    monkeypatch.setenv("EDGE_CLASSIFIER_BACKEND", "rules")
    from backend.app.config import reload_settings

    reload_settings()
    clasificador = IntentClassifier()
    assert clasificador.configurado == ["reglas"]
    assert clasificador.classify("dame un gráfico de ventas").intent == "grafico"
    monkeypatch.setenv("EDGE_CLASSIFIER_BACKEND", "edge")
    reload_settings()


def test_saludo_y_cortesia_no_convierten_una_pregunta_en_aclaracion():
    """Regresión: «hola puedes decirme el meargen de categorias?» caía en aclaracion."""
    clasificador = get_classifier()
    frases = [
        "hola puedes decirme el meargen de categorias?",
        "buenos días, dame el ingreso por región",
        "porfavor muestrame el ticket promedio por canal",
        "me puedes decir cuánto vendimos por canal",
    ]
    for frase in frases:
        assert clasificador.classify(frase).intent != "aclaracion", frase


def test_errores_de_tipeo_no_rompen_la_intencion():
    clasificador = get_classifier()
    for frase in ["meargen por categoria", "vantas por mes", "ingrso por region"]:
        assert clasificador.classify(frase).intent == "KPI", frase


def test_saludo_solo_sigue_siendo_aclaracion():
    clasificador = get_classifier()
    for frase in ["hola", "buenos días", "ayúdame", "hola quiero datos"]:
        assert clasificador.classify(frase).intent == "aclaracion", frase


def test_limpieza_de_cortesia():
    from backend.app.agent.intent_classifier import limpiar_cortesia

    assert limpiar_cortesia("hola puedes decirme el margen") == "el margen"
    assert limpiar_cortesia("hola") == "hola"  # sin resto, se conserva el texto
