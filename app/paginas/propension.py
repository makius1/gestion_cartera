# -*- coding: utf-8 -*-
"""
Propensión a compromiso de pago (fase 4).

  1. Entrenar (supervisor y administrador): sobre una carga con historial de
     gestiones, entrena los cuatro modelos candidatos y guarda el ganador.
  2. Comparación de modelos: por qué ganó, con las métricas de los cuatro.
  3. Detalle: curva de captura y estabilidad (PSI) del modelo elegido.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from analisis import propension as prop


from app import comun
from datos import base_datos as bd

comun.exigir("ver_propension")
comun.encabezado("Propensión a pago", "Qué cuentas tienen más probabilidad de pagar si se gestionan")
usuario = comun.usuario_actual()["usuario"]


# ---------------------------------------------------------------------------
# 1. ENTRENAR
# ---------------------------------------------------------------------------

if comun.puede("ejecutar_propension"):
    with st.container(border=True):
        st.subheader("Nuevo entrenamiento")
        carga = comun.selector_carga("carga_propension")
        if carga is not None:
            if st.button("Entrenar y comparar", type="primary", icon=":material/model_training:"):
                try:
                    with st.spinner("Entrenando los cuatro modelos y validando con fechas "
                                    "posteriores al entrenamiento..."):
                        resumen = prop.ejecutar(int(carga["id"]), usuario=usuario)
                except ValueError as error:
                    st.error(str(error))
                else:
                    comun.limpiar_cache()
                    st.session_state["modelo_elegido"] = resumen["modelo_id"]
                    st.success("Modelo {} guardado. Elegido: {} (AUC {:.3f}).".format(
                        resumen["modelo_id"], prop.MODELOS[resumen["modelo_elegido"]], resumen["auc"]))


# ---------------------------------------------------------------------------
# Selección del entrenamiento a consultar
# ---------------------------------------------------------------------------

historial = bd.listar_modelos_propension()
if historial.empty:
    st.info("Todavía no hay modelos entrenados. Necesita una carga con historial de "
           "gestiones simulado o real (ver issue #11).")
    st.stop()

etiquetas = {int(f.id): "Modelo {} · carga {} · {} · por {}".format(
    int(f.id), int(f.carga_id), prop.MODELOS[f.modelo_elegido], f.usuario)
    for f in historial.itertuples()}
ids = list(etiquetas)
preferido = st.session_state.get("modelo_elegido")
elegido = st.selectbox("Entrenamiento", ids, index=ids.index(preferido) if preferido in ids else 0,
                       format_func=etiquetas.get)
cabecera = historial[historial["id"] == elegido].iloc[0]
metricas_todos = bd.leer_metricas_modelo(elegido)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Modelo elegido", prop.MODELOS[cabecera["modelo_elegido"]])
c2.metric("AUC", "{:.3f}".format(cabecera["auc"]))
c3.metric("KS", "{:.3f}".format(cabecera["ks"]))
c4.metric("Brier", "{:.3f}".format(cabecera["brier"]))
c5.metric("PSI", "{:.3f}".format(cabecera["psi"]),
          help="Estabilidad entre entrenamiento y validación. Menor es más estable.")
st.caption("Validado con gestiones a partir del {}.".format(cabecera["fecha_corte"]))

pestanas = st.tabs(["Comparación de modelos", "Detalle del modelo elegido"])


# ---------------------------------------------------------------------------
# 2. COMPARACIÓN DE MODELOS
# ---------------------------------------------------------------------------

with pestanas[0]:
    comparacion = pd.DataFrame([{
        "Modelo": prop.MODELOS[m], "AUC": round(v["auc"], 3), "KS": round(v["ks"], 3),
        "Brier": round(v["brier"], 3), "PSI": round(v["psi"], 3),
        "Captura 20% superior": comun.porcentaje(v["captura_20pct"]),
        "Elegido": m == cabecera["modelo_elegido"],
    } for m, v in metricas_todos.items()]).sort_values("AUC", ascending=False)
    st.dataframe(comparacion, hide_index=True, use_container_width=True,
                 column_config={"Elegido": st.column_config.CheckboxColumn()})

    st.caption("AUC: capacidad de ordenar cuentas por probabilidad de pago. KS: separación "
              "máxima entre quienes pagaron y quienes no. Brier: calibración (menor es "
              "mejor). PSI: estabilidad de la población entre entrenamiento y validación. "
              "Si el mejor modelo no supera a la regresión logística o al árbol CART por "
              "más de 0,02 de AUC, se prefiere el interpretable (ver docs/ALGORITMOS.md, "
              "sección 9).")

    largo = pd.DataFrame([{"Modelo": prop.MODELOS[m], "Métrica": etiqueta, "Valor": v[clave]}
                          for m, v in metricas_todos.items()
                          for clave, etiqueta in [("auc", "AUC"), ("ks", "KS"),
                                                  ("captura_20pct", "Captura 20%")]])
    st.plotly_chart(px.bar(largo, x="Métrica", y="Valor", color="Modelo", barmode="group",
                           range_y=[0, 1.05], title="Métricas por modelo"), use_container_width=True)


# ---------------------------------------------------------------------------
# 3. DETALLE DEL MODELO ELEGIDO
# ---------------------------------------------------------------------------

with pestanas[1]:
    detalle = metricas_todos[cabecera["modelo_elegido"]]
    izquierda, derecha = st.columns(2)
    with izquierda:
        st.markdown("**Por qué se eligió este modelo**")
        st.markdown("- **AUC** {:.3f}: entre 0,5 (azar) y 1,0 (perfecto).\n"
                    "- **KS** {:.3f}: separación entre quienes pagaron y quienes no.\n"
                    "- **Brier** {:.3f}: error de calibración (0 es perfecto).\n"
                    "- **PSI** {:.3f}: {}.".format(
                        detalle["auc"], detalle["ks"], detalle["brier"], detalle["psi"],
                        "estable" if detalle["psi"] < 0.1 else
                        "cambio moderado" if detalle["psi"] < 0.25 else "cambio importante"))
    with derecha:
        st.markdown("**Captura en el 20 % superior**")
        st.metric("Del recaudo esperado, queda en la cola del día",
                  comun.porcentaje(detalle["captura_20pct"]))
        st.caption("Cuánto del total de acuerdos caería si solo se trabajara el 20 % de "
                  "cuentas con mayor probabilidad predicha por este modelo.")