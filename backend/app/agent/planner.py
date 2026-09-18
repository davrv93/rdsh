"""Planificador determinista de consultas (NL -> plan -> SQL).

Es el generador SQL por defecto: funciona sin LLM, sin red y sin GPU, lo que
permite que la demo corra en cualquier máquina. Cuando hay LLM configurado, el
orquestador intenta primero el LLM y usa este planificador como respaldo.

El plan se arma con:
  - la intención del clasificador edge,
  - el contexto recuperado por el retriever vectorial,
  - un analizador de expresiones temporales y de ranking en español.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..semantic.catalog import Catalog
from ..semantic.embeddings import normalizar, tokenizar

GRANOS = {
    "dia": ("day", "día"),
    "semana": ("week", "semana"),
    "mes": ("month", "mes"),
    "trimestre": ("quarter", "trimestre"),
    "anio": ("year", "año"),
}

PATRONES_GRANO = [
    (r"\b(por|cada|x)\s+d[ií]a\b|\bdiari[ao]\b", "dia"),
    (r"\b(por|cada|x)\s+semanas?\b|\bsemanal\b", "semana"),
    (r"\b(por|cada|x)\s+mes(es)?\b|\bmensual(es)?\b|\bmes a mes\b", "mes"),
    (r"\b(por|cada|x)\s+trimestres?\b|\btrimestral\b", "trimestre"),
    (r"\b(por|cada|x)\s+a[nñ]os?\b|\banual\b|\ba[nñ]o a a[nñ]o\b", "anio"),
]

# dimensión pedida -> (tabla, columna, etiqueta)
DIMENSIONES_TEXTO: list[tuple[str, tuple[str, str, str]]] = [
    (r"\bclientes?\b|\bcompradores?\b|\bcuentas?\b", ("clientes", "nombre", "cliente")),
    (r"\bsegmentos?\b", ("clientes", "segmento", "segmento")),
    (r"\bsubcategor[ií]as?\b", ("productos", "subcategoria", "subcategoria")),
    (r"\bcategor[ií]as?\b", ("productos", "categoria", "categoria")),
    (r"\bproductos?\b|\bsku\b|\bart[ií]culos?\b", ("productos", "nombre", "producto")),
    (r"\bcampa[nñ]as?\b", ("campanias", "nombre", "campania")),
    (r"\bregi[oó]n(es)?\b|\bciudad(es)?\b|\bzona\b|\bterritorio\b", ("regiones", "region", "region")),
    (r"\bpa[ií]s(es)?\b", ("regiones", "pais", "pais")),
    (r"\bcanal(es)?\s+de\s+contacto\b", ("tickets_soporte", "canal_contacto", "canal_contacto")),
    (r"\bcanal(es)?\b", ("ventas", "canal", "canal")),
    (r"\bmotivos?\b", ("tickets_soporte", "motivo", "motivo")),
    (r"\bdispositivos?\b", ("web_sessions", "dispositivo", "dispositivo")),
]

# Vocabulario para tolerar errores de tipeo: palabra escrita -> dimensión.
# El orden importa: "subcategoria" antes que "categoria".
VOCABULARIO_DIMENSIONES: list[tuple[str, tuple[str, str, str]]] = [
    ("cliente", ("clientes", "nombre", "cliente")),
    ("clientes", ("clientes", "nombre", "cliente")),
    ("comprador", ("clientes", "nombre", "cliente")),
    ("segmento", ("clientes", "segmento", "segmento")),
    ("subcategoria", ("productos", "subcategoria", "subcategoria")),
    ("categoria", ("productos", "categoria", "categoria")),
    ("producto", ("productos", "nombre", "producto")),
    ("productos", ("productos", "nombre", "producto")),
    ("articulo", ("productos", "nombre", "producto")),
    ("campania", ("campanias", "nombre", "campania")),
    ("campaña", ("campanias", "nombre", "campania")),
    ("campañas", ("campanias", "nombre", "campania")),
    ("region", ("regiones", "region", "region")),
    ("regiones", ("regiones", "region", "region")),
    ("ciudad", ("regiones", "region", "region")),
    ("zona", ("regiones", "region", "region")),
    ("territorio", ("regiones", "region", "region")),
    ("pais", ("regiones", "pais", "pais")),
    ("canal", ("ventas", "canal", "canal")),
    ("canales", ("ventas", "canal", "canal")),
    ("motivo", ("tickets_soporte", "motivo", "motivo")),
    ("dispositivo", ("web_sessions", "dispositivo", "dispositivo")),
]

# Vocabulario equivalente para las métricas.
VOCABULARIO_METRICAS: list[tuple[str, str]] = [
    ("ingreso", "ingreso_total"),
    ("ingresos", "ingreso_total"),
    ("venta", "ingreso_total"),
    ("ventas", "ingreso_total"),
    ("facturacion", "ingreso_total"),
    ("margen", "margen_total"),
    ("utilidad", "margen_total"),
    ("ganancia", "margen_total"),
    ("unidades", "unidades_vendidas"),
    ("cantidad", "unidades_vendidas"),
    ("ticket", "ticket_promedio"),
    ("roi", "roi_campania"),
    ("csat", "csat_promedio"),
    ("satisfaccion", "csat_promedio"),
    ("conversion", "tasa_conversion_web"),
]

# Palabras que piden explícitamente ver los datos como tabla
PIDE_TABLA = re.compile(r"\b(tabla|tablita|listado|planilla|cuadro|matriz)\b", re.I)


def _coincidencia_aproximada(tokens: list[str], vocabulario: list[tuple[str, Any]],
                             corte: float = 0.78) -> Any | None:
    """Tolera errores de tipeo: "regino" o "regin" siguen siendo "region".

    Se usa solo cuando la coincidencia exacta falló, para no cambiar el
    comportamiento de las preguntas bien escritas.
    """
    claves = [clave for clave, _ in vocabulario]
    mejor: tuple[float, Any] | None = None
    for token in tokens:
        if len(token) < 4:
            continue
        for candidata in difflib.get_close_matches(token, claves, n=3, cutoff=corte):
            puntaje = difflib.SequenceMatcher(None, token, candidata).ratio()
            if mejor is None or puntaje > mejor[0]:
                valor = next(v for k, v in vocabulario if k == candidata)
                mejor = (puntaje, valor)
    return mejor[1] if mejor else None


# KPI -> (tabla base, expresión SQL, etiqueta, formato)
METRICAS: dict[str, dict[str, Any]] = {
    "ingreso_total": {"tabla": "ventas", "expr": "SUM(ventas.ingreso)", "label": "ingreso", "formato": "currency"},
    "margen_total": {"tabla": "ventas", "expr": "SUM(ventas.margen)", "label": "margen", "formato": "currency"},
    "unidades_vendidas": {"tabla": "ventas", "expr": "SUM(ventas.unidades)", "label": "unidades", "formato": "number"},
    "ticket_promedio": {"tabla": "ventas", "expr": "SUM(ventas.ingreso) / NULLIF(COUNT(DISTINCT ventas.venta_id), 0)", "label": "ticket_promedio", "formato": "currency"},
    "margen_pct": {"tabla": "ventas", "expr": "SUM(ventas.margen) / NULLIF(SUM(ventas.ingreso), 0)", "label": "margen_pct", "formato": "percent"},
    "clientes_activos": {"tabla": "ventas", "expr": "COUNT(DISTINCT ventas.cliente_id)", "label": "clientes_activos", "formato": "number"},
    "csat_promedio": {"tabla": "tickets_soporte", "expr": "AVG(tickets_soporte.csat)", "label": "csat_promedio", "formato": "number"},
    "tasa_conversion_web": {"tabla": "web_sessions", "expr": "AVG(CASE WHEN web_sessions.convirtio THEN 1.0 ELSE 0.0 END)", "label": "tasa_conversion", "formato": "percent"},
    "roi_campania": {"tabla": "campanias", "expr": "ROI", "label": "roi", "formato": "ratio"},
}

PALABRAS_METRICA = [
    (r"\broi\b|\broas\b|\bretorno\b", "roi_campania"),
    (r"\bcsat\b|\bsatisfacci[oó]n\b", "csat_promedio"),
    (r"\bconversi[oó]n\b|\bconvirtieron\b|\btasa de conversi[oó]n\b", "tasa_conversion_web"),
    (r"\bticket promedio\b|\baov\b|\bvalor promedio\b", "ticket_promedio"),
    (r"\bmargen\s*%|\bporcentaje de margen\b|\brentabilidad\b", "margen_pct"),
    (r"\bmargen\b|\butilidad\b|\bganancia\b", "margen_total"),
    (r"\bunidades\b|\bcantidad\b|\bvolumen\b|\bpiezas\b", "unidades_vendidas"),
    (r"\bclientes activos\b|\bcu[aá]ntos clientes\b", "clientes_activos"),
    (r"\bingreso\w*\b|\bventas?\b|\bfacturaci[oó]n\b|\brevenue\b|\bvendimos\b|\bvendi[oó]\b", "ingreso_total"),
]

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


@dataclass
class Filtro:
    expresion: str
    descripcion: str
    tabla: str


@dataclass
class QueryPlan:
    intent: str
    metrica: str
    metrica_label: str
    formato: str
    dimension: tuple[str, str, str] | None
    grano: str | None
    filtros: list[Filtro] = field(default_factory=list)
    limite: int | None = None
    tablas: list[str] = field(default_factory=list)
    comparacion_temporal: bool = False
    solo_tabla: bool = False
    sql: str = ""
    transform_sql: str | None = None
    explicacion: str = ""
    joins: list[dict[str, Any]] = field(default_factory=list)
    join_issue: dict[str, Any] | None = None
    tipo_resultado: str = "agregado"  # agregado | serie | ranking | detalle | comparacion

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "metrica": self.metrica,
            "dimension": ".".join(self.dimension[:2]) if self.dimension else None,
            "grano_temporal": self.grano,
            "filtros": [f.descripcion for f in self.filtros],
            "limite": self.limite,
            "tablas": self.tablas,
            "tipo_resultado": self.tipo_resultado,
            "joins": self.joins,
            "join_issue": self.join_issue,
        }


class Planner:
    def __init__(self, catalog: Catalog, fecha_referencia: date | None = None) -> None:
        self.catalog = catalog
        self.hoy = fecha_referencia or date.today()

    # ---------------- análisis de la pregunta ----------------
    def detectar_grano(self, texto: str) -> str | None:
        plano = normalizar(texto)
        for patron, grano in PATRONES_GRANO:
            if re.search(patron, plano):
                return grano
        if re.search(r"\bevoluci[oó]n\b|\btendencia\b|\bhist[oó]ric[ao]\b|\bserie\b", plano):
            return "mes"
        return None

    def detectar_metrica(self, texto: str, contexto: list[Any]) -> str:
        plano = normalizar(texto)
        for patron, metrica in PALABRAS_METRICA:
            if re.search(patron, plano):
                return metrica
        aproximada = _coincidencia_aproximada(tokenizar(texto), VOCABULARIO_METRICAS)
        if aproximada:
            return aproximada
        # "los mejores clientes", "top productos": sin métrica explícita, el
        # negocio se refiere al ingreso, no a un conteo.
        if re.search(r"\b(mejores|top|peores|principales|ranking)\b", plano):
            return "ingreso_total"
        for res in contexto:
            if res.documento.tipo == "kpi":
                nombre = res.documento.metadata.get("kpi")
                if nombre in METRICAS:
                    return nombre
        return "ingreso_total"

    def detectar_dimension(self, texto: str, metrica: str) -> tuple[str, str, str] | None:
        plano = normalizar(texto)
        # Devuelve la dimensión aunque pertenezca a una tabla sin relación declarada:
        # build() detecta la falta de relación y el agente pide confirmación en vez
        # de descartar la dimensión en silencio.
        for patron, dim in DIMENSIONES_TEXTO:
            if re.search(patron, plano):
                return dim
        # La pregunta pudo venir con errores de tipeo: "por regino", "por categoia"
        return _coincidencia_aproximada(tokenizar(texto), VOCABULARIO_DIMENSIONES)

    def detectar_limite(self, texto: str) -> int | None:
        plano = normalizar(texto)
        m = re.search(r"\b(?:top|primeros?|mejores?|peores?|[uú]ltim[oa]s?)\s+(\d{1,3})\b", plano)
        if m:
            return int(m.group(1))
        if re.search(r"\btop\b|\branking\b|\bmejores\b|\bpeores\b", plano):
            return 10
        return None

    def detectar_filtros_tiempo(self, texto: str, columna_fecha: str) -> list[Filtro]:
        plano = normalizar(texto)
        filtros: list[Filtro] = []
        hoy = self.hoy

        m = re.search(r"\b(20\d{2})\b", plano)
        if m:
            anio = int(m.group(1))
            filtros.append(
                Filtro(
                    f"{columna_fecha} >= DATE '{anio}-01-01' AND {columna_fecha} <= DATE '{anio}-12-31'",
                    f"año {anio}",
                    columna_fecha.split(".")[0],
                )
            )
            return filtros

        m = re.search(r"[uú]ltim[oa]s?\s+(\d{1,2})\s+(meses|mes|semanas|semana|d[ií]as|d[ií]a)", plano)
        if m:
            cantidad, unidad = int(m.group(1)), m.group(2)
            unidad_sql = {"mes": "months", "meses": "months", "semana": "weeks",
                          "semanas": "weeks", "dia": "days", "día": "days",
                          "dias": "days", "días": "days"}[unidad]
            filtros.append(
                Filtro(
                    f"{columna_fecha} >= DATE '{hoy.isoformat()}' - INTERVAL '{cantidad} {unidad_sql}'",
                    f"últimos {cantidad} {unidad}",
                    columna_fecha.split(".")[0],
                )
            )
            return filtros

        for nombre, numero in MESES.items():
            if re.search(rf"\b{nombre}\b", plano):
                anio = hoy.year
                inicio = date(anio, numero, 1)
                fin = date(anio + (numero == 12), (numero % 12) + 1, 1)
                filtros.append(
                    Filtro(
                        f"{columna_fecha} >= DATE '{inicio}' AND {columna_fecha} < DATE '{fin}'",
                        f"{nombre} {anio}",
                        columna_fecha.split(".")[0],
                    )
                )
                return filtros

        if re.search(r"\beste trimestre\b|\btrimestre actual\b", plano):
            inicio = self._inicio_trimestre(hoy)
            filtros.append(
                Filtro(f"{columna_fecha} >= DATE '{inicio}'", "trimestre en curso", columna_fecha.split(".")[0])
            )
        elif re.search(r"\beste a[nñ]o\b|\ba[nñ]o actual\b|\bytd\b", plano):
            filtros.append(
                Filtro(
                    f"{columna_fecha} >= DATE '{date(hoy.year, 1, 1)}'",
                    f"año {hoy.year} a la fecha",
                    columna_fecha.split(".")[0],
                )
            )
        elif re.search(r"\bmes pasado\b|\bmes anterior\b", plano):
            primero = date(hoy.year, hoy.month, 1)
            anterior_fin = primero
            anterior_ini = date(primero.year - (primero.month == 1), ((primero.month - 2) % 12) + 1, 1)
            filtros.append(
                Filtro(
                    f"{columna_fecha} >= DATE '{anterior_ini}' AND {columna_fecha} < DATE '{anterior_fin}'",
                    "mes anterior",
                    columna_fecha.split(".")[0],
                )
            )
        return filtros

    @staticmethod
    def _inicio_trimestre(dia: date) -> date:
        return date(dia.year, 3 * ((dia.month - 1) // 3) + 1, 1)

    def detectar_filtros_categoricos(self, texto: str, tablas: set[str]) -> list[Filtro]:
        tokens = set(tokenizar(texto))
        filtros: list[Filtro] = []
        for tabla in self.catalog.tables:
            if tabla["name"] not in tablas:
                continue
            for col in tabla["columns"]:
                for valor in col.get("categorias", []):
                    vtokens = set(tokenizar(str(valor)))
                    if vtokens and vtokens <= tokens:
                        filtros.append(
                            Filtro(
                                f"{tabla['name']}.{col['name']} = '{valor}'",
                                f"{col['name']} = {valor}",
                                tabla["name"],
                            )
                        )
        return filtros

    # ---------------- construcción del plan ----------------
    def build(self, pregunta: str, intent: str, contexto: list[Any]) -> QueryPlan:
        metrica = self.detectar_metrica(pregunta, contexto)
        if metrica == "roi_campania":
            return self._plan_roi(pregunta, intent)

        dimension = self.detectar_dimension(pregunta, metrica)
        # Contar clientes y además agrupar por cliente no aporta nada: en ese
        # caso el usuario quiere el ingreso de cada cliente.
        if metrica == "clientes_activos" and dimension and dimension[0] == "clientes":
            metrica = "ingreso_total"
        meta = METRICAS[metrica]
        tabla_base = meta["tabla"]
        grano = self.detectar_grano(pregunta)
        # Si piden un gráfico pero no dicen de qué agruparlo, la lectura natural
        # es la evolución en el tiempo.
        if intent == "grafico" and not grano and not self.detectar_dimension(pregunta, metrica):
            grano = "mes"
        limite = self.detectar_limite(pregunta)
        columna_fecha = f"{tabla_base}.fecha"
        filtros = self.detectar_filtros_tiempo(pregunta, columna_fecha)

        tablas = {tabla_base}
        joins: list[dict[str, Any]] = []
        join_issue = None
        if dimension:
            tabla_dim = dimension[0]
            if tabla_dim != tabla_base:
                rel = self.catalog.relation_between(tabla_base, tabla_dim)
                if rel:
                    joins.append(rel)
                    tablas.add(tabla_dim)
                else:
                    join_issue = {
                        "tablas": [tabla_base, tabla_dim],
                        "motivo": "sin relación declarada entre las tablas requeridas",
                    }
                    dimension = None
        filtros += self.detectar_filtros_categoricos(pregunta, tablas)

        comparacion = intent == "comparacion" or bool(
            re.search(r"\bcay[oó]\b|\bcayeron\b|\bsubi[oó]\b|\bcrecimiento\b|\bvariaci[oó]n\b|\bvs\b|\bversus\b|\bcompar\w+", normalizar(pregunta))
        )

        if intent == "detalle":
            return self._plan_detalle(pregunta, tabla_base, dimension, filtros, joins, limite)
        if comparacion and dimension and not grano:
            return self._plan_comparacion_periodos(
                pregunta, metrica, meta, dimension, joins, filtros
            )

        plan = QueryPlan(
            intent=intent,
            metrica=metrica,
            metrica_label=meta["label"],
            formato=meta["formato"],
            dimension=dimension,
            grano=grano,
            filtros=filtros,
            limite=limite,
            tablas=sorted(tablas),
            joins=joins,
            join_issue=join_issue,
            solo_tabla=bool(PIDE_TABLA.search(pregunta)) and intent != "grafico",
        )
        self._sql_agregado(plan, meta, tabla_base)
        return plan

    # ---------------- generadores SQL ----------------
    def _from_clause(self, tabla_base: str, joins: list[dict[str, Any]]) -> str:
        sql = f"FROM {tabla_base}"
        for rel in joins:
            izq_t, izq_c = rel["left"].split(".")
            der_t, der_c = rel["right"].split(".")
            destino, cond = (der_t, f"{rel['left']} = {rel['right']}")
            if der_t == tabla_base:
                destino, cond = (izq_t, f"{rel['right']} = {rel['left']}")
            sql += f"\n  LEFT JOIN {destino} ON {cond}"
        return sql

    def _where_clause(self, filtros: list[Filtro]) -> str:
        if not filtros:
            return ""
        return "\nWHERE " + "\n  AND ".join(f.expresion for f in filtros)

    def _sql_agregado(self, plan: QueryPlan, meta: dict[str, Any], tabla_base: str) -> None:
        selects: list[str] = []
        grupos: list[str] = []
        if plan.grano:
            unidad = GRANOS[plan.grano][0]
            selects.append(f"CAST(date_trunc('{unidad}', {tabla_base}.fecha) AS DATE) AS periodo")
            grupos.append("1")
        if plan.dimension:
            tabla_dim, columna_dim, etiqueta = plan.dimension
            selects.append(f"{tabla_dim}.{columna_dim} AS {etiqueta}")
            grupos.append(str(len(selects)))
        selects.append(f"{meta['expr']} AS {meta['label']}")
        if plan.metrica in {"ingreso_total", "margen_total"}:
            selects.append("COUNT(*) AS ventas_contadas")

        sql = "SELECT " + ",\n       ".join(selects)
        sql += "\n" + self._from_clause(tabla_base, plan.joins)
        sql += self._where_clause(plan.filtros)
        if grupos:
            sql += "\nGROUP BY " + ", ".join(grupos)
            if plan.grano and not plan.dimension:
                sql += "\nORDER BY periodo"
                plan.tipo_resultado = "serie"
            else:
                sql += f"\nORDER BY {meta['label']} DESC"
                plan.tipo_resultado = "ranking" if not plan.grano else "serie"
            if plan.limite:
                sql += f"\nLIMIT {plan.limite}"
        else:
            plan.tipo_resultado = "agregado"
        plan.sql = sql
        plan.transform_sql = self._transform_para(plan, meta["label"])
        plan.explicacion = self._explicar(plan, meta)

    def _plan_comparacion_periodos(self, pregunta: str, metrica: str, meta: dict[str, Any],
                                   dimension: tuple[str, str, str], joins: list[dict[str, Any]],
                                   filtros: list[Filtro]) -> QueryPlan:
        """Compara el periodo actual contra el anterior por dimensión."""
        tabla_base = meta["tabla"]
        tabla_dim, columna_dim, etiqueta = dimension
        plano = normalizar(pregunta)
        if re.search(r"\btrimestre\b", plano):
            ini_actual = self._inicio_trimestre(self.hoy)
            ini_previo = self._inicio_trimestre(
                date(ini_actual.year, ini_actual.month - 1, 1) if ini_actual.month > 1
                else date(ini_actual.year - 1, 12, 1)
            )
            etiqueta_periodo = "trimestre"
        elif re.search(r"\ba[nñ]o\b", plano):
            ini_actual = date(self.hoy.year, 1, 1)
            ini_previo = date(self.hoy.year - 1, 1, 1)
            etiqueta_periodo = "año"
        else:
            ini_actual = date(self.hoy.year, self.hoy.month, 1)
            ini_previo = (
                date(ini_actual.year - 1, 12, 1) if ini_actual.month == 1
                else date(ini_actual.year, ini_actual.month - 1, 1)
            )
            etiqueta_periodo = "mes"

        medida = meta["expr"]
        agregada_actual = medida.replace(
            f"{tabla_base}.ingreso", f"CASE WHEN {tabla_base}.fecha >= DATE '{ini_actual}' THEN {tabla_base}.ingreso ELSE 0 END"
        ).replace(
            f"{tabla_base}.margen", f"CASE WHEN {tabla_base}.fecha >= DATE '{ini_actual}' THEN {tabla_base}.margen ELSE 0 END"
        ).replace(
            f"{tabla_base}.unidades", f"CASE WHEN {tabla_base}.fecha >= DATE '{ini_actual}' THEN {tabla_base}.unidades ELSE 0 END"
        )
        agregada_previa = medida.replace(
            f"{tabla_base}.ingreso", f"CASE WHEN {tabla_base}.fecha >= DATE '{ini_previo}' AND {tabla_base}.fecha < DATE '{ini_actual}' THEN {tabla_base}.ingreso ELSE 0 END"
        ).replace(
            f"{tabla_base}.margen", f"CASE WHEN {tabla_base}.fecha >= DATE '{ini_previo}' AND {tabla_base}.fecha < DATE '{ini_actual}' THEN {tabla_base}.margen ELSE 0 END"
        ).replace(
            f"{tabla_base}.unidades", f"CASE WHEN {tabla_base}.fecha >= DATE '{ini_previo}' AND {tabla_base}.fecha < DATE '{ini_actual}' THEN {tabla_base}.unidades ELSE 0 END"
        )

        sql = f"""WITH comparacion AS (
  SELECT {tabla_dim}.{columna_dim} AS {etiqueta},
         {agregada_actual} AS {meta['label']}_actual,
         {agregada_previa} AS {meta['label']}_anterior
  {self._from_clause(tabla_base, joins).strip()}
  WHERE {tabla_base}.fecha >= DATE '{ini_previo}'
  GROUP BY 1
)
SELECT {etiqueta},
       {meta['label']}_actual,
       {meta['label']}_anterior,
       {meta['label']}_actual - {meta['label']}_anterior AS variacion,
       ({meta['label']}_actual - {meta['label']}_anterior) / NULLIF({meta['label']}_anterior, 0) AS variacion_pct
