# -*- coding: utf-8 -*-
"""
Prueba de la confirmación antes de escribir en una base remota (issue #36).

No toca ninguna base: cambia la dirección configurada por una falsa y simula
la terminal, así que se puede correr en cualquier equipo sin riesgo.

Uso:
    python -m pruebas.prueba_confirmacion
"""

import builtins
import sys

import config
from datos import base_datos as bd

REMOTA = "postgresql://usuario:clave@127.0.0.1:1/ninguna"
LOCAL = "sqlite:///salidas/no_se_usa.db"


class Terminal:
    """Simula la entrada: si es una terminal y qué escribe la persona."""

    def __init__(self, interactiva, respuesta=None):
        self.interactiva, self.respuesta = interactiva, respuesta
        self.preguntas = 0

    def isatty(self):
        return self.interactiva

    def leer(self, _mensaje=""):
        self.preguntas += 1
        if self.respuesta is None:
            raise EOFError
        return self.respuesta


def caso(url, confirmada, interactiva, respuesta=None):
    terminal = Terminal(interactiva, respuesta)
    url_original, entrada, lectura = config.URL_BASE_DATOS, sys.stdin, builtins.input
    config.URL_BASE_DATOS, sys.stdin, builtins.input = url, terminal, terminal.leer
    try:
        return bd.confirmar_escritura_remota("probar", confirmada), terminal.preguntas
    finally:
        config.URL_BASE_DATOS, sys.stdin, builtins.input = url_original, entrada, lectura


CASOS = [
    ("base local, sin confirmar", LOCAL, False, True, None, True, 0),
    ("remota con --confirmar-remota", REMOTA, True, False, None, True, 0),
    ("remota sin terminal", REMOTA, False, False, None, False, 0),
    ("remota, escribe CONFIRMAR", REMOTA, False, True, "CONFIRMAR", True, 1),
    ("remota, escribe otra cosa", REMOTA, False, True, "si", False, 1),
    ("remota, terminal sin respuesta", REMOTA, False, True, None, False, 1),
]


if __name__ == "__main__":
    fallas = 0
    for nombre, url, confirmada, interactiva, respuesta, esperado, preguntas_esperadas in CASOS:
        resultado, preguntas = caso(url, confirmada, interactiva, respuesta)
        bien = resultado == esperado and preguntas == preguntas_esperadas
        fallas += not bien
        print("  {:<34} {:<9} {}".format(
            nombre, "sigue" if resultado else "se detiene",
            "OK" if bien else "FALLA (preguntó {} veces)".format(preguntas)))
    if fallas:
        print("{} casos fallaron".format(fallas))
        sys.exit(1)
    print("Confirmación de escritura remota verificada.")
