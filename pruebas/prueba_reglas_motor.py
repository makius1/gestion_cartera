# -*- coding: utf-8 -*-
"""Pruebas unitarias de las 21 reglas del motor (issue #7)."""

import config
from motor import base_conocimiento as bc
from motor.elegibilidad import evaluar_cuenta


def hechos_base():
    return {
        "dia_habil": True,
        "datos_completos": True,
        "dias_desde_contacto": config.DIAS_MINIMOS_ENTRE_CONTACTOS,
        "dias_para_compromiso": None,
        "codigo": "POSIBLE LOCALIZACION",
        "resultado_gestion": "CONTACTO_TITULAR",
        "tiene_celular": True,
        "tiene_fijo": True,
        "tiene_email": True,
        "exigir_autorizacion_canal": True,
        "autoriza_llamada": True,
        "autoriza_whatsapp": True,
        "autoriza_sms": True,
        "autoriza_email": True,
    }


def evaluar(**cambios):
    hechos = hechos_base()
    hechos.update(cambios)
    return evaluar_cuenta(hechos)


CASOS = {
    "L1": ({"dia_habil": False}, {}),
    "N1": ({"codigo": sorted(config.CODIGOS_EXCLUYENTES)[0]}, {}),
    "L3": ({"datos_completos": False}, {}),
    "L2": ({"dias_desde_contacto": 0}, {}),
    "N3": ({"dias_para_compromiso": 0}, {}),
    "N4": ({"dias_para_compromiso": config.DIAS_AVISO_COMPROMISO + 1}, {}),
    "C1": ({"tiene_celular": False}, {}),
    "C2": ({"tiene_celular": False, "tiene_fijo": False}, {}),
    "C3": ({"tiene_email": False}, {}),
    "C4": ({"resultado_gestion": "NUMERO_ERRADO"}, {}),
    "C5": ({"autoriza_llamada": False}, {}),
    "C6": ({"autoriza_whatsapp": False}, {}),
    "C7": ({"autoriza_sms": False}, {}),
    "C8": ({"autoriza_email": False}, {}),
    "N2": ({"tiene_celular": False, "tiene_fijo": False, "tiene_email": False}, {}),
    "E1": ({"dias_para_compromiso": -1}, {}),
    "E2": ({"codigo": "CONTACTO SIN ACUERDO"}, {}),
    "E3": ({"resultado_gestion": "SIN_GESTION_REAL"}, {}),
    "E4": ({"resultado_gestion": "BUZON"}, {}),
    "E5": ({"resultado_gestion": "CUELGA"}, {}),
    "E9": ({}, {"dias_para_compromiso": -1}),
}


def prueba_cobertura():
    existentes = {r["id"] for r in bc.REGLAS}
    cubiertas = set(CASOS)
    assert existentes == cubiertas, (
        "Cobertura incompleta. Sin prueba: {}. Sobrantes: {}.".format(
            sorted(existentes - cubiertas), sorted(cubiertas - existentes)
        )
    )
    print("  Cobertura: {} reglas con caso positivo y negativo".format(len(existentes)))


def prueba_reglas():
    for rid, (positivo, negativo) in CASOS.items():
        resultado_si = evaluar(**positivo)
        assert rid in resultado_si["reglas"], (
            "{} no se disparó con su caso positivo: {}".format(rid, resultado_si["reglas"])
        )
        resultado_no = evaluar(**negativo)
        assert rid not in resultado_no["reglas"], (
            "{} se disparó con su caso negativo: {}".format(rid, resultado_no["reglas"])
        )
        print("  {}: dispara / no dispara OK".format(rid))


if __name__ == "__main__":
    print("Pruebas unitarias de reglas del motor")
    prueba_cobertura()
    prueba_reglas()
    print("21 reglas verificadas.")
