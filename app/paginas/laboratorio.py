# -*- coding: utf-8 -*-
"""
Laboratorio de algoritmos: los motores del sistema, funcionando a la vista.

Muestra en una página completa el laboratorio interactivo de
app/recursos/laboratorio.html, en doce pestañas: el mapa de quién llama a
quién, las 21 reglas por fase con sus bloqueos y estados, el motor de
elegibilidad regla por regla, Thompson, la lógica difusa, TOPSIS y el árbitro,
la segmentación, la propensión, el reparto del plan, las reglas G1 a G10, los
seudónimos y la seguridad con los permisos de cada rol. Es material de demostración: corre en el navegador con cuentas de
ejemplo y no lee ni escribe en la base de datos.

Solo lo ve el administrador, que es quien presenta el sistema.
"""

import streamlit as st
import streamlit.components.v1 as componentes

import config
from app import comun

comun.exigir("ver_laboratorio")

RUTA = config.RAIZ / "app" / "recursos" / "laboratorio.html"

# Alto del marco. El laboratorio tiene su propio desplazamiento interno, así que
# el marco solo necesita ocupar la pantalla; las pestañas quedan fijas arriba.
ALTO = 1500


@st.cache_data
def _pagina(texto):
    """El archivo es el mismo que se publica como página suelta, sin la
    cabecera HTML completa: se le agrega aquí la declaración del documento."""
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '</head><body style="margin:0">' + texto + "</body></html>")


comun.encabezado("Laboratorio de algoritmos",
                 "Los motores del sistema funcionando en vivo, con las mismas reglas y fórmulas del código")
st.caption("Material de demostración: usa cuentas de ejemplo, corre en el navegador y no "
           "modifica la base de datos. Cada pestaña indica en qué pantalla, archivo y función "
           "vive el algoritmo.")
componentes.html(_pagina(RUTA.read_text(encoding="utf-8")), height=ALTO, scrolling=True)
