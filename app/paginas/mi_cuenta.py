# -*- coding: utf-8 -*-
"""
Datos de la sesión y cambio de la contraseña propia.

Disponible para todos los roles. El cambio exige la contraseña actual: si
alguien encuentra una sesión abierta en un equipo desatendido, no puede
apropiarse de la cuenta cambiándole la contraseña.
"""

import pandas as pd
import streamlit as st

import config
from app import comun
from seguridad import autenticacion as auth

usuario = comun.usuario_actual()
comun.encabezado("Mi cuenta")

c1, c2, c3 = st.columns(3)
c1.metric("Usuario", usuario["usuario"])
c2.metric("Rol", usuario["rol"].capitalize())
ultimo = usuario.get("ultimo_ingreso")
c3.metric("Ingreso anterior", pd.Timestamp(ultimo).strftime("%Y-%m-%d %H:%M") if ultimo else "Primer ingreso")
st.caption("La sesión se cierra sola tras {} minutos sin actividad.".format(config.MINUTOS_INACTIVIDAD))

st.subheader("Cambiar contraseña")
with st.form("cambiar_clave", clear_on_submit=True):
    actual = st.text_input("Contraseña actual", type="password", autocomplete="current-password")
    nueva = st.text_input("Contraseña nueva", type="password", autocomplete="new-password",
                          help="Al menos {} caracteres, con letras y números.".format(
                              config.LONGITUD_MINIMA_CLAVE))
    repetida = st.text_input("Repita la contraseña nueva", type="password", autocomplete="new-password")
    if st.form_submit_button("Cambiar", type="primary"):
        if nueva != repetida:
            st.error("Las contraseñas nuevas no coinciden.")
        else:
            try:
                auth.cambiar_clave_propia(usuario["usuario"], actual, nueva)
                st.success("Contraseña actualizada.")
            except ValueError as error:
                st.error(str(error))
