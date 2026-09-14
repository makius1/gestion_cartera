# -*- coding: utf-8 -*-
"""
Administración de titulares y datos de contacto.

El gestor mantiene al día la información del titular desde el sistema, sin
esperar a la siguiente asignación: agrega el celular nuevo que le dictó el
titular, marca como errado el número que resultó ser de otra persona, corrige
el nombre o la ciudad.

Cada cambio recalcula qué canales tiene disponibles la cuenta, y el motor de
elegibilidad lo usa desde ese momento: si se marca errado el único celular, el
motor deja de ofrecer SMS y WhatsApp; si se agrega un correo, habilita EMAIL.

Protección de datos (Ley 1581 de 2012):
  * Los contactos se muestran enmascarados. Ver el dato completo es una
    acción explícita que queda en la auditoría con usuario y fecha.
  * Un contacto errado no se borra: queda como evidencia de que ese número no
    es del titular, para no volver a llamarlo si llega en otra asignación.
"""

import re

import pandas as pd
from sqlalchemy import insert, select, update

import config
from datos import base_datos as bd

TIPOS = {"CELULAR": "Celular", "FIJO": "Teléfono fijo", "EMAIL": "Correo electrónico"}
ESTADOS = {"SIN_VERIFICAR": "Sin verificar", "VALIDO": "Válido", "ERRADO": "Errado"}
INDICADOR = {"CELULAR": "tiene_celular", "FIJO": "tiene_fijo", "EMAIL": "tiene_email"}


def normalizar(tipo, valor):
    valor = (valor or "").strip()
    return valor.lower() if tipo == "EMAIL" else re.sub(r"[\s\-\.\(\)+]", "", valor)


def validar_contacto(tipo, valor):
    """Formato del dato según su tipo. Retorna un mensaje de error o None.

    Celular: diez dígitos que empiezan por 3. Fijo: diez dígitos que empiezan
    por 60 (numeración vigente desde 2021, con el indicativo de la región) o
    siete dígitos de la numeración anterior.
    """
    if tipo not in TIPOS:
        return "Tipo de contacto desconocido."
    if tipo == "CELULAR" and not re.fullmatch(r"3\d{9}", valor):
        return "Un celular debe tener diez dígitos y empezar por 3."
    if tipo == "FIJO" and not re.fullmatch(r"60\d{8}|\d{7}", valor):
        return "Un teléfono fijo debe tener diez dígitos y empezar por 60, o siete dígitos."
    if tipo == "EMAIL" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", valor):
        return "El correo no tiene un formato válido."
    return None


def enmascarar(tipo, valor):
    """Muestra lo justo para reconocer el dato sin exponerlo."""
    if tipo == "EMAIL":
        usuario, _, dominio = valor.partition("@")
        return "{}***@{}".format(usuario[:2], dominio)
    return "{}****{}".format(valor[:3], valor[-2:]) if len(valor) > 5 else "****"


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def leer_titular(cuenta_id):
    with bd.obtener_motor().connect() as conexion:
        fila = conexion.execute(select(bd.titulares).where(bd.titulares.c.cuenta_id == cuenta_id)).first()
    return dict(fila._mapping) if fila else None


def leer_contactos(cuenta_id):
    """Contactos del titular con el valor enmascarado (sin el valor completo)."""
    with bd.obtener_motor().connect() as conexion:
        tabla = pd.read_sql(select(bd.contactos).where(bd.contactos.c.cuenta_id == cuenta_id)
                            .order_by(bd.contactos.c.tipo, bd.contactos.c.id), conexion)
    tabla["mostrado"] = [enmascarar(t, v) for t, v in zip(tabla["tipo"], tabla["valor"])]
    return tabla.drop(columns=["valor"])


def revelar(contacto_id, usuario):
    """Valor completo de un contacto. Cada consulta queda en la auditoría."""
    with bd.obtener_motor().connect() as conexion:
        fila = conexion.execute(select(bd.contactos.c.cuenta_id, bd.contactos.c.tipo,
                                       bd.contactos.c.valor).where(bd.contactos.c.id == contacto_id)).first()
    if fila is None:
        raise LookupError("El contacto no existe.")
    bd.registrar_evento(usuario, "VER_CONTACTO", "titular {} · {} · contacto {}".format(
        fila.cuenta_id, fila.tipo, contacto_id))
    return fila.valor


