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
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey,
                        Index, Integer, MetaData, Numeric, String, Table, Text,
                        create_engine, event, exc, func, insert, inspect, select,
                        text, update)

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


# --- Directorio de titulares -----------------------------------------------------
# La identidad y los contactos viven aparte de la cartera, unidos solo por el
# seudónimo del titular. El titular no depende de la carga: una misma persona
# aparece en varias asignaciones y sus datos se administran una sola vez.

titulares = Table(
    "titulares", metadatos,
    Column("cuenta_id", String(13), primary_key=True),
    Column("nombre", String(120)),
    # Solo los cuatro últimos dígitos: suficiente para confirmar identidad.
    Column("documento_enmascarado", String(20)),
    Column("ciudad", String(60)),
    Column("actualizado", DateTime),
    Column("actualizado_por", String(40)),
)

contactos = Table(
    "contactos", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cuenta_id", String(13), nullable=False),
    Column("tipo", String(10), nullable=False),          # CELULAR, FIJO o EMAIL
    Column("valor", String(120), nullable=False),
    # SIN_VERIFICAR al llegar en una carga; VALIDO o ERRADO según lo que
    # confirme el gestor. Un contacto errado no se borra: queda como evidencia de
    # que ese número no pertenece al titular y no se debe volver a marcar.
    Column("estado", String(15), nullable=False),
    Column("origen", String(10), nullable=False),        # CARGA o GESTOR
    Column("creado", DateTime, nullable=False),
    Column("creado_por", String(40), nullable=False),
    Column("actualizado", DateTime),
    Column("actualizado_por", String(40)),
)
Index("ix_contactos_cuenta", contactos.c.cuenta_id)


# --- Plan de trabajo -----------------------------------------------------------------
# El reparto de las cuentas del día entre los gestores. El avance no se guarda:
# se calcula cruzando las asignaciones con las gestiones registradas, así nunca
# puede quedar desactualizado.

planes = Table(
    "planes", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", Date, nullable=False),
    Column("carga_id", Integer, ForeignKey("cargas.id"), nullable=False),
    Column("priorizacion_id", Integer, ForeignKey("priorizaciones.id"), nullable=False),
    Column("gestores", Integer, nullable=False),
    Column("cupo", Integer, nullable=False),
    Column("cuentas", Integer, nullable=False),
    Column("creado", DateTime, nullable=False),
    Column("creado_por", String(40), nullable=False),
)

plan_asignaciones = Table(
    "plan_asignaciones", metadatos,
    Column("plan_id", Integer, ForeignKey("planes.id"), primary_key=True),
    Column("credito_id", String(13), primary_key=True),
    Column("gestor", String(40), nullable=False),
    Column("orden", Integer, nullable=False),
    Column("posicion", Integer),
    Column("prioridad", Float),
)
Index("ix_plan_gestor", plan_asignaciones.c.plan_id, plan_asignaciones.c.gestor)
Index("ux_contactos_valor", contactos.c.cuenta_id, contactos.c.tipo, contactos.c.valor, unique=True)


# ---------------------------------------------------------------------------
# 2. CONEXIÓN Y CREACIÓN
# ---------------------------------------------------------------------------

_MOTORES = {}

# Una conexión que estuvo quieta más de este tiempo se verifica antes de usarla.
SEGUNDOS_SIN_VERIFICAR = 60


def _verificar_si_estuvo_inactiva(motor):
    """Verificación de conexión solo cuando hace falta.

    Los servicios en la nube cierran las conexiones inactivas, y usar una
    conexión cerrada produce un error. La solución habitual (pool_pre_ping)
    manda una consulta de prueba antes de CADA uso: con una latencia de medio
    segundo hasta el servidor, eso duplica el tiempo de todas las consultas.
    Aquí la prueba solo se hace si la conexión lleva más de un minuto sin
    usarse, que es cuando de verdad puede haberse cerrado. Si la prueba falla,
    el grupo descarta esa conexión y entrega una nueva.
    """
    @event.listens_for(motor, "checkout")
    def _al_tomar(conexion_dbapi, registro, _proxy):
        ultimo = registro.info.get("ultimo_uso")
        if ultimo is not None and time.monotonic() - ultimo > SEGUNDOS_SIN_VERIFICAR:
            cursor = conexion_dbapi.cursor()
            try:
                cursor.execute("SELECT 1")
            except Exception:
                raise exc.DisconnectionError()
            finally:
                cursor.close()
        registro.info["ultimo_uso"] = time.monotonic()


