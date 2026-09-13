# -*- coding: utf-8 -*-
"""
Base de datos del sistema.

Guarda la cartera ya procesada por el cargador —limpia, seudonimizada y con
las variables derivadas—, nunca el archivo de asignación en bruto.

El diseño tiene una decisión central: cada carga mensual se conserva junto a
las anteriores en lugar de reemplazarlas. La tabla `cartera` usa como llave el
par (carga, crédito), de modo que una misma cuenta aparece una vez por cada mes
en que fue asignada. Eso es lo que permite, a partir del tercer mes, entrenar
modelos con historia real: saber qué cuentas generaron compromiso, cuáles se
repitieron sin resolverse y qué estrategia funcionó con cada perfil.

El motor se elige por configuración: SQLite en local sin instalar nada, o
PostgreSQL (por ejemplo Supabase) definiendo DATABASE_URL en el archivo .env.
El código es el mismo en ambos casos gracias a SQLAlchemy.
"""

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey,
                        Index, Integer, MetaData, Numeric, String, Table,
                        create_engine, func, insert, inspect, select)

import config


# ---------------------------------------------------------------------------
# 1. ESQUEMA
# ---------------------------------------------------------------------------
# Los tipos se declaran explícitamente en lugar de dejar que pandas los
# adivine: así la tabla queda igual en SQLite y en PostgreSQL, y los montos se
# guardan como numéricos exactos y no como flotantes que pierden centavos.

metadatos = MetaData()

cargas = Table(
    "cargas", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha_carga", DateTime, nullable=False),
    # REAL, SINTETICO o ENMASCARADO: toda consulta sabe con qué clase de dato
    # está trabajando.
    Column("origen", String(20), nullable=False),
    # Solo el nombre del archivo, nunca la ruta completa: la ruta revela la
    # estructura de la red interna y el nombre del cliente.
    Column("archivo", String(255)),
    Column("registros", Integer, nullable=False),
    Column("saldo_total", Numeric(18, 2), nullable=False),
    Column("meta_recaudo", Numeric(18, 2), nullable=False),
    Column("semilla", Integer),
)

cartera = Table(
    "cartera", metadatos,
    Column("carga_id", Integer, ForeignKey("cargas.id"), primary_key=True),
    Column("credito_id", String(13), primary_key=True),
    Column("cuenta_id", String(13), nullable=False),

    Column("saldo", Numeric(18, 2)),
    Column("cobranza_min", Numeric(18, 2)),
    Column("cobranza_max", Numeric(18, 2)),
    Column("proyeccion", Numeric(18, 2)),
    Column("margen_negociacion", Numeric(18, 2)),
    Column("margen_pct", Float),
    Column("dias_mora", Integer),

    Column("franja", String(40)),
    Column("rango_mora", String(20)),
    Column("ciudad", String(60)),
    Column("producto", String(30)),
    Column("estado", String(20)),
    Column("codigo", String(40)),
    Column("gestor_ultimo", String(40)),

    Column("canales_disponibles", Integer),
    Column("resultado_gestion", String(30)),
    Column("meses_en_gestion", Integer),
    Column("gestionada", Boolean),
    Column("gestionable", Boolean),
    Column("tiene_compromiso", Boolean),
    Column("tipo_acuerdo", String(20)),
    Column("fecha_compromiso", Date),
)

# Índices para las consultas que más va a hacer el sistema: seguir a un titular
# entre meses, agrupar por código de gestión y repartir por gestor.
Index("ix_cartera_cuenta", cartera.c.cuenta_id)
Index("ix_cartera_codigo", cartera.c.codigo)
Index("ix_cartera_gestor", cartera.c.gestor_ultimo)


# ---------------------------------------------------------------------------
# 2. CONEXIÓN Y CREACIÓN
# ---------------------------------------------------------------------------

def obtener_motor():
    return create_engine(config.URL_BASE_DATOS, future=True)


def es_local():
    return config.URL_BASE_DATOS.startswith("sqlite")


def describir_motor():
    if es_local():
        return "SQLite local ({})".format(Path(config.URL_BASE_DATOS.split("///")[-1]).name)
    if "supabase" in config.URL_BASE_DATOS:
        return "PostgreSQL en Supabase"
    return "PostgreSQL remoto"


def crear_esquema(motor=None):
    """Crea las tablas si no existen. Es seguro ejecutarlo varias veces."""
    motor = motor or obtener_motor()
    metadatos.create_all(motor)
    return sorted(inspect(motor).get_table_names())


