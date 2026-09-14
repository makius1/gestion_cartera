# -*- coding: utf-8 -*-
"""
Traza de trabajo.

Dos miradas sobre lo que hizo el equipo:
  * Por gestor: cuántas gestiones hizo cada uno, a qué horas, con qué
    resultado y cuánto dinero comprometió. El gestor ve solo la suya; el
    supervisor la de todo el equipo.
  * Por cuenta: la línea de tiempo completa de una cuenta, desde que llegó en
    la carga hasta la última gestión, con las decisiones del motor y la
    priorización entre medio.
"""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from app import comun
from datos import base_datos as bd

comun.exigir("ver_traza")
comun.encabezado("Traza de trabajo", "Qué hizo cada gestor y qué pasó con cada cuenta")
usuario = comun.usuario_actual()["usuario"]
equipo = comun.puede("ver_traza_equipo")

por_gestor, por_cuenta = st.tabs(["Por gestor", "Por cuenta"])


# ---------------------------------------------------------------------------
# 1. POR GESTOR
# ---------------------------------------------------------------------------

with por_gestor:
    c1, c2 = st.columns([2, 3])
    hoy = config.hoy()
    periodo = c1.date_input("Periodo", value=(hoy - timedelta(days=6), hoy), format="YYYY-MM-DD")
    desde, hasta = (periodo if isinstance(periodo, tuple) and len(periodo) == 2 else (hoy, hoy))
    gestiones = bd.leer_gestiones_periodo(desde, hasta, None if equipo else usuario)
    if equipo and not gestiones.empty:
        elegidos = c2.multiselect("Gestores", sorted(gestiones["usuario"].unique()))
        if elegidos:
            gestiones = gestiones[gestiones["usuario"].isin(elegidos)]

    if gestiones.empty:
        st.info("No hay gestiones registradas en el periodo.")
    else:
        gestiones["fecha"] = pd.to_datetime(gestiones["fecha"])
        gestiones["dia"] = gestiones["fecha"].dt.date
        gestiones["hora"] = gestiones["fecha"].dt.hour
        gestiones["contacto"] = gestiones["resultado"].isin(config.RESULTADOS_CON_CONTACTO)
        gestiones["acuerdo"] = gestiones["codigo"].isin(config.CODIGOS_CON_COMPROMISO)
        gestiones["valor_acordado"] = pd.to_numeric(gestiones["valor_acordado"], errors="coerce")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Gestiones", comun.numero(len(gestiones)))
        c2.metric("Contacto con el titular", comun.porcentaje(gestiones["contacto"].mean()))
        c3.metric("Acuerdos", comun.numero(gestiones["acuerdo"].sum()))
        c4.metric("Valor acordado", comun.pesos(gestiones["valor_acordado"].sum()))

        # Jornada: primera y última gestión del día muestran la duración real
        # del trabajo, no solo el volumen.
        jornada = gestiones.groupby(["usuario", "dia"]).agg(
            gestiones=("id", "size"), cuentas=("credito_id", "nunique"),
            contactos=("contacto", "sum"), acuerdos=("acuerdo", "sum"),
            valor_acordado=("valor_acordado", "sum"),
            inicio=("fecha", "min"), fin=("fecha", "max")).reset_index()
        jornada["efectividad"] = jornada["contactos"] / jornada["gestiones"]
        jornada["inicio"] = jornada["inicio"].dt.strftime("%H:%M")
        jornada["fin"] = jornada["fin"].dt.strftime("%H:%M")
        st.dataframe(jornada.sort_values(["dia", "usuario"], ascending=[False, True]),
                     hide_index=True, use_container_width=True, column_config={
                         "usuario": "Gestor", "dia": "Día", "gestiones": "Gestiones", "cuentas": "Cuentas",
                         "contactos": "Contactos", "acuerdos": "Acuerdos",
                         "valor_acordado": st.column_config.NumberColumn("Valor acordado", format="$ %d"),
                         "inicio": "Primera", "fin": "Última",
                         "efectividad": st.column_config.ProgressColumn("Efectividad de contacto",
                                                                        min_value=0, max_value=1,
                                                                        format="%.0f%%")})

        por_hora = (gestiones.assign(tipo=gestiones["contacto"].map(
            {True: "Con contacto", False: "Sin contacto"}))
            .groupby(["hora", "tipo"]).size().reset_index(name="gestiones"))
        st.plotly_chart(px.bar(por_hora, x="hora", y="gestiones", color="tipo",
                               title="Gestiones por hora del día",
                               labels={"hora": "Hora", "gestiones": "Gestiones", "tipo": ""}),
                        use_container_width=True)

        detalle = gestiones[["fecha", "usuario", "credito_id", "canal", "sentido", "resultado",
                             "codigo", "valor_acordado", "observacion"]].sort_values("fecha", ascending=False)
        with st.expander("Detalle de las gestiones ({})".format(len(detalle))):
            st.dataframe(detalle, hide_index=True, use_container_width=True, column_config={
                "fecha": st.column_config.DatetimeColumn("Fecha", format="YYYY-MM-DD HH:mm"),
                "valor_acordado": st.column_config.NumberColumn("Valor acordado", format="$ %d"),
                "observacion": st.column_config.TextColumn("Observación", width="large")})
            st.download_button("Descargar traza (CSV)", detalle.to_csv(index=False).encode("utf-8"),
                               file_name="traza_{}_{}.csv".format(desde, hasta), mime="text/csv",
                               on_click=bd.registrar_evento,
                               args=(usuario, "EXPORTAR_TRAZA", "{} a {}: {} gestiones".format(
                                   desde, hasta, len(detalle))))


# ---------------------------------------------------------------------------
# 2. POR CUENTA
# ---------------------------------------------------------------------------

with por_cuenta:
    carga = comun.selector_carga("carga_traza")
    if carga is not None:
        cartera = comun.cartera(int(carga["id"]))
        texto = st.text_input("Crédito o titular", placeholder="Seudónimo del crédito (K…) o del titular (C…)")
        if texto.strip():
            buscado = texto.strip().upper()
            encontradas = cartera[cartera["credito_id"].str.startswith(buscado)
                                  | cartera["cuenta_id"].str.startswith(buscado)]
            if encontradas.empty:
                st.warning("No se encontró la cuenta en esta carga.")
            else:
                credito = st.selectbox("Crédito", encontradas["credito_id"].head(50).tolist())
                fila = encontradas[encontradas["credito_id"] == credito].iloc[0]
                traza = bd.traza_cuenta(int(carga["id"]), credito, fila["cuenta_id"])
                st.caption("{} eventos · titular {}".format(len(traza), fila["cuenta_id"]))
                st.dataframe(traza, hide_index=True, use_container_width=True, height=420,
                             column_config={
                                 "fecha": st.column_config.DatetimeColumn("Fecha", format="YYYY-MM-DD HH:mm"),
                                 "evento": "Evento", "usuario": "Usuario",
                                 "detalle": st.column_config.TextColumn("Detalle", width="large")})
