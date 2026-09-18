"""Pruebas de extremo a extremo de la API conversacional."""


def test_salud_modo_demo(client):
    datos = client.get("/api/salud").json()
    assert datos["ok"] is True
    assert datos["fuente"] == "duckdb_demo"
    assert datos["capa_semantica"]["documentos"] > 50


def test_pregunta_kpi_devuelve_tabla_y_grafico(client):
    r = client.post("/api/preguntar", json={"pregunta": "Muéstrame las ventas por mes",
                                            "session_id": "test-kpi"}).json()
    assert r["estado"] == "ok"
    assert r["intencion"]["intent"] in {"KPI", "grafico", "comparacion"}
    assert r["total_filas"] > 5
    assert r["grafico"]["tipo"] in {"linea", "barras"}
    assert "SELECT" in r["sql"].upper()
    assert r["metricas"]["latencia_clasificador_ms"] > 0


def test_pasos_incluyen_clasificador_y_transformacion(client):
    r = client.post("/api/preguntar", json={"pregunta": "Top 10 clientes por ingreso",
                                            "session_id": "test-pasos"}).json()
    nombres = [p["nombre"] for p in r["pasos"]]
    assert "clasificador_edge" in nombres
    assert "retriever_vectorial" in nombres
    assert "validacion_sql" in nombres
    assert "transformacion_duckdb" in nombres
    assert r["transformacion_duckdb"] and "OVER" in r["transformacion_duckdb"]


def test_aclaracion_no_ejecuta_sql(client):
    r = client.post("/api/preguntar", json={"pregunta": "ayúdame", "session_id": "test-acl"}).json()
    assert r["estado"] == "aclaracion"
    assert r["sql"] == ""
    assert r["total_filas"] == 0


def test_exploracion_de_tablas_sin_relacion(client):
    r = client.post("/api/preguntar",
                    json={"pregunta": "¿Qué tablas no relacionadas puedo combinar?",
                          "session_id": "test-expl"}).json()
    assert r["estado"] == "exploracion"
    assert "relación declarada" in r["respuesta"] or "relacion" in r["respuesta"].lower()
    assert r["sql"] == ""


def test_no_inventa_joins_sin_relacion_declarada(client):
    r = client.post("/api/preguntar",
                    json={"pregunta": "ingreso por motivo de ticket",
                          "session_id": "test-join"}).json()
    # O bien pide confirmación, o bien resuelve sin cruzar las tablas huérfanas.
    if r["estado"] == "necesita_confirmacion":
        assert any(o["accion"] == "separado" for o in r["opciones"])
    else:
        assert "tickets_soporte" not in r["sql"] or "ventas" not in r["sql"]


def test_exportacion_reutiliza_ultimo_resultado(client):
    client.post("/api/preguntar", json={"pregunta": "Top 5 productos por margen",
                                        "session_id": "test-export"})
    r = client.post("/api/preguntar", json={"pregunta": "exporta el resultado a csv",
                                            "session_id": "test-export"}).json()
    assert r["exportacion"]["disponible"] is True
    csv = client.get("/api/export/test-export.csv")
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert len(csv.text.splitlines()) > 1


def test_comparacion_de_periodos(client):
    r = client.post("/api/preguntar",
                    json={"pregunta": "¿Qué productos cayeron este trimestre?",
                          "session_id": "test-comp"}).json()
    assert r["estado"] == "ok"
    assert "variacion_pct" in r["columnas"]
    assert r["intencion"]["intent"] == "comparacion"


def test_pii_enmascarada_en_detalle(client):
    r = client.get("/api/admin/muestra/clientes").json()
    correos = [f["email"] for f in r["filas"]]
    assert all("*" in c for c in correos)


def test_comparativa_de_arquitecturas(client):
    c = client.get("/api/comparativa").json()
    assert c["tradicional"]["duracion_total_minutos"] > 60
    assert c["conversacional"]["latencia_dato_horas"] == 0


