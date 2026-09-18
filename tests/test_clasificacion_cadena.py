"""Cadena de motores de clasificación: relevo, umbrales y trazabilidad."""
from __future__ import annotations

import pytest

from backend.app.agent.clasificacion.base import Prediccion
from backend.app.agent.clasificacion.cadena import CadenaClasificadores
from backend.app.agent.clasificacion.motores import MotorReglas, construir_motor
from backend.app.agent.intent_data import EVALUACION


class MotorCaido:
    """Motor que siempre revienta, para probar el relevo por error."""

    nombre = "caido"

    def disponible(self): return True
    def medir(self, texto): raise RuntimeError("el modelo no cargó")
    def clasificar(self, texto): raise RuntimeError("el modelo no cargó")
    def info(self): return {"motor": self.nombre, "disponible": True}


class MotorAusente:
    """Motor que se declara no disponible, como un modelo sin descargar."""

    nombre = "ausente"

    def disponible(self): return False
    def medir(self, texto): raise AssertionError("no debería ejecutarse")
    def clasificar(self, texto): raise AssertionError("no debería ejecutarse")
    def info(self): return {"motor": self.nombre, "disponible": False}


class MotorDubitativo:
    """Motor que responde siempre con poca confianza."""

    nombre = "dubitativo"

    def disponible(self): return True
    def clasificar(self, texto): return Prediccion("detalle", 0.05, {"detalle": 0.05})
    def medir(self, texto): return self.clasificar(texto), 0.1
    def info(self): return {"motor": self.nombre, "disponible": True}


class MotorSeguro:
    """Motor que responde con mucha confianza."""

    nombre = "seguro"

    def disponible(self): return True
    def clasificar(self, texto): return Prediccion("exportacion", 0.99, {"exportacion": 0.99})
    def medir(self, texto): return self.clasificar(texto), 0.1
    def info(self): return {"motor": self.nombre, "disponible": True}


def cadena_con(*motores, umbral: float = 0.35) -> CadenaClasificadores:
    cadena = CadenaClasificadores([], umbral_general=umbral, umbrales={})
    cadena.motores = list(motores)
    return cadena


def test_intent_engines_manda_sobre_la_configuracion_anterior(monkeypatch):
    monkeypatch.setenv("INTENT_ENGINES", "reglas")
    monkeypatch.setenv("EDGE_CLASSIFIER_BACKEND", "edge")
    from backend.app.config import reload_settings

    reload_settings()
    assert CadenaClasificadores().nombres == ["reglas"]
    monkeypatch.delenv("INTENT_ENGINES")
    reload_settings()


def test_cadena_por_defecto_usa_el_motor_local_y_cierra_con_reglas():
    cadena = CadenaClasificadores()
    assert cadena.nombres[0] == "edge"
    assert cadena.nombres[-1] == "reglas"


def test_las_reglas_siempre_cierran_la_cadena_aunque_no_se_declaren():
    cadena = CadenaClasificadores(["edge"])
    assert cadena.nombres == ["edge", "reglas"]


def test_un_motor_desconocido_no_rompe_la_cadena():
    cadena = CadenaClasificadores(["inexistente", "edge"])
    assert cadena.nombres == ["edge", "reglas"]
    assert "inexistente" in cadena.errores_de_construccion


def test_releva_cuando_el_motor_falla():
    cadena = cadena_con(MotorCaido(), MotorSeguro())
    resultado = cadena.clasificar("exporta el resultado a csv")
    assert resultado.motor == "seguro"
    assert resultado.fallback_used is True
    assert resultado.intentos[0].estado == "error"
    assert "el modelo no cargó" in resultado.intentos[0].detalle


def test_releva_cuando_el_motor_no_esta_disponible():
    cadena = cadena_con(MotorAusente(), MotorSeguro())
    resultado = cadena.clasificar("descarga esto")
    assert resultado.motor == "seguro"
    assert resultado.intentos[0].estado == "no_disponible"


def test_releva_cuando_la_confianza_no_alcanza_el_umbral():
    cadena = cadena_con(MotorDubitativo(), MotorSeguro(), umbral=0.5)
    resultado = cadena.clasificar("exporta a csv")
    assert resultado.motor == "seguro"
    assert resultado.intentos[0].estado == "baja_confianza"
    assert "umbral" in resultado.intentos[0].detalle
    assert resultado.relevos == 1


def test_el_ultimo_motor_responde_aunque_dude():
    """Si nadie supera el umbral, el último acepta: siempre hay respuesta."""
    cadena = cadena_con(MotorDubitativo(), MotorDubitativo(), umbral=0.9)
    resultado = cadena.clasificar("algo")
    assert resultado.intent == "detalle"
    assert resultado.intentos[-1].estado == "aceptado"


def test_cadena_vacia_responde_pidiendo_aclaracion():
    cadena = cadena_con()
    resultado = cadena.clasificar("lo que sea")
    assert resultado.intent == "aclaracion"
    assert resultado.motor == "ninguno"


def test_umbral_por_motor_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("INTENT_MIN_CONFIDENCE_EDGE", "0.99")
    from backend.app.config import reload_settings

    reload_settings()
    cadena = CadenaClasificadores()
    assert cadena.umbral_de("edge") == 0.99
    resultado = cadena.clasificar("ventas por mes")
    assert resultado.motor == "reglas"
    assert resultado.intentos[0].estado == "baja_confianza"
    monkeypatch.delenv("INTENT_MIN_CONFIDENCE_EDGE")
    reload_settings()


def test_orden_configurable_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("INTENT_ENGINES", "reglas,edge")
    from backend.app.config import reload_settings

    reload_settings()
    assert CadenaClasificadores().nombres == ["reglas", "edge"]
    monkeypatch.delenv("INTENT_ENGINES")
    reload_settings()


def test_cada_intento_queda_registrado_para_el_panel():
    cadena = cadena_con(MotorCaido(), MotorAusente(), MotorSeguro())
    resultado = cadena.clasificar("descarga el csv")
    estados = [i.estado for i in resultado.intentos]
    assert estados == ["error", "no_disponible", "aceptado"]
    assert resultado.to_dict()["intentos"][2]["motor"] == "seguro"


def test_la_evaluacion_reporta_quien_resolvio_cada_caso():
    evaluacion = CadenaClasificadores().evaluar(EVALUACION)
    assert evaluacion["accuracy"] >= 0.75
    assert sum(evaluacion["resueltas_por_motor"].values()) == len(EVALUACION)


def test_guardia_analitica_corrige_la_aclaracion():
    """Cortesía más errores de tipeo no convierten una pregunta en aclaración."""
    cadena = CadenaClasificadores()
    resultado = cadena.clasificar("hola puedes decirme el meargen de categorias?")
    assert resultado.intent != "aclaracion"


def test_el_motor_de_reglas_no_necesita_dependencias():
    motor = construir_motor("reglas")
    assert isinstance(motor, MotorReglas)
    assert motor.disponible() is True
    assert motor.clasificar("exporta a csv").intent == "exportacion"


@pytest.mark.parametrize("alias", ["reglas", "rules", "edge", "llm", "transformers"])
def test_el_registro_acepta_los_alias_documentados(alias):
    assert construir_motor(alias) is not None