FROM comparacion
WHERE {meta['label']}_anterior > 0
ORDER BY variacion_pct ASC
LIMIT 20"""

        plan = QueryPlan(
            intent="comparacion",
            metrica=metrica,
            metrica_label=meta["label"],
            formato=meta["formato"],
            dimension=dimension,
            grano=None,
            filtros=filtros,
            limite=20,
            tablas=sorted({tabla_base, tabla_dim}),
            joins=joins,
            comparacion_temporal=True,
            tipo_resultado="comparacion",
        )
        plan.sql = sql
        plan.transform_sql = f"""SELECT *,
       CASE WHEN variacion_pct < -0.05 THEN 'cayó'
            WHEN variacion_pct > 0.05 THEN 'creció'
            ELSE 'estable' END AS tendencia,
       ROW_NUMBER() OVER (ORDER BY variacion_pct ASC) AS ranking_caida
FROM _resultado
ORDER BY variacion_pct ASC"""
        plan.explicacion = (
            f"Comparo {meta['label']} por {etiqueta} entre el {etiqueta_periodo} en curso "
            f"(desde {ini_actual}) y el {etiqueta_periodo} anterior (desde {ini_previo}), "
            "usando agregación condicional en una sola pasada sobre la tabla de hechos."
        )
        return plan

    def _plan_roi(self, pregunta: str, intent: str) -> QueryPlan:
        filtros = self.detectar_filtros_tiempo(pregunta, "ventas.fecha")
        where = ("\n  WHERE " + " AND ".join(f.expresion for f in filtros)) if filtros else ""
        limite = self.detectar_limite(pregunta) or 20
        sql = f"""WITH ingresos_campania AS (
  SELECT ventas.campania_id,
         SUM(ventas.ingreso) AS ingreso,
         SUM(ventas.margen) AS margen,
         COUNT(*) AS ventas_atribuidas
  FROM ventas{where}
  GROUP BY 1
)
SELECT campanias.nombre AS campania,
       campanias.canal,
       campanias.tipo,
       campanias.inversion,
       COALESCE(ingresos_campania.ingreso, 0) AS ingreso,
       COALESCE(ingresos_campania.margen, 0) AS margen,
       (COALESCE(ingresos_campania.ingreso, 0) - campanias.inversion)
         / NULLIF(campanias.inversion, 0) AS roi
FROM campanias
  LEFT JOIN ingresos_campania ON campanias.campania_id = ingresos_campania.campania_id
ORDER BY roi DESC
LIMIT {limite}"""
        plan = QueryPlan(
            intent=intent,
            metrica="roi_campania",
            metrica_label="roi",
            formato="ratio",
            dimension=("campanias", "nombre", "campania"),
            grano=None,
            filtros=filtros,
            limite=limite,
            tablas=["campanias", "ventas"],
            joins=[{"left": "ventas.campania_id", "right": "campanias.campania_id",
                    "type": "many_to_one", "declared": True}],
            tipo_resultado="ranking",
        )
        plan.sql = sql
        plan.transform_sql = """SELECT campania, canal, tipo, inversion, ingreso, margen, roi,
       ROUND(roi * 100, 1) AS roi_pct,
       RANK() OVER (ORDER BY roi DESC) AS ranking,
       AVG(roi) OVER () AS roi_promedio,
       roi - AVG(roi) OVER () AS brecha_vs_promedio
FROM _resultado
ORDER BY roi DESC"""
        plan.explicacion = (
            "Calculo el ROI por campaña: agrego el ingreso atribuido en una CTE y lo comparo "
            "contra la inversión declarada de cada campaña. Se usa LEFT JOIN para no perder "
            "campañas sin ventas atribuidas."
        )
        return plan

    def _plan_detalle(self, pregunta: str, tabla_base: str, dimension, filtros, joins,
                      limite: int | None) -> QueryPlan:
        limite = limite or 50
        tabla = self.catalog.table(tabla_base)
        columnas = [f"{tabla_base}.{c['name']}" for c in tabla["columns"]][:10]
        if dimension:
            columnas.insert(1, f"{dimension[0]}.{dimension[1]} AS {dimension[2]}")
        sql = "SELECT " + ",\n       ".join(columnas)
        sql += "\n" + self._from_clause(tabla_base, joins)
        sql += self._where_clause(filtros)
        sql += f"\nORDER BY {tabla_base}.fecha DESC\nLIMIT {limite}"
        plan = QueryPlan(
            intent="detalle",
            metrica="detalle",
            metrica_label="filas",
            formato="number",
            dimension=dimension,
            grano=None,
            filtros=filtros,
            limite=limite,
            tablas=sorted({tabla_base} | ({dimension[0]} if dimension else set())),
            joins=joins,
            tipo_resultado="detalle",
        )
        plan.sql = sql
        plan.transform_sql = "SELECT * FROM _resultado"
        plan.explicacion = (
            f"Devuelvo el detalle fila a fila de {tabla_base} con las columnas más relevantes, "
            f"ordenado por fecha descendente y limitado a {limite} filas."
        )
        return plan

    # ---------------- transformación DuckDB ----------------
    def _transform_para(self, plan: QueryPlan, label: str) -> str:
        """SQL de transformación ejecutado SIEMPRE en DuckDB sobre el resultado."""
        if plan.tipo_resultado == "serie" and not plan.dimension:
            return f"""SELECT periodo,
       {label},
       {label} - LAG({label}) OVER (ORDER BY periodo) AS variacion_periodo,
       ({label} - LAG({label}) OVER (ORDER BY periodo))
         / NULLIF(LAG({label}) OVER (ORDER BY periodo), 0) AS variacion_pct,
       SUM({label}) OVER (ORDER BY periodo ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS acumulado,
       AVG({label}) OVER (ORDER BY periodo ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS media_movil_3
FROM _resultado
ORDER BY periodo"""
        if plan.tipo_resultado == "ranking":
            etiqueta = plan.dimension[2] if plan.dimension else "categoria"
            return f"""SELECT {etiqueta},
       {label},
       ROW_NUMBER() OVER (ORDER BY {label} DESC) AS ranking,
       {label} / NULLIF(SUM({label}) OVER (), 0) AS participacion,
       SUM({label}) OVER (ORDER BY {label} DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
         / NULLIF(SUM({label}) OVER (), 0) AS participacion_acumulada
FROM _resultado
ORDER BY {label} DESC"""
        if plan.tipo_resultado == "serie" and plan.dimension:
            etiqueta = plan.dimension[2]
            return f"""SELECT periodo, {etiqueta}, {label},
       {label} / NULLIF(SUM({label}) OVER (PARTITION BY periodo), 0) AS participacion_periodo
FROM _resultado
ORDER BY periodo, {label} DESC"""
        return "SELECT * FROM _resultado"

    def _explicar(self, plan: QueryPlan, meta: dict[str, Any]) -> str:
        partes = [f"Calculo {meta['label']} con {meta['expr']}"]
        if plan.grano:
            partes.append(f"agrupado por {GRANOS[plan.grano][1]}")
        if plan.dimension:
            partes.append(f"y por {plan.dimension[2]}")
        if plan.filtros:
            partes.append("filtrando por " + ", ".join(f.descripcion for f in plan.filtros))
        if plan.limite:
            partes.append(f"tomando el top {plan.limite}")
        if plan.joins:
            partes.append(
                "usando las relaciones declaradas "
                + ", ".join(f"{r['left']}={r['right']}" for r in plan.joins)
            )
        return " ".join(partes) + "."
