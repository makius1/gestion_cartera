# -*- coding: utf-8 -*-
"""
Plan de trabajo diario.

El supervisor reparte las cuentas del día entre los gestores a partir de una
priorización; el reparto y sus reglas están en gestion/plan.py. Todos ven el
avance: el supervisor el de todo el equipo, el gestor el suyo.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from app import comun
from datos import base_datos as bd
from gestion import plan as pl

comun.exigir("ver_plan")
comun.encabezado("Plan de trabajo", "Reparto de las cuentas del día entre los gestores y su avance")
usuario = comun.usuario_actual()["usuario"]
equipo = comun.puede("gestionar_plan")

aviso = st.session_state.pop("aviso_plan", None)
if aviso:
    st.success(aviso)


# ---------------------------------------------------------------------------
# 1. CREAR EL PLAN (supervisor y administrador)
# ---------------------------------------------------------------------------

if equipo:
    with st.container(border=True):
        st.subheader("Nuevo plan")
        carga = comun.selector_carga("carga_plan")
        if carga is not None:
            priorizaciones = comun.priorizaciones()
            priorizaciones = priorizaciones[priorizaciones["carga_id"] == int(carga["id"])]
            if priorizaciones.empty:
                st.info("Esta carga no tiene priorizaciones. Priorícela primero en la pantalla Priorización.")
            else:
                disponibles = pl.gestores_disponibles()
                with st.form("crear_plan"):
                    c1, c2 = st.columns(2)
                    priorizacion = c1.selectbox(
                        "Priorización", priorizaciones["id"].astype(int).tolist(),
                        format_func=lambda i: "Priorización {}".format(i))
                    fecha = c2.date_input("Fecha del plan", value=config.hoy(), format="YYYY-MM-DD")
                    gestores = st.multiselect("Gestores", disponibles, default=disponibles)
                    cupo = st.number_input("Cuentas por gestor", min_value=1, max_value=500,
                                           value=config.GESTIONES_POR_GESTOR_DIA)
                    metodo = st.radio(
                        "Método de reparto", ["serpentina", "optimo"], horizontal=True,
                        format_func=lambda m: "Serpentina" if m == "serpentina" else "Óptimo (recaudo máximo)",
                        help="Serpentina reparte en orden equitativo entre gestores. Óptimo usa "
                             "programación lineal entera para maximizar el recaudo esperado total, "
                             "respetando el cupo de cada gestor (issue #14).")
                    crear = st.form_submit_button("Crear plan", type="primary")
                if crear:
                    try:
                        with st.spinner("Evaluando las cuentas para la fecha del plan y repartiendo..."):
                            plan_id, resumen = pl.crear_plan(int(carga["id"]), priorizacion, fecha,
                                                             gestores, int(cupo), usuario, metodo)
                    except (ValueError, LookupError) as error:
                        st.error(str(error))
                    else:
                        st.session_state["plan_elegido"] = plan_id
                        diferencia = resumen["valor_optimo"] - resumen["valor_serpentina"]
                        st.session_state["aviso_plan"] = (
                            "Plan {} creado: {} cuentas entre {} gestores, método {}. {} cuentas de la "
                            "priorización se descartaron porque el motor no permite contactarlas ese día. "
                            "Valor esperado: serpentina {} · óptimo {} ({}{}).".format(
                                plan_id, resumen["cuentas"], resumen["gestores"],
                                "óptimo" if metodo == "optimo" else "serpentina", resumen["descartadas"],
                                comun.pesos(resumen["valor_serpentina"]), comun.pesos(resumen["valor_optimo"]),
                                "+" if diferencia >= 0 else "", comun.pesos(diferencia)))
                        st.rerun()
                st.caption("Reparto en serpentina: 1, 2, 3… y en la siguiente vuelta …3, 2, 1. Así "
                           "cada gestor recibe una mezcla equivalente de cuentas de alta y baja prioridad.")


# ---------------------------------------------------------------------------
# 2. AVANCE
# ---------------------------------------------------------------------------

planes = bd.listar_planes()
if planes.empty:
    st.info("Todavía no hay planes de trabajo.")
    st.stop()

etiquetas = {int(f.id): "Plan {} · {} · carga {} · {} cuentas · {} gestores".format(
    int(f.id), pd.Timestamp(f.fecha).strftime("%Y-%m-%d"), int(f.carga_id), int(f.cuentas), int(f.gestores))
    for f in planes.itertuples()}
ids = list(etiquetas)
preferido = st.session_state.get("plan_elegido")
elegido = st.selectbox("Plan", ids, index=ids.index(preferido) if preferido in ids else 0,
                       format_func=etiquetas.get)
fila_plan = planes[planes["id"] == elegido].iloc[0]
avance = pl.avance(fila_plan)
if not equipo:
    avance = avance[avance["gestor"] == usuario]
    if avance.empty:
        st.info("No tiene cuentas asignadas en este plan.")
        st.stop()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Cuentas asignadas", comun.numero(len(avance)))
c2.metric("Gestionadas", comun.numero(avance["gestionada"].sum()),
          comun.porcentaje(avance["gestionada"].mean()), delta_color="off")
c3.metric("Contacto con el titular", comun.numero(avance["contacto"].sum()))
c4.metric("Acuerdos", comun.numero(avance["acuerdo"].sum()))
c5.metric("Valor acordado", comun.pesos(pd.to_numeric(avance["valor_acordado"], errors="coerce").sum()))

if pd.notna(fila_plan.get("valor_serpentina")) and pd.notna(fila_plan.get("valor_optimo")):
    st.markdown("**Comparación del método de reparto (issue #14)**")
    d1, d2, d3 = st.columns(3)
    d1.metric("Método usado en este plan",
              "Óptimo" if fila_plan["metodo"] == "optimo" else "Serpentina")
    d2.metric("Valor esperado con serpentina", comun.pesos(fila_plan["valor_serpentina"]))
    diferencia_plan = fila_plan["valor_optimo"] - fila_plan["valor_serpentina"]
    d3.metric("Valor esperado con el óptimo", comun.pesos(fila_plan["valor_optimo"]),
              "{}{}".format("+" if diferencia_plan >= 0 else "", comun.pesos(diferencia_plan)),
              delta_color="normal")
    st.caption("Ambos valores se calculan sobre el mismo universo de cuentas permitidas ese día, "
              "así que la comparación es justa sin importar cuál método se haya usado para el reparto.")

if equipo:
    resumen = pl.resumen_por_gestor(avance)
    izquierda, derecha = st.columns([3, 2])
    izquierda.dataframe(resumen, hide_index=True, use_container_width=True, column_config={
        "gestor": "Gestor", "asignadas": "Asignadas", "gestionadas": "Gestionadas",
        "pendientes": "Pendientes", "contactos": "Contactos", "acuerdos": "Acuerdos",
        "valor_acordado": st.column_config.NumberColumn("Valor acordado", format="$ %d"),
        "cumplimiento": st.column_config.ProgressColumn("Cumplimiento", min_value=0, max_value=1,
                                                        format="%.0f%%")})
    derecha.plotly_chart(px.bar(resumen, x="gestor", y=["gestionadas", "pendientes"],
                                title="Avance por gestor", labels={"value": "Cuentas", "gestor": "",
                                                                   "variable": ""}),
                         use_container_width=True)
    ver = st.selectbox("Cuentas del gestor", sorted(avance["gestor"].unique()))
    lista = avance[avance["gestor"] == ver]
else:
    lista = avance

st.dataframe(lista[["orden", "credito_id", "posicion", "prioridad", "gestionada", "resultado",
                    "codigo", "usuario"]],
             hide_index=True, use_container_width=True, height=380,
             column_config={"orden": "Orden", "credito_id": "Crédito", "posicion": "Posición en la cola",
                            "prioridad": st.column_config.NumberColumn("Prioridad", format="%.1f"),
                            "gestionada": st.column_config.CheckboxColumn("Gestionada"),
                            "resultado": "Resultado", "codigo": "Código", "usuario": "Gestionada por"})