# ---------------------------------------------------------------------------
# 3. CARGA
# ---------------------------------------------------------------------------

def registrar_carga(df, origen, archivo=None, semilla=None, permitir_real_en_nube=False):
    """Guarda una cartera procesada como una carga nueva y retorna su id.

    Regla de protección: los datos de origen REAL solo se guardan en la base
    local. Aunque ya están seudonimizados, siguen siendo datos personales para
    la empresa que conserva el archivo original, y subirlos a un servicio en la
    nube requiere una decisión explícita, no un descuido de configuración.
    """
    if origen == "REAL" and not es_local() and not permitir_real_en_nube:
        raise PermissionError(
            "Se intentó guardar datos REALES en una base remota ({}). Use la base "
            "local, cargue la cartera sintética, o confirme explícitamente con "
            "permitir_real_en_nube=True.".format(describir_motor()))

    motor = obtener_motor()
    crear_esquema(motor)

    columnas = [c.name for c in cartera.columns if c.name != "carga_id"]
    tabla = df[columnas].copy()
    for booleana in ["gestionada", "gestionable", "tiene_compromiso"]:
        tabla[booleana] = tabla[booleana].astype(bool)
    tabla["fecha_compromiso"] = pd.to_datetime(tabla["fecha_compromiso"]).dt.date
    tabla = tabla.astype(object).where(tabla.notna(), None)

    with motor.begin() as conexion:
        resultado = conexion.execute(insert(cargas).values(
            fecha_carga=datetime.now(),
            origen=origen,
            archivo=Path(archivo).name if archivo else None,
            registros=len(tabla),
            saldo_total=float(df["saldo"].sum()),
            meta_recaudo=float(df["saldo"].sum() * config.META_PORCENTAJE),
            semilla=semilla,
        ))
        carga_id = resultado.inserted_primary_key[0]
        tabla.insert(0, "carga_id", carga_id)
        # Se inserta en bloques para no armar una sola sentencia gigante:
        # PostgreSQL y SQLite tienen límites en el número de parámetros.
        filas = tabla.to_dict(orient="records")
        for inicio in range(0, len(filas), 1000):
            conexion.execute(insert(cartera), filas[inicio:inicio + 1000])

    return carga_id


# ---------------------------------------------------------------------------
# 4. CONSULTA
# ---------------------------------------------------------------------------

def listar_cargas():
    with obtener_motor().connect() as conexion:
        return pd.read_sql(select(cargas).order_by(cargas.c.id), conexion)


def leer_cartera(carga_id=None):
    """Lee la cartera de una carga. Sin id, lee la más reciente."""
    motor = obtener_motor()
    with motor.connect() as conexion:
        if carga_id is None:
            carga_id = conexion.execute(select(func.max(cargas.c.id))).scalar()
        consulta = select(cartera).where(cartera.c.carga_id == carga_id)
        return pd.read_sql(consulta, conexion)


# ---------------------------------------------------------------------------
# 5. LÍNEA DE COMANDOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Administra la base de datos del sistema.")
    sub = parser.add_subparsers(dest="accion", required=True)
    sub.add_parser("crear", help="crea las tablas")
    p_sint = sub.add_parser("sintetica", help="genera una cartera ficticia y la carga")
    p_sint.add_argument("--registros", type=int, default=None)
    p_sint.add_argument("--semilla", type=int, default=config.SEMILLA)
    sub.add_parser("real", help="carga la asignación real (solo en base local)")
    sub.add_parser("cargas", help="lista las cargas registradas")
    args = parser.parse_args()

    print("Base de datos: {}".format(describir_motor()))

    if args.accion == "crear":
        print("  Tablas: {}".format(", ".join(crear_esquema())))

    elif args.accion == "sintetica":
        from datos.cargador import cargar
        from datos.generador import generar
        from datos.perfilador import cargar_perfil
        bruto = generar(cargar_perfil(), n=args.registros, semilla=args.semilla)
        carga_id = registrar_carga(cargar(bruto=bruto), "SINTETICO",
                                   "generada_en_memoria", semilla=args.semilla)
        print("  Carga {} registrada: {:,} cuentas ficticias".format(carga_id, len(bruto)))

    elif args.accion == "real":
        from datos.cargador import cargar
        carga_id = registrar_carga(cargar(), "REAL", config.ARCHIVO_ASIGNACION)
        print("  Carga {} registrada con la asignación real".format(carga_id))

    elif args.accion == "cargas":
        print(listar_cargas().to_string(index=False))
