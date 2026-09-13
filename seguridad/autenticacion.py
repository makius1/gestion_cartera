# -*- coding: utf-8 -*-
"""
Autenticación, usuarios y roles.

Este módulo no depende de la interfaz: la aplicación web lo usa para el
ingreso, y la terminal lo usa una sola vez para crear el primer administrador.
Así las reglas de seguridad son las mismas por cualquier vía y se pueden probar
sin abrir el navegador.

Decisiones de seguridad:

  * Las contraseñas nunca se guardan. Se guarda una derivación con scrypt y una
    sal aleatoria por usuario. scrypt es lento y consume memoria a propósito:
    probar millones de contraseñas contra una base robada se vuelve costoso. Un
    SHA-256 simple, en cambio, se calcula miles de millones de veces por segundo
    en una tarjeta gráfica.
  * La comparación final se hace en tiempo constante (hmac.compare_digest), para
    no revelar por el tiempo de respuesta cuántos caracteres coinciden.
  * Ante un error de ingreso el mensaje es siempre el mismo, exista o no el
    usuario: no se le confirma a un atacante qué usuarios existen. Por la misma
    razón, con un usuario inexistente también se calcula un scrypt, para que el
    tiempo de respuesta no lo delate.
  * Tras varios intentos fallidos seguidos, la cuenta se bloquea unos minutos.
  * Todo ingreso, intento fallido, bloqueo y cambio de usuarios queda en la
    bitácora de auditoría.

Uso (solo para crear el primer administrador):
    python -m seguridad.autenticacion crear-admin
"""

import base64
import getpass
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import func, insert, select, update

import config
from datos import base_datos as bd

ROLES = list(config.PERMISOS)
MENSAJE_ERROR_INGRESO = "Usuario o contraseña incorrectos."

# Parámetros de scrypt: 2^15 iteraciones de memoria con bloques de 8 usan unos
# 32 MB y tardan alrededor de una décima de segundo por intento. Imperceptible
# para una persona, prohibitivo para un ataque masivo.
_N, _R, _P, _LARGO = 2 ** 15, 8, 1, 64
_MEMORIA = 64 * 1024 * 1024

# Contraseñas que aparecen primero en cualquier diccionario de ataque.
_COMUNES = {"1234567890", "0123456789", "contraseña", "contrasena", "password",
            "qwertyuiop", "administrador", "cobranza123", "colombia123", "123456789a"}


# ---------------------------------------------------------------------------
# 1. CONTRASEÑAS
# ---------------------------------------------------------------------------

def derivar_clave(clave):
    """Derivación scrypt con sal aleatoria, en un formato que guarda los
    parámetros junto al resultado. Si en el futuro se endurecen los parámetros,
    las claves antiguas se siguen pudiendo verificar."""
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=_N, r=_R, p=_P,
                              maxmem=_MEMORIA, dklen=_LARGO)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(sal).decode(), base64.b64encode(derivada).decode())


