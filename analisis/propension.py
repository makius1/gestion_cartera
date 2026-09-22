# -*- coding: utf-8 -*-
"""
Propensión a compromiso de pago (fase 4).

Entrena regresión logística, árbol CART, bosque aleatorio y
HistGradientBoosting sobre el historial de gestiones, valida con fechas
posteriores al entrenamiento (nunca con una partición aleatoria: mezclaría
meses y daría una precisión falsa) y elige el mejor con el mismo principio de
todo el sistema: varios algoritmos compiten con métricas explícitas, y se
prefiere el modelo interpretable si el más complejo no lo supera por un
margen real. Ver docs/ALGORITMOS.md, sección 9.
"""

import base64
import io

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.tree import DecisionTreeClassifier

MODELOS = {
    "logistica": "Regresión logística",
    "cart": "Árbol CART",
    "bosque": "Bosque aleatorio",
    "boosting": "Gradient Boosting",
}

# Diferencia de AUC por debajo de la cual se prefiere el modelo interpretable
# sobre uno más complejo (principio de parsimonia, sección 9 de
# docs/ALGORITMOS.md): si la ganancia de precisión es marginal, no se
# justifica perder la explicación directa de sus coeficientes o sus reglas.
MARGEN_PARSIMONIA = 0.02
INTERPRETABLES = ("logistica", "cart")

CANALES = ["LLAMADA", "WHATSAPP", "SMS", "EMAIL"]


def _construir_modelo(nombre):
    if nombre == "logistica":
        return LogisticRegression(max_iter=1000, class_weight="balanced")
    if nombre == "cart":
        return DecisionTreeClassifier(max_depth=6, min_samples_leaf=30, class_weight="balanced")
    if nombre == "bosque":
        return RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=20,
                                      class_weight="balanced", n_jobs=-1, random_state=1)
    if nombre == "boosting":
        return HistGradientBoostingClassifier(max_depth=6, max_iter=200, random_state=1)
    raise ValueError("Modelo desconocido: {}".format(nombre))


def preparar_dataset(carga_id):
    """Arma la tabla de entrenamiento a partir del historial de gestiones.

    Cada fila es una gestión. Las variables se reconstruyen con la misma
    fórmula del simulador (datos/generador.py:_probabilidad_pago): mora
    efectiva en la fecha de la gestión (la mora de la carga más los días
    transcurridos desde que se registró), saldo, contactabilidad (canales de
    contacto que tenía la cuenta) y el canal usado. El objetivo es 1 si la
    gestión terminó en ACUERDO, 0 en cualquier otro resultado.
    """
    from datos import base_datos as bd

    gestiones = bd.leer_gestiones(carga_id)
    if gestiones.empty:
        raise ValueError("La carga {} no tiene gestiones. Simule un historial primero "
                         "(python -m datos.generador --historial).".format(carga_id))

    cartera = bd.leer_cartera(carga_id)[
        ["credito_id", "saldo", "dias_mora", "tiene_celular", "tiene_fijo", "tiene_email"]]
    cartera.columns = cartera.columns.astype(str)
    fecha_carga = bd.listar_cargas().set_index("id").loc[carga_id, "fecha_carga"]

    datos = gestiones.merge(cartera, on="credito_id", how="inner")
    datos.columns = [str(c) for c in datos.columns]
    datos["fecha"] = pd.to_datetime(datos["fecha"])
    datos["mora_efectiva"] = datos["dias_mora"] + (datos["fecha"] - fecha_carga).dt.days
    datos["contactabilidad"] = (datos[["tiene_celular", "tiene_fijo", "tiene_email"]]
                                .fillna(False).sum(axis=1))
    datos["acuerdo"] = (datos["resultado"] == "ACUERDO").astype(int)

    for c in CANALES:
        datos["canal_" + c.lower()] = (datos["canal"] == c).astype(int)

    columnas_x = ["mora_efectiva", "saldo", "contactabilidad"] + ["canal_" + c.lower() for c in CANALES]
    datos = datos.dropna(subset=columnas_x + ["acuerdo"])
    return datos, columnas_x


def _particion_temporal(datos, fecha_corte=None):
    """Separa entrenamiento y validación por fecha, no al azar.

    Sin fecha de corte se usa el punto que deja el 75 % más antiguo de las
    gestiones para entrenar y el 25 % más reciente para validar. Es el
    criterio de aceptación central del issue #12: validar con fechas
    posteriores al entrenamiento, como el modelo se va a usar en producción.
    """
    datos = datos.sort_values("fecha")
    if fecha_corte is None:
        fecha_corte = datos["fecha"].quantile(0.75, interpolation="nearest")
    entrenamiento = datos[datos["fecha"] < fecha_corte]
    validacion = datos[datos["fecha"] >= fecha_corte]
    return entrenamiento, validacion, fecha_corte


def _ks(y_true, y_score):
    """Estadístico Kolmogorov-Smirnov: separación máxima entre las curvas
    acumuladas de puntaje de quienes pagaron y quienes no."""
    orden = np.argsort(y_score)
    y_true = np.asarray(y_true)[orden]
    positivos, negativos = y_true.sum(), len(y_true) - y_true.sum()
    if positivos == 0 or negativos == 0:
        return 0.0
    cum_pos = np.cumsum(y_true) / positivos
    cum_neg = np.cumsum(1 - y_true) / negativos
    return float(np.max(np.abs(cum_pos - cum_neg)))


def _psi(esperado, observado, cortes=10):
    """Índice de estabilidad poblacional: cuánto cambió la distribución de
    probabilidades predichas entre entrenamiento y validación. Menor es
    más estable."""
    bordes = np.quantile(esperado, np.linspace(0, 1, cortes + 1))
    bordes[0], bordes[-1] = -np.inf, np.inf
    freq_e, _ = np.histogram(esperado, bins=bordes)
    freq_o, _ = np.histogram(observado, bins=bordes)
    p_e = np.clip(freq_e / len(esperado), 1e-6, None)
    p_o = np.clip(freq_o / len(observado), 1e-6, None)
    return float(np.sum((p_o - p_e) * np.log(p_o / p_e)))


def _captura_20pct(y_true, y_score):
    """Fracción del total de acuerdos que caería en el 20 % de cuentas con
    mayor puntaje: qué tan bien el modelo concentra el recaudo en la cola."""
    n = max(1, int(len(y_true) * 0.20))
    top = np.argsort(y_score)[::-1][:n]
    total = np.asarray(y_true).sum()
    return float(np.asarray(y_true)[top].sum() / total) if total else 0.0


def entrenar_y_comparar(carga_id, fecha_corte=None):
    """Entrena los cuatro modelos, los valida con fechas posteriores al
    entrenamiento y elige el mejor por un puntaje compuesto, con parsimonia.

    Retorna (resumen, modelo_ganador, columnas_x). `resumen` queda listo
    para bd.guardar_modelo_propension().
    """
    datos, columnas_x = preparar_dataset(carga_id)
    entrenamiento, validacion, fecha_corte = _particion_temporal(datos, fecha_corte)
    if len(entrenamiento) < 30 or len(validacion) < 30:
        raise ValueError("Muy pocas gestiones para entrenar y validar con confianza "
                         "({} y {}). Simule más semanas de historial.".format(
                             len(entrenamiento), len(validacion)))

    X_train, y_train = entrenamiento[columnas_x], entrenamiento["acuerdo"]
    X_valid, y_valid = validacion[columnas_x], validacion["acuerdo"]

    metricas, modelos_entrenados = {}, {}
    for nombre in MODELOS:
        modelo = _construir_modelo(nombre)
        modelo.fit(X_train, y_train)
        prob_valid = modelo.predict_proba(X_valid)[:, 1]
        prob_train = modelo.predict_proba(X_train)[:, 1]
        metricas[nombre] = {
            "auc": float(roc_auc_score(y_valid, prob_valid)) if y_valid.nunique() > 1 else 0.5,
            "ks": _ks(y_valid, prob_valid),
            "brier": float(brier_score_loss(y_valid, prob_valid)),
            "psi": _psi(prob_train, prob_valid),
            "captura_20pct": _captura_20pct(y_valid, prob_valid),
        }
        modelos_entrenados[nombre] = modelo

    # Puntaje compuesto: AUC, KS y captura son "mejor cuanto más alto"; Brier
    # y PSI son "mejor cuanto más bajo", así que se invierten antes de sumar.
    tabla = pd.DataFrame(metricas).T
    rango = lambda s: (s.max() - s.min()) + 1e-9
    puntaje = (
        0.35 * (tabla["auc"] - tabla["auc"].min()) / rango(tabla["auc"])
        + 0.30 * (tabla["ks"] - tabla["ks"].min()) / rango(tabla["ks"])
        + 0.20 * (tabla["brier"].max() - tabla["brier"]) / rango(tabla["brier"])
        + 0.15 * (tabla["psi"].max() - tabla["psi"]) / rango(tabla["psi"])
    )
    ganador = puntaje.sort_values(ascending=False).index[0]

    # Parsimonia: si un modelo interpretable queda a menos de 0,02 de AUC del
    # mejor, se prefiere el interpretable (sección 9 de ALGORITMOS.md).
    mejor_auc = tabla.loc[ganador, "auc"]
    for candidato in INTERPRETABLES:
        if candidato in tabla.index and mejor_auc - tabla.loc[candidato, "auc"] < MARGEN_PARSIMONIA:
            ganador = candidato
            break

    buffer = io.BytesIO()
    joblib.dump(modelos_entrenados[ganador], buffer)
    modelo_serializado = base64.b64encode(buffer.getvalue()).decode("ascii")

    resumen = {
        "carga_id": carga_id,
        "fecha_corte": fecha_corte.date() if hasattr(fecha_corte, "date") else fecha_corte,
        "modelo_elegido": ganador,
        "auc": float(tabla.loc[ganador, "auc"]),
        "ks": float(tabla.loc[ganador, "ks"]),
        "brier": float(tabla.loc[ganador, "brier"]),
        "psi": float(tabla.loc[ganador, "psi"]),
        "captura_20pct": float(tabla.loc[ganador, "captura_20pct"]),
        "metricas_todos": metricas,
        "modelo_serializado": modelo_serializado,
    }
    return resumen, modelos_entrenados[ganador], columnas_x


def ejecutar(carga_id, fecha_corte=None, usuario="sistema"):
    """Entrena, compara y guarda. Retorna el resumen con el id del modelo."""
    from datos import base_datos as bd

    resumen, _, _ = entrenar_y_comparar(carga_id, fecha_corte)
    resumen["modelo_id"] = bd.guardar_modelo_propension(resumen, usuario)
    return resumen