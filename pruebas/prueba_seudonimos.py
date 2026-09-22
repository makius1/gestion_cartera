# -*- coding: utf-8 -*-
"""
Prueba del rechazo al seudonimizar sin clave contra una base remota (#37).

No toca ninguna base: cambia la dirección configurada por una falsa y borra o
define la variable de entorno segun el caso, asi se puede correr en cualquier
equipo sin riesgo.

Uso:
    python -m pruebas.prueba_seudonimos
"""

import os
import sys

import config
from datos import cargador

REMOTA = "postgresql://usuario:clave@127.0.0.1:1/ninguna"
LOCAL = "sqlite:///salidas/no_se_usa.db"


def caso(url, clave):
    url_original = config.URL_BASE_DATOS
    clave_original = os.environ.pop("SEUDONIMO_CLAVE", None)
    config.URL_BASE_DATOS = url
    if clave is not None:
        os.environ["SEUDONIMO_CLAVE"] = clave
    cargador._CLAVE_EFIMERA = None
    try:
        return cargador._clave_seudonimos()
    finally:
        config.URL_BASE_DATOS = url_original
        if clave_original is not None:
            os.environ["SEUDONIMO_CLAVE"] = clave_original
        else:
            os.environ.pop("SEUDONIMO_CLAVE", None)
        cargador._CLAVE_EFIMERA = None


def prueba_local_sin_clave_usa_una_temporal():
    resultado = caso(LOCAL, None)
    assert isinstance(resultado, bytes) and len(resultado) == 32
    print("  Local sin clave: usa una temporal, no rechaza OK")


def prueba_local_con_clave_usa_la_definida():
    resultado = caso(LOCAL, "clave-de-prueba")
    assert resultado == b"clave-de-prueba"
    print("  Local con clave: usa la definida OK")


def prueba_remota_con_clave_usa_la_definida():
    resultado = caso(REMOTA, "clave-de-prueba")
    assert resultado == b"clave-de-prueba"
    print("  Remota con clave: usa la definida OK")


def prueba_remota_sin_clave_se_rechaza():
    try:
        caso(REMOTA, None)
    except PermissionError as error:
        assert "SEUDONIMO_CLAVE" in str(error)
        print("  Remota sin clave: se rechaza OK")
    else:
        raise AssertionError("remota sin clave no se rechazó")


if __name__ == "__main__":
    print("Pruebas de la clave de seudónimos contra una base remota")
    prueba_local_sin_clave_usa_una_temporal()
    prueba_local_con_clave_usa_la_definida()
    prueba_remota_con_clave_usa_la_definida()
    prueba_remota_sin_clave_se_rechaza()
    print("Clave de seudónimos verificada.")
