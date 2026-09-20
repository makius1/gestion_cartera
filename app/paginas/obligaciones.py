# -*- coding: utf-8 -*-
"""
Obligación nueva.

El supervisor da de alta un crédito puntual —el que llegó después del corte
del mes, o el que se omitió por error— sin tener que preparar y subir un
archivo de asignación completo. Ver gestion/obligaciones.py para el porqué de
cada regla.
"""

import streamlit as st

import config
from app import comun
from datos import base_datos as bd
from gestion import obligaciones as ob
from gestion import titulares as tit

comun.exigir("gestionar_obligaciones")
comun.encabezado("Obligación nueva", "Registra un crédito con su titular y contactos sin hacer una carga completa")
usuario = comun.usuario_actual()["usuario"]

aviso = st.session_state.pop("aviso_obligacion", None)
if aviso:
    st.success(aviso)

cargas = bd.listar_cargas()
if cargas.empty:
    st.info("No hay ninguna carga todavía. Registre o genere una carga primero, desde la pantalla Cargas.")
    st.stop()

etiqueta_carga = {int(fila["id"]): "Carga #{} · {} · {} cuentas".format(
    int(fila["id"]), fila["fecha_carga"].strftime("%Y-%m-%d"), int(fila["registros"]))
    for _, fila in cargas.iterrows()}
carga_id = st.selectbox("Carga a la que pertenece la obligación", list(etiqueta_carga),
                        index=len(etiqueta_carga) - 1, format_func=etiqueta_carga.get,
                        help="La cuenta entra a la cola de esa carga: el motor y la priorización la "
                             "toman la próxima vez que se ejecuten sobre ella.")

if "obligacion_contactos" not in st.session_state:
    st.session_state["obligacion_contactos"] = []

with st.container(border=True):
    st.subheader("Titular y crédito")
    c1, c2 = st.columns(2)
    documento = c1.text_input("Cédula del titular", max_chars=10)
    credito = c2.text_input("Número de obligación (crédito)", max_chars=20)
    nombre = st.text_input("Nombre del titular", max_chars=120)
    c3, c4 = st.columns(2)
    ciudad = c3.text_input("Ciudad", max_chars=60)
    producto = c4.text_input("Producto", max_chars=30)
    codigo = st.selectbox("Código de gestión", config.CODIGOS_GESTION,
                          help="El mismo código que trae el archivo de asignación para esta cuenta.")

    st.subheader("Financiero")
    c5, c6, c7 = st.columns(3)
    saldo = c5.number_input("Saldo", min_value=0.0, step=1000.0, format="%.2f")
    cobranza_min = c6.number_input("Cobranza mínima", min_value=0.0, step=1000.0, format="%.2f")
    cobranza_max = c7.number_input("Cobranza máxima", min_value=0.0, step=1000.0, format="%.2f")
    dias_mora = st.number_input("Días de mora", min_value=0, step=1)

    st.subheader("Contactos")
    st.caption("Al menos uno es recomendable, pero no obligatorio: sin ninguno la cuenta queda "
               "registrada, solo que el motor no podrá contactarla hasta que se agregue alguno.")
    cc1, cc2, cc3 = st.columns([1, 2, 1])
    tipo_contacto = cc1.selectbox("Tipo", list(tit.TIPOS), format_func=tit.TIPOS.get, key="oc_tipo")
    valor_contacto = cc2.text_input("Dato de contacto", placeholder="3001234567 o correo@dominio.com",
                                    key="oc_valor")
    if cc3.button("Agregar a la lista", use_container_width=True):
        valor_normalizado = tit.normalizar(tipo_contacto, valor_contacto)
        error = tit.validar_contacto(tipo_contacto, valor_normalizado)
        if error:
            st.error(error)
        elif any(t == tipo_contacto and v == valor_normalizado
                 for t, v in st.session_state["obligacion_contactos"]):
            st.warning("Ese contacto ya está en la lista.")
        else:
            st.session_state["obligacion_contactos"].append((tipo_contacto, valor_normalizado))

    if st.session_state["obligacion_contactos"]:
        for i, (t, v) in enumerate(st.session_state["obligacion_contactos"]):
            fc1, fc2 = st.columns([5, 1])
            fc1.write("**{}** · {}".format(tit.TIPOS[t], tit.enmascarar(t, v)))
            if fc2.button("Quitar", key="quitar_{}".format(i)):
                st.session_state["obligacion_contactos"].pop(i)
                st.rerun()
    else:
        st.caption("Todavía no se ha agregado ningún contacto.")

    st.divider()
    if st.button("Registrar obligación", type="primary", icon=":material/note_add:"):
        datos = {
            "documento": documento.strip(), "credito": credito.strip(), "nombre": nombre,
            "ciudad": ciudad, "producto": producto, "codigo": codigo,
            "saldo": saldo, "cobranza_min": cobranza_min, "cobranza_max": cobranza_max,
            "dias_mora": int(dias_mora),
        }
        errores = ob.validar(datos)
        if errores:
            for error in errores:
                st.error(error)
        else:
            try:
                credito_id = ob.registrar_obligacion(
                    carga_id, datos, st.session_state["obligacion_contactos"], usuario)
            except ValueError as error:
                st.error(str(error))
            else:
                st.session_state["obligacion_contactos"] = []
                st.session_state["aviso_obligacion"] = (
                    "Obligación {} registrada. Ya está disponible en la Cartera de esa carga; para que "
                    "entre a un plan de trabajo hace falta volver a ejecutar el motor y la priorización "
                    "de esa carga.".format(credito_id))
                st.rerun()