def verificar_clave(clave, almacenada):
    try:
        _, n, r, p, sal, esperada = almacenada.split("$")
        derivada = hashlib.scrypt(clave.encode("utf-8"), salt=base64.b64decode(sal),
                                  n=int(n), r=int(r), p=int(p), maxmem=_MEMORIA,
                                  dklen=len(base64.b64decode(esperada)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivada, base64.b64decode(esperada))


# Derivación de referencia para igualar tiempos con usuarios inexistentes. Se
# calcula la primera vez que se necesita, no al importar el módulo.
_REFERENCIA = []


def _derivacion_de_referencia():
    if not _REFERENCIA:
        _REFERENCIA.append(derivar_clave(secrets.token_urlsafe(16)))
    return _REFERENCIA[0]


def validar_politica(clave, usuario=""):
    """Errores de la contraseña frente a la política. Lista vacía si cumple."""
    errores = []
    if len(clave) < config.LONGITUD_MINIMA_CLAVE:
        errores.append("debe tener al menos {} caracteres".format(config.LONGITUD_MINIMA_CLAVE))
    if not re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", clave) or not re.search(r"\d", clave):
        errores.append("debe combinar letras y números")
    if usuario and usuario.lower() in clave.lower():
        errores.append("no puede contener el nombre de usuario")
    if clave.lower() in _COMUNES:
        errores.append("es una contraseña demasiado común")
    return errores


def normalizar_usuario(usuario):
    return (usuario or "").strip().lower()


def _validar_nombre_usuario(usuario):
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", usuario):
        raise ValueError("El usuario debe tener entre 3 y 40 caracteres: letras "
                         "minúsculas, números, punto, guion o guion bajo.")


# ---------------------------------------------------------------------------
# 2. INGRESO
# ---------------------------------------------------------------------------

def _publico(fila):
    """Datos del usuario que pueden circular por la aplicación: todo menos la
    derivación de la contraseña."""
    return {"usuario": fila.usuario, "nombre": fila.nombre, "rol": fila.rol,
            "ultimo_ingreso": fila.ultimo_ingreso}


def autenticar(usuario, clave):
    """Verifica un intento de ingreso. Retorna (usuario_publico, mensaje).

    Si el ingreso es correcto, usuario_publico trae los datos de la sesión y el
    mensaje es None. Si no, usuario_publico es None y el mensaje explica el
    rechazo sin revelar si el usuario existe.
    """
    usuario = normalizar_usuario(usuario)
    motor = bd.obtener_motor()
    bd.crear_esquema(motor)
    ahora = config.ahora()

    with motor.connect() as conexion:
        fila = conexion.execute(
            select(bd.usuarios).where(bd.usuarios.c.usuario == usuario)).first()

    if fila is None or not fila.activo:
        verificar_clave(clave, _derivacion_de_referencia())
        bd.registrar_evento(usuario or "(vacío)", "INGRESO_FALLIDO",
                            "usuario inexistente o inactivo")
        return None, MENSAJE_ERROR_INGRESO

    if fila.bloqueado_hasta and fila.bloqueado_hasta > ahora:
        bd.registrar_evento(usuario, "INGRESO_RECHAZADO", "cuenta bloqueada temporalmente")
        return None, "Cuenta bloqueada temporalmente por intentos fallidos. Intente después de las {}.".format(
            fila.bloqueado_hasta.strftime("%H:%M"))

    if not verificar_clave(clave, fila.hash_clave):
        intentos = (fila.intentos_fallidos or 0) + 1
        cambios = {"intentos_fallidos": intentos}
        if intentos >= config.INTENTOS_MAXIMOS:
            cambios = {"intentos_fallidos": 0,
                       "bloqueado_hasta": ahora + timedelta(minutes=config.MINUTOS_BLOQUEO)}
        with motor.begin() as conexion:
            conexion.execute(update(bd.usuarios).where(bd.usuarios.c.id == fila.id).values(**cambios))
        if "bloqueado_hasta" in cambios:
            bd.registrar_evento(usuario, "BLOQUEO", "{} intentos fallidos seguidos".format(intentos))
            return None, "Demasiados intentos fallidos. La cuenta queda bloqueada {} minutos.".format(
                config.MINUTOS_BLOQUEO)
        bd.registrar_evento(usuario, "INGRESO_FALLIDO", "contraseña incorrecta ({} de {})".format(
            intentos, config.INTENTOS_MAXIMOS))
        return None, MENSAJE_ERROR_INGRESO

    with motor.begin() as conexion:
        conexion.execute(update(bd.usuarios).where(bd.usuarios.c.id == fila.id).values(
            intentos_fallidos=0, bloqueado_hasta=None, ultimo_ingreso=ahora))
    bd.registrar_evento(usuario, "INGRESO", "rol {}".format(fila.rol))
    return _publico(fila), None


def puede(rol, permiso):
    return permiso in config.PERMISOS.get(rol, set())


# ---------------------------------------------------------------------------
# 3. ADMINISTRACIÓN DE USUARIOS
# ---------------------------------------------------------------------------

def hay_usuarios():
    motor = bd.obtener_motor()
    bd.crear_esquema(motor)
    with motor.connect() as conexion:
        return conexion.execute(select(func.count()).select_from(bd.usuarios)).scalar() > 0


def listar_usuarios():
    """Usuarios sin la derivación de la contraseña."""
    import pandas as pd
    columnas = [c for c in bd.usuarios.columns if c.name != "hash_clave"]
    with bd.obtener_motor().connect() as conexion:
        return pd.read_sql(select(*columnas).order_by(bd.usuarios.c.usuario), conexion)


def crear_usuario(usuario, nombre, rol, clave, creado_por):
    usuario = normalizar_usuario(usuario)
    _validar_nombre_usuario(usuario)
    if rol not in ROLES:
        raise ValueError("Rol desconocido: {}".format(rol))
    if not nombre.strip():
        raise ValueError("El nombre es obligatorio.")
    errores = validar_politica(clave, usuario)
    if errores:
        raise ValueError("La contraseña " + "; ".join(errores) + ".")

    motor = bd.obtener_motor()
    bd.crear_esquema(motor)
    with motor.begin() as conexion:
        existe = conexion.execute(
            select(bd.usuarios.c.id).where(bd.usuarios.c.usuario == usuario)).first()
        if existe:
            raise ValueError("Ya existe el usuario '{}'.".format(usuario))
        conexion.execute(insert(bd.usuarios).values(
            usuario=usuario, nombre=nombre.strip()[:80], rol=rol,
            hash_clave=derivar_clave(clave), activo=True, creado=config.ahora(),
            intentos_fallidos=0))
    bd.registrar_evento(creado_por, "CREAR_USUARIO", "{} con rol {}".format(usuario, rol))


def _actualizar(usuario, **valores):
    with bd.obtener_motor().begin() as conexion:
        resultado = conexion.execute(update(bd.usuarios).where(
            bd.usuarios.c.usuario == normalizar_usuario(usuario)).values(**valores))
    if resultado.rowcount == 0:
        raise ValueError("No existe el usuario '{}'.".format(usuario))


def _administradores_activos():
    with bd.obtener_motor().connect() as conexion:
        return conexion.execute(select(func.count()).select_from(bd.usuarios).where(
            bd.usuarios.c.rol == "ADMINISTRADOR", bd.usuarios.c.activo.is_(True))).scalar()


def _es_admin_activo(usuario):
    with bd.obtener_motor().connect() as conexion:
        fila = conexion.execute(select(bd.usuarios.c.rol, bd.usuarios.c.activo).where(
            bd.usuarios.c.usuario == normalizar_usuario(usuario))).first()
    return bool(fila) and fila.rol == "ADMINISTRADOR" and fila.activo


def cambiar_estado(usuario, activo, responsable):
    """Activa o desactiva un usuario. Los usuarios no se borran: la bitácora
    los sigue nombrando y debe poder saberse quiénes fueron."""
    if normalizar_usuario(usuario) == normalizar_usuario(responsable) and not activo:
        raise ValueError("Un usuario no puede desactivarse a sí mismo.")
    if not activo and _es_admin_activo(usuario) and _administradores_activos() <= 1:
        raise ValueError("No se puede desactivar al único administrador activo.")
    _actualizar(usuario, activo=activo)
    bd.registrar_evento(responsable, "ACTIVAR_USUARIO" if activo else "DESACTIVAR_USUARIO", usuario)


def cambiar_rol(usuario, rol, responsable):
    if rol not in ROLES:
        raise ValueError("Rol desconocido: {}".format(rol))
    if rol != "ADMINISTRADOR" and _es_admin_activo(usuario) and _administradores_activos() <= 1:
        raise ValueError("No se puede quitar el rol al único administrador activo.")
    _actualizar(usuario, rol=rol)
    bd.registrar_evento(responsable, "CAMBIAR_ROL", "{} ahora es {}".format(usuario, rol))


def restablecer_clave(usuario, nueva, responsable):
    """Un administrador asigna una contraseña nueva y desbloquea la cuenta."""
    errores = validar_politica(nueva, normalizar_usuario(usuario))
    if errores:
        raise ValueError("La contraseña " + "; ".join(errores) + ".")
    _actualizar(usuario, hash_clave=derivar_clave(nueva), intentos_fallidos=0, bloqueado_hasta=None)
    bd.registrar_evento(responsable, "RESTABLECER_CLAVE", usuario)


def cambiar_clave_propia(usuario, actual, nueva):
    """El propio usuario cambia su contraseña; debe conocer la actual."""
    with bd.obtener_motor().connect() as conexion:
        fila = conexion.execute(select(bd.usuarios.c.hash_clave).where(
            bd.usuarios.c.usuario == normalizar_usuario(usuario))).first()
    if fila is None or not verificar_clave(actual, fila.hash_clave):
        raise ValueError("La contraseña actual no es correcta.")
    if actual == nueva:
        raise ValueError("La contraseña nueva debe ser distinta de la actual.")
    errores = validar_politica(nueva, normalizar_usuario(usuario))
    if errores:
        raise ValueError("La contraseña " + "; ".join(errores) + ".")
    _actualizar(usuario, hash_clave=derivar_clave(nueva))
    bd.registrar_evento(usuario, "CAMBIAR_CLAVE", "cambio de contraseña propia")


# ---------------------------------------------------------------------------
# 4. PRIMER ADMINISTRADOR
# ---------------------------------------------------------------------------
# La aplicación web no permite crear el primer usuario: si lo hiciera, la
# primera persona que abriera la dirección pública se volvería administradora.
# Se crea una sola vez desde la terminal, con acceso a la base; después todo se
# administra desde la aplicación.

if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["crear-admin"]:
        print("Uso: python -m seguridad.autenticacion crear-admin")
        raise SystemExit(1)

    print("CREACIÓN DE ADMINISTRADOR — base: {}".format(bd.describir_motor()))
    print("-" * 60)
    usuario = normalizar_usuario(input("Usuario: "))
    nombre = input("Nombre completo: ")
    print("La contraseña debe tener al menos {} caracteres, con letras y números.".format(
        config.LONGITUD_MINIMA_CLAVE))
    clave = getpass.getpass("Contraseña (no se mostrará): ")
    if clave != getpass.getpass("Repita la contraseña: "):
        print("  Las contraseñas no coinciden.")
        raise SystemExit(1)
    try:
        crear_usuario(usuario, nombre, "ADMINISTRADOR", clave, creado_por="terminal")
    except ValueError as error:
        print("  " + str(error))
        raise SystemExit(1)
    print("  Administrador '{}' creado. Ya puede ingresar a la aplicación web.".format(usuario))
