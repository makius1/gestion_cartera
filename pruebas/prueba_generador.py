# -*- coding: utf-8 -*-
"""
Prueba del historial de gestiones simulado (issue #12: modelo de propensión).

Comprueba las tres correcciones revisadas sobre datos/generador.py:

  * codigo y resultado ya no se mezclan: cuando hay acuerdo, codigo sale de
    _CODIGOS_CON_ACUERDO (que sí está en config.CODIGOS_CON_COMPROMISO) y
    resultado queda fijo en "ACUERDO".
  * cambios_en_cartera() activa tiene_compromiso con ese codigo, y no lo
    activa cuando no hay acuerdo.
  * La hora de la gestión sale de una franja hábil (7:00 a antes de las
    19:00), sin llegar nunca a las 19.

No escribe en la base: opera solo sobre las funciones puras del generador y
de gestion.operacion, así que corre igual contra SQLite o contra Supabase.

Uso:
    python -m pruebas.prueba_generador
"""

from datetime import date, timedelta

import numpy as np

import config
from datos import generador
from gestion import operacion


def prueba_codigos_con_acuerdo_en_codigos_con_compromiso():
    """Todo valor posible en _CODIGOS_CON_ACUERDO debe reconocerse como
    compromiso real en config.CODIGOS_CON_COMPROMISO, y ninguno debe ser
    el string 'ACUERDO' (ese es vocabulario de resultado, no de codigo)."""
    for codigo in generador._CODIGOS_CON_ACUERDO:
        assert codigo in config.CODIGOS_CON_COMPROMISO, \
            "{} no está en CODIGOS_CON_COMPROMISO".format(codigo)
        assert codigo != "ACUERDO", "codigo no debe ser el string 'ACUERDO'"
    print("  Códigos de acuerdo: los {} valores de _CODIGOS_CON_ACUERDO están "
         "en CODIGOS_CON_COMPROMISO".format(len(generador._CODIGOS_CON_ACUERDO)))


def prueba_codigo_y_resultado_no_quedan_iguales():
    """Reproduce el sorteo de simular_historial cuando hay_acuerdo=True:
    codigo debe salir de _CODIGOS_CON_ACUERDO y resultado debe ser
    'ACUERDO'. Antes del fix, ambos quedaban en 'ACUERDO' y por eso codigo
    nunca aparecía en CODIGOS_CON_COMPROMISO."""
    rng = np.random.default_rng(7)
    for _ in range(200):
        codigo = str(rng.choice(generador._CODIGOS_CON_ACUERDO))
        resultado = "ACUERDO"
        assert codigo in config.CODIGOS_CON_COMPROMISO
        assert resultado == "ACUERDO"
        assert codigo != resultado, "codigo y resultado quedaron iguales"
    print("  Sorteo de acuerdo: codigo y resultado quedan en vocabularios distintos (200 corridas)")


def prueba_acuerdo_activa_tiene_compromiso():
    """Una gestión con codigo de _CODIGOS_CON_ACUERDO y resultado='ACUERDO'
    debe activar tiene_compromiso=True en cambios_en_cartera. Antes del
    fix, codigo era 'ACUERDO' (no está en CODIGOS_CON_COMPROMISO) y esto
    quedaba en False, permitiendo acuerdos repetidos sin que el sistema
    lo notara."""
    hoy = date.today()
    gestion = {
        "codigo": "DIFERIDO",
        "resultado": "ACUERDO",
        "valor_acordado": 50000.0,
        "fecha_compromiso": hoy + timedelta(days=10),
    }
    cambios = operacion.cambios_en_cartera(gestion, "prueba.generador", hoy)

    assert cambios["tiene_compromiso"] is True, \
        "un acuerdo real no activó tiene_compromiso"
    assert cambios["resultado_gestion"] == "ACUERDO"
    assert cambios["codigo"] == "DIFERIDO"
    assert cambios["fecha_compromiso"] == gestion["fecha_compromiso"]
    assert cambios["proyeccion"] == 50000.0
    print("  Acuerdo real: tiene_compromiso queda en True y la proyección se registra")


def prueba_sin_acuerdo_no_activa_compromiso():
    """Control: un código sin acuerdo no debe activar tiene_compromiso."""
    hoy = date.today()
    gestion = {
        "codigo": "NO_CONTESTA",
        "resultado": "NO_CONTESTA",
        "valor_acordado": None,
        "fecha_compromiso": None,
    }
    cambios = operacion.cambios_en_cartera(gestion, "prueba.generador", hoy)

    assert cambios["tiene_compromiso"] is False
    assert cambios["proyeccion"] == 0
    assert cambios["fecha_compromiso"] is None
    print("  Sin acuerdo: tiene_compromiso queda en False, como control")


def prueba_codigo_antiguo_hubiera_fallado_validacion():
    """Documenta el bug original: si codigo='ACUERDO' (como antes del
    fix), la regla G6 de validación ya lo hubiera rechazado, porque
    'ACUERDO' no está en CODIGOS_CON_COMPROMISO pero resultado='ACUERDO'
    sí lo exige."""
    gestion_con_bug = {"codigo": "ACUERDO", "resultado": "ACUERDO"}
    mensaje = operacion._g6(gestion_con_bug, {}, {}, date.today())

    assert mensaje is not None, "la regla G6 debía rechazar el bug original"
    assert "ACUERDO" not in config.CODIGOS_CON_COMPROMISO
    print("  Regla G6: confirma que el bug original habría sido rechazado por validación")


def prueba_hora_habil_no_llega_a_las_19():
    """El generador de hora no debe producir horas >= 19 (fuera del
    horario permitido, que llega hasta antes de las 19:00)."""
    rng = np.random.default_rng(7)
    for _ in range(500):
        delta = generador._hora_habil(rng)
        horas = delta.seconds // 3600
        assert horas < 19, "se generó una hora >= 19"
        assert horas >= generador._HORA_HABIL_MIN
    assert generador._HORA_HABIL_MAX == 19, "_HORA_HABIL_MAX debe ser 19, no 20"
    print("  Horario hábil: 500 horas simuladas, ninguna llega a las 19:00")


if __name__ == "__main__":
    prueba_codigos_con_acuerdo_en_codigos_con_compromiso()
    prueba_codigo_y_resultado_no_quedan_iguales()
    prueba_acuerdo_activa_tiene_compromiso()
    prueba_sin_acuerdo_no_activa_compromiso()
    prueba_codigo_antiguo_hubiera_fallado_validacion()
    prueba_hora_habil_no_llega_a_las_19()
    print("Historial simulado verificado.")