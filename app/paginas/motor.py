# -*- coding: utf-8 -*-
"""
Motor de elegibilidad de contacto.

Tres partes:
  1. Ejecutar el motor sobre una carga para una fecha (supervisor y
     administrador). Cada ejecución queda guardada y en la bitácora.
  2. Consultar el resultado de cualquier ejecución guardada: cuántas cuentas
     se pueden contactar, por qué canal y qué reglas bloquearon a las demás.
  3. Explicar una cuenta: los hechos que vio el motor y la cadena de reglas que
     llevó a la decisión. Es el módulo de explicación del sistema experto.
"""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from app import comun
from motor import base_conocimiento as bc
from motor import elegibilidad as motor

comun.exigir("ver_motor")
comun.encabezado("Motor de elegibilidad",
                 "A quién se puede contactar, por qué canal y por qué razón")
usuario = comun.usuario_actual()


def describir_dia(fecha):
    dia = motor.diagnostico_fecha(fecha)
    if dia["dia_habil"]:
        return "{} {}: día hábil, contacto de {}.".format(
            dia["motivo"].capitalize(), fecha.strftime("%Y-%m-%d"), dia["horario"])
    return "{}: no hábil ({}). La Ley 2300 prohíbe el contacto.".format(
        fecha.strftime("%Y-%m-%d"), dia["motivo"])


# ---------------------------------------------------------------------------
# 1. EJECUTAR
# ---------------------------------------------------------------------------

if comun.puede("ejecutar_motor"):
    with st.container(border=True):
        st.subheader("Nueva ejecución")
        carga = comun.selector_carga("carga_motor")
        if carga is not None:
            fecha = st.date_input("Fecha a evaluar", value=config.hoy(),
                                  min_value=config.hoy() - timedelta(days=60),
                                  max_value=config.hoy() + timedelta(days=60),
                                  format="YYYY-MM-DD")
            st.caption(describir_dia(fecha))
            if st.button("Ejecutar motor", type="primary", icon=":material/play_arrow:"):
                try:
                    with st.spinner("Evaluando la cartera regla por regla..."):
                        resumen, _ = motor.ejecutar(int(carga["id"]), fecha,
                                                    usuario=usuario["usuario"], guardar=True)
                except (ValueError, LookupError) as error:
                    # Base de conocimiento inconsistente o carga vacía: el motor
                    # se niega a decidir y lo dice, en lugar de decidir mal.
                    st.error(str(error))
                else:
                    comun.limpiar_cache()
                    st.session_state["ejecucion_elegida"] = resumen["ejecucion_id"]
                    st.success("Ejecución {} guardada: {} de {} cuentas contactables.".format(
                        resumen["ejecucion_id"], comun.numero(resumen["CONTACTABLE"]),
                        comun.numero(resumen["total"])))


# ---------------------------------------------------------------------------
# 2. RESULTADOS
# ---------------------------------------------------------------------------

st.subheader("Resultados")
historial = comun.ejecuciones()
if historial.empty:
    st.info("Todavía no hay ejecuciones del motor.")
    st.stop()

etiquetas = {int(f.id): "Ejecución {} · carga {} · para el {} · por {}".format(
    int(f.id), int(f.carga_id), pd.Timestamp(f.fecha_objetivo).strftime("%Y-%m-%d"), f.usuario)
    for f in historial.itertuples()}
ids = list(etiquetas)
preferida = st.session_state.get("ejecucion_elegida")
elegida = st.selectbox("Ejecución", ids, index=ids.index(preferida) if preferida in ids else 0,
                       format_func=etiquetas.get)
cabecera = historial[historial["id"] == elegida].iloc[0]
fecha_objetivo = pd.Timestamp(cabecera["fecha_objetivo"]).date()
resultados = comun.evaluaciones(elegida)
st.caption(describir_dia(fecha_objetivo))

c1, c2, c3, c4 = st.columns(4)
for columna, estado in zip((c1, c2, c3, c4), motor.ESTADOS):
    n = int((resultados["estado"] == estado).sum())
    columna.metric("{} · {}".format(estado.replace("_", " ").capitalize(),
                                    comun.porcentaje(n / len(resultados))), comun.numero(n))

canales = resultados["canal_recomendado"].dropna().value_counts()
costo = sum(config.CANALES[c]["costo"] * n for c, n in canales.items())
st.caption("Costo estimado de ejecutar los contactos recomendados: {}".format(comun.pesos(costo)))

izquierda, derecha = st.columns(2)
por_regla = resultados["regla_determinante"].value_counts().rename_axis("regla").reset_index(name="cuentas")
por_regla["nombre"] = por_regla["regla"].map(
    lambda r: "{} · {}".format(r, bc.regla_por_id(r)["nombre"]) if bc.regla_por_id(r) else r)
izquierda.plotly_chart(px.bar(por_regla.sort_values("cuentas"), x="cuentas", y="nombre",
                              orientation="h", title="Regla determinante",
                              labels={"cuentas": "Cuentas", "nombre": ""}),
                       use_container_width=True)
if canales.empty:
    derecha.info("Ninguna cuenta tiene contacto recomendado para esta fecha.")
else:
    por_canal = canales.rename_axis("canal").reset_index(name="cuentas")
    derecha.plotly_chart(px.bar(por_canal, x="canal", y="cuentas", title="Canal recomendado",
                                labels={"cuentas": "Cuentas", "canal": ""}),
                         use_container_width=True)

c1, c2, c3 = st.columns(3)
filtro_estado = c1.multiselect("Estado", motor.ESTADOS)
filtro_canal = c2.multiselect("Canal", list(bc.CANALES_POR_COSTO))
filtro_regla = c3.multiselect("Regla determinante", sorted(resultados["regla_determinante"].dropna().unique()))
tabla = resultados
if filtro_estado:
    tabla = tabla[tabla["estado"].isin(filtro_estado)]
if filtro_canal:
    tabla = tabla[tabla["canal_recomendado"].isin(filtro_canal)]
if filtro_regla:
    tabla = tabla[tabla["regla_determinante"].isin(filtro_regla)]
st.dataframe(tabla[["credito_id", "estado", "canal_recomendado", "canales_permitidos",
                    "regla_determinante", "reglas", "explicacion"]],
             hide_index=True, use_container_width=True, height=360,
             column_config={"credito_id": "Crédito", "estado": "Estado",
                            "canal_recomendado": "Canal", "canales_permitidos": "Permitidos",
                            "regla_determinante": "Determina", "reglas": "Reglas disparadas",
                            "explicacion": st.column_config.TextColumn("Explicación", width="large")})


# ---------------------------------------------------------------------------
# 3. EXPLICAR UNA CUENTA
# ---------------------------------------------------------------------------

st.subheader("¿Por qué? — explicación de una cuenta")
opciones = tabla["credito_id"].tolist() or resultados["credito_id"].tolist()
credito = st.selectbox("Crédito", opciones, help="Se listan las cuentas del filtro actual.")

guardada = resultados[resultados["credito_id"] == credito].iloc[0]
fila = comun.cartera(int(cabecera["carga_id"]))
fila = fila[fila["credito_id"] == credito]
if fila.empty:
    st.warning("La cuenta ya no está en la cartera de esta carga.")
    st.stop()

decision = motor.evaluar_cuenta(motor.construir_hechos(fila.iloc[0].to_dict(), fecha_objetivo))

st.markdown("**Decisión registrada:** {} · canal {}  \n{}".format(
    guardada["estado"], guardada["canal_recomendado"] or "—", guardada["explicacion"]))

izquierda, derecha = st.columns([1, 2])
with izquierda:
    st.markdown("**Hechos de la cuenta**")
    hechos = pd.DataFrame({"hecho": list(decision["hechos"]),
                           "valor": [("desconocido" if v is None else str(v))
                                     for v in decision["hechos"].values()]})
    st.dataframe(hechos, hide_index=True, use_container_width=True)
with derecha:
    st.markdown("**Cadena de razonamiento**")
    nombres_fase = dict(bc.FASES)
    for paso, (fase, regla) in enumerate(decision["traza"], start=1):
        marca = " — determina" if regla["id"] == decision["regla_determinante"] else ""
        st.markdown("{}. **{} · {}**{}  \n_{}_  \n{}".format(
            paso, regla["id"], regla["nombre"], marca, regla["descripcion"], regla["fundamento"]))
        st.caption("Fase: {}".format(nombres_fase[fase]))
    if decision["descartadas"]:
        st.caption("Estrategias que también aplicaban, con menor prioridad: {}".format(
            ", ".join("{} ({})".format(r["id"], r["nombre"]) for r in decision["descartadas"])))

if decision["estado"] != guardada["estado"] or decision["canal_recomendado"] != guardada["canal_recomendado"]:
    st.warning("La base de conocimiento cambió desde esta ejecución: hoy el motor decidiría "
               "{} por {}. La decisión registrada es la que vale para esa fecha.".format(
                   decision["estado"], decision["canal_recomendado"] or "ningún canal"))
