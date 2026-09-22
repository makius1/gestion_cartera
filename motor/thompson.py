# -*- coding: utf-8 -*-
"""
Selección adaptativa del canal mediante muestreo de Thompson.

Cada canal se modela con una distribución Beta(alpha, beta):

    alpha = 1 + respuestas observadas
    beta  = 1 + no respuestas observadas

Se considera respuesta una gestión SALIENTE cuyo resultado indique contacto
real con el titular. El suavizado Beta(1, 1) permite explorar canales con poca
o ninguna historia.

Este módulo no decide qué canales son legales o técnicamente disponibles.
Recibe únicamente los canales que sobrevivieron al motor de elegibilidad.
"""

import hashlib
import random

import config


def _es_respuesta(resultado):
    """Indica si el resultado representa respuesta real del titular."""
    return resultado in config.RESULTADOS_CON_CONTACTO


def estadisticas(gestiones, hasta=None):
    """Resume éxitos y fracasos por canal a partir del historial de gestiones.

    Solo usa gestiones SALIENTES porque son aquellas en las que el sistema
    eligió activamente un canal de cobranza.

    Retorna:
        {
            "EMAIL": {"exitos": 2, "fracasos": 8, "total": 10},
            ...
        }
    """
    resumen = {
        canal: {"exitos": 0, "fracasos": 0, "total": 0}
        for canal in config.CANALES
    }

    if gestiones is None or gestiones.empty:
        return resumen

    gestiones = gestiones.copy()

    # En ejecuciones retrospectivas solo se puede aprender de información
    # conocida hasta la fecha objetivo. Así se evita fuga de datos futuros.
    if hasta is not None and "fecha" in gestiones.columns:
        fechas = __import__("pandas").to_datetime(
            gestiones["fecha"], errors="coerce"
        ).dt.date
        gestiones = gestiones[fechas <= hasta]

    necesarias = {"canal", "resultado", "sentido"}
    faltantes = necesarias - set(gestiones.columns)
    if faltantes:
        raise ValueError(
            "El historial de gestiones no contiene: {}".format(
                ", ".join(sorted(faltantes))
            )
        )

    for fila in gestiones.to_dict(orient="records"):
        canal = fila.get("canal")
        sentido = fila.get("sentido")

        if sentido != "SALIENTE" or canal not in resumen:
            continue

        resumen[canal]["total"] += 1

        if _es_respuesta(fila.get("resultado")):
            resumen[canal]["exitos"] += 1
        else:
            resumen[canal]["fracasos"] += 1

    return resumen


def hay_historia(resumen):
    """True si existe al menos una observación de gestión saliente."""
    return any(datos["total"] > 0 for datos in resumen.values())


def _semilla_estable(semilla, clave):
    """Deriva una semilla estable sin depender del hash aleatorio de Python."""
    texto = "{}|{}".format(semilla, clave).encode("utf-8")
    return int(hashlib.sha256(texto).hexdigest()[:16], 16)


def elegir(canales_permitidos, resumen, semilla=config.SEMILLA, clave=""):
    """Selecciona un canal permitido mediante muestreo de Thompson.

    Para cada canal:
        theta ~ Beta(1 + exitos, 1 + fracasos)

    Se elige el canal cuyo theta sea mayor.

    La clave permite obtener una decisión reproducible por cuenta y fecha.
    """
    canales = list(canales_permitidos)

    if not canales:
        return None, {}

    desconocidos = [c for c in canales if c not in resumen]
    if desconocidos:
        raise ValueError(
            "Canales sin estadísticas: {}".format(", ".join(desconocidos))
        )

    rng = random.Random(_semilla_estable(semilla, clave))
    muestras = {}

    for canal in canales:
        datos = resumen[canal]
        alpha = 1 + datos["exitos"]
        beta = 1 + datos["fracasos"]
        muestras[canal] = rng.betavariate(alpha, beta)

    elegido = max(canales, key=lambda canal: muestras[canal])
    return elegido, muestras
