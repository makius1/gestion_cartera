# -*- coding: utf-8 -*-
"""
Criterios de decisión de cada cuenta.

La segmentación y los tres métodos de priorización trabajan sobre la misma
tabla de criterios. Tenerla en un solo lugar garantiza que la comparación entre
métodos sea justa: todos ven exactamente los mismos datos.
"""

import numpy as np
import pandas as pd

import config

COLUMNAS = list(config.CRITERIOS)


def contactabilidad(cartera):
    """Probabilidad relativa de contacto efectivo, entre 0 y 1.

    Combina el resultado de la última gestión (70 %), que dice qué pasó la
    última vez que se intentó, con la cantidad de canales disponibles (30 %),
    que dice por cuántas vías más se puede intentar.
    """
    por_resultado = (cartera["resultado_gestion"].map(config.CONTACTABILIDAD_RESULTADO)
                     .fillna(config.CONTACTABILIDAD_RESULTADO["OTRO"]))
    por_canales = pd.to_numeric(cartera["canales_disponibles"], errors="coerce").fillna(0) / 4
    return (0.7 * por_resultado + 0.3 * por_canales.clip(0, 1)).astype(float)


def preparar(cartera, canales=None, usar_modelo=True):
    """Tabla de criterios indexada por crédito, sin valores faltantes.

    contactabilidad viene del modelo de propensión entrenado (issue #12)
    cuando usar_modelo=True y hay un modelo guardado para esta carga; si no
    hay modelo, o usar_modelo=False, usa la heurística del experto (sección
    1.3 de docs/ALGORITMOS.md). Con usar_modelo=True y sin modelo entrenado
    cae a la heurística sin avisar: mantiene la priorización operando aunque
    todavía no se haya entrenado un modelo para esa carga.
    """
    tabla = pd.DataFrame(index=cartera["credito_id"].values)
    tabla["saldo"] = pd.to_numeric(cartera["saldo"], errors="coerce").values

    probabilidad = None
    if usar_modelo:
        from analisis import propension
        probabilidad = propension.predecir(cartera, canales=canales)
    if probabilidad is not None:
        tabla["contactabilidad"] = probabilidad.reindex(tabla.index).values
    else:
        tabla["contactabilidad"] = contactabilidad(cartera).values

    tabla["dias_mora"] = pd.to_numeric(cartera["dias_mora"], errors="coerce").values
    tabla["margen_pct"] = pd.to_numeric(cartera["margen_pct"], errors="coerce").values
    tabla["meses_en_gestion"] = pd.to_numeric(cartera["meses_en_gestion"], errors="coerce").values
    return tabla.fillna(tabla.median(numeric_only=True)).astype(float)


def perturbar(criterios, semilla, ruido=config.RUIDO_ROBUSTEZ):
    """Copia de los criterios con una variación aleatoria de ±ruido.

    Sirve para medir la robustez de un método: si una variación pequeña en los
    datos —del orden del error de digitación o de un día más de mora— cambia
    mucho la cola de trabajo, el método no es confiable.
    """
    rng = np.random.default_rng(semilla)
    factor = rng.uniform(1 - ruido, 1 + ruido, size=criterios.shape)
    variada = criterios * factor
    variada["contactabilidad"] = variada["contactabilidad"].clip(0, 1)
    return variada
