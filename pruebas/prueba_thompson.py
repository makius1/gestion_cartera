# -*- coding: utf-8 -*-
"""Pruebas del muestreo de Thompson para selección de canal (issue #9)."""

import pandas as pd

from motor import thompson


def prueba_estadisticas():
    gestiones = pd.DataFrame([
        {"canal": "LLAMADA", "sentido": "SALIENTE", "resultado": "CONTACTO_TITULAR"},
        {"canal": "LLAMADA", "sentido": "SALIENTE", "resultado": "NO_CONTESTA"},
        {"canal": "WHATSAPP", "sentido": "SALIENTE", "resultado": "ACUERDO"},
        {"canal": "WHATSAPP", "sentido": "SALIENTE", "resultado": "REINTENTAR"},
        {"canal": "EMAIL", "sentido": "SALIENTE", "resultado": "CORREO_ENVIADO"},
        {"canal": "SMS", "sentido": "ENTRANTE", "resultado": "CONTACTO_TITULAR"},
    ])

    resumen = thompson.estadisticas(gestiones)

    assert resumen["LLAMADA"] == {"exitos": 1, "fracasos": 1, "total": 2}
    assert resumen["WHATSAPP"] == {"exitos": 2, "fracasos": 0, "total": 2}
    assert resumen["EMAIL"] == {"exitos": 0, "fracasos": 1, "total": 1}

    # Las gestiones entrantes no deben entrenar la elección de un canal saliente.
    assert resumen["SMS"] == {"exitos": 0, "fracasos": 0, "total": 0}

    print("  Estadísticas: éxitos y no respuestas calculados correctamente")


def prueba_reproducible():
    resumen = {
        "EMAIL": {"exitos": 5, "fracasos": 10, "total": 15},
        "SMS": {"exitos": 8, "fracasos": 7, "total": 15},
        "WHATSAPP": {"exitos": 12, "fracasos": 3, "total": 15},
        "LLAMADA": {"exitos": 2, "fracasos": 13, "total": 15},
    }

    uno, muestras_uno = thompson.elegir(
        ["EMAIL", "SMS", "WHATSAPP", "LLAMADA"],
        resumen,
        semilla=123,
        clave="C0001|2026-09-22",
    )
    dos, muestras_dos = thompson.elegir(
        ["EMAIL", "SMS", "WHATSAPP", "LLAMADA"],
        resumen,
        semilla=123,
        clave="C0001|2026-09-22",
    )

    assert uno == dos
    assert muestras_uno == muestras_dos

    print("  Reproducibilidad: misma semilla y clave producen la misma decisión")


def prueba_respeta_canales_permitidos():
    resumen = {
        "EMAIL": {"exitos": 0, "fracasos": 100, "total": 100},
        "SMS": {"exitos": 0, "fracasos": 100, "total": 100},
        "WHATSAPP": {"exitos": 100, "fracasos": 0, "total": 100},
        "LLAMADA": {"exitos": 100, "fracasos": 0, "total": 100},
    }

    permitido = ["EMAIL", "SMS"]
    elegido, muestras = thompson.elegir(
        permitido,
        resumen,
        semilla=456,
        clave="restricciones",
    )

    assert elegido in permitido
    assert set(muestras) == set(permitido)
    assert "WHATSAPP" not in muestras
    assert "LLAMADA" not in muestras

    print("  Restricciones: Thompson solo evalúa canales permitidos")


def prueba_sin_historia():
    vacio = pd.DataFrame(columns=["canal", "sentido", "resultado"])
    resumen = thompson.estadisticas(vacio)

    assert not thompson.hay_historia(resumen)

    print("  Sin historia: el sistema detecta correctamente la ausencia de datos")


def prueba_no_usa_futuro():
    """Una evaluación histórica no puede aprender de gestiones posteriores."""
    from datetime import date

    gestiones = pd.DataFrame([
        {
            "fecha": "2026-09-10 10:00:00",
            "canal": "LLAMADA",
            "sentido": "SALIENTE",
            "resultado": "CONTACTO_TITULAR",
        },
        {
            "fecha": "2026-09-20 10:00:00",
            "canal": "LLAMADA",
            "sentido": "SALIENTE",
            "resultado": "NO_CONTESTA",
        },
    ])

    resumen = thompson.estadisticas(
        gestiones,
        hasta=date(2026, 9, 15),
    )

    assert resumen["LLAMADA"] == {
        "exitos": 1,
        "fracasos": 0,
        "total": 1,
    }

    print("  Temporalidad: no se usan gestiones posteriores a la fecha objetivo")


if __name__ == "__main__":
    print("Pruebas de muestreo de Thompson")
    prueba_estadisticas()
    prueba_reproducible()
    prueba_respeta_canales_permitidos()
    prueba_sin_historia()
    prueba_no_usa_futuro()
    print("Muestreo de Thompson verificado.")
