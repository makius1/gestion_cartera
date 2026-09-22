# -*- coding: utf-8 -*-
"""Pruebas del historial simulado (datos/generador.py) sobre el bug de
codigo/resultado mezclados y la ventana horaria hábil."""

import numpy as np

import config
from datos import generador


def test_codigos_con_acuerdo_estan_en_codigos_con_compromiso():
    """Todo valor posible en _CODIGOS_CON_ACUERDO debe reconocerse como
    compromiso real en config.CODIGOS_CON_COMPROMISO, y ninguno debe ser
    el string 'ACUERDO' (ese es vocabulario de resultado, no de codigo)."""
    for codigo in generador._CODIGOS_CON_ACUERDO:
        assert codigo in config.CODIGOS_CON_COMPROMISO
        assert codigo != "ACUERDO"


def test_codigo_y_resultado_no_quedan_iguales_cuando_hay_acuerdo():
    """Reproduce la lógica de simular_historial cuando hay_acuerdo=True:
    codigo debe salir de _CODIGOS_CON_ACUERDO y resultado debe ser
    'ACUERDO'. Antes del fix, ambos quedaban en 'ACUERDO' y por eso
    codigo nunca aparecía en CODIGOS_CON_COMPROMISO."""
    rng = np.random.default_rng(7)
    for _ in range(200):  # cubre el sorteo aleatorio con varias corridas
        codigo = str(rng.choice(generador._CODIGOS_CON_ACUERDO))
        resultado = "ACUERDO"
        assert codigo in config.CODIGOS_CON_COMPROMISO
        assert resultado == "ACUERDO"
        assert codigo != resultado


def test_hora_habil_nunca_llega_a_las_19():
    """El generador de hora no debe producir horas >= 19 (fuera del
    horario permitido, que llega hasta antes de las 19:00)."""
    rng = np.random.default_rng(7)
    for _ in range(500):
        delta = generador._hora_habil(rng)
        horas = delta.seconds // 3600
        assert horas < 19
        assert horas >= generador._HORA_HABIL_MIN


def test_hora_habil_max_es_19_no_20():
    """Constante explícita: evita que alguien vuelva a subirla a 20 por
    error en el futuro."""
    assert generador._HORA_HABIL_MAX == 19


def test_acuerdo_activa_tiene_compromiso_en_cambios_en_cartera():
    """Una gestión con codigo de _CODIGOS_CON_ACUERDO y resultado='ACUERDO'
    debe activar tiene_compromiso=True en cambios_en_cartera. Antes del fix,
    codigo era 'ACUERDO' (no está en CODIGOS_CON_COMPROMISO) y esto quedaba
    en False, permitiendo acuerdos repetidos sin que el sistema los notara."""
    from datetime import date, timedelta
    from gestion import operacion

    hoy = date.today()
    gestion = {
        "codigo": "DIFERIDO",  # un valor de _CODIGOS_CON_ACUERDO
        "resultado": "ACUERDO",
        "valor_acordado": 50000.0,
        "fecha_compromiso": hoy + timedelta(days=10),
    }

    cambios = operacion.cambios_en_cartera(gestion, "prueba", hoy)

    assert cambios["tiene_compromiso"] is True
    assert cambios["resultado_gestion"] == "ACUERDO"
    assert cambios["codigo"] == "DIFERIDO"
    assert cambios["fecha_compromiso"] == gestion["fecha_compromiso"]
    assert cambios["proyeccion"] == 50000.0


def test_sin_acuerdo_no_activa_compromiso():
    """Control: un código sin acuerdo no debe activar tiene_compromiso."""
    from datetime import date
    from gestion import operacion

    hoy = date.today()
    gestion = {
        "codigo": "NO_CONTESTA",
        "resultado": "NO_CONTESTA",
        "valor_acordado": None,
        "fecha_compromiso": None,
    }

    cambios = operacion.cambios_en_cartera(gestion, "prueba", hoy)

    assert cambios["tiene_compromiso"] is False
    assert cambios["proyeccion"] == 0
    assert cambios["fecha_compromiso"] is None


def test_codigo_antiguo_acuerdo_hubiera_fallado_validacion():
    """Documenta el bug original: si codigo='ACUERDO' (como antes del fix),
    la regla G6 de validación ya lo hubiera rechazado, porque 'ACUERDO' no
    está en CODIGOS_CON_COMPROMISO pero resultado='ACUERDO' sí lo exige."""
    from datetime import date
    import config
    from gestion.operacion import _g6

    gestion_con_bug = {"codigo": "ACUERDO", "resultado": "ACUERDO"}
    mensaje = _g6(gestion_con_bug, {}, {}, date.today())

    assert mensaje is not None  # la regla debía rechazarlo
    assert "ACUERDO" not in config.CODIGOS_CON_COMPROMISO