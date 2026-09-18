"""Genera los datos demo (Parquet) que simulan el warehouse de Redshift.

Modelo:
  - Tablas con relación declarada: ventas -> clientes, productos, campanias, regiones, dim_fechas
  - Tablas SIN relación declarada: tickets_soporte, web_sessions
    (tienen claves *compatibles* pero no declaradas: el agente debe detectarlas,
     no inventarlas)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SEED_DIR

RNG = np.random.default_rng(20250918)

MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

REGIONES = [
    (1, "Lima", "Perú", "Centro"),
    (2, "Arequipa", "Perú", "Sur"),
    (3, "Trujillo", "Perú", "Norte"),
    (4, "Cusco", "Perú", "Sur"),
    (5, "Piura", "Perú", "Norte"),
    (6, "Bogotá", "Colombia", "Andina"),
    (7, "Santiago", "Chile", "Cono Sur"),
]

CATEGORIAS = {
    "Electrónica": ["Smartphones", "Laptops", "Audio"],
    "Hogar": ["Cocina", "Muebles", "Limpieza"],
    "Moda": ["Calzado", "Ropa", "Accesorios"],
    "Deportes": ["Fitness", "Outdoor", "Ciclismo"],
}

SEGMENTOS = ["Retail", "Corporativo", "PYME", "Gobierno"]
CANALES = ["web", "tienda", "marketplace", "call center"]
CANAL_CAMPANIA = ["email", "paid_search", "social", "display", "influencers"]


def _clientes(n: int = 600) -> pd.DataFrame:
    nombres = ["Ana", "Luis", "María", "Jorge", "Rosa", "Carlos", "Lucía", "Pedro", "Elena", "Diego"]
    apellidos = ["Quispe", "Rojas", "Vargas", "Mendoza", "Flores", "Ramos", "Castillo", "Núñez"]
    idx = np.arange(1, n + 1)
    nombre = [
        f"{RNG.choice(nombres)} {RNG.choice(apellidos)}" for _ in idx
    ]
    return pd.DataFrame(
        {
            "cliente_id": idx,
            "nombre": nombre,
            "email": [f"cliente{i}@correo-demo.com" for i in idx],
            "documento": [f"{40000000 + int(i) * 7:08d}" for i in idx],
            "segmento": RNG.choice(SEGMENTOS, size=n, p=[0.55, 0.15, 0.25, 0.05]),
            "region_id": RNG.choice([r[0] for r in REGIONES], size=n),
            "fecha_alta": pd.to_datetime("2022-01-01")
            + pd.to_timedelta(RNG.integers(0, 1000, size=n), unit="D"),
        }
    )


def _productos(n: int = 120) -> pd.DataFrame:
    cats, subs = [], []
    for _ in range(n):
        c = RNG.choice(list(CATEGORIAS))
        cats.append(c)
        subs.append(RNG.choice(CATEGORIAS[c]))
    costo = np.round(RNG.uniform(8, 900, size=n), 2)
    return pd.DataFrame(
        {
            "producto_id": np.arange(1, n + 1),
            "nombre": [f"{s} modelo {i:03d}" for i, s in enumerate(subs, start=1)],
            "categoria": cats,
            "subcategoria": subs,
            "costo_unitario": costo,
            "precio_lista": np.round(costo * RNG.uniform(1.25, 2.1, size=n), 2),
        }
    )


def _campanias(n: int = 24) -> pd.DataFrame:
    inicio = pd.to_datetime("2024-01-01") + pd.to_timedelta(
        RNG.integers(0, 600, size=n), unit="D"
    )
    canal = RNG.choice(CANAL_CAMPANIA, size=n)
    return pd.DataFrame(
        {
            "campania_id": np.arange(1, n + 1),
            "nombre": [f"{c}_{i:02d}_2025" for i, c in enumerate(canal, start=1)],
            "canal": canal,
            "tipo": RNG.choice(["awareness", "performance", "retencion"], size=n),
            "fecha_inicio": inicio,
            "fecha_fin": inicio + pd.to_timedelta(RNG.integers(14, 90, size=n), unit="D"),
            "inversion": np.round(RNG.uniform(3000, 80000, size=n), 2),
        }
    )


def _dim_fechas(start: str = "2024-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    fechas = pd.date_range(start, end, freq="D")
    return pd.DataFrame(
        {
            "fecha": fechas,
            "anio": fechas.year,
            "mes": fechas.month,
            "nombre_mes": [MESES_ES[m - 1] for m in fechas.month],
            "anio_mes": fechas.strftime("%Y-%m"),
            "trimestre": fechas.quarter,
            "semana": fechas.isocalendar().week.astype(int),
            "dia_semana": fechas.dayofweek + 1,
            "es_fin_semana": fechas.dayofweek >= 5,
        }
    )


def _ventas(clientes: pd.DataFrame, productos: pd.DataFrame, campanias: pd.DataFrame,
            n: int = 40000) -> pd.DataFrame:
    fechas = pd.date_range("2024-01-01", "2025-09-30", freq="D")
    # Estacionalidad: más ventas a fin de año y tendencia creciente
    peso = np.array(
        [1.0 + 0.6 * np.sin((d.dayofyear / 365) * 2 * np.pi - 1.2) + d.year % 2024 * 0.15
         for d in fechas]
    )
    peso = np.clip(peso, 0.2, None)
    peso = peso / peso.sum()
    fecha = RNG.choice(fechas, size=n, p=peso)

    producto_id = RNG.choice(productos["producto_id"].to_numpy(), size=n)
    prod = productos.set_index("producto_id").loc[producto_id]
    unidades = RNG.integers(1, 9, size=n)
    descuento = np.round(RNG.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.25], size=n), 2)
    precio = prod["precio_lista"].to_numpy()
    ingreso = np.round(unidades * precio * (1 - descuento), 2)
    costo = np.round(unidades * prod["costo_unitario"].to_numpy(), 2)

    cliente_id = RNG.choice(clientes["cliente_id"].to_numpy(), size=n)
    region_por_cliente = clientes.set_index("cliente_id")["region_id"]

    df = pd.DataFrame(
        {
            "venta_id": np.arange(1, n + 1),
            "fecha": pd.to_datetime(fecha),
            "cliente_id": cliente_id,
            "producto_id": producto_id,
            "campania_id": RNG.choice(
                np.append(campanias["campania_id"].to_numpy(), [0]), size=n
            ),
            "region_id": region_por_cliente.loc[cliente_id].to_numpy(),
            "canal": RNG.choice(CANALES, size=n, p=[0.45, 0.3, 0.2, 0.05]),
            "unidades": unidades,
            "precio_unitario": precio,
            "descuento": descuento,
            "ingreso": ingreso,
            "costo": costo,
        }
    )
    df["margen"] = np.round(df["ingreso"] - df["costo"], 2)

    # Caída deliberada en una categoría durante Q3-2025 (pregunta demo:
    # "¿qué productos cayeron este trimestre?")
    caida = (df["fecha"] >= "2025-07-01") & (
        df["producto_id"].isin(productos.loc[productos["categoria"] == "Moda", "producto_id"])
    )
    df.loc[caida, ["ingreso", "margen"]] *= 0.45
    return df


def _tickets_soporte(clientes: pd.DataFrame, n: int = 5000) -> pd.DataFrame:
    """Tabla SIN relación declarada con clientes (clave compatible: documento)."""
    docs = clientes["documento"].to_numpy()
    return pd.DataFrame(
        {
            "ticket_id": np.arange(1, n + 1),
            "fecha": pd.to_datetime("2024-01-01")
            + pd.to_timedelta(RNG.integers(0, 640, size=n), unit="D"),
            "documento_cliente": RNG.choice(docs, size=n),
            "canal_contacto": RNG.choice(["telefono", "chat", "email", "whatsapp"], size=n),
            "motivo": RNG.choice(
                ["facturacion", "envio", "garantia", "producto_danado", "consulta"], size=n
            ),
            "estado": RNG.choice(["abierto", "cerrado", "escalado"], size=n, p=[0.15, 0.78, 0.07]),
            "tiempo_resolucion_h": np.round(RNG.gamma(2.0, 6.0, size=n), 1),
            "csat": RNG.integers(1, 6, size=n),
        }
    )


def _web_sessions(campanias: pd.DataFrame, n: int = 25000) -> pd.DataFrame:
    """Tabla SIN relación declarada ni clave confiable con el modelo de ventas."""
    utm = np.append(campanias["nombre"].to_numpy(), ["organic", "direct", "referral"])
    return pd.DataFrame(
        {
            "session_id": [f"s-{i:07d}" for i in range(1, n + 1)],
            "fecha": pd.to_datetime("2024-01-01")
            + pd.to_timedelta(RNG.integers(0, 640, size=n), unit="D"),
            "utm_campaign": RNG.choice(utm, size=n),
            "dispositivo": RNG.choice(["mobile", "desktop", "tablet"], size=n, p=[0.62, 0.33, 0.05]),
            "duracion_s": RNG.integers(5, 1800, size=n),
            "paginas_vistas": RNG.integers(1, 25, size=n),
            "convirtio": RNG.choice([True, False], size=n, p=[0.06, 0.94]),
        }
    )


def build_seed(force: bool = False) -> dict[str, int]:
    """Escribe los Parquet de demo. Devuelve {tabla: filas}."""
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    marker = SEED_DIR / "_seed_ok"
    if marker.exists() and not force:
        return {p.stem: -1 for p in SEED_DIR.glob("*.parquet")}

    regiones = pd.DataFrame(REGIONES, columns=["region_id", "region", "pais", "macro_zona"])
    clientes = _clientes()
    productos = _productos()
    campanias = _campanias()
    ventas = _ventas(clientes, productos, campanias)
    tablas = {
        "regiones": regiones,
        "clientes": clientes,
        "productos": productos,
        "campanias": campanias,
        "dim_fechas": _dim_fechas(),
        "ventas": ventas,
        "tickets_soporte": _tickets_soporte(clientes),
        "web_sessions": _web_sessions(campanias),
    }
    conteo = {}
    for nombre, df in tablas.items():
        df.to_parquet(SEED_DIR / f"{nombre}.parquet", index=False)
        conteo[nombre] = len(df)
    marker.write_text("ok", encoding="utf-8")
    return conteo


if __name__ == "__main__":  # pragma: no cover
    for tabla, filas in build_seed(force=True).items():
        print(f"{tabla:18s} {filas:>8,} filas")
    print(f"\nParquet en: {SEED_DIR}")