def obtener_motor():
    """Devuelve la conexión definida en la configuración, reutilizándola.

    El motor se crea una sola vez por cadena de conexión y se reutiliza. No es
    un detalle: abrir una conexión cifrada hasta el servidor tarda varios
    segundos, y en la aplicación web cada pantalla hace varias consultas. Con
    el motor reutilizado, las conexiones quedan abiertas en un grupo y cada
    consulta tarda lo que tarda el viaje de ida y vuelta.
    """
    url = config.URL_BASE_DATOS
    if url not in _MOTORES:
        motor = create_engine(url, future=True, pool_recycle=1800)
        if motor.dialect.name != "sqlite":
            _verificar_si_estuvo_inactiva(motor)
        _MOTORES[url] = motor
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


# Cadenas de conexión cuyo esquema ya se verificó en este proceso.
_ESQUEMA_VERIFICADO = {}


def crear_esquema(motor=None, forzar=False):
    """Crea las tablas que falten y agrega las columnas nuevas. Idempotente.

    Se verifica una sola vez por proceso: la aplicación lo hace al arrancar y
    las llamadas siguientes no cuestan nada. Antes se verificaba en cada
    operación, y con la latencia de un servidor en la nube eso sumaba decenas
    de segundos por pantalla.

    La verificación usa tres consultas en total —tablas existentes, columnas
    existentes y tablas sin RLS— en lugar de una por tabla.

    En PostgreSQL además activa Row Level Security, pero solo en las tablas que
    no lo tienen. Supabase publica cada tabla en una API REST accesible con la
    llave pública del proyecto; con RLS activo y sin políticas, esa API no
    devuelve ninguna fila, y el sistema no se ve afectado porque se conecta como
    dueño de las tablas. Activarlo exige un bloqueo exclusivo de la tabla, que
    espera a que terminen todas las lecturas en curso; repetirlo en tablas que
    ya lo tienen congelaba la aplicación mientras alguien consultaba. Por
    seguridad, cualquier cambio de estructura espera como máximo diez segundos
    por un bloqueo en lugar de esperar indefinidamente.
    """
    motor = motor or obtener_motor()
    clave = str(motor.url)
    if clave in _ESQUEMA_VERIFICADO and not forzar:
        return _ESQUEMA_VERIFICADO[clave]

    postgres = motor.dialect.name == "postgresql"
    with motor.begin() as conexion:
        if postgres:
            conexion.execute(text("SET LOCAL lock_timeout = '10s'"))
        existentes = set(inspect(conexion).get_table_names())
        faltantes = [t for t in metadatos.sorted_tables if t.name not in existentes]
        if faltantes:
            metadatos.create_all(conexion, tables=faltantes, checkfirst=False)
        _migrar_columnas(conexion, existentes)
        if postgres:
            sin_rls = conexion.execute(text(
                "SELECT relname FROM pg_class WHERE relnamespace = current_schema()::regnamespace "
                "AND relkind = 'r' AND NOT relrowsecurity")).scalars().all()
            for nombre in sin_rls:
                if nombre in metadatos.tables:
                    conexion.execute(text('ALTER TABLE "{}" ENABLE ROW LEVEL SECURITY'.format(nombre)))

    _ESQUEMA_VERIFICADO[clave] = sorted(metadatos.tables)
    return _ESQUEMA_VERIFICADO[clave]


def _columnas_existentes(conexion, tablas):
    """Columnas actuales de cada tabla. En PostgreSQL con una sola consulta."""
    if conexion.dialect.name == "postgresql":
        filas = conexion.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema()"))
        columnas = {}
        for tabla, columna in filas:
            columnas.setdefault(tabla, set()).add(columna)
        return columnas
    inspector = inspect(conexion)
    return {t: {c["name"] for c in inspector.get_columns(t)} for t in tablas}


