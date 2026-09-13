# -*- coding: utf-8 -*-
"""
Bitácora de auditoría.

Registro de solo lectura de todo lo que pasa en el sistema: ingresos, intentos
fallidos, bloqueos, cargas, ejecuciones del motor, descargas y cambios de
usuarios. No hay forma de editarlo ni de borrarlo desde la aplicación.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from app import comun
from datos import base_datos as bd

comun.exigir("ver_auditoria")
comun.encabezado("Auditoría", "Quién hizo qué y cuándo")

# Sin caché a propósito: la bitácora debe mostrarse siempre al día.
bitacora = bd.leer_auditoria(limite=5000)
if bitacora.empty:
    st.info("La bitácora está vacía.")
    st.stop()
bitacora["fecha"] = pd.to_datetime(bitacora["fecha"])

c1, c2, c3 = st.columns(3)
usuarios = c1.multiselect("Usuario", sorted(bitacora["usuario"].unique()))
acciones = c2.multiselect("Acción", sorted(bitacora["accion"].unique()))
desde, hasta = bitacora["fecha"].min().date(), bitacora["fecha"].max().date()
rango = c3.date_input("Periodo", value=(desde, hasta), min_value=desde, max_value=hasta,
                      format="YYYY-MM-DD")

filtrada = bitacora
if usuarios:
    filtrada = filtrada[filtrada["usuario"].isin(usuarios)]
if acciones:
    filtrada = filtrada[filtrada["accion"].isin(acciones)]
if isinstance(rango, tuple) and len(rango) == 2:
    filtrada = filtrada[filtrada["fecha"].dt.date.between(rango[0], rango[1])]

# Señales de alerta: los intentos fallidos y bloqueos son lo primero que se
# revisa ante una sospecha de acceso indebido.
fallidos = filtrada["accion"].isin(["INGRESO_FALLIDO", "INGRESO_RECHAZADO"]).sum()
bloqueos = (filtrada["accion"] == "BLOQUEO").sum()
c1, c2, c3 = st.columns(3)
c1.metric("Eventos", comun.numero(len(filtrada)))
c2.metric("Ingresos fallidos o rechazados", comun.numero(fallidos))
c3.metric("Bloqueos por intentos", comun.numero(bloqueos))

por_accion = filtrada["accion"].value_counts().rename_axis("accion").reset_index(name="eventos")
st.plotly_chart(px.bar(por_accion, x="accion", y="eventos", title="Eventos por acción",
                       labels={"accion": "", "eventos": "Eventos"}), use_container_width=True)

st.dataframe(filtrada.drop(columns=["id"]), hide_index=True, use_container_width=True, height=420,
             column_config={"fecha": st.column_config.DatetimeColumn("Fecha", format="YYYY-MM-DD HH:mm:ss"),
                            "usuario": "Usuario", "accion": "Acción",
                            "detalle": st.column_config.TextColumn("Detalle", width="large")})