def test_admin_relacion_virtual_ciclo_completo(client):
    payload = {"left": "tickets_soporte.documento_cliente", "right": "clientes.documento",
               "tipo": "many_to_one", "nota": "test"}
    creada = client.post("/api/admin/relaciones", json=payload)
    assert creada.status_code == 200
    relaciones = client.get("/api/admin/relaciones").json()
    assert any(r["left"] == payload["left"] for r in relaciones["virtuales"])
    borrada = client.delete(
        f"/api/admin/relaciones?left={payload['left']}&right={payload['right']}"
    )
    assert borrada.status_code == 200


def test_endpoint_de_intencion(client):
    r = client.get("/api/intencion", params={"texto": "exporta a csv"}).json()
    assert r["intent"] == "exportacion"
    assert r["latency_ms"] < 50


def test_busqueda_semantica(client):
    r = client.post("/api/admin/buscar", json={"consulta": "ticket promedio", "k": 5}).json()
    assert len(r["resultados"]) == 5
    assert any("ticket" in x["texto"] for x in r["resultados"])


def test_respuesta_trae_capa_de_presentacion(client):
    r = client.post("/api/preguntar", json={"pregunta": "Ventas por mes",
                                            "session_id": "test-ux"}).json()
    assert r["titulo"]
    assert r["resumen"] and isinstance(r["resumen"], list)
    assert r["intencion"]["etiqueta"] == "Indicador"
    assert r["metricas"]["moneda"]
    assert r["metricas"]["segundos"] >= 0
    etiquetas = {c["nombre"]: c for c in r["columnas_meta"]}
    assert etiquetas["ingreso"]["etiqueta"] == "Ingreso"
    assert etiquetas["ingreso"]["tipo"] == "moneda"
    assert etiquetas["periodo"]["tipo"] == "fecha"


def test_resumen_ejecutivo_no_expone_sql(client):
    r = client.post("/api/preguntar", json={"pregunta": "Top 10 clientes por ingreso",
                                            "session_id": "test-ux2"}).json()
    texto = r["respuesta"].upper()
    for jerga in ["SELECT", "SUM(", "GROUP BY", "JOIN"]:
        assert jerga not in texto
    # El detalle técnico sigue disponible para el equipo de datos
    assert "SUM(" in r["respuesta_tecnica"] or "SELECT" in r["sql"].upper()


def test_pasos_tienen_titulo_y_descripcion_de_negocio(client):
    r = client.post("/api/preguntar", json={"pregunta": "Ventas por mes",
                                            "session_id": "test-ux3"}).json()
    paso = next(p for p in r["pasos"] if p["nombre"] == "clasificador_edge")
    assert paso["titulo"] == "Entendí tu pregunta"
    assert paso["descripcion"]


def test_ejemplos_tienen_titulo_de_negocio(client):
    preguntas = client.get("/api/ejemplos").json()["preguntas"]
    assert all("titulo" in p for p in preguntas)
    assert any(p.get("solo_experto") for p in preguntas)


def test_nombres_de_cliente_se_enmascaran_en_los_resultados(client):
    r = client.post("/api/preguntar", json={"pregunta": "Top 5 clientes por ingreso",
                                            "session_id": "test-pii"}).json()
    assert "cliente" in r["pii_enmascarada"]
    assert all("." in fila["cliente"] for fila in r["filas"])


def test_typo_en_la_dimension_devuelve_el_desglose(client):
    r = client.post("/api/preguntar", json={"pregunta": "e el ingreso por regino",
                                            "session_id": "test-typo"}).json()
    assert r["total_filas"] == 7
    assert r["grafico"]["tipo"] == "barras"
    assert "región" in r["titulo"].lower()


def test_error_de_ejecucion_se_explica_sin_jerga(client, monkeypatch):
    from backend.app.agent.orchestrator import get_orchestrator

    orquestador = get_orchestrator()
    original = orquestador._ejecutar

    def falla(*args, **kwargs):
        raise RuntimeError("connection refused to warehouse:5439")

    monkeypatch.setattr(orquestador, "_ejecutar", falla)
    try:
        r = client.post("/api/preguntar", json={"pregunta": "ventas por mes",
                                                "session_id": "test-err"}).json()
    finally:
        monkeypatch.setattr(orquestador, "_ejecutar", original)

    assert r["estado"] == "error"
    assert "connection refused" not in r["respuesta"]
    assert "connection refused" in r["respuesta_tecnica"]
