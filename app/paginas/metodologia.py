# -*- coding: utf-8 -*-
"""
Metodología: los algoritmos del sistema, explicados.

Muestra el documento docs/ALGORITMOS.md, el mismo que se lee en el
repositorio, dividido en secciones desplegables. Tener una sola fuente evita
que la explicación de la aplicación y la del repositorio digan cosas
distintas.
"""

import streamlit as st

import config
from app import comun

comun.exigir("ver_conocimiento")

RUTA = config.RAIZ / "docs" / "ALGORITMOS.md"


@st.cache_data
def _secciones(texto):
    """Divide el documento por sus títulos de segundo nivel (## …)."""
    bloques = texto.split("\n## ")
    introduccion = bloques[0]
    secciones = []
    for bloque in bloques[1:]:
        titulo, _, cuerpo = bloque.partition("\n")
        secciones.append((titulo.strip(), cuerpo))
    return introduccion, secciones


texto = RUTA.read_text(encoding="utf-8")
introduccion, secciones = _secciones(texto)

# El título del documento se reemplaza por el encabezado estándar de la
# aplicación; el resto de la introducción se muestra tal cual.
comun.encabezado("Metodología", "Qué hace cada algoritmo del sistema, qué busca y qué método aplica")
st.markdown(introduccion.split("\n", 1)[1] if introduccion.startswith("# ") else introduccion)

for numero, (titulo, cuerpo) in enumerate(secciones):
    with st.expander(titulo, expanded=numero == 0):
        st.markdown(cuerpo)
