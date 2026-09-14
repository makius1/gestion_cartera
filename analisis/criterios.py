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


def preparar(cartera):
    """Tabla de criterios indexada por crédito, sin valores faltantes."""
    tabla = pd.DataFrame(index=cartera["credito_id"].values)
    tabla["saldo"] = pd.to_numeric(cartera["saldo"], errors="coerce").values
    tabla["contactabilidad"] = contactabilidad(cartera).values
    tabla["dias_mora"] = pd.to_numeric(cartera["dias_mora"], errors="coerce").values
    tabla["margen_pct"] = pd.to_numeric(cartera["margen_pct"], errors="coerce").values
    tabla["meses_en_gestion"] = pd.to_numeric(cartera["meses_en_gestion"], errors="coerce").values
    # Un faltante se reemplaza por la mediana de la cartera: ni premia ni castiga
    # a la cuenta en ese criterio.
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
