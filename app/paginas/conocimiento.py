# -*- coding: utf-8 -*-
"""
Base de conocimiento: las reglas del sistema experto, a la vista.

Muestra cada regla con su condición, su efecto y su fundamento legal o de
negocio, y ofrece un simulador de consulta: se describen los hechos de una
cuenta imaginaria y el motor responde qué haría y por qué. Es la forma de
revisar la base de conocimiento con un experto del negocio o con el área
jurídica sin leer código.

Incluye también la base difusa de la priorización: variables lingüísticas, sus
conjuntos y las reglas con que se ordena la cartera.

Las reglas se modifican en motor/base_conocimiento.py y
decision/conocimiento_difuso.py, no desde la pantalla:
así cada cambio de una regla queda registrado en el historial del repositorio,
con autor, fecha y motivo, que es lo que exige una norma auditable.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from app import comun
from decision import conocimiento_difuso as kd
from decision.priorizacion import _pertenencia
from motor import base_conocimiento as bc
from motor import elegibilidad as motor

comun.exigir("ver_conocimiento")
comun.encabezado("Base de conocimiento",
                 "Reglas del motor de elegibilidad, con su fundamento")

errores = bc.validar()
if errores:
    st.error("La base de conocimiento tiene inconsistencias:\n\n" +
             "\n".join("- " + e for e in errores))
else:
    st.success("{} reglas en {} fases, sin inconsistencias.".format(len(bc.REGLAS), len(bc.FASES)))

OPERADORES = {"<": "menor que", "<=": "menor o igual a", ">": "mayor que",
              ">=": "mayor o igual a", "en": "es uno de", "entre": "está entre"}


def describir_condicion(condicion):
    if not condicion:
        return "siempre"
    partes = []
    for hecho, valor in condicion.items():
        if isinstance(valor, tuple):
            operador, referencia = valor
            if operador == "entre":
                referencia = "{} y {}".format(*referencia)
            elif isinstance(referencia, (list, tuple)):
                referencia = ", ".join(map(str, referencia))
            partes.append("{} {} {}".format(hecho, OPERADORES[operador], referencia))
        else:
            partes.append("{} = {}".format(hecho, valor))
    return " Y ".join(partes)


def describir_efecto(efecto):
    partes = []
    if "estado" in efecto:
        partes.append("estado {}".format(efecto["estado"]))
    if "quitar_canales" in efecto:
        partes.append("quita {}".format(", ".join(efecto["quitar_canales"])))
    if "canales_preferidos" in efecto:
        partes.append("prefiere {}".format(", ".join(efecto["canales_preferidos"])))
    if "canal" in efecto:
        partes.append("recomienda {}".format(efecto["canal"]))
    return "; ".join(partes)


pestana_reglas, pestana_simulador, pestana_parametros, pestana_difusa = st.tabs(
    ["Reglas", "Simulador de consulta", "Parámetros y calendario", "Reglas difusas de priorización"])

# --- Reglas por fase ------------------------------------------------------------
with pestana_reglas:
    st.caption("Las fases se evalúan en orden. Una regla de bloqueo detiene el "
               "razonamiento: la ley está por encima de la estrategia comercial.")
    for numero_fase, (fase, descripcion) in enumerate(bc.FASES, start=1):
        reglas = bc.reglas_de_fase(fase)
        with st.expander("Fase {} · {} ({} reglas)".format(numero_fase, descripcion, len(reglas)),
                         expanded=numero_fase == 1):
            st.dataframe(pd.DataFrame([{
                "Id": r["id"], "Regla": r["nombre"],
                "Si": describir_condicion(r["condicion"]),
                "Entonces": describir_efecto(r["efecto"]),
                "Prioridad": r.get("prioridad"),
                "Fundamento": r["fundamento"],
            } for r in reglas]), hide_index=True, use_container_width=True,
                column_config={"Fundamento": st.column_config.TextColumn(width="large")})

# --- Simulador ------------------------------------------------------------------
with pestana_simulador:
    st.caption("Describa una cuenta y consulte al motor. No usa ni modifica datos de la base.")
    codigos = sorted({"POSIBLE LOCALIZACION", "CONTACTO SIN ACUERDO", "RENUENTE", "DESEMPLEO"}
                     | config.CODIGOS_EXCLUYENTES | config.CODIGOS_CON_COMPROMISO)
    resultados = sorted({etiqueta for _, etiqueta in config.PATRONES_GESTION}
                        | {config.ETIQUETA_GESTION_POR_DEFECTO})

    with st.form("simulador"):
        c1, c2, c3 = st.columns(3)
        dia_habil = c1.checkbox("Día hábil", value=True)
        codigo = c2.selectbox("Código de gestión", codigos, index=codigos.index("POSIBLE LOCALIZACION"))
        resultado = c3.selectbox("Resultado de la última gestión", resultados,
                                 index=resultados.index("BUZON"))
        c1, c2, c3 = st.columns(3)
        con_contacto = c1.checkbox("Tuvo contacto real", value=True)
        dias_contacto = c1.number_input("Días desde el último contacto", 0, 365, 10)
        con_compromiso = c2.checkbox("Tiene compromiso de pago", value=False)
        dias_compromiso = c2.number_input("Días para el compromiso (negativo si ya pasó)", -60, 60, 5)
        celular = c3.checkbox("Tiene celular", value=True)
        fijo = c3.checkbox("Tiene fijo", value=True)
        correo = c3.checkbox("Tiene correo", value=True)
        consultar = st.form_submit_button("Consultar al motor", type="primary")

    if consultar:
        hechos = {
            "dia_habil": dia_habil,
            "datos_completos": True,
            "dias_desde_contacto": int(dias_contacto) if con_contacto else None,
            "dias_para_compromiso": int(dias_compromiso) if con_compromiso else None,
            "codigo": codigo,
            "resultado_gestion": "SIN_GESTION_REAL" if not con_contacto else resultado,
            "tiene_celular": celular, "tiene_fijo": fijo, "tiene_email": correo,
        }
        decision = motor.evaluar_cuenta(hechos)
        color = {"CONTACTABLE": "green", "RECORDATORIO": "blue",
                 "EN_ESPERA": "orange", "BLOQUEADA": "red"}[decision["estado"]]
        st.markdown("### :{}[{}]".format(color, decision["estado"]))
        if decision["canal_recomendado"]:
            st.markdown("Canal recomendado: **{}** · permitidos: {}".format(
                decision["canal_recomendado"], ", ".join(decision["canales_permitidos"])))
        st.info(decision["explicacion"])
        st.markdown("**Reglas disparadas, en orden:** {}".format(
            " → ".join(decision["reglas"]) or "ninguna"))

# --- Parámetros -------------------------------------------------------------------
with pestana_parametros:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Parámetros de contacto** (config.py)")
        st.dataframe(pd.DataFrame([
            ("Días mínimos entre contactos", config.DIAS_MINIMOS_ENTRE_CONTACTOS),
            ("Días de aviso antes de un compromiso", config.DIAS_AVISO_COMPROMISO),
            ("Códigos que excluyen la cuenta", ", ".join(sorted(config.CODIGOS_EXCLUYENTES))),
        ], columns=["Parámetro", "Valor"]).astype(str), hide_index=True, use_container_width=True)
        horario = [(motor.NOMBRE_DIA[d].capitalize(),
                    "{}:00 a {}:00".format(*f) if f else "Sin contacto")
                   for d, f in config.HORARIO_HABIL.items()]
        st.markdown("**Horario permitido**")
        st.dataframe(pd.DataFrame(horario, columns=["Día", "Horario"]),
                     hide_index=True, use_container_width=True)
    with c2:
        anio = config.hoy().year
        st.markdown("**Festivos de Colombia {}** (sin contacto)".format(anio))
        festivos = motor._festivos(anio)
        st.dataframe(pd.DataFrame(sorted(festivos.items()), columns=["Fecha", "Festivo"]),
                     hide_index=True, use_container_width=True, height=420)

# --- Base difusa de la priorización -----------------------------------------------
with pestana_difusa:
    errores_difusos = kd.validar()
    if errores_difusos:
        st.error("La base difusa tiene inconsistencias:\n\n" +
                 "\n".join("- " + e for e in errores_difusos))
    else:
        st.success("{} reglas difusas sobre {} variables, sin inconsistencias y con cobertura "
                   "completa de saldo y mora.".format(len(kd.REGLAS_DIFUSAS), len(kd.VARIABLES)))
    st.caption("Inferencia Mamdani: la fuerza de cada regla es el mínimo de sus premisas, las "
               "salidas se unen con el máximo y la prioridad es el centro de gravedad del área.")

    st.dataframe(pd.DataFrame([{
        "Id": r["id"],
        "Si": " Y ".join("{} es {}".format(v, c) for v, c in r["si"].items()),
        "Entonces": "prioridad " + r["entonces"],
        "Fundamento": r["fundamento"],
    } for r in kd.REGLAS_DIFUSAS]), hide_index=True, use_container_width=True,
        column_config={"Fundamento": st.column_config.TextColumn(width="large")})

    # Gráfica de los conjuntos de cada variable: muestra dónde se solapan, que
    # es lo que permite que un mismo valor sea "medio" y "alto" a la vez.
    variables = list(kd.VARIABLES.items()) + [(kd.SALIDA["nombre"], kd.SALIDA)]
    columnas = st.columns(2)
    for i, (nombre, variable) in enumerate(variables):
        x = np.linspace(*variable["universo"], 300)
        figura = go.Figure()
        for conjunto, definicion in variable["conjuntos"].items():
            figura.add_trace(go.Scatter(x=x, y=_pertenencia(x, definicion), name=conjunto,
                                        mode="lines", fill="tozeroy"))
        figura.update_layout(title=variable["descripcion"], height=260,
                             margin=dict(l=10, r=10, t=40, b=10), yaxis_title="Grado")
        columnas[i % 2].plotly_chart(figura, use_container_width=True)
