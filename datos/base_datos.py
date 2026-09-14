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
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey,
                        Index, Integer, MetaData, Numeric, String, Table, Text,
                        create_engine, func, insert, inspect, select, text, update)

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
    # La regla que decidió el resultado, separada de la lista completa: permite
    # contar de inmediato cuántas cuentas bloqueó cada norma.
    Column("regla_determinante", String(10)),
    Column("reglas", String(200)),
    Column("explicacion", String(1000)),
)


# --- Segmentación y priorización -------------------------------------------------
# Cada priorización guarda qué método resultó óptimo y por qué (las métricas de
# los tres métodos van en el resumen), y el puntaje de cada cuenta con los tres
# métodos: así se puede revisar después cómo habría quedado la cola con otro.

priorizaciones = Table(
    "priorizaciones", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", DateTime, nullable=False),
    Column("usuario", String(40), nullable=False),
    Column("carga_id", Integer, ForeignKey("cargas.id"), nullable=False),
    # Ejecución del motor de la que salen las cuentas contactables. Sin ella se
    # prioriza toda la cartera gestionable.
    Column("ejecucion_id", Integer, ForeignKey("ejecuciones_motor.id")),
    Column("candidatos", Integer, nullable=False),
    Column("capacidad", Integer, nullable=False),
    Column("k_segmentos", Integer, nullable=False),
    Column("silueta", Float, nullable=False),
    Column("metodo_elegido", String(20), nullable=False),
    # Métricas por método, siluetas por k y perfiles de segmento, en JSON.
    Column("resumen", Text, nullable=False),
)

prioridades = Table(
    "prioridades", metadatos,
    Column("priorizacion_id", Integer, ForeignKey("priorizaciones.id"), primary_key=True),
    Column("credito_id", String(13), primary_key=True),
    Column("segmento", Integer, nullable=False),
    Column("nombre_segmento", String(80)),
    Column("estado_motor", String(20)),
    Column("candidata", Boolean, nullable=False),
    Column("puntaje_difuso", Float),
    Column("puntaje_topsis", Float),
    Column("puntaje_ponderado", Float),
    Column("prioridad", Float),
    Column("posicion", Integer),
    Column("en_capacidad", Boolean),
    Column("pca_x", Float),
    Column("pca_y", Float),
)


# --- Gestiones ---------------------------------------------------------------------
# Cada intento de contacto que registra un gestor. Es la historia completa de la
# cuenta: la tabla cartera guarda solo el estado más reciente, esta tabla guarda
# todos los pasos. Es también la materia prima del modelo de propensión: qué se
# hizo con cada cuenta y qué resultó.

gestiones = Table(
    "gestiones", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", DateTime, nullable=False),
    Column("usuario", String(40), nullable=False),
    Column("carga_id", Integer, ForeignKey("cargas.id"), nullable=False),
    Column("credito_id", String(13), nullable=False),
    Column("canal", String(20), nullable=False),
    # SALIENTE: la casa de cobranza contacta. ENTRANTE: el titular se comunica.
    # La Ley 2300 regula el primero; el segundo puede atenderse cualquier día.
    Column("sentido", String(10), nullable=False),
    Column("resultado", String(30), nullable=False),
    Column("codigo", String(40), nullable=False),
    Column("motivo_no_pago", String(40)),
    Column("valor_acordado", Numeric(18, 2)),
    Column("fecha_compromiso", Date),
    Column("fecha_proxima_gestion", Date),
    Column("observacion", String(500), nullable=False),
    # Estado que el motor asignaba a la cuenta en el momento de la gestión: deja
    # constancia de que el contacto estaba permitido cuando se hizo.
    Column("estado_motor", String(20)),
)
Index("ix_gestiones_cuenta", gestiones.c.carga_id, gestiones.c.credito_id)


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
            fecha_carga=config.ahora(),
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


def guardar_ejecucion(resumen, resultados, usuario):
    """Guarda una ejecución del motor de elegibilidad y su resultado por cuenta.

    El encabezado y el detalle se escriben en una sola transacción: si algo
    falla a mitad de camino no queda una ejecución sin sus evaluaciones.
    Retorna el id de la ejecución.
    """
    motor = obtener_motor()
    crear_esquema(motor)
    columnas = [c.name for c in evaluaciones.columns if c.name != "ejecucion_id"]
    detalle = resultados[columnas].astype(object).where(resultados[columnas].notna(), None)

    with motor.begin() as conexion:
        ejecucion_id = conexion.execute(insert(ejecuciones_motor).values(
            fecha=config.ahora(),
            usuario=usuario,
            carga_id=int(resumen["carga_id"]),
            fecha_objetivo=resumen["fecha_objetivo"],
            total=resumen["total"],
            contactables=resumen["CONTACTABLE"],
            bloqueadas=resumen["BLOQUEADA"],
            en_espera=resumen["EN_ESPERA"],
            recordatorio=resumen["RECORDATORIO"],
        )).inserted_primary_key[0]
        filas = detalle.to_dict(orient="records")
        for fila in filas:
            fila["ejecucion_id"] = ejecucion_id
        for inicio in range(0, len(filas), 1000):
            conexion.execute(insert(evaluaciones), filas[inicio:inicio + 1000])
    return ejecucion_id


def guardar_priorizacion(resumen, tabla, usuario):
    """Guarda una priorización y el resultado de cada cuenta en una transacción."""
    motor = obtener_motor()
    crear_esquema(motor)
    columnas = [c.name for c in prioridades.columns if c.name != "priorizacion_id"]
    detalle = tabla[columnas].astype(object).where(tabla[columnas].notna(), None)

    with motor.begin() as conexion:
        priorizacion_id = conexion.execute(insert(priorizaciones).values(
            fecha=config.ahora(),
            usuario=usuario,
            carga_id=int(resumen["carga_id"]),
            ejecucion_id=resumen.get("ejecucion_id"),
            candidatos=int(resumen["candidatos"]),
            capacidad=int(resumen["capacidad"]),
            k_segmentos=int(resumen["k"]),
            silueta=float(resumen["silueta"]),
            metodo_elegido=resumen["elegido"],
            resumen=json.dumps(resumen["detalle"], ensure_ascii=False, default=float),
        )).inserted_primary_key[0]
        filas = detalle.to_dict(orient="records")
        for fila in filas:
            fila["priorizacion_id"] = priorizacion_id
        for inicio in range(0, len(filas), 1000):
            conexion.execute(insert(prioridades), filas[inicio:inicio + 1000])
    return priorizacion_id


def registrar_gestion(gestion, cambios_cartera):
    """Guarda una gestión y actualiza el estado de la cuenta en la cartera.

    Las dos escrituras van en una sola transacción: nunca queda una gestión
    registrada sin que la cartera lo refleje, ni una cartera actualizada sin la
    gestión que lo justifica. Retorna el id de la gestión.
    """
    motor = obtener_motor()
    crear_esquema(motor)
    with motor.begin() as conexion:
        gestion_id = conexion.execute(insert(gestiones).values(**gestion)).inserted_primary_key[0]
        resultado = conexion.execute(update(cartera).where(
            cartera.c.carga_id == gestion["carga_id"],
            cartera.c.credito_id == gestion["credito_id"]).values(**cambios_cartera))
        if resultado.rowcount != 1:
            # Lanzar dentro de la transacción la deshace completa.
            raise LookupError("La cuenta {} no existe en la carga {}.".format(
                gestion["credito_id"], gestion["carga_id"]))
    return gestion_id


def registrar_evento(usuario, accion, detalle=None):
    """Deja constancia de una acción en la bitácora de auditoría.

    Se registra quién hizo qué y cuándo: ingresos, intentos fallidos, cargas,
    ejecuciones del motor y cambios de usuarios. La bitácora solo crece: el
    sistema no ofrece ninguna forma de editarla ni de borrarla.
    """
    motor = obtener_motor()
    # Se recortan los textos al tamaño de las columnas: en un intento de ingreso
    # el usuario lo escribe cualquiera, y PostgreSQL rechaza un texto más largo
    # que la columna, con lo que el intento quedaría sin registrar.
    with motor.begin() as conexion:
        conexion.execute(insert(auditoria).values(
            fecha=config.ahora(), usuario=(usuario or "")[:40], accion=accion[:40],
            detalle=(detalle or "")[:500]))


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


def cargas_incompletas():
    """Ids de las cargas a las que les faltan los datos de contacto.

    Son las registradas antes de que el esquema guardara los canales por tipo y
    la fecha del último contacto. El motor las bloquea completas por precaución
    (regla L3), así que las pantallas deben advertirlo antes de usarlas.
    """
    with obtener_motor().connect() as conexion:
        filas = conexion.execute(
            select(cartera.c.carga_id)
            .group_by(cartera.c.carga_id)
            .having(func.count(cartera.c.tiene_celular) < func.count()))
        return {int(f.carga_id) for f in filas}


def listar_ejecuciones(limite=50):
    with obtener_motor().connect() as conexion:
        consulta = select(ejecuciones_motor).order_by(ejecuciones_motor.c.id.desc()).limit(limite)
        return pd.read_sql(consulta, conexion)


def leer_evaluaciones(ejecucion_id):
    with obtener_motor().connect() as conexion:
        consulta = select(evaluaciones).where(evaluaciones.c.ejecucion_id == ejecucion_id)
        return pd.read_sql(consulta, conexion)


def listar_priorizaciones(limite=50):
    """Priorizaciones guardadas, sin el resumen JSON (se lee aparte)."""
    columnas = [c for c in priorizaciones.columns if c.name != "resumen"]
    with obtener_motor().connect() as conexion:
        consulta = select(*columnas).order_by(priorizaciones.c.id.desc()).limit(limite)
        return pd.read_sql(consulta, conexion)


def leer_resumen_priorizacion(priorizacion_id):
    with obtener_motor().connect() as conexion:
        texto = conexion.execute(select(priorizaciones.c.resumen).where(
            priorizaciones.c.id == priorizacion_id)).scalar()
    return json.loads(texto) if texto else {}


def leer_prioridades(priorizacion_id):
    with obtener_motor().connect() as conexion:
        consulta = select(prioridades).where(prioridades.c.priorizacion_id == priorizacion_id)
        return pd.read_sql(consulta, conexion)


def leer_gestiones(carga_id, credito_id=None):
    """Gestiones de una carga (o de una cuenta), de la más reciente a la más antigua."""
    consulta = select(gestiones).where(gestiones.c.carga_id == carga_id)
    if credito_id is not None:
        consulta = consulta.where(gestiones.c.credito_id == credito_id)
    with obtener_motor().connect() as conexion:
        return pd.read_sql(consulta.order_by(gestiones.c.id.desc()), conexion)


def leer_auditoria(limite=500):
    with obtener_motor().connect() as conexion:
        consulta = select(auditoria).order_by(auditoria.c.id.desc()).limit(limite)
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
