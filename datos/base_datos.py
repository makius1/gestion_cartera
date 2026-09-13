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
                        create_engine, func, insert, inspect, select, text)

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

    # Canales concretos y fecha del último contacto: los hechos que necesita el
    # motor de elegibilidad para aplicar la Ley 2300.
    Column("tiene_celular", Boolean),
    Column("tiene_fijo", Boolean),
    Column("tiene_email", Boolean),
    Column("fecha_ultima_gestion", Date),
)

# Índices para las consultas que más va a hacer el sistema: seguir a un titular
# entre meses, agrupar por código de gestión y repartir por gestor.
Index("ix_cartera_cuenta", cartera.c.cuenta_id)
Index("ix_cartera_codigo", cartera.c.codigo)
Index("ix_cartera_gestor", cartera.c.gestor_ultimo)


# --- Usuarios y auditoría ---------------------------------------------------

usuarios = Table(
    "usuarios", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario", String(40), nullable=False, unique=True),
    Column("nombre", String(80), nullable=False),
    # ADMINISTRADOR, SUPERVISOR o GESTOR: define qué pantallas y acciones ve.
    Column("rol", String(20), nullable=False),
    # Nunca la contraseña: solo su derivación con scrypt y una sal aleatoria.
    Column("hash_clave", String(255), nullable=False),
    Column("activo", Boolean, nullable=False, default=True),
    Column("creado", DateTime, nullable=False),
    Column("ultimo_ingreso", DateTime),
    # Control de fuerza bruta: intentos fallidos seguidos y bloqueo temporal.
    Column("intentos_fallidos", Integer, nullable=False, default=0),
    Column("bloqueado_hasta", DateTime),
)

auditoria = Table(
    "auditoria", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", DateTime, nullable=False),
    Column("usuario", String(40), nullable=False),
    Column("accion", String(40), nullable=False),
    Column("detalle", String(500)),
)
Index("ix_auditoria_fecha", auditoria.c.fecha)


# --- Motor de elegibilidad ----------------------------------------------------
# Cada ejecución del motor queda registrada con su resultado cuenta por cuenta.
# Es lo que permite demostrar después, ante una auditoría o una queja, que el
# contacto con un titular estaba permitido el día en que se hizo y por qué.

ejecuciones_motor = Table(
    "ejecuciones_motor", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", DateTime, nullable=False),
    Column("usuario", String(40), nullable=False),
    Column("carga_id", Integer, ForeignKey("cargas.id"), nullable=False),
    Column("fecha_objetivo", Date, nullable=False),
    Column("total", Integer, nullable=False),
    Column("contactables", Integer, nullable=False),
    Column("bloqueadas", Integer, nullable=False),
    Column("en_espera", Integer, nullable=False),
    Column("recordatorio", Integer, nullable=False),
)

evaluaciones = Table(
    "evaluaciones", metadatos,
    Column("ejecucion_id", Integer, ForeignKey("ejecuciones_motor.id"), primary_key=True),
    Column("credito_id", String(13), primary_key=True),
    Column("estado", String(20), nullable=False),
    Column("canal_recomendado", String(20)),
    Column("canales_permitidos", String(60)),
    Column("reglas", String(200)),
    Column("explicacion", String(1000)),
)


# ---------------------------------------------------------------------------
# 2. CONEXIÓN Y CREACIÓN
# ---------------------------------------------------------------------------

_MOTORES = {}


def obtener_motor():
    """Devuelve la conexión definida en la configuración, reutilizándola.

    El motor se crea una sola vez por cadena de conexión y se reutiliza. No es
    un detalle: abrir una conexión cifrada hasta el servidor tarda más de un
    segundo, y en la aplicación web cada pantalla hace varias consultas. Con el
    motor reutilizado, las conexiones quedan abiertas en un grupo y cada
    consulta tarda lo que tarda el viaje de ida y vuelta.

    pool_pre_ping verifica que la conexión siga viva antes de usarla: los
    servicios en la nube cierran las conexiones inactivas.
    """
    url = config.URL_BASE_DATOS
    if url not in _MOTORES:
        _MOTORES[url] = create_engine(url, future=True, pool_pre_ping=True,
                                      pool_recycle=1800)
    return _MOTORES[url]


def es_local():
    return config.URL_BASE_DATOS.startswith("sqlite")


def describir_motor():
    """Describe el motor sin mostrar nunca la cadena de conexión, que contiene
    la contraseña."""
    url = config.URL_BASE_DATOS
    if es_local():
        return "SQLite local ({})".format(Path(url.split("///")[-1]).name)
    if "pooler.supabase.com" in url:
        return "PostgreSQL en Supabase (pooler)"
    if "supabase" in url:
        return "PostgreSQL en Supabase (conexión directa)"
    return "PostgreSQL remoto"


def crear_esquema(motor=None):
    """Crea las tablas si no existen. Es seguro ejecutarlo varias veces.

    En PostgreSQL además activa Row Level Security. Supabase publica cada tabla
    del esquema public en una API REST a la que se accede con la llave pública
    del proyecto; con RLS activo y sin políticas definidas, esa API no devuelve
    ninguna fila. El sistema no se ve afectado porque se conecta como dueño de
    las tablas, y los dueños no quedan sujetos a RLS.
    """
    motor = motor or obtener_motor()
    metadatos.create_all(motor)
    _migrar_columnas(motor)
    if motor.dialect.name == "postgresql":
        with motor.begin() as conexion:
            for tabla in metadatos.sorted_tables:
                conexion.execute(text(
                    'ALTER TABLE "{}" ENABLE ROW LEVEL SECURITY'.format(tabla.name)))
    return sorted(inspect(motor).get_table_names())


def _migrar_columnas(motor):
    """Agrega a las tablas existentes las columnas que el esquema tiene de más.

    create_all crea las tablas que faltan, pero no modifica las que ya existen.
    Cuando el esquema crece —por ejemplo, al agregar los canales por tipo que
    necesita el motor de elegibilidad—, una base ya en uso quedaría sin esas
    columnas y las consultas fallarían. Esta función compara el esquema con la
    base real y agrega lo que falte, sin tocar ni borrar los datos existentes.

    Solo agrega columnas que admiten nulos: las filas antiguas quedan con esos
    campos vacíos y el sistema los trata como desconocidos.
    """
    inspector = inspect(motor)
    existentes = set(inspector.get_table_names())
    agregadas = []
    with motor.begin() as conexion:
        for tabla in metadatos.sorted_tables:
            if tabla.name not in existentes:
                continue
            actuales = {c["name"] for c in inspector.get_columns(tabla.name)}
            for columna in tabla.columns:
                if columna.name in actuales or not columna.nullable:
                    continue
                tipo = columna.type.compile(dialect=motor.dialect)
                conexion.execute(text('ALTER TABLE "{}" ADD COLUMN "{}" {}'.format(
                    tabla.name, columna.name, tipo)))
                agregadas.append("{}.{}".format(tabla.name, columna.name))
    return agregadas


def _cifrado_del_cliente(conexion):
    """Protocolo de cifrado entre este equipo y el servidor, o False si no hay.

    Se consulta al CLIENTE y no al servidor a propósito. Detrás de un pooler
    como el de Supabase hay dos tramos: equipo → pooler, que viaja por
    internet, y pooler → PostgreSQL, que ocurre dentro de la red del proveedor.
    Preguntarle a PostgreSQL por su conexión (pg_stat_ssl) describe el segundo
    tramo, y puede decir que no hay cifrado aunque el tramo que sale a internet
    sí lo tenga. Lo que importa proteger es el primero.
    """
    try:
        info = conexion.connection.dbapi_connection.info
        return (info.ssl_attribute("protocol") or "sí") if info.ssl_in_use else False
    except AttributeError:
        return None


def _milisegundos(desde):
    return round((datetime.now() - desde).total_seconds() * 1000)


def probar_conexion():
    """Verifica la conexión y resume el estado de la base.

    Es lo primero que conviene ejecutar al configurar un servidor nuevo: si
    falla aquí, el problema es de red o de credenciales y no del sistema.

    Mide por separado el tiempo de abrir la conexión y el de una consulta. La
    apertura incluye la negociación del cifrado y la autenticación, y ocurre una
    sola vez; la consulta es lo que tarda cada operación después.
    """
    motor = obtener_motor()
    inicio = datetime.now()
    with motor.connect() as conexion:
        conexion.execute(text("SELECT 1"))
        apertura = _milisegundos(inicio)

        inicio_consulta = datetime.now()
        conexion.execute(text("SELECT 1"))
        consulta = _milisegundos(inicio_consulta)

        if motor.dialect.name == "postgresql":
            version = conexion.execute(text("SHOW server_version")).scalar()
            cifrado = _cifrado_del_cliente(conexion)
        else:
            version = conexion.execute(text("SELECT sqlite_version()")).scalar()
            cifrado = None

        tablas = sorted(inspect(motor).get_table_names())
        conteos = {t: conexion.execute(text('SELECT COUNT(*) FROM "{}"'.format(t))).scalar()
                   for t in tablas}

    return {"motor": describir_motor(), "version": version, "ssl": cifrado,
            "apertura_ms": apertura, "consulta_ms": consulta, "tablas": conteos}


def formatear_estado(estado):
    """Líneas legibles con el resultado de probar_conexion()."""
    lineas = ["  Motor             : {}".format(estado["motor"]),
              "  Versión           : {}".format(estado["version"])]
    if estado["ssl"] is not None:
        lineas.append("  Conexión cifrada  : {}".format(
            "sí ({})".format(estado["ssl"]) if estado["ssl"] else "NO"))
    lineas.append("  Abrir conexión    : {} ms".format(estado["apertura_ms"]))
    lineas.append("  Cada consulta     : {} ms".format(estado["consulta_ms"]))
    if estado["tablas"]:
        for tabla, filas in estado["tablas"].items():
            lineas.append("  Tabla {:<12}: {:,} filas".format(tabla, filas))
    else:
        lineas.append("  Tablas            : ninguna todavía")
    return lineas


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
    for booleana in ["gestionada", "gestionable", "tiene_compromiso",
                     "tiene_celular", "tiene_fijo", "tiene_email"]:
        tabla[booleana] = tabla[booleana].astype(bool)
    for fecha in ["fecha_compromiso", "fecha_ultima_gestion"]:
        tabla[fecha] = pd.to_datetime(tabla[fecha]).dt.date
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
    sub.add_parser("probar", help="verifica la conexión y muestra el estado de la base")
    sub.add_parser("crear", help="crea las tablas")
    p_sint = sub.add_parser("sintetica", help="genera una cartera ficticia y la carga")
    p_sint.add_argument("--registros", type=int, default=None)
    p_sint.add_argument("--semilla", type=int, default=config.SEMILLA)
    sub.add_parser("real", help="carga la asignación real (solo en base local)")
    sub.add_parser("cargas", help="lista las cargas registradas")
    args = parser.parse_args()

    print("Base de datos: {}".format(describir_motor()))

    if args.accion == "probar":
        print("\n".join(formatear_estado(probar_conexion())))

    elif args.accion == "crear":
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
