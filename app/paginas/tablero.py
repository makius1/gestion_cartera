# -*- coding: utf-8 -*-
"""
Tablero: la situación de la cartera frente a la meta, en una sola vista.

Responde las preguntas con las que empieza el día de un supervisor: cuánto se
asignó, cuánto hay que recaudar, cuánto está comprometido, cuánto falta, y qué
dijo el motor sobre a quién se puede contactar hoy.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from app import comun

comun.exigir("ver_tablero")
comun.encabezado("Tablero", "Situación de la cartera frente a la meta de recaudo")

carga = comun.selector_carga()
if carga is None:
    st.stop()
df = comun.cartera(int(carga["id"]))

# --- Indicadores principales ------------------------------------------------
saldo = float(df["saldo"].sum())
meta = saldo * config.META_PORCENTAJE
proyeccion = float(df["proyeccion"].sum())
brecha = max(meta - proyeccion, 0)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cuentas asignadas", comun.numero(len(df)))
c2.metric("Saldo asignado", comun.pesos(saldo))
c3.metric("Meta de recaudo ({:.0%})".format(config.META_PORCENTAJE), comun.pesos(meta))
c4.metric("Proyección comprometida", comun.pesos(proyeccion),
          "{} de la meta".format(comun.porcentaje(proyeccion / meta if meta else 0)))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Brecha por cubrir", comun.pesos(brecha))
c2.metric("Cuentas con gestión real", comun.porcentaje(df["gestionada"].mean()))
c3.metric("Cuentas con compromiso", comun.numero(df["tiene_compromiso"].sum()))
c4.metric("Excluidas de gestión", comun.numero((~df["gestionable"].astype(bool)).sum()))

st.progress(min(proyeccion / meta, 1.0) if meta else 0.0,
            text="Avance de la proyección sobre la meta")

# --- Composición de la cartera ------------------------------------------------
st.subheader("Composición de la cartera")
izquierda, derecha = st.columns(2)

por_franja = df.groupby("franja", as_index=False)["saldo"].sum().sort_values("saldo")
izquierda.plotly_chart(px.bar(por_franja, x="saldo", y="franja", orientation="h",
                              title="Saldo por franja", labels={"saldo": "Saldo", "franja": ""}),
                       use_container_width=True)

resultado = df["resultado_gestion"].value_counts().rename_axis("resultado").reset_index(name="cuentas")
derecha.plotly_chart(px.bar(resultado, x="cuentas", y="resultado", orientation="h",
                            title="Resultado de la última gestión",
                            labels={"cuentas": "Cuentas", "resultado": ""}),
                     use_container_width=True)

izquierda, derecha = st.columns(2)
mora = df["rango_mora"].value_counts().rename_axis("rango").reset_index(name="cuentas")
izquierda.plotly_chart(px.pie(mora, names="rango", values="cuentas", title="Cuentas por rango de mora",
                              hole=0.45), use_container_width=True)

acuerdos = (df[df["tiene_compromiso"].astype(bool)]
            .groupby("tipo_acuerdo", as_index=False)["proyeccion"].sum())
if acuerdos.empty:
    derecha.info("La carga no tiene compromisos de pago.")
else:
    derecha.plotly_chart(px.pie(acuerdos, names="tipo_acuerdo", values="proyeccion",
                                title="Proyección por tipo de acuerdo", hole=0.45),
                         use_container_width=True)

# --- Última decisión del motor --------------------------------------------------
st.subheader("Última ejecución del motor de elegibilidad")
ejecuciones = comun.ejecuciones()
ejecuciones = ejecuciones[ejecuciones["carga_id"] == int(carga["id"])]
if ejecuciones.empty:
    st.info("El motor todavía no se ha ejecutado sobre esta carga.")
else:
    ultima = ejecuciones.iloc[0]
    st.caption("Ejecución {} para el {} · realizada por {} el {}".format(
        int(ultima["id"]), pd.Timestamp(ultima["fecha_objetivo"]).strftime("%Y-%m-%d"),
        ultima["usuario"], pd.Timestamp(ultima["fecha"]).strftime("%Y-%m-%d %H:%M")))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Contactables", comun.numero(ultima["contactables"]))
    c2.metric("Recordatorios", comun.numero(ultima["recordatorio"]))
    c3.metric("En espera", comun.numero(ultima["en_espera"]))
    c4.metric("Bloqueadas", comun.numero(ultima["bloqueadas"]))
