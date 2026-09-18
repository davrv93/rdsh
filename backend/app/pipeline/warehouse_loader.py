"""Carga del almacén analítico (Redshift o su equivalente local).

Este proceso hace lo mismo que haría un ingeniero de datos contra Redshift:
crea el esquema, crea las tablas con sus tipos, carga los datos y otorga
permisos de solo lectura al usuario de la aplicación.

Se ejecuta una vez al levantar el entorno:
    python -m backend.app.pipeline.warehouse_loader
"""
from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass

import pandas as pd

from ..config import SEED_DIR
from ..seed.generate_seed import build_seed

log = logging.getLogger("optimiza.warehouse")

ESQUEMA = os.getenv("REDSHIFT_SCHEMA", "analytics")
USUARIO_LECTURA = os.getenv("REDSHIFT_USER", "optimiza_ro")

# DDL portable entre PostgreSQL y Redshift.
DDL: dict[str, str] = {
    "regiones": """
        CREATE TABLE {esquema}.regiones (
            region_id   BIGINT PRIMARY KEY,
            region      VARCHAR(80),
            pais        VARCHAR(80),
            macro_zona  VARCHAR(80)
        )""",
    "clientes": """
        CREATE TABLE {esquema}.clientes (
            cliente_id  BIGINT PRIMARY KEY,
            nombre      VARCHAR(160),
            email       VARCHAR(160),
            documento   VARCHAR(32),
            segmento    VARCHAR(40),
            region_id   BIGINT,
            fecha_alta  DATE
        )""",
    "productos": """
        CREATE TABLE {esquema}.productos (
            producto_id    BIGINT PRIMARY KEY,
            nombre         VARCHAR(160),
            categoria      VARCHAR(80),
            subcategoria   VARCHAR(80),
            costo_unitario DOUBLE PRECISION,
            precio_lista   DOUBLE PRECISION
        )""",
    "campanias": """
        CREATE TABLE {esquema}.campanias (
            campania_id  BIGINT PRIMARY KEY,
            nombre       VARCHAR(120),
            canal        VARCHAR(60),
            tipo         VARCHAR(60),
            fecha_inicio DATE,
            fecha_fin    DATE,
            inversion    DOUBLE PRECISION
        )""",
    "dim_fechas": """
        CREATE TABLE {esquema}.dim_fechas (
            fecha         DATE PRIMARY KEY,
            anio          INTEGER,
            mes           INTEGER,
            nombre_mes    VARCHAR(20),
            anio_mes      VARCHAR(7),
            trimestre     INTEGER,
            semana        INTEGER,
            dia_semana    INTEGER,
            es_fin_semana BOOLEAN
        )""",
    "ventas": """
        CREATE TABLE {esquema}.ventas (
            venta_id        BIGINT PRIMARY KEY,
            fecha           DATE,
            cliente_id      BIGINT,
            producto_id     BIGINT,
            campania_id     BIGINT,
            region_id       BIGINT,
            canal           VARCHAR(40),
            unidades        INTEGER,
            precio_unitario DOUBLE PRECISION,
            descuento       DOUBLE PRECISION,
            ingreso         DOUBLE PRECISION,
            costo           DOUBLE PRECISION,
            margen          DOUBLE PRECISION
        )""",
    "tickets_soporte": """
        CREATE TABLE {esquema}.tickets_soporte (
            ticket_id           BIGINT PRIMARY KEY,
            fecha               DATE,
            documento_cliente   VARCHAR(32),
            canal_contacto      VARCHAR(40),
            motivo              VARCHAR(60),
            estado              VARCHAR(30),
            tiempo_resolucion_h DOUBLE PRECISION,
            csat                INTEGER
        )""",
    "web_sessions": """
        CREATE TABLE {esquema}.web_sessions (
            session_id    VARCHAR(30) PRIMARY KEY,
            fecha         DATE,
            utm_campaign  VARCHAR(120),
            dispositivo   VARCHAR(30),
            duracion_s    INTEGER,
            paginas_vistas INTEGER,
            convirtio     BOOLEAN
        )""",
}

INDICES = [
    "CREATE INDEX IF NOT EXISTS ix_ventas_fecha ON {esquema}.ventas (fecha)",
    "CREATE INDEX IF NOT EXISTS ix_ventas_cliente ON {esquema}.ventas (cliente_id)",
    "CREATE INDEX IF NOT EXISTS ix_ventas_producto ON {esquema}.ventas (producto_id)",
    "CREATE INDEX IF NOT EXISTS ix_tickets_fecha ON {esquema}.tickets_soporte (fecha)",
    "CREATE INDEX IF NOT EXISTS ix_web_fecha ON {esquema}.web_sessions (fecha)",
]


@dataclass
class ResultadoCarga:
    tabla: str
    filas: int
    ms: float


def _conexion_admin():
    """Conexión con el usuario administrador del almacén (no el de la app)."""
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("WAREHOUSE_HOST", os.getenv("REDSHIFT_HOST", "warehouse")),
        port=int(os.getenv("WAREHOUSE_PORT", os.getenv("REDSHIFT_PORT", "5432"))),
        dbname=os.getenv("WAREHOUSE_DB", os.getenv("REDSHIFT_DB", "analytics")),
        user=os.getenv("WAREHOUSE_ADMIN_USER", "optimiza_admin"),
        password=os.getenv("WAREHOUSE_ADMIN_PASSWORD", "optimiza_admin_pwd"),
        connect_timeout=15,
    )


def _copiar(cur, tabla: str, df: pd.DataFrame, esquema: str) -> int:
    """Carga masiva con COPY (equivalente a COPY desde S3 en Redshift)."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)
    columnas = ", ".join(f'"{c}"' for c in df.columns)
    cur.copy_expert(
        f"COPY {esquema}.{tabla} ({columnas}) FROM STDIN WITH (FORMAT csv, NULL '')",
        buffer,
    )
    return len(df)


def cargar(recrear: bool = True, esquema: str | None = None) -> list[ResultadoCarga]:
    esquema = esquema or ESQUEMA
    build_seed()
    resultados: list[ResultadoCarga] = []

    with _conexion_admin() as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {esquema}")
            for tabla, ddl in DDL.items():
                archivo = SEED_DIR / f"{tabla}.parquet"
                if not archivo.exists():
                    log.warning("Sin datos para %s", tabla)
                    continue
                t0 = time.perf_counter()
                if recrear:
                    cur.execute(f"DROP TABLE IF EXISTS {esquema}.{tabla} CASCADE")
                    cur.execute(ddl.format(esquema=esquema))
                else:
                    cur.execute(ddl.format(esquema=esquema).replace(
                        "CREATE TABLE", "CREATE TABLE IF NOT EXISTS"))
                    cur.execute(f"TRUNCATE {esquema}.{tabla}")
                df = pd.read_parquet(archivo)
                filas = _copiar(cur, tabla, df, esquema)
                resultados.append(
                    ResultadoCarga(tabla, filas, (time.perf_counter() - t0) * 1000)
                )
            for indice in INDICES:
                cur.execute(indice.format(esquema=esquema))
            cur.execute(f"ANALYZE {esquema}.ventas")
            # Permisos de solo lectura para la aplicación
            cur.execute(f"GRANT USAGE ON SCHEMA {esquema} TO {USUARIO_LECTURA}")
            cur.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {esquema} TO {USUARIO_LECTURA}")
            cur.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {esquema} "
                f"GRANT SELECT ON TABLES TO {USUARIO_LECTURA}"
            )
        conn.commit()
    return resultados


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(f"Cargando el almacén analítico en el esquema '{ESQUEMA}'…")
    for r in cargar():
        print(f"  {r.tabla:18s} {r.filas:>8,} filas  {r.ms:8.0f} ms")
    print("Carga completa. El usuario de la aplicación solo tiene SELECT.")
