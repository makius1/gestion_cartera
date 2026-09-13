# -*- coding: utf-8 -*-
"""
Consulta de la cartera.

Muestra la cartera ya procesada y seudonimizada: los identificadores son
seudónimos y no hay nombres, documentos, teléfonos ni correos. Los filtros
permiten armar los grupos con los que trabaja un supervisor, por ejemplo las
cuentas nunca gestionadas de las franjas de saldo más altas.
"""

import streamlit as st

from app import comun
from datos import base_datos as bd

comun.exigir("ver_cartera")
comun.encabezado("Cartera", "Cuentas de la carga, seudonimizadas, con filtros de trabajo")

carga = comun.selector_carga()
if carga is None:
    st.stop()
df = comun.cartera(int(carga["id"]))

# --- Filtros -------------------------------------------------------------------
with st.expander("Filtros", expanded=True):
    c1, c2, c3 = st.columns(3)
    franjas = c1.multiselect("Franja de saldo", sorted(df["franja"].dropna().unique()))
    moras = c2.multiselect("Rango de mora", sorted(df["rango_mora"].dropna().unique()))
    codigos = c3.multiselect("Código de gestión", sorted(df["codigo"].dropna().unique()))
    c1, c2, c3 = st.columns(3)
    resultados = c1.multiselect("Resultado de la última gestión",
                                sorted(df["resultado_gestion"].dropna().unique()))
    gestion = c2.radio("Gestión real", ["Todas", "Con gestión", "Sin gestión"], horizontal=True)
    compromiso = c3.radio("Compromiso", ["Todas", "Con compromiso", "Sin compromiso"], horizontal=True)

filtrado = df
if franjas:
    filtrado = filtrado[filtrado["franja"].isin(franjas)]
if moras:
    filtrado = filtrado[filtrado["rango_mora"].isin(moras)]
if codigos:
    filtrado = filtrado[filtrado["codigo"].isin(codigos)]
if resultados:
    filtrado = filtrado[filtrado["resultado_gestion"].isin(resultados)]
if gestion != "Todas":
    filtrado = filtrado[filtrado["gestionada"].astype(bool) == (gestion == "Con gestión")]
if compromiso != "Todas":
    filtrado = filtrado[filtrado["tiene_compromiso"].astype(bool) == (compromiso == "Con compromiso")]

c1, c2, c3 = st.columns(3)
c1.metric("Cuentas", comun.numero(len(filtrado)))
c2.metric("Saldo", comun.pesos(filtrado["saldo"].sum()))
c3.metric("Margen negociable", comun.pesos(filtrado["margen_negociacion"].sum()))

# --- Tabla ---------------------------------------------------------------------
columnas = ["credito_id", "cuenta_id", "saldo", "cobranza_min", "cobranza_max", "dias_mora",
            "franja", "rango_mora", "codigo", "resultado_gestion", "fecha_ultima_gestion",
            "fecha_compromiso", "proyeccion", "tiene_celular", "tiene_fijo", "tiene_email"]
dinero = {"saldo", "cobranza_min", "cobranza_max", "proyeccion"}
st.dataframe(
    filtrado[columnas].sort_values("saldo", ascending=False),
    hide_index=True, use_container_width=True, height=480,
    column_config={
        "credito_id": "Crédito", "cuenta_id": "Titular",
        **{c: st.column_config.NumberColumn(c.replace("_", " ").capitalize(), format="$ %d")
           for c in dinero},
        "dias_mora": st.column_config.NumberColumn("Días de mora"),
        "fecha_ultima_gestion": st.column_config.DateColumn("Última gestión"),
        "fecha_compromiso": st.column_config.DateColumn("Compromiso"),
        "tiene_celular": st.column_config.CheckboxColumn("Celular"),
        "tiene_fijo": st.column_config.CheckboxColumn("Fijo"),
        "tiene_email": st.column_config.CheckboxColumn("Correo"),
    },
)

# Toda descarga queda en la bitácora: sacar datos del sistema es una de las
# acciones que una auditoría de protección de datos pide rastrear.
usuario = comun.usuario_actual()["usuario"]
st.download_button("Descargar selección (CSV)", filtrado[columnas].to_csv(index=False).encode("utf-8"),
                   file_name="cartera_carga_{}.csv".format(int(carga["id"])), mime="text/csv",
                   on_click=bd.registrar_evento,
                   args=(usuario, "EXPORTAR_CARTERA", "carga {}: {} cuentas".format(
                       int(carga["id"]), len(filtrado))))
