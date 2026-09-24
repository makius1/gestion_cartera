# -*- coding: utf-8 -*-
"""
Prueba de la verificación del reloj del servidor contra la base de datos
(issue #51).

No toca ninguna base real: contra "local" no consulta nada, y contra
"remota" reemplaza la conexión por una falsa que responde la hora que se le
pida, así se puede probar sin Postgres.

Uso:
    python -m pruebas.prueba_reloj
"""

from datetime import datetime, timedelta

import config
from datos import base_datos as bd
from gestion import operacion as op

MARTES_HABIL = datetime(2026, 9, 15, 10, 0)   # dentro de horario, día hábil confirmado
DOMINGO = datetime(2026, 9, 20, 10, 0)        # fuera de horario por el día, no por el reloj


class _ConexionFalsa:
    """Responde SELECT NOW() con la hora que se le configuró, sin tocar Postgres."""

    def __init__(self, momento_bd):
        self.momento_bd = momento_bd

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _consulta):
        return self

    def scalar(self):
        return self.momento_bd


class _MotorFalso:
    def __init__(self, momento_bd):
        self.momento_bd = momento_bd

    def connect(self):
        return _ConexionFalsa(self.momento_bd)


def _con_base_remota(momento_bd, prueba):
    url_original, motor_original = config.URL_BASE_DATOS, bd.obtener_motor
    config.URL_BASE_DATOS = "postgresql://usuario:clave@127.0.0.1:1/ninguna"
    bd.obtener_motor = lambda: _MotorFalso(momento_bd)
    try:
        prueba()
    finally:
        config.URL_BASE_DATOS, bd.obtener_motor = url_original, motor_original


def prueba_local_siempre_confiable():
    url_original = config.URL_BASE_DATOS
    config.URL_BASE_DATOS = "sqlite:///salidas/no_se_usa.db"
    try:
        assert bd.reloj_confiable() is True
    finally:
        config.URL_BASE_DATOS = url_original
    print("  Base local: siempre confiable, sin consultar nada")


def prueba_remota_reloj_igual_es_confiable():
    _con_base_remota(config.ahora(), lambda: _assert(bd.reloj_confiable() is True))
    print("  Base remota, reloj igual al de la base: confiable")


def prueba_remota_reloj_desfasado_no_es_confiable():
    momento_bd = config.ahora() - timedelta(hours=5)
    _con_base_remota(momento_bd, lambda: _assert(bd.reloj_confiable(margen_minutos=10) is False))
    print("  Base remota, reloj desfasado 5 horas: no confiable")


def prueba_en_horario_rechaza_si_el_reloj_no_es_confiable():
    """Reproduce el issue #51: el reloj local dice que son las 10 a. m. de un
    martes (en horario), pero el de la base dice que en realidad son 5 horas
    después. en_horario() debe rechazar, aunque la hora local se vea normal."""
    momento_bd = config.ahora() - timedelta(hours=5)
    _con_base_remota(momento_bd, lambda: _assert(op.en_horario(MARTES_HABIL) is False))
    print("  en_horario(): rechaza un martes en horario si el reloj no es confiable")


def prueba_en_horario_acepta_si_el_reloj_es_confiable():
    _con_base_remota(config.ahora(), lambda: _assert(op.en_horario(MARTES_HABIL) is True))
    print("  en_horario(): acepta un martes en horario si el reloj sí es confiable")


def prueba_en_horario_domingo_no_consulta_el_reloj():
    """Un domingo ya está fuera de horario por el día: no debe importar lo que
    diga (o falle) la comparación con la base."""
    assert op.en_horario(DOMINGO) is False
    print("  en_horario(): un domingo es falso sin necesidad de consultar la base")


def _assert(condicion):
    assert condicion


if __name__ == "__main__":
    prueba_local_siempre_confiable()
    prueba_remota_reloj_igual_es_confiable()
    prueba_remota_reloj_desfasado_no_es_confiable()
    prueba_en_horario_rechaza_si_el_reloj_no_es_confiable()
    prueba_en_horario_acepta_si_el_reloj_es_confiable()
    prueba_en_horario_domingo_no_consulta_el_reloj()
    print("Reloj del servidor verificado.")