def _migrar_columnas(conexion, existentes):
    """Agrega a las tablas existentes las columnas que el esquema tiene de más.

    create_all crea las tablas que faltan, pero no modifica las que ya existen.
    Cuando el esquema crece —por ejemplo, al agregar los canales por tipo que
    necesita el motor de elegibilidad—, una base ya en uso quedaría sin esas
    columnas y las consultas fallarían. Esta función compara el esquema con la
    base real y agrega lo que falte, sin tocar ni borrar los datos existentes.

    Solo agrega columnas que admiten nulos: las filas antiguas quedan con esos
    campos vacíos y el sistema los trata como desconocidos.
    """
    actuales = _columnas_existentes(conexion, [t for t in metadatos.tables if t in existentes])
    agregadas = []
    for tabla in metadatos.sorted_tables:
        if tabla.name not in existentes:
            continue
        for columna in tabla.columns:
            if columna.name in actuales.get(tabla.name, set()) or not columna.nullable:
                continue
            tipo = columna.type.compile(dialect=conexion.dialect)
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


def _ids_existentes(conexion, columna, valores, *condiciones):
    """Valores de `columna` que ya existen, consultados por bloques de 1.000
    para no pasar miles de parámetros en una sola sentencia."""
    existentes = set()
    valores = list(valores)
    for inicio in range(0, len(valores), 1000):
        consulta = select(columna).where(columna.in_(valores[inicio:inicio + 1000]), *condiciones)
        existentes.update(conexion.execute(consulta).scalars())
    return existentes


def registrar_directorio(titulares_df, contactos_df, origen, usuario="sistema",
                         permitir_real_en_nube=False):
    """Agrega al directorio los titulares y contactos que aún no existen.

    No sobrescribe nada: si un gestor ya corrigió el nombre de un titular o
    marcó un teléfono como errado, una carga posterior no deshace ese trabajo.
    Aplica la misma protección que las cargas: datos reales solo en la base
    local, salvo confirmación explícita. Retorna (titulares_nuevos, contactos_nuevos).
    """
    if origen == "REAL" and not es_local() and not permitir_real_en_nube:
        raise PermissionError("Se intentó guardar el directorio de datos REALES en una base "
                              "remota ({}).".format(describir_motor()))
    motor = obtener_motor()
    crear_esquema(motor)
    ahora = config.ahora()
    with motor.begin() as conexion:
        existentes = _ids_existentes(conexion, titulares.c.cuenta_id, titulares_df["cuenta_id"])
        nuevos = titulares_df[~titulares_df["cuenta_id"].isin(existentes)].copy()
        nuevos["actualizado"], nuevos["actualizado_por"] = ahora, usuario
        filas = nuevos.to_dict(orient="records")
        for inicio in range(0, len(filas), 1000):
            conexion.execute(insert(titulares), filas[inicio:inicio + 1000])

        # Un contacto ya registrado se identifica por (titular, tipo, valor).
        claves = set()
        cuentas = contactos_df["cuenta_id"].unique().tolist()
        for inicio in range(0, len(cuentas), 1000):
            consulta = select(contactos.c.cuenta_id, contactos.c.tipo, contactos.c.valor).where(
                contactos.c.cuenta_id.in_(cuentas[inicio:inicio + 1000]))
            claves.update(tuple(f) for f in conexion.execute(consulta))
        clave = list(zip(contactos_df["cuenta_id"], contactos_df["tipo"], contactos_df["valor"]))
        faltantes = contactos_df[[c not in claves for c in clave]].copy()
        faltantes["estado"], faltantes["origen"] = "SIN_VERIFICAR", "CARGA"
        faltantes["creado"], faltantes["creado_por"] = ahora, usuario
        filas = faltantes.to_dict(orient="records")
        for inicio in range(0, len(filas), 1000):
            conexion.execute(insert(contactos), filas[inicio:inicio + 1000])
    return len(nuevos), len(faltantes)


def completar_columnas(carga_id, tabla, columnas):
    """Llena en la cartera de una carga las columnas que están vacías.

    Solo toca celdas nulas: lo que un gestor ya actualizó no se sobrescribe.
    En PostgreSQL se hace con una sola sentencia UPDATE ... FROM (VALUES ...)
    por bloque; fila por fila serían miles de viajes de ida y vuelta al
    servidor. Retorna la cantidad de filas procesadas.
    """
    motor = obtener_motor()
    filas = tabla[["credito_id"] + columnas].astype(object).where(tabla[["credito_id"] + columnas].notna(), None)
    registros = [tuple(f) for f in filas.itertuples(index=False)]
    with motor.begin() as conexion:
        if motor.dialect.name == "postgresql":
            from psycopg2.extras import execute_values
            # Cada valor se convierte al tipo de su columna: en una lista VALUES
            # PostgreSQL no sabe de qué tipo es un NULL.
            asignaciones = ", ".join('"{0}" = COALESCE(c."{0}", v."{0}"::{1})'.format(
                c, cartera.c[c].type.compile(dialect=motor.dialect)) for c in columnas)
            sentencia = ('UPDATE cartera AS c SET {} FROM (VALUES %s) AS v(credito_id, {}) '
                         'WHERE c.carga_id = {} AND c.credito_id = v.credito_id').format(
                asignaciones, ", ".join('"{}"'.format(c) for c in columnas), int(carga_id))
            cursor = conexion.connection.dbapi_connection.cursor()
            execute_values(cursor, sentencia, registros, page_size=1000)
        else:
            sentencia = text('UPDATE cartera SET {} WHERE carga_id = :carga AND credito_id = :credito'.format(
                ", ".join('"{0}" = COALESCE("{0}", :{0})'.format(c) for c in columnas)))
            conexion.execute(sentencia, [dict(zip(["credito"] + columnas, r), carga=int(carga_id))
                                         for r in registros])
    return len(registros)


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


def guardar_plan(plan, asignaciones):
    """Guarda un plan de trabajo con sus asignaciones. Retorna el id del plan."""
    motor = obtener_motor()
    crear_esquema(motor)
    with motor.begin() as conexion:
        plan_id = conexion.execute(insert(planes).values(**plan)).inserted_primary_key[0]
        filas = asignaciones.astype(object).where(asignaciones.notna(), None).to_dict(orient="records")
        for fila in filas:
            fila["plan_id"] = plan_id
        for inicio in range(0, len(filas), 1000):
            conexion.execute(insert(plan_asignaciones), filas[inicio:inicio + 1000])
    return plan_id


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


def listar_planes(limite=100):
    with obtener_motor().connect() as conexion:
        return pd.read_sql(select(planes).order_by(planes.c.id.desc()).limit(limite), conexion)


def leer_asignaciones(plan_id, gestor=None):
    consulta = select(plan_asignaciones).where(plan_asignaciones.c.plan_id == plan_id)
    if gestor is not None:
        consulta = consulta.where(plan_asignaciones.c.gestor == gestor)
    with obtener_motor().connect() as conexion:
        return pd.read_sql(consulta.order_by(plan_asignaciones.c.gestor, plan_asignaciones.c.orden), conexion)


def leer_gestiones_periodo(desde, hasta, usuario=None):
    """Gestiones entre dos fechas (inclusive), de todas las cargas."""
    consulta = select(gestiones).where(func.date(gestiones.c.fecha) >= desde,
                                       func.date(gestiones.c.fecha) <= hasta)
    if usuario is not None:
        consulta = consulta.where(gestiones.c.usuario == usuario)
    with obtener_motor().connect() as conexion:
        return pd.read_sql(consulta.order_by(gestiones.c.fecha), conexion)


def traza_cuenta(carga_id, credito_id, cuenta_id):
    """Línea de tiempo de todo lo que el sistema hizo con una cuenta.

    Reúne en un solo listado la carga, cada decisión del motor, cada
    priorización, cada asignación a un plan, cada gestión y cada cambio en los
    datos del titular. Es lo que se presenta ante una auditoría o una queja:
    qué se sabía de la cuenta, qué decidió el sistema y qué hizo el equipo.
    """
    eventos = []
    with obtener_motor().connect() as conexion:
        carga = conexion.execute(select(cargas).where(cargas.c.id == carga_id)).first()
        if carga:
            eventos.append((carga.fecha_carga, "Carga", "sistema",
                            "La cuenta llega en la carga {} ({})".format(carga_id, carga.origen)))
        for f in conexion.execute(
                select(ejecuciones_motor.c.fecha, ejecuciones_motor.c.usuario, ejecuciones_motor.c.fecha_objetivo,
                       evaluaciones.c.estado, evaluaciones.c.canal_recomendado, evaluaciones.c.regla_determinante)
                .join(evaluaciones, evaluaciones.c.ejecucion_id == ejecuciones_motor.c.id)
                .where(ejecuciones_motor.c.carga_id == carga_id, evaluaciones.c.credito_id == credito_id)):
            eventos.append((f.fecha, "Motor", f.usuario, "Para el {}: {}{} (regla {})".format(
                f.fecha_objetivo, f.estado, " por " + f.canal_recomendado if f.canal_recomendado else "",
                f.regla_determinante)))
        for f in conexion.execute(
                select(priorizaciones.c.fecha, priorizaciones.c.usuario, priorizaciones.c.metodo_elegido,
                       prioridades.c.posicion, prioridades.c.prioridad, prioridades.c.nombre_segmento)
                .join(prioridades, prioridades.c.priorizacion_id == priorizaciones.c.id)
                .where(priorizaciones.c.carga_id == carga_id, prioridades.c.credito_id == credito_id)):
            eventos.append((f.fecha, "Priorización", f.usuario, "{} · posición {} · prioridad {:.1f} ({})".format(
                f.nombre_segmento, f.posicion if f.posicion is not None else "fuera de la cola",
                f.prioridad or 0, f.metodo_elegido)))
        for f in conexion.execute(
                select(planes.c.creado, planes.c.creado_por, planes.c.fecha, plan_asignaciones.c.gestor,
                       plan_asignaciones.c.orden)
                .join(plan_asignaciones, plan_asignaciones.c.plan_id == planes.c.id)
                .where(planes.c.carga_id == carga_id, plan_asignaciones.c.credito_id == credito_id)):
            eventos.append((f.creado, "Plan de trabajo", f.creado_por,
                            "Asignada a {} para el {} (orden {})".format(f.gestor, f.fecha, f.orden)))
        for f in conexion.execute(select(gestiones).where(gestiones.c.carga_id == carga_id,
                                                          gestiones.c.credito_id == credito_id)):
            eventos.append((f.fecha, "Gestión", f.usuario, "{} {} por {}: {} · {}{} — {}".format(
                f.sentido.lower(), f.id, f.canal, f.resultado, f.codigo,
                " · acuerdo {:,.0f} para el {}".format(float(f.valor_acordado), f.fecha_compromiso)
                if f.valor_acordado else "", f.observacion)))
        for f in conexion.execute(select(auditoria).where(
                auditoria.c.accion.in_(["AGREGAR_CONTACTO", "ESTADO_CONTACTO", "VER_CONTACTO", "ACTUALIZAR_TITULAR"]),
                auditoria.c.detalle.like("%{}%".format(cuenta_id)))):
            eventos.append((f.fecha, "Titular", f.usuario, "{}: {}".format(f.accion, f.detalle)))
    tabla = pd.DataFrame(eventos, columns=["fecha", "evento", "usuario", "detalle"])
    return tabla.sort_values("fecha", ascending=False).reset_index(drop=True)


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
        from datos.cargador import extraer_directorio
        bruto = generar(cargar_perfil(), n=args.registros, semilla=args.semilla)
        carga_id = registrar_carga(cargar(bruto=bruto), "SINTETICO",
                                   "generada_en_memoria", semilla=args.semilla)
        titulares_n, contactos_n = registrar_directorio(*extraer_directorio(bruto), "SINTETICO", "terminal")
        print("  Carga {} registrada: {:,} cuentas simuladas, {:,} titulares y {:,} contactos nuevos"
              .format(carga_id, len(bruto), titulares_n, contactos_n))

    elif args.accion == "real":
        from datos.cargador import cargar, extraer_directorio, leer_bruto
        bruto = leer_bruto()
        carga_id = registrar_carga(cargar(bruto=bruto), "REAL", config.ARCHIVO_ASIGNACION)
        registrar_directorio(*extraer_directorio(bruto), "REAL", "terminal")
        print("  Carga {} registrada con la asignación real".format(carga_id))

    elif args.accion == "cargas":
        print(listar_cargas().to_string(index=False))
