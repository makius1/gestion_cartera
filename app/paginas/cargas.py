# -*- coding: utf-8 -*-
"""
Cargas de cartera.

Desde la web solo se generan carteras ficticias. La carga de una asignación
real se hace desde la terminal y únicamente contra la base local: subir datos
personales a un servicio en la nube tiene que ser una decisión explícita, no
un botón al alcance de cualquier usuario.
"""

import pandas as pd
import streamlit as st

import config
from app import comun
from datos import base_datos as bd

comun.exigir("gestionar_cargas")
comun.encabezado("Cargas", "Historial de carteras y generación de carteras ficticias")
usuario = comun.usuario_actual()["usuario"]

with st.container(border=True):
    st.subheader("Generar una cartera ficticia")
    st.caption("Se genera a partir del perfil estadístico de demostración. Los "
               "documentos, teléfonos y correos pertenecen a rangos reservados que "
               "no corresponden a personas reales.")
    with st.form("generar"):
        c1, c2 = st.columns(2)
        registros = c1.number_input("Cuentas", min_value=500, max_value=20000, value=5000, step=500)
        semilla = c2.number_input("Semilla", min_value=0, max_value=999999, value=config.SEMILLA,
                                  help="La misma semilla produce exactamente la misma cartera.")
        generar = st.form_submit_button("Generar y cargar", type="primary")

    if generar:
        from datos.cargador import cargar
        from datos.generador import generar as generar_bruto
        from datos.perfilador import cargar_perfil

        with st.spinner("Generando {} cuentas y guardándolas...".format(comun.numero(registros))):
            bruto = generar_bruto(cargar_perfil(), n=int(registros), semilla=int(semilla),
                                  fecha_referencia=config.hoy())
            carga_id = bd.registrar_carga(cargar(bruto=bruto), "SINTETICO", "generada_en_la_web",
                                          semilla=int(semilla))
        bd.registrar_evento(usuario, "CARGAR_CARTERA", "carga {}: {} cuentas ficticias, semilla {}".format(
            carga_id, registros, semilla))
        comun.limpiar_cache()
        st.success("Carga {} registrada con {} cuentas ficticias.".format(carga_id, comun.numero(registros)))

st.subheader("Historial de cargas")
tabla = comun.cargas()
if tabla.empty:
    st.info("Todavía no hay cargas.")
else:
    tabla = tabla.sort_values("id", ascending=False).copy()
    tabla["saldo_total"] = tabla["saldo_total"].map(comun.pesos)
    tabla["meta_recaudo"] = tabla["meta_recaudo"].map(comun.pesos)
    tabla["fecha_carga"] = pd.to_datetime(tabla["fecha_carga"]).dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(tabla, hide_index=True, use_container_width=True,
                 column_config={"id": "Carga", "fecha_carga": "Fecha", "origen": "Origen",
                                "archivo": "Archivo", "registros": "Cuentas",
                                "saldo_total": "Saldo", "meta_recaudo": "Meta", "semilla": "Semilla"})
