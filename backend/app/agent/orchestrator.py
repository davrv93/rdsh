"""Orquestador del agente conversacional.

Flujo: clasificador edge -> retriever vectorial -> generación SQL (LLM o
planificador determinista) -> validación -> ejecución (Redshift o DuckDB) ->
transformación DuckDB -> visualización -> respuesta con pasos y tiempos.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from ..config import get_settings
from ..engines.duckdb_engine import QueryResult, get_duckdb
from ..engines.redshift_adapter import get_redshift
from ..security import audit
from ..security.pii import enmascarar_dataframe
from ..semantic.catalog import get_catalog
from . import chart, llm, presentacion
from .intent_classifier import get_classifier
from .validator import validar_sql
from .planner import Planner

MAX_FILAS_RESPUESTA = 500


@dataclass
class Paso:
    nombre: str
    detalle: str
    ms: float
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"nombre": self.nombre, "detalle": self.detalle, "ms": round(self.ms, 3), **({"extra": self.extra} if self.extra else {})}


class Cronometro:
    def __init__(self) -> None:
        self.pasos: list[Paso] = []
        self._t0 = time.perf_counter()

    def marcar(self, nombre: str, detalle: str, ms: float, **extra: Any) -> None:
        self.pasos.append(Paso(nombre, detalle, ms, extra))

    def medir(self, nombre: str, detalle: str):
        cronometro = self

        class _Ctx:
            def __enter__(self):
                self.t = time.perf_counter()
                return self

            def __exit__(self, *exc):
                cronometro.marcar(nombre, detalle, (time.perf_counter() - self.t) * 1000)
                return False

        return _Ctx()

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000


def _json_safe(df: pd.DataFrame, limite: int = MAX_FILAS_RESPUESTA) -> list[dict[str, Any]]:
    """Convierte el DataFrame a JSON puro (sin tipos numpy) para la API."""
    import json

    recorte = df.head(limite).copy()
    for col in recorte.columns:
        if pd.api.types.is_datetime64_any_dtype(recorte[col]):
            recorte[col] = recorte[col].dt.strftime("%Y-%m-%d")
    recorte = recorte.replace([np.inf, -np.inf], np.nan)
    recorte.columns = [str(c) for c in recorte.columns]
    return json.loads(recorte.to_json(orient="records", date_format="iso", default_handler=str))


def _to_native(valor: Any) -> Any:
    """Convierte recursivamente tipos numpy/pandas a tipos nativos de Python.

    Se aplica a toda la respuesta: los specs de gráfico y las métricas también
    pueden contener escalares numpy.
    """
    if isinstance(valor, dict):
        return {str(k): _to_native(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_to_native(v) for v in valor]
    if isinstance(valor, np.generic):
        return valor.item()
    if isinstance(valor, (pd.Timestamp, datetime, date)):
        return valor.isoformat()
    if valor is pd.NaT:
        return None
    if isinstance(valor, float) and pd.isna(valor):
        return None
    return valor


class Session:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.historial: list[dict[str, str]] = []
        self.ultimo_resultado: pd.DataFrame | None = None
        self.ultimo_sql: str = ""
        self.pendiente_join: dict[str, Any] | None = None
        self.creada = datetime.utcnow()


class Orchestrator:
    def __init__(self) -> None:
        self.catalog = get_catalog()
        self.duckdb = get_duckdb()
        self.redshift = get_redshift()
        self.classifier = get_classifier()
        self.sessions: dict[str, Session] = {}
        self.ultima_ruta: str = self.fuente_activa
        self.fecha_referencia = self._fecha_maxima()
        self.planner = Planner(self.catalog, self.fecha_referencia)

    def _fecha_maxima(self) -> date:
        """Usa la fecha máxima de los datos como 'hoy' para que 'este trimestre' tenga sentido."""
        try:
            valor = self.duckdb.execute("SELECT MAX(fecha) AS f FROM ventas").dataframe.iloc[0]["f"]
            return pd.Timestamp(valor).date()
        except Exception:
            return date.today()

    # ---------- sesiones ----------
    def session(self, session_id: str | None) -> Session:
        sid = session_id or str(uuid.uuid4())
        if sid not in self.sessions:
            self.sessions[sid] = Session(sid)
        return self.sessions[sid]

    # ---------- utilidades ----------
    @property
    def fuente_activa(self) -> str:
        settings = get_settings()
        if settings.use_redshift and self.redshift.available:
            return "redshift"
        return "duckdb_demo"

    def decidir_ruta(self, tablas: list[str]) -> tuple[str, str]:
        """Elige dónde ejecutar la consulta y explica por qué.

        - `duckdb_demo`: no hay Redshift configurado.
        - `duckdb_cache`: los datos ya están materializados y frescos en DuckDB.
        - `redshift`: se consulta el almacén directamente.
        """
        settings = get_settings()
        if self.fuente_activa != "redshift":
            return "duckdb_demo", "sin Redshift configurado: se usan los datos de demostración"

        from ..pipeline import sync

        routing = settings.query_routing.lower()
        en_cache = self.duckdb.tablas_en_cache()
        faltantes = [t for t in tablas if t not in en_cache]

        if routing == "redshift":
            return "redshift", "ruteo fijado a Redshift por configuración"
        if routing == "cache":
            if faltantes:
                return "redshift", (
                    "ruteo fijado a caché, pero faltan tablas materializadas: "
                    + ", ".join(faltantes)
                )
            return "duckdb_cache", "ruteo fijado a la caché local"
        # auto
        if faltantes:
            return "redshift", (
                "sin copia local de " + ", ".join(faltantes) + ": se consulta el almacén"
            )
        if sync.tablas_frescas(tablas):
            return "duckdb_cache", (
                f"copia local vigente (menos de {settings.cache_max_age_min} min)"
            )
        return "redshift", "la copia local está vencida: se refresca desde el almacén"

    def _ejecutar(self, sql: str, tablas: list[str], cronometro: Cronometro) -> QueryResult:
        settings = get_settings()
        ruta, motivo = self.decidir_ruta(tablas)

        if ruta == "redshift":
            try:
                resultado = self.redshift.execute(sql)
                cronometro.marcar(
                    "ejecucion_redshift",
                    f"Redshift en solo lectura, {resultado.rows} filas · {motivo}",
                    resultado.elapsed_ms, motor="redshift", ruta=ruta, motivo=motivo,
                )
                self.ultima_ruta = "redshift"
                return resultado
            except Exception as exc:
                cronometro.marcar("ejecucion_redshift", f"Falló Redshift: {exc}", 0.0,
                                  motor="redshift", error=str(exc)[:200])
                if not self.duckdb.tablas_en_cache() >= set(tablas):
                    raise
                ruta, motivo = "duckdb_cache", "respaldo tras el fallo de Redshift"

        resultado = self.duckdb.execute(sql, max_rows=settings.max_rows)
        etiqueta = {
            "duckdb_cache": "DuckDB sobre la copia materializada de Redshift",
            "duckdb_demo": "DuckDB con los datos de demostración",
        }[ruta]
        cronometro.marcar(
            "ejecucion_cache" if ruta == "duckdb_cache" else "ejecucion_duckdb",
            f"{etiqueta}, {resultado.rows} filas · {motivo}",
            resultado.elapsed_ms, motor="duckdb", ruta=ruta, motivo=motivo,
        )
        self.ultima_ruta = ruta
        return resultado

    def _enmascarar(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
        settings = get_settings()
        if not settings.mask_pii or df.empty:
            return df, []
        declaradas = {c.split(".")[-1] for c in self.catalog.pii_columns()}
        objetivo = [c for c in df.columns if str(c).lower() in declaradas or str(c).lower() in {"cliente", "email", "documento"}]
        return enmascarar_dataframe(df, objetivo)

    # ---------- rutas por intención ----------
    def _respuesta_aclaracion(self, pregunta: str, intencion, cronometro: Cronometro,
                              contexto) -> dict[str, Any]:
        sugerencias = []
        for res in contexto[:5]:
            meta = res.documento.metadata
            if res.documento.tipo == "kpi":
                sugerencias.append(f"¿Quieres ver el KPI **{meta['kpi']}**?")
            elif res.documento.tipo == "tabla":
                sugerencias.append(f"¿Te sirve explorar la tabla **{meta['tabla']}**?")
        if not sugerencias:
            sugerencias = [
                "Prueba: «ventas por mes»",
                "Prueba: «top 10 clientes por ingreso»",
                "Prueba: «compara campañas por ROI»",
            ]
        texto = (
            "Necesito un poco más de contexto para consultar los datos. "
            "No ejecuté SQL todavía.\n\n" + "\n".join(f"- {s}" for s in sugerencias[:4])
            + "\n\nDime la métrica, la dimensión y el periodo que te interesan."
        )
        return self._envolver(
            pregunta, intencion, cronometro, texto,
            estado="aclaracion", contexto=contexto,
        )

    def _respuesta_exploracion(self, pregunta: str, intencion, cronometro: Cronometro,
                               contexto) -> dict[str, Any]:
        plano = pregunta.lower()
        if any(p in plano for p in ["no relacionad", "sin relaci", "combinar", "cruzar", "unir"]):
            with cronometro.medir("analisis_relaciones", "Perfilado de claves candidatas en DuckDB"):
                candidatos = self.analizar_tablas_sin_relacion()
            lineas = ["Estas son las combinaciones posibles entre tablas que hoy no están relacionadas:", ""]
            for c in candidatos:
                izquierda = c["izquierda"].replace("_", " ").replace(".", " → ")
                derecha = c["derecha"].replace("_", " ").replace(".", " → ")
                if c["confiable"]:
                    lineas.append(
                        f"- **{izquierda}** con **{derecha}**: coinciden el "
                        f"{c['cobertura_izquierda']:.0%} de los valores. Se puede combinar con confianza, "
                        "si tú lo autorizas."
                    )
                else:
                    lineas.append(
                        f"- **{izquierda}** con **{derecha}**: solo coincide el "
                        f"{c['cobertura_izquierda']:.0%} de los valores. No es confiable, así que no la usaré."
                    )
            lineas.append("")
            lineas.append(
                "Nunca combino tablas por mi cuenta. Puedo mostrarte los datos por separado, o el "
                "equipo de datos puede dejar la relación declarada desde Configuración."
            )
            tabla = pd.DataFrame(candidatos)
            return self._envolver(
                pregunta, intencion, cronometro, "\n".join(lineas),
                estado="exploracion", contexto=contexto, dataframe=tabla,
            )

        NOMBRES_AMIGABLES = {
            "ventas": ("Ventas", "cada venta con su ingreso, costo, margen y unidades"),
            "clientes": ("Clientes", "quiénes compran, su segmento y su región"),
            "productos": ("Productos", "catálogo con categoría, costo y precio"),
            "campanias": ("Campañas de marketing", "inversión, canal y fechas de cada campaña"),
            "regiones": ("Regiones", "ciudades, países y zonas comerciales"),
            "dim_fechas": ("Calendario", "meses, trimestres y años para agrupar"),
            "tickets_soporte": ("Tickets de soporte", "reclamos, tiempos de respuesta y satisfacción"),
            "web_sessions": ("Sesiones web", "visitas, dispositivos y conversiones"),
        }
        lineas = ["Esta es la información que puedo consultar por ti:", ""]
        for tabla in self.catalog.tables:
            nombre, descripcion = NOMBRES_AMIGABLES.get(
                tabla["name"],
                (tabla["name"].replace("_", " ").capitalize(), tabla["description"].split(".")[0]),
            )
            registros = f"{tabla.get('row_estimate', 0):,}".replace(",", " ")
            aviso = " · todavía no se puede cruzar con las ventas" if tabla.get("orphan") else ""
            lineas.append(f"- **{nombre}**: {descripcion} (~{registros} registros){aviso}")
        lineas.append("")
        lineas.append(
            "**Indicadores listos para usar:** "
            + ", ".join(k["label"] for k in self.catalog.kpis)
            + "."
        )
        lineas.append("")
        lineas.append("Pregúntame por cualquiera de ellos, por periodo, cliente, producto, campaña o región.")
        resumen = pd.DataFrame(
            [
                {
                    "informacion": NOMBRES_AMIGABLES.get(t["name"], (t["name"], ""))[0],
                    "registros": t.get("row_estimate", 0),
                    "campos": len(t["columns"]),
                    "se_cruza_con_ventas": "sí" if not t.get("orphan", False) else "no",
                    "tabla_tecnica": t["name"],
                }
                for t in self.catalog.tables
            ]
        )
        return self._envolver(
            pregunta, intencion, cronometro, "\n".join(lineas),
            estado="exploracion", contexto=contexto, dataframe=resumen,
        )

    def _respuesta_exportacion(self, pregunta: str, intencion, cronometro: Cronometro,
                               contexto, sesion: Session) -> dict[str, Any]:
        """Exporta el último resultado de la sesión sin volver a consultar la base."""
        df = sesion.ultimo_resultado
        with cronometro.medir("preparacion_csv", "Serializando el último resultado a CSV"):
            filas = len(df)
        visual = chart.elegir_grafico(df, "ranking", "exportacion", "")
        texto = (
            f"Tu archivo está listo: **{filas} registros** y {len(df.columns)} columnas. "
            "No volví a consultar la base de datos: reutilicé el último resultado."
        )
        return self._envolver(
            pregunta, intencion, cronometro, texto, estado="ok", contexto=contexto,
            sql=sesion.ultimo_sql, dataframe=df, visual=visual,
            tarjetas=chart.tarjetas_kpi(df, "", "number"),
            exportacion={"disponible": True, "url": f"/api/export/{sesion.id}.csv", "filas": filas},
            sesion=sesion, resumen=[texto],
        )

    def analizar_tablas_sin_relacion(self) -> list[dict[str, Any]]:
        """Perfila claves candidatas entre tablas huérfanas y el modelo principal."""
        candidatos: list[dict[str, Any]] = []
        huerfanas = [t for t in self.catalog.tables if t.get("orphan")]
        otras = [t for t in self.catalog.tables if not t.get("orphan")]
        for h in huerfanas:
            for col_h in h["columns"]:
                if col_h.get("role") not in {"dimension", "fk", "pk"}:
                    continue
                for o in otras:
                    for col_o in o["columns"]:
                        if col_o.get("role") not in {"pk", "dimension", "fk"}:
                            continue
                        if self.catalog.relation_between(h["name"], o["name"]):
                            continue
                        nombres_parecidos = (
                            col_h["name"].split("_")[0] in col_o["name"]
                            or col_o["name"].split("_")[0] in col_h["name"]
                        )
                        if not nombres_parecidos:
                            continue
                        try:
                            prueba = self.duckdb.probe_join_key(
                                h["name"], col_h["name"], o["name"], col_o["name"]
                            )
                        except Exception:
                            continue
                        if prueba["valores_comunes"] > 0 or prueba["cobertura_izquierda"] > 0:
                            candidatos.append(prueba)
        candidatos.sort(key=lambda c: c["cobertura_izquierda"], reverse=True)
        return candidatos[:10]

    def _respuesta_join_faltante(self, pregunta: str, intencion, cronometro: Cronometro,
                                 plan, contexto, sesion: Session) -> dict[str, Any] | None:
        issue = plan.join_issue
        if not issue:
            return None
        tabla_a, tabla_b = issue["tablas"]
        with cronometro.medir("guardia_join", f"Buscando claves compatibles {tabla_a}/{tabla_b}"):
            candidatos = [
                c for c in self.analizar_tablas_sin_relacion()
                if {c["izquierda"].split(".")[0], c["derecha"].split(".")[0]} == {tabla_a, tabla_b}
            ]
        opciones = [
            {"accion": "separado", "texto": f"Mostrar {tabla_a} y {tabla_b} por separado"},
        ]
        detalle = ""
        if candidatos:
            mejor = candidatos[0]
            detalle = (
                f"\n\nDetecté una clave **compatible pero no declarada**: "
                f"`{mejor['izquierda']}` ↔ `{mejor['derecha']}` "
                f"(cobertura {mejor['cobertura_izquierda']:.0%}, cardinalidad {mejor['cardinalidad']}). "
                "No la uso sin tu confirmación."
            )
            opciones.append(
                {
                    "accion": "probar_relacion",
                    "texto": f"Probar la relación {mejor['izquierda']} = {mejor['derecha']}",
                    "relacion": {"left": mejor["izquierda"], "right": mejor["derecha"],
                                 "type": mejor["cardinalidad"]},
                }
            )
            sesion.pendiente_join = mejor
        texto = (
            f"No encontré una relación declarada entre **{tabla_a}** y **{tabla_b}**; "
            "puedo mostrar los datos por separado o probar una relación sugerida." + detalle
        )
        return self._envolver(
            pregunta, intencion, cronometro, texto, estado="necesita_confirmacion",
            contexto=contexto, opciones=opciones, plan=plan,
        )

    # ---------- flujo principal ----------
    def preguntar(self, pregunta: str, session_id: str | None = None,
                  forzar_grafico: bool = False) -> dict[str, Any]:
        settings = get_settings()
        cronometro = Cronometro()
        sesion = self.session(session_id)
        sesion.historial.append({"role": "user", "content": pregunta})

        # 1. Clasificador edge
        intencion = self.classifier.classify(pregunta)
        cronometro.marcar(
            "clasificador_edge",
            f"Intención «{intencion.intent}» (confianza {intencion.confidence:.2f}) "
            f"con backend {intencion.backend}",
            intencion.latency_ms,
            **intencion.to_dict(),
        )

        # 2. Retriever vectorial
        t0 = time.perf_counter()
        contexto = self.catalog.search(pregunta, k=12)
        cronometro.marcar(
            "retriever_vectorial",
            f"{len(contexto)} fragmentos recuperados de {self.catalog.store.size} documentos "
            f"({self.catalog.store.backend})",
            (time.perf_counter() - t0) * 1000,
            top=[{"id": r.documento.id, "score": round(r.score, 4)} for r in contexto[:5]],
        )

        if intencion.intent == "aclaracion":
            return self._respuesta_aclaracion(pregunta, intencion, cronometro, contexto)
        if intencion.intent == "exploracion":
            return self._respuesta_exploracion(pregunta, intencion, cronometro, contexto)
        if intencion.intent == "exportacion" and sesion.ultimo_resultado is not None:
            return self._respuesta_exportacion(pregunta, intencion, cronometro, contexto, sesion)

        # 3. Generación de SQL
        plan = self.planner.build(pregunta, intencion.intent, contexto)
        sql = plan.sql
        explicacion = plan.explicacion
        origen_sql = "planificador_determinista"
        costo_usd = 0.0
        tokens = {"input": 0, "output": 0}
        grafico_sugerido = ""

        if settings.llm_enabled:
            contexto_llm = llm.construir_contexto(self.catalog, contexto)
            resultado_llm = llm.generar_sql(
                pregunta, intencion.intent, contexto_llm, sesion.historial[:-1]
            )
            if resultado_llm.ok:
                sql = resultado_llm.sql
                explicacion = resultado_llm.explicacion or explicacion
                grafico_sugerido = resultado_llm.grafico_sugerido
                origen_sql = f"llm::{resultado_llm.modelo}"
                tokens = {"input": resultado_llm.input_tokens, "output": resultado_llm.output_tokens}
                costo_usd = llm.estimar_costo(resultado_llm.input_tokens, resultado_llm.output_tokens)
                cronometro.marcar(
                    "generacion_sql_llm", f"SQL generado por {resultado_llm.modelo}",
                    resultado_llm.latency_ms, tokens=tokens, costo_usd=costo_usd,
                )
            else:
                cronometro.marcar(
                    "generacion_sql_llm",
                    f"LLM no disponible ({resultado_llm.error}); uso el planificador determinista",
                    resultado_llm.latency_ms, error=resultado_llm.error,
                )
        cronometro.marcar(
            "generacion_sql", f"Plan: {plan.tipo_resultado} · origen {origen_sql}", 0.0,
            plan=plan.to_dict(),
        )

        # 3b. Guardia de joins no declarados
        faltante = self._respuesta_join_faltante(pregunta, intencion, cronometro, plan, contexto, sesion)
        if faltante:
            return faltante

        # 4. Validación
        t0 = time.perf_counter()
        estimaciones = {t["name"]: t.get("row_estimate", 0) for t in self.catalog.tables}
        permitidas = {t["name"] for t in self.catalog.tables}
        validacion = validar_sql(sql, permitidas, settings.max_rows, estimaciones)
        cronometro.marcar(
            "validacion_sql",
            "SQL válido" if validacion.ok else f"SQL rechazado: {'; '.join(validacion.errores)}",
            (time.perf_counter() - t0) * 1000,
            **validacion.to_dict(),
        )
        if not validacion.ok:
            audit.registrar("sql_rechazado", {"session": sesion.id, "sql": sql,
                                              "errores": validacion.errores})
            return self._envolver(
                pregunta, intencion, cronometro,
                "No puedo responder esa pregunta con una consulta segura. "
                "Reformúlala o pide ayuda al equipo de datos.",
                estado="error", contexto=contexto, sql=sql, plan=plan,
                texto_tecnico="El SQL generado no pasó la validación: "
                              + "; ".join(validacion.errores),
                resumen=["La consulta generada no pasó los controles de seguridad."],
            )
        sql = validacion.sql

        # 5. Ejecución (Redshift directo o copia materializada en DuckDB)
        try:
            resultado = self._ejecutar(sql, validacion.tablas, cronometro)
        except Exception as exc:
            audit.registrar("ejecucion_fallida", {"session": sesion.id, "sql": sql,
                                                  "error": str(exc)[:300]})
            detalle = str(exc).strip().splitlines()[0][:200]
            return self._envolver(
                pregunta, intencion, cronometro,
                "No pude obtener los datos en este momento. La fuente de información no "
                "respondió y no hay una copia local disponible. Vuelve a intentarlo en unos "
                "minutos o avisa al equipo de datos.",
                estado="error", contexto=contexto, sql=sql, plan=plan,
                texto_tecnico=f"Fallo al ejecutar la consulta: {detalle}",
                resumen=["La fuente de información no respondió."],
            )

        # 6. Transformación DuckDB (siempre, incluso si el origen fue Redshift)
        df = resultado.dataframe
        transformacion_aplicada = None
        if plan.transform_sql:
            try:
                transformado = self.duckdb.transform(df, plan.transform_sql)
                df = transformado.dataframe
                transformacion_aplicada = plan.transform_sql
                cronometro.marcar(
                    "transformacion_duckdb",
                    f"Transformación DuckDB aplicada ({len(df)} filas, "
                    f"{len(df.columns)} columnas)",
                    transformado.elapsed_ms, sql=plan.transform_sql,
                )
            except Exception as exc:
                cronometro.marcar("transformacion_duckdb", f"Transformación omitida: {exc}", 0.0)

        # 7. PII y visualización
        with cronometro.medir("enmascaramiento_pii", "Aplicando política de PII"):
            df, columnas_enmascaradas = self._enmascarar(df)

        t0 = time.perf_counter()
        visual = chart.elegir_grafico(df, plan.tipo_resultado, intencion.intent, plan.metrica_label)
        if plan.solo_tabla and not forzar_grafico:
            visual = {"tipo": "tabla", "motivo": "Pediste verlo como tabla."}
        if forzar_grafico or intencion.intent == "grafico":
            if visual["tipo"] in {"tabla", "ninguno", "kpi"} and len(df.columns) >= 2:
                visual = chart.elegir_grafico(df, "ranking", "grafico", plan.metrica_label)
        if grafico_sugerido:
            visual["sugerido_por_llm"] = grafico_sugerido
        tarjetas = chart.tarjetas_kpi(df, plan.metrica_label, plan.formato)
        cronometro.marcar(
            "visualizacion", f"Gráfico elegido: {visual['tipo']} — {visual.get('motivo', '')}",
            (time.perf_counter() - t0) * 1000,
        )

        sesion.ultimo_resultado = df
        sesion.ultimo_sql = sql
        audit.registrar(
            "consulta",
            {
                "session": sesion.id, "pregunta": pregunta, "intent": intencion.intent,
                "sql": sql, "fuente": self.fuente_activa, "filas": len(df),
                "ms_total": round(cronometro.total_ms, 1), "origen_sql": origen_sql,
                "pii_enmascarada": columnas_enmascaradas,
            },
        )

        resumen = presentacion.resumen_ejecutivo(plan, df, visual)
        texto = " ".join(resumen)
        texto_tecnico = self._redactar_respuesta(plan, df, explicacion, visual, intencion)
        exportacion = None
        if intencion.intent == "exportacion":
            exportacion = {"disponible": True, "url": f"/api/export/{sesion.id}.csv",
                           "filas": len(df)}
            texto += f" El archivo está listo para descargar: {len(df)} registros."

        return self._envolver(
            pregunta, intencion, cronometro, texto, estado="ok", contexto=contexto,
            sql=sql, plan=plan, dataframe=df, visual=visual, tarjetas=tarjetas,
            costo_usd=costo_usd, tokens=tokens, origen_sql=origen_sql,
            transformacion=transformacion_aplicada, validacion=validacion.to_dict(),
            exportacion=exportacion, pii=columnas_enmascaradas, sesion=sesion,
            truncado=resultado.truncated, resumen=resumen, texto_tecnico=texto_tecnico,
        )

    @staticmethod
    def _tipo_metrica(plan, df: pd.DataFrame) -> str | None:
        """Tipo de la métrica principal; en comparaciones vive como `<metrica>_actual`."""
        if plan is None:
            return None
        for candidata in (plan.metrica_label, f"{plan.metrica_label}_actual"):
            if candidata in df.columns:
                return presentacion.tipo_columna(candidata, df[candidata])
        return None

    def _redactar_respuesta(self, plan, df: pd.DataFrame, explicacion: str, visual,
                            intencion) -> str:
        if df.empty:
            return ("La consulta se ejecutó pero no devolvió filas. "
                    "Prueba ampliando el periodo o quitando filtros.")
        partes = [explicacion]
        numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        principal = plan.metrica_label if plan.metrica_label in df.columns else (
            numericas[0] if numericas else None
        )
        if principal:
            total = df[principal].sum()
            if plan.tipo_resultado == "serie":
                mejor = df.loc[df[principal].idxmax()]
                etiqueta = mejor.get("periodo", "")
                if isinstance(etiqueta, pd.Timestamp):
                    etiqueta = etiqueta.strftime("%Y-%m-%d")
                partes.append(
                    f"El total de {principal} en el periodo es {total:,.2f} y el pico está en "
                    f"{etiqueta} con {mejor[principal]:,.2f}."
                )
            elif plan.tipo_resultado == "ranking":
                categoricas = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
                if categoricas:
                    top = df.iloc[0]
                    partes.append(
                        f"Lidera **{top[categoricas[0]]}** con {top[principal]:,.2f} "
                        f"({top[principal] / total:.1%} del total mostrado)."
                    )
            elif plan.tipo_resultado == "comparacion" and "variacion_pct" in df.columns:
                caidas = df[df["variacion_pct"] < 0]
                partes.append(
                    f"{len(caidas)} de {len(df)} filas cayeron respecto al periodo anterior; "
                    f"la mayor caída es {df['variacion_pct'].min():.1%}."
                )
        partes.append(f"Visualización elegida: {visual['tipo']} ({visual.get('motivo', '')})")
        return " ".join(p for p in partes if p)

    def _envolver(self, pregunta: str, intencion, cronometro: Cronometro, texto: str,
                  estado: str, contexto, sql: str = "", plan=None,
                  dataframe: pd.DataFrame | None = None, visual=None, tarjetas=None,
                  costo_usd: float = 0.0, tokens=None, origen_sql: str = "",
                  transformacion: str | None = None, validacion=None, exportacion=None,
                  pii=None, opciones=None, sesion: Session | None = None,
                  truncado: bool = False, resumen: list[str] | None = None,
                  texto_tecnico: str = "") -> dict[str, Any]:
        settings = get_settings()
        df = dataframe if dataframe is not None else pd.DataFrame()
        intencion_dict = intencion.to_dict()
        intencion_dict["etiqueta"] = presentacion.intencion_negocio(intencion.intent)
        respuesta = {
            "session_id": sesion.id if sesion else None,
            "pregunta": pregunta,
            "estado": estado,
            "respuesta": texto,
            "resumen": resumen or [],
            "respuesta_tecnica": texto_tecnico,
            "titulo": presentacion.titulo_resultado(plan) if plan else "Resultado",
            "intencion": intencion_dict,
            "sql": sql,
            "plan": plan.to_dict() if plan else None,
            "explicacion_plan": plan.explicacion if plan else "",
            "transformacion_duckdb": transformacion,
            "validacion": validacion,
            "columnas": [str(c) for c in df.columns],
            "columnas_meta": presentacion.columnas_meta(df, self._tipo_metrica(plan, df)),
            "filas": _json_safe(df),
            "total_filas": int(len(df)),
            "truncado": truncado,
            "tarjetas_kpi": tarjetas or [],
            "grafico": visual,
            "opciones": opciones or [],
            "exportacion": exportacion,
            "pii_enmascarada": pii or [],
            "contexto_semantico": [
                {
                    "id": r.documento.id,
                    "tipo": r.documento.tipo,
                    "score": round(r.score, 4),
                    "score_vectorial": round(r.score_vectorial, 4),
                    "score_lexico": round(r.score_lexico, 4),
                    "texto": r.documento.texto[:160],
                }
                for r in contexto[:8]
            ],
            "pasos": [
                {**p.to_dict(), "titulo": presentacion.paso_negocio(p.nombre)[0],
                 "descripcion": presentacion.paso_negocio(p.nombre)[1]}
                for p in cronometro.pasos
            ],
            "metricas": {
                "latencia_total_ms": round(cronometro.total_ms, 2),
                "latencia_clasificador_ms": round(intencion.latency_ms, 3),
                "costo_llm_usd": costo_usd,
                "tokens": tokens or {"input": 0, "output": 0},
                "origen_sql": origen_sql or "n/a",
                "fuente": getattr(self, "ultima_ruta", self.fuente_activa),
                "fuente_configurada": self.fuente_activa,
                "modo_demo": getattr(self, "ultima_ruta", self.fuente_activa) == "duckdb_demo",
                "max_rows": settings.max_rows,
                "segundos": round(cronometro.total_ms / 1000, 3),
                "moneda": settings.currency_symbol,
                "fecha_datos": self.fecha_referencia.isoformat(),
            },
        }
        if sesion:
            sesion.historial.append({"role": "assistant", "content": texto})
        return _to_native(respuesta)

    # ---------- confirmación de relación sugerida ----------
    def confirmar_relacion(self, session_id: str, aceptar: bool,
                           declarar: bool = False) -> dict[str, Any]:
        sesion = self.session(session_id)
        pendiente = sesion.pendiente_join
        if not pendiente:
            return {"ok": False, "mensaje": "No hay ninguna relación pendiente en esta sesión."}
        if not aceptar:
            sesion.pendiente_join = None
            return {"ok": True, "mensaje": "De acuerdo: muestro los datos por separado, sin join."}
        if declarar:
            self.catalog.add_virtual_relation(
                pendiente["izquierda"], pendiente["derecha"], pendiente["cardinalidad"],
                nota="Confirmada por el usuario desde el chat",
            )
        sesion.pendiente_join = None
        return {
            "ok": True,
            "mensaje": (
                f"Relación {pendiente['izquierda']} = {pendiente['derecha']} "
                f"{'declarada como virtual' if declarar else 'aceptada para esta sesión'}. "
                "Vuelve a hacer la pregunta y la usaré."
            ),
            "relacion": pendiente,
        }


_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
