# -*- coding: utf-8 -*-
"""
Utilidades compartidas por todas las pantallas de la aplicación web.

Tres responsabilidades:
  1. Sesión: quién está conectado, cierre por inactividad y revalidación
     periódica del usuario contra la base.
  2. Control de acceso: cada pantalla declara el permiso que exige y se detiene
     si el rol del usuario no lo tiene. El menú ya oculta las pantallas no
     permitidas, pero la verificación se repite dentro de cada una: ocultar un
     enlace no es un control de seguridad.
  3. Datos: lecturas de la base con caché, para no repetir la misma consulta en
     cada interacción, y formatos de presentación.
"""

from datetime import timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import select

import config
from datos import base_datos as bd
from seguridad import autenticacion as auth

# Cada cuánto se vuelve a consultar en la base si el usuario sigue activo y con
# el mismo rol. Si un administrador desactiva a alguien, esa persona pierde el
# acceso en menos de un minuto aunque tenga la sesión abierta.
SEGUNDOS_REVALIDACION = 60

COLORES_ESTADO = {"CONTACTABLE": "#2e7d32", "RECORDATORIO": "#1565c0",
                  "EN_ESPERA": "#f9a825", "BLOQUEADA": "#c62828"}


# ---------------------------------------------------------------------------
# 1. SESIÓN
# ---------------------------------------------------------------------------

def usuario_actual():
    return st.session_state.get("usuario")


def iniciar_sesion(usuario):
    st.session_state["usuario"] = usuario
    st.session_state["ultima_actividad"] = config.ahora()
    st.session_state["ultima_revalidacion"] = config.ahora()


def cerrar_sesion(motivo=None, registrar=True):
    usuario = usuario_actual()
    if usuario and registrar:
        bd.registrar_evento(usuario["usuario"], "SALIDA", motivo or "cierre voluntario")
    # Se borra todo el estado, no solo el usuario: filtros, resultados y
    # selecciones de la sesión anterior no deben quedar a la vista del siguiente.
    st.session_state.clear()
    if motivo:
        st.session_state["aviso_salida"] = motivo


def controlar_sesion():
    """Se ejecuta en cada interacción. Retorna False si la sesión terminó."""
    usuario = usuario_actual()
    if not usuario:
        return False
    ahora = config.ahora()

    limite = timedelta(minutes=config.MINUTOS_INACTIVIDAD)
    if ahora - st.session_state.get("ultima_actividad", ahora) > limite:
        cerrar_sesion("Sesión cerrada por {} minutos de inactividad.".format(
            config.MINUTOS_INACTIVIDAD))
        return False
    st.session_state["ultima_actividad"] = ahora

    ultima = st.session_state.get("ultima_revalidacion", ahora)
    if (ahora - ultima).total_seconds() > SEGUNDOS_REVALIDACION:
        with bd.obtener_motor().connect() as conexion:
            fila = conexion.execute(select(bd.usuarios.c.rol, bd.usuarios.c.activo).where(
                bd.usuarios.c.usuario == usuario["usuario"])).first()
        if fila is None or not fila.activo:
            cerrar_sesion("El usuario fue desactivado por un administrador.")
            return False
        usuario["rol"] = fila.rol
        st.session_state["ultima_revalidacion"] = ahora
    return True


# ---------------------------------------------------------------------------
# 2. CONTROL DE ACCESO
# ---------------------------------------------------------------------------

def puede(permiso):
    usuario = usuario_actual()
    return bool(usuario) and auth.puede(usuario["rol"], permiso)


def exigir(permiso):
    if not puede(permiso):
        st.error("No tiene permiso para ver esta pantalla.")
        st.stop()


def encabezado(titulo, descripcion=None):
    st.title(titulo)
    if descripcion:
        st.caption(descripcion)


# ---------------------------------------------------------------------------
# 3. DATOS Y FORMATOS
# ---------------------------------------------------------------------------
# La caché se guarda por parámetros: la cartera de la carga 3 se consulta una
# vez y se reutiliza hasta que vence o hasta que alguien registra una carga
# nueva, momento en que se limpia.

@st.cache_data(ttl=600, show_spinner="Consultando cargas...")
def cargas():
    return bd.listar_cargas()


@st.cache_data(ttl=600, show_spinner="Consultando la cartera...")
def cartera(carga_id):
    return bd.leer_cartera(carga_id)


@st.cache_data(ttl=120, show_spinner="Consultando ejecuciones...")
def ejecuciones():
    return bd.listar_ejecuciones(200)


@st.cache_data(ttl=600, show_spinner="Consultando resultados del motor...")
def evaluaciones(ejecucion_id):
    return bd.leer_evaluaciones(ejecucion_id)


def limpiar_cache():
    st.cache_data.clear()


def pesos(valor):
    """Formato de moneda colombiano: punto como separador de miles."""
    if valor is None or pd.isna(valor):
        return "—"
    return "$ {:,.0f}".format(float(valor)).replace(",", ".")


def numero(valor):
    return "{:,.0f}".format(float(valor)).replace(",", ".")


def porcentaje(valor):
    return "{:.1f} %".format(float(valor) * 100).replace(".", ",")


def selector_carga(clave="carga"):
    """Selector de carga compartido. Retorna la fila de la carga elegida o
    None si no hay cargas. Por defecto propone la más reciente."""
    tabla = cargas()
    if tabla.empty:
        st.info("Todavía no hay carteras cargadas. Un supervisor o administrador "
                "puede generar una desde la pantalla Cargas.")
        return None
    tabla = tabla.sort_values("id", ascending=False)
    etiquetas = {int(f.id): "Carga {} · {} · {} cuentas · {}".format(
        int(f.id), f.origen, numero(f.registros), pd.Timestamp(f.fecha_carga).strftime("%Y-%m-%d %H:%M"))
        for f in tabla.itertuples()}
    elegido = st.selectbox("Carga", list(etiquetas), format_func=etiquetas.get, key=clave)
    fila = tabla[tabla["id"] == elegido].iloc[0]
    if fila["origen"] == "SINTETICO":
        st.caption("Cartera ficticia: ningún dato corresponde a una persona real.")
    return fila
