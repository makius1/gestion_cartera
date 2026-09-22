# -*- coding: utf-8 -*-
"""
Cargas de cartera.

Desde la web se registran carteras simuladas y se completan las cargas a las
que les faltan datos. La carga de una asignación desde archivo se hace desde la
terminal y únicamente contra la base local: subir datos personales a un
servicio en la nube tiene que ser una decisión explícita, no un botón al
alcance de cualquier usuario.
"""

import pandas as pd
import streamlit as st

import config
from app import comun
from datos import base_datos as bd

comun.exigir("gestionar_cargas")
comun.encabezado("Cargas", "Historial de carteras, simulación y completado de cargas")
usuario = comun.usuario_actual()["usuario"]

aviso = st.session_state.pop("aviso_cargas", None)
if aviso:
    st.success(aviso)

with st.container(border=True):
    st.subheader("Simular una cartera")
    st.caption("Se genera a partir del perfil estadístico de referencia, junto con el directorio "
               "de titulares y sus contactos. Los documentos, teléfonos y correos pertenecen a "
               "rangos reservados que no corresponden a personas.")
    with st.form("generar"):
        c1, c2 = st.columns(2)
        registros = c1.number_input("Cuentas", min_value=500, max_value=20000, value=5000, step=500)
        semilla = c2.number_input("Semilla", min_value=0, max_value=999999, value=config.SEMILLA,
                                  help="La misma semilla produce exactamente la misma cartera.")
        generar = st.form_submit_button("Generar y cargar", type="primary")

    if generar:
        from datos.cargador import cargar, extraer_directorio
        from datos.generador import generar as generar_bruto
        from datos.perfilador import cargar_perfil

        try:
            with st.spinner("Generando {} cuentas y guardándolas...".format(comun.numero(registros))):
                bruto = generar_bruto(cargar_perfil(), n=int(registros), semilla=int(semilla),
                                      fecha_referencia=config.hoy())
                carga_id = bd.registrar_carga(cargar(bruto=bruto), "SINTETICO", "generada_en_la_web",
                                              semilla=int(semilla))
                titulares_n, contactos_n = bd.registrar_directorio(
                    *extraer_directorio(bruto), "SINTETICO", usuario)
        except PermissionError as error:
            st.error(str(error))
        else:
            bd.registrar_evento(usuario, "CARGAR_CARTERA", "carga {}: {} cuentas simuladas, semilla {}".format(
                carga_id, registros, semilla))
            comun.limpiar_cache()
            st.session_state["aviso_cargas"] = (
                "Carga {} registrada con {} cuentas; {} titulares y {} contactos nuevos en el directorio."
                .format(carga_id, comun.numero(registros), comun.numero(titulares_n), comun.numero(contactos_n)))
            st.rerun()

# --- Completar cargas incompletas ------------------------------------------------
incompletas = sorted(comun.cargas_incompletas())
if incompletas:
    with st.container(border=True):
        st.subheader("Completar cargas incompletas")
        st.caption("Estas cargas se registraron antes de que el sistema guardara los canales de "
                   "contacto y la fecha del último contacto; el motor las bloquea completas. Una "
                   "carga simulada se reconstruye de forma exacta con su semilla y se verifica "
                   "cuenta por cuenta antes de escribir. Solo se llenan los datos vacíos.")
        elegida = st.selectbox("Carga", incompletas, format_func=lambda i: "Carga {}".format(i))
        if st.button("Completar datos de contacto", icon=":material/build:"):
            from datos.completar import completar_carga
            try:
                with st.spinner("Reconstruyendo y verificando la carga {}...".format(elegida)):
                    resultado = completar_carga(elegida, usuario)
            except (ValueError, LookupError, PermissionError) as error:
                st.error(str(error))
            else:
                comun.limpiar_cache()
                st.session_state["aviso_cargas"] = (
                    "Carga {carga_id} completada: {cuentas_completadas} cuentas, {titulares_nuevos} "
                    "titulares y {contactos_nuevos} contactos nuevos.".format(**resultado))
                st.rerun()

st.subheader("Historial de cargas")
tabla = comun.cargas()
if tabla.empty:
    st.info("Todavía no hay cargas.")
else:
    tabla = tabla.sort_values("id", ascending=False).copy()
    tabla["estado"] = tabla["id"].map(lambda i: "Incompleta" if i in incompletas else "Completa")
    tabla["saldo_total"] = tabla["saldo_total"].map(comun.pesos)
    tabla["meta_recaudo"] = tabla["meta_recaudo"].map(comun.pesos)
    tabla["fecha_carga"] = pd.to_datetime(tabla["fecha_carga"]).dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(tabla, hide_index=True, use_container_width=True,
                 column_config={"id": "Carga", "fecha_carga": "Fecha", "origen": "Origen",
                                "archivo": "Archivo", "registros": "Cuentas", "estado": "Estado",
                                "saldo_total": "Saldo", "meta_recaudo": "Meta", "semilla": "Semilla"})