# ---------------------------------------------------------------------------
# Cambios
# ---------------------------------------------------------------------------

def actualizar_indicadores(cuenta_id):
    """Recalcula los canales disponibles de todas las cuentas del titular.

    Un canal está disponible si el titular tiene al menos un contacto de ese
    tipo que no esté marcado como errado.
    """
    with bd.obtener_motor().begin() as conexion:
        tipos = set(conexion.execute(select(bd.contactos.c.tipo).where(
            bd.contactos.c.cuenta_id == cuenta_id, bd.contactos.c.estado != "ERRADO")).scalars())
        valores = {columna: tipo in tipos for tipo, columna in INDICADOR.items()}
        conexion.execute(update(bd.cartera).where(bd.cartera.c.cuenta_id == cuenta_id).values(**valores))
    return valores


def agregar_contacto(cuenta_id, tipo, valor, usuario):
    """Agrega un contacto confirmado por el gestor. Retorna los canales nuevos."""
    valor = normalizar(tipo, valor)
    error = validar_contacto(tipo, valor)
    if error:
        raise ValueError(error)
    with bd.obtener_motor().begin() as conexion:
        existente = conexion.execute(select(bd.contactos.c.estado).where(
            bd.contactos.c.cuenta_id == cuenta_id, bd.contactos.c.tipo == tipo,
            bd.contactos.c.valor == valor)).first()
        if existente is not None:
            if existente.estado == "ERRADO":
                raise ValueError("Ese dato ya está registrado como errado para este titular. "
                                 "Si se confirmó que sí le pertenece, márquelo como válido.")
            raise ValueError("Ese dato ya está registrado para este titular.")
        conexion.execute(insert(bd.contactos).values(
            cuenta_id=cuenta_id, tipo=tipo, valor=valor, estado="VALIDO", origen="GESTOR",
            creado=config.ahora(), creado_por=usuario[:40]))
    bd.registrar_evento(usuario, "AGREGAR_CONTACTO", "titular {} · {} {}".format(
        cuenta_id, tipo, enmascarar(tipo, valor)))
    return actualizar_indicadores(cuenta_id)


def cambiar_estado_contacto(contacto_id, estado, usuario):
    """Marca un contacto como válido o errado. Retorna los canales nuevos."""
    if estado not in ESTADOS:
        raise ValueError("Estado desconocido.")
    with bd.obtener_motor().begin() as conexion:
        fila = conexion.execute(select(bd.contactos.c.cuenta_id, bd.contactos.c.tipo).where(
            bd.contactos.c.id == contacto_id)).first()
        if fila is None:
            raise LookupError("El contacto no existe.")
        conexion.execute(update(bd.contactos).where(bd.contactos.c.id == contacto_id).values(
            estado=estado, actualizado=config.ahora(), actualizado_por=usuario[:40]))
    bd.registrar_evento(usuario, "ESTADO_CONTACTO", "titular {} · contacto {} ({}) marcado {}".format(
        fila.cuenta_id, contacto_id, fila.tipo, estado))
    return actualizar_indicadores(fila.cuenta_id)


def actualizar_titular(cuenta_id, nombre, ciudad, usuario):
    """Corrige el nombre o la ciudad del titular (o lo crea si no existía)."""
    nombre, ciudad = (nombre or "").strip()[:120], (ciudad or "").strip().upper()[:60]
    if len(nombre) < 3:
        raise ValueError("El nombre del titular es obligatorio.")
    with bd.obtener_motor().begin() as conexion:
        valores = {"nombre": nombre, "ciudad": ciudad, "actualizado": config.ahora(),
                   "actualizado_por": usuario[:40]}
        resultado = conexion.execute(update(bd.titulares).where(
            bd.titulares.c.cuenta_id == cuenta_id).values(**valores))
        if resultado.rowcount == 0:
            conexion.execute(insert(bd.titulares).values(cuenta_id=cuenta_id, **valores))
    bd.registrar_evento(usuario, "ACTUALIZAR_TITULAR", "titular {}".format(cuenta_id))
