# -*- coding: utf-8 -*-
"""
Segmentación y priorización de la cartera.

  1. Ejecutar (supervisor y administrador): sobre una carga y, si se elige, una
     ejecución del motor, de la que salen las cuentas contactables del día.
  2. Comparación de métodos: por qué ganó el método elegido, con las tres
     métricas de cada uno.
  3. Segmentación: cuántos segmentos, por qué ese número y cómo es cada uno.
  4. Cola del día: las cuentas en el orden en que el equipo debe trabajarlas.
  5. Explicación de una cuenta: grados de pertenencia y reglas difusas
     activadas, y distancias de TOPSIS.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from app import comun
from datos import base_datos as bd
from decision import conocimiento_difuso as kd
from decision import priorizacion as prio

comun.exigir("ver_priorizacion")
comun.encabezado("Priorización", "En qué orden trabajar la cartera y con qué método decidirlo")
usuario = comun.usuario_actual()["usuario"]


# ---------------------------------------------------------------------------
# 1. EJECUTAR
# ---------------------------------------------------------------------------

if comun.puede("ejecutar_priorizacion"):
    with st.container(border=True):
        st.subheader("Nueva priorización")
        carga = comun.selector_carga("carga_priorizacion")
        if carga is not None:
            ejecuciones = comun.ejecuciones()
            ejecuciones = ejecuciones[ejecuciones["carga_id"] == int(carga["id"])]
            opciones = [None] + ejecuciones["id"].astype(int).tolist()
            etiquetas = {None: "Sin motor: toda la cartera gestionable"}
            etiquetas.update({int(f.id): "Ejecución {} · para el {} · {} contactables".format(
                int(f.id), pd.Timestamp(f.fecha_objetivo).strftime("%Y-%m-%d"),
                comun.numero(f.contactables)) for f in ejecuciones.itertuples()})
            ejecucion = st.selectbox("Cuentas candidatas", opciones, format_func=etiquetas.get,
                                     index=1 if len(opciones) > 1 else 0,
                                     help="Con una ejecución del motor solo se priorizan las "
                                          "cuentas que la ley y las reglas permiten contactar.")
            if st.button("Priorizar", type="primary", icon=":material/sort:"):
                try:
                    with st.spinner("Segmentando y comparando los tres métodos..."):
                        resumen, _ = prio.ejecutar(int(carga["id"]), ejecucion, usuario=usuario)
                except (ValueError, LookupError) as error:
                    st.error(str(error))
                else:
                    comun.limpiar_cache()
                    st.session_state["priorizacion_elegida"] = resumen["priorizacion_id"]
                    st.success("Priorización {} guardada. Método elegido: {}.".format(
                        resumen["priorizacion_id"], prio.METODOS[resumen["elegido"]]))


# ---------------------------------------------------------------------------
# Selección de la priorización a consultar
# ---------------------------------------------------------------------------

historial = comun.priorizaciones()
if historial.empty:
    st.info("Todavía no hay priorizaciones.")
    st.stop()

etiquetas = {int(f.id): "Priorización {} · carga {} · {} · por {}".format(
    int(f.id), int(f.carga_id),
    "ejecución {}".format(int(f.ejecucion_id)) if pd.notna(f.ejecucion_id) else "sin motor",
    f.usuario) for f in historial.itertuples()}
ids = list(etiquetas)
preferida = st.session_state.get("priorizacion_elegida")
elegida = st.selectbox("Priorización", ids, index=ids.index(preferida) if preferida in ids else 0,
                       format_func=etiquetas.get)
cabecera = historial[historial["id"] == elegida].iloc[0]
resumen = comun.resumen_priorizacion(elegida)
tabla = comun.prioridades(elegida)
metodo = cabecera["metodo_elegido"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cuentas candidatas", comun.numero(cabecera["candidatos"]))
c2.metric("Capacidad del día", comun.numero(cabecera["capacidad"]))
c3.metric("Segmentos", int(cabecera["k_segmentos"]), "silueta {:.3f}".format(cabecera["silueta"]),
          delta_color="off")
c4.metric("Método elegido", prio.METODOS[metodo])

pestanas = st.tabs(["Comparación de métodos", "Segmentación", "Cola del día", "¿Por qué esta prioridad?"])


# ---------------------------------------------------------------------------
# 2. COMPARACIÓN DE MÉTODOS
# ---------------------------------------------------------------------------

with pestanas[0]:
    metricas = resumen["metricas"]
    comparacion = pd.DataFrame([{
        "Método": prio.METODOS[m], "Recaudo esperado": comun.pesos(v["recaudo"]),
        "Recaudo relativo": round(v["recaudo_relativo"], 3), "Robustez": round(v["robustez"], 3),
        "Discriminación": round(v["discriminacion"], 3), "Puntaje": round(v["puntaje"], 3),
        "Elegido": m == metodo,
    } for m, v in metricas.items()]).sort_values("Puntaje", ascending=False)
    st.dataframe(comparacion, hide_index=True, use_container_width=True,
                 column_config={"Elegido": st.column_config.CheckboxColumn()})

    pesos = resumen["pesos_evaluacion"]
    st.caption(("Puntaje = {:.2f} × recaudo relativo + {:.2f} × robustez + {:.2f} × discriminación. "
                "Recaudo esperado: lo que se espera recuperar trabajando, en el orden del método, "
                "las cuentas que caben en la capacidad del día. Robustez: cuánto de esa cola se "
                "mantiene si los datos varían ±10 %. Discriminación: fracción de puntajes distintos "
                "dentro de la cola.").format(pesos["recaudo"], pesos["robustez"],
                                             pesos["discriminacion"]).replace("0.", "0,"))

    largo = pd.DataFrame([{"Método": prio.METODOS[m], "Métrica": etiqueta, "Valor": v[clave]}
                          for m, v in metricas.items()
                          for clave, etiqueta in [("recaudo_relativo", "Recaudo relativo"),
                                                  ("robustez", "Robustez"),
                                                  ("discriminacion", "Discriminación"),
                                                  ("puntaje", "Puntaje")]])
    st.plotly_chart(px.bar(largo, x="Métrica", y="Valor", color="Método", barmode="group",
                           range_y=[0, 1.05], title="Métricas por método"), use_container_width=True)

    # Coincidencia de colas: cuántas de las cuentas que cada método manda
    # trabajar hoy coinciden con las del método elegido.
    candidatas = tabla[tabla["candidata"]]
    capacidad = int(cabecera["capacidad"])
    colas = {m: set(candidatas.nlargest(capacidad, "puntaje_" + m)["credito_id"]) for m in prio.METODOS}
    st.markdown("**Coincidencia con la cola del método elegido**")
    st.dataframe(pd.DataFrame([{"Método": prio.METODOS[m],
                                "Cuentas en común": len(colas[m] & colas[metodo]),
                                "Coincidencia": comun.porcentaje(len(colas[m] & colas[metodo]) / capacidad)}
                               for m in prio.METODOS]), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# 3. SEGMENTACIÓN
# ---------------------------------------------------------------------------

with pestanas[1]:
    siluetas = pd.DataFrame([(int(k), v) for k, v in resumen["siluetas"].items()],
                            columns=["Segmentos (k)", "Silueta"])
    izquierda, derecha = st.columns([1, 2])
    figura = px.line(siluetas, x="Segmentos (k)", y="Silueta", markers=True,
                     title="Silueta según el número de segmentos")
    figura.add_vline(x=int(cabecera["k_segmentos"]), line_dash="dash")
    izquierda.plotly_chart(figura, use_container_width=True)
    izquierda.caption("Se elige el menor k cuya silueta queda a menos de 0,01 de la mejor: "
                      "entre segmentaciones casi igual de buenas, la de menos segmentos se "
                      "opera y explica mejor.")

    muestra = tabla.sample(min(3000, len(tabla)), random_state=1)
    derecha.plotly_chart(px.scatter(muestra, x="pca_x", y="pca_y", color="nombre_segmento",
                                    opacity=0.6, title="Mapa de segmentos (componentes principales)",
                                    labels={"pca_x": "Componente 1", "pca_y": "Componente 2",
                                            "nombre_segmento": "Segmento"}),
                         use_container_width=True)

    perfiles = pd.DataFrame(resumen["perfiles"])
    perfiles["saldo_total"] = perfiles["saldo_total"].map(comun.pesos)
    perfiles["saldo_mediano"] = perfiles["saldo_mediano"].map(comun.pesos)
    st.dataframe(perfiles.drop(columns=["segmento"]), hide_index=True, use_container_width=True,
                 column_config={
                     "nombre": "Segmento", "cuentas": "Cuentas", "saldo_total": "Saldo total",
                     "saldo_mediano": "Saldo mediano", "mora_mediana": "Mora mediana (días)",
                     "contactabilidad": st.column_config.NumberColumn("Contactabilidad", format="%.2f"),
                     "margen": st.column_config.NumberColumn("Margen medio", format="%.3f"),
                     "meses": st.column_config.NumberColumn("Meses en gestión", format="%.1f"),
                     "prioridad_media": st.column_config.NumberColumn("Prioridad media", format="%.1f"),
                     "en_capacidad": "En la cola de hoy"})


# ---------------------------------------------------------------------------
# 4. COLA DEL DÍA
# ---------------------------------------------------------------------------

with pestanas[2]:
    cola = tabla[tabla["candidata"]].sort_values("posicion")
    c1, c2 = st.columns(2)
    solo_hoy = c1.toggle("Solo las cuentas que caben hoy", value=True)
    segmentos = c2.multiselect("Segmento", sorted(cola["nombre_segmento"].dropna().unique()))
    if solo_hoy:
        cola = cola[cola["en_capacidad"]]
    if segmentos:
        cola = cola[cola["nombre_segmento"].isin(segmentos)]
    columnas = ["posicion", "credito_id", "nombre_segmento", "prioridad",
                "puntaje_difuso", "puntaje_topsis", "puntaje_ponderado"]
    st.dataframe(cola[columnas], hide_index=True, use_container_width=True, height=440,
                 column_config={
                     "posicion": "Posición", "credito_id": "Crédito", "nombre_segmento": "Segmento",
                     "prioridad": st.column_config.ProgressColumn(
                         "Prioridad ({})".format(prio.METODOS[metodo]), min_value=0, max_value=100,
                         format="%.1f"),
                     "puntaje_difuso": st.column_config.NumberColumn("Difuso", format="%.1f"),
                     "puntaje_topsis": st.column_config.NumberColumn("TOPSIS", format="%.1f"),
                     "puntaje_ponderado": st.column_config.NumberColumn("Ponderado", format="%.1f")})
    st.download_button("Descargar cola (CSV)", cola[columnas].to_csv(index=False).encode("utf-8"),
                       file_name="cola_priorizacion_{}.csv".format(elegida), mime="text/csv",
                       on_click=bd.registrar_evento,
                       args=(usuario, "EXPORTAR_COLA", "priorización {}: {} cuentas".format(
                           elegida, len(cola))))


# ---------------------------------------------------------------------------
# 5. EXPLICACIÓN DE UNA CUENTA
# ---------------------------------------------------------------------------

with pestanas[3]:
    opciones = tabla[tabla["candidata"]].sort_values("posicion")["credito_id"].tolist()
    credito = st.selectbox("Crédito", opciones, help="Ordenadas por posición en la cola.")
    fila = tabla[tabla["credito_id"] == credito].iloc[0]
    detalle = prio.explicar_cuenta(comun.cartera(int(cabecera["carga_id"])), credito,
                                   candidatos=opciones)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Posición", comun.numero(fila["posicion"]))
    c2.metric("Difuso", "{:.1f}".format(fila["puntaje_difuso"]))
    c3.metric("TOPSIS", "{:.1f}".format(fila["puntaje_topsis"]))
    c4.metric("Ponderado", "{:.1f}".format(fila["puntaje_ponderado"]))
    st.caption("Segmento: {}".format(fila["nombre_segmento"]))

    izquierda, derecha = st.columns(2)
    with izquierda:
        st.markdown("**Lógica difusa: grado de pertenencia de cada dato**")
        grados = []
        for variable, conjuntos in detalle["grados"].items():
            valor = detalle["entradas"][variable]
            for conjunto, grado in conjuntos.items():
                grados.append({"Variable": variable, "Valor": round(valor, 3),
                               "Conjunto": conjunto, "Grado": round(grado, 2)})
        st.dataframe(pd.DataFrame(grados), hide_index=True, use_container_width=True, height=360,
                     column_config={"Grado": st.column_config.ProgressColumn(min_value=0, max_value=1)})
    with derecha:
        st.markdown("**Reglas difusas activadas (fuerza = mínimo de sus premisas)**")
        reglas = {r["id"]: r for r in kd.REGLAS_DIFUSAS}
        activas = [(rid, f) for rid, f in detalle["reglas"] if f > 0]
        if not activas:
            st.info("Ninguna regla se activó.")
        for rid, fuerza in activas:
            regla = reglas[rid]
            premisas = " Y ".join("{} es {}".format(v, c) for v, c in regla["si"].items())
            st.markdown("**{}** · fuerza {:.2f}  \nSI {} ENTONCES prioridad {}".format(
                rid, fuerza, premisas, regla["entonces"]))
            st.caption(regla["fundamento"])
        st.markdown("**TOPSIS**")
        st.caption("Distancia a la cuenta ideal: {:.4f} · distancia a la anti-ideal: {:.4f}. "
                   "Cuanto más cerca de la ideal y más lejos de la anti-ideal, mayor el puntaje."
                   .format(detalle["d_ideal"], detalle["d_anti"]))
