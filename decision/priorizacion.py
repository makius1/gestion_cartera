# -*- coding: utf-8 -*-
"""
Priorización de la cartera con tres métodos y selección del óptimo.

Decide en qué orden trabajar las cuentas contactables. En lugar de apostar por
un solo método, calcula tres y elige el mejor para esta cartera con un puntaje
explícito:

  1. Lógica difusa (Mamdani). Razona como el experto, con reglas lingüísticas
     del tipo "saldo alto y mora reciente, prioridad alta". Las reglas están en
     conocimiento_difuso.py.
  2. TOPSIS. Método multicriterio clásico: ordena cada cuenta por su cercanía a
     una cuenta ideal (mejor valor en cada criterio) y su lejanía de la peor.
  3. Ponderación simple (SAW). Normaliza cada criterio entre 0 y 1 y suma con
     los pesos de config.py. Es la referencia: lo que haría una hoja de cálculo.

Cómo se elige el óptimo (métricas en el mismo orden de importancia):

  * Recaudo esperado: cuánto dinero se espera recuperar si el equipo trabaja,
    en el orden del método, las cuentas que le caben en un día. Por cuenta es
    piso de cobranza × contactabilidad × tasa de respuesta del canal.
  * Robustez: se perturban los datos ±10 % varias veces y se mide cuánto de la
    cola del día se mantiene (índice de Jaccard). Un método cuya cola cambia con
    un error de digitación no es confiable.
  * Discriminación: fracción de puntajes distintos dentro de la cola. Un método
    que deja cientos de cuentas empatadas obliga a desempatar a ciegas.

Puntaje = 0,60 × recaudo relativo + 0,25 × robustez + 0,15 × discriminación.

Uso desde la terminal (la operación normal es desde la aplicación web):
    python -m decision.priorizacion [--carga N] [--ejecucion N] [--no-guardar]
"""

import argparse

import numpy as np
import pandas as pd
import skfuzzy as fuzz

import config
from analisis import criterios as crit
from analisis import segmentacion
from decision import conocimiento_difuso as kd

METODOS = {"difuso": "Lógica difusa", "topsis": "TOPSIS", "ponderado": "Ponderación simple"}
PUNTOS_SALIDA = 201     # resolución del universo de salida para el centro de gravedad


# ---------------------------------------------------------------------------
# 1. LÓGICA DIFUSA (MAMDANI)
# ---------------------------------------------------------------------------

def _pertenencia(valores, definicion):
    forma, puntos = definicion
    x = np.asarray(valores, dtype=float)
    return fuzz.trimf(x, puntos) if forma == "tri" else fuzz.trapmf(x, puntos)


def entradas_difusas(criterios):
    """Adapta los criterios al universo de cada variable difusa.

    El saldo pasa a percentil dentro de la cartera. Los demás se recortan a su
    universo: una mora de 4.000 días es tan "antigua" como una de 3.000, y sin
    el recorte quedaría fuera de todo conjunto, con pertenencia cero.
    """
    entradas = pd.DataFrame(index=criterios.index)
    entradas["saldo"] = criterios["saldo"].rank(pct=True)
    for variable in ("dias_mora", "contactabilidad", "margen_pct", "meses_en_gestion"):
        bajo, alto = kd.VARIABLES[variable]["universo"]
        entradas[variable] = criterios[variable].clip(bajo, alto)
    return entradas


def inferir_difuso(criterios, detalle=False):
    """Inferencia Mamdani vectorizada sobre todas las cuentas a la vez.

    1. Fuzzificación: grado de pertenencia de cada cuenta a cada conjunto.
    2. Evaluación de reglas: la fuerza de una regla es el MÍNIMO de los grados
       de sus premisas (conjunción).
    3. Implicación y agregación: cada regla recorta su conjunto de salida a su
       fuerza (MIN) y los recortes se unen tomando el MÁXIMO punto a punto.
    4. Defuzzificación: centro de gravedad del área resultante.

    Se calcula como matrices (cuentas × puntos de salida) en lugar de un ciclo
    por cuenta: 5.000 cuentas se resuelven en una fracción de segundo.
    """
    entradas = entradas_difusas(criterios)
    grados = {(v, c): _pertenencia(entradas[v].values, d)
              for v, var in kd.VARIABLES.items() for c, d in var["conjuntos"].items()}

    y = np.linspace(*kd.SALIDA["universo"], PUNTOS_SALIDA)
    salida = {c: _pertenencia(y, d) for c, d in kd.SALIDA["conjuntos"].items()}

    agregada = np.zeros((len(entradas), len(y)))
    fuerzas = {}
    for regla in kd.REGLAS_DIFUSAS:
        fuerza = np.minimum.reduce([grados[(v, c)] for v, c in regla["si"].items()])
        fuerzas[regla["id"]] = fuerza
        agregada = np.maximum(agregada, np.minimum(fuerza[:, None], salida[regla["entonces"]][None, :]))

    area = agregada.sum(axis=1)
    # Si ninguna regla se activa el área es cero; la validación de cobertura lo
    # impide, pero se protege la división de todos modos.
    puntaje = np.divide((agregada * y).sum(axis=1), area, out=np.zeros(len(area)), where=area > 0)
    puntaje = pd.Series(puntaje, index=criterios.index)
    if detalle:
        return puntaje, {"entradas": entradas, "grados": grados, "fuerzas": fuerzas}
    return puntaje


# ---------------------------------------------------------------------------
# 2. TOPSIS Y PONDERACIÓN SIMPLE
# ---------------------------------------------------------------------------

def _pesos_y_sentidos():
    columnas = list(config.CRITERIOS)
    pesos = np.array([config.CRITERIOS[c]["peso"] for c in columnas])
    beneficio = np.array([config.CRITERIOS[c]["sentido"] == "beneficio" for c in columnas])
    return columnas, pesos / pesos.sum(), beneficio


def topsis(criterios, detalle=False):
    """Cercanía relativa a la solución ideal, de 0 a 100.

    Normalización vectorial, ponderación, distancia euclidiana a la cuenta
    ideal (mejor valor de cada criterio) y a la anti-ideal (peor valor). La
    cercanía es d- / (d+ + d-): 1 si la cuenta es la ideal, 0 si es la peor.
    """
    columnas, pesos, beneficio = _pesos_y_sentidos()
    x = criterios[columnas].values
    norma = np.sqrt((x ** 2).sum(axis=0))
    v = np.divide(x, norma, out=np.zeros_like(x), where=norma > 0) * pesos
    ideal = np.where(beneficio, v.max(axis=0), v.min(axis=0))
    anti = np.where(beneficio, v.min(axis=0), v.max(axis=0))
    d_ideal = np.sqrt(((v - ideal) ** 2).sum(axis=1))
    d_anti = np.sqrt(((v - anti) ** 2).sum(axis=1))
    total = d_ideal + d_anti
    cercania = np.divide(d_anti, total, out=np.zeros_like(total), where=total > 0)
    puntaje = pd.Series(100 * cercania, index=criterios.index)
    if detalle:
        return puntaje, {"d_ideal": pd.Series(d_ideal, index=criterios.index),
                         "d_anti": pd.Series(d_anti, index=criterios.index)}
    return puntaje


def ponderado(criterios):
    """Suma ponderada de criterios normalizados entre 0 y 1 (0 a 100).

    En los criterios de costo la escala se invierte: la cuenta con menos mora
    recibe 1 y la de más mora recibe 0.
    """
    columnas, pesos, beneficio = _pesos_y_sentidos()
    x = criterios[columnas].values
    minimo, maximo = x.min(axis=0), x.max(axis=0)
    rango = np.where(maximo > minimo, maximo - minimo, 1)
    normal = (x - minimo) / rango
    normal = np.where(beneficio, normal, 1 - normal)
    return pd.Series(100 * (normal * pesos).sum(axis=1), index=criterios.index)


def calcular(criterios):
    """Puntaje de cada cuenta con los tres métodos."""
    return {"difuso": inferir_difuso(criterios), "topsis": topsis(criterios),
            "ponderado": ponderado(criterios)}


# ---------------------------------------------------------------------------
# 3. EVALUACIÓN Y SELECCIÓN DEL MÉTODO ÓPTIMO
# ---------------------------------------------------------------------------

def ordenar(puntaje, saldo):
    """Índices ordenados por puntaje descendente; los empates se resuelven por
    saldo mayor y luego por crédito, para que el orden sea siempre el mismo."""
    tabla = pd.DataFrame({"p": puntaje.round(6), "s": saldo, "c": puntaje.index})
    return tabla.sort_values(["p", "s", "c"], ascending=[False, False, True]).index


def evaluar(criterios, candidatos, valor_esperado, capacidad, semilla=config.SEMILLA):
    """Métricas de cada método sobre las cuentas candidatas y método elegido."""
    base = criterios.loc[candidatos]
    k = max(1, min(capacidad, len(base)))
    puntajes = calcular(base)
    colas = {m: set(ordenar(p, base["saldo"])[:k]) for m, p in puntajes.items()}

    replicas = [calcular(crit.perturbar(base, semilla + r)) for r in range(config.REPLICAS_ROBUSTEZ)]
    metricas = {}
    for m, p in puntajes.items():
        jaccard = []
        for replica in replicas:
            otra = set(ordenar(replica[m], base["saldo"])[:k])
            jaccard.append(len(colas[m] & otra) / len(colas[m] | otra))
        cola = list(colas[m])
        metricas[m] = {
            "recaudo": float(valor_esperado.loc[cola].sum()),
            "robustez": float(np.mean(jaccard)),
            "discriminacion": float(p.loc[cola].round(2).nunique() / len(cola)),
        }

    mejor_recaudo = max(v["recaudo"] for v in metricas.values()) or 1
    pesos = config.PESOS_EVALUACION
    for v in metricas.values():
        v["recaudo_relativo"] = v["recaudo"] / mejor_recaudo
        v["puntaje"] = (pesos["recaudo"] * v["recaudo_relativo"] + pesos["robustez"] * v["robustez"]
                        + pesos["discriminacion"] * v["discriminacion"])
    elegido = max(metricas, key=lambda m: metricas[m]["puntaje"])
    return elegido, metricas, k


# ---------------------------------------------------------------------------
# 4. EJECUCIÓN COMPLETA
# ---------------------------------------------------------------------------

def _valor_esperado(cartera, criterios, canales):
    """Recaudo esperado de contactar cada cuenta hoy por su canal."""
    piso = pd.Series(pd.to_numeric(cartera["cobranza_min"], errors="coerce").fillna(0).values,
                     index=criterios.index)
    tasa = canales.map(lambda c: config.CANALES.get(c, config.CANALES["LLAMADA"])["tasa_respuesta"])
    return piso * criterios["contactabilidad"] * tasa


def priorizar(cartera, evaluacion=None, capacidad=None, semilla=config.SEMILLA):
    """Segmenta, prioriza con los tres métodos y elige el óptimo.

    Sin evaluación del motor, las candidatas son las cuentas gestionables y el
    canal de referencia es la llamada. Con evaluación, solo las CONTACTABLES,
    cada una con el canal que recomendó el motor.
    """
    criterios = crit.preparar(cartera)
    capacidad = capacidad or config.NUMERO_GESTORES * config.GESTIONES_POR_GESTOR_DIA

    if evaluacion is not None:
        estados = evaluacion.set_index("credito_id")["estado"].reindex(criterios.index)
        canales = evaluacion.set_index("credito_id")["canal_recomendado"].reindex(criterios.index)
        candidatos = estados.index[estados == "CONTACTABLE"]
    else:
        estados = pd.Series(None, index=criterios.index, dtype=object)
        canales = pd.Series("LLAMADA", index=criterios.index)
        candidatos = criterios.index[cartera["gestionable"].astype(bool).values]
    if len(candidatos) == 0:
        raise LookupError("No hay cuentas candidatas para priorizar: la ejecución del motor no "
                          "dejó ninguna cuenta contactable.")

    seg = segmentacion.segmentar(criterios, semilla)
    valor = _valor_esperado(cartera, criterios, canales.fillna("LLAMADA"))
    elegido, metricas, k = evaluar(criterios, candidatos, valor, capacidad, semilla)

    # Puntajes finales sobre las candidatas (los mismos que se evaluaron) y, como
    # referencia, sobre toda la cartera para las que no entran hoy.
    todas = calcular(criterios)
    en_cola = calcular(criterios.loc[candidatos])
    tabla = pd.DataFrame(index=criterios.index)
    tabla["credito_id"] = criterios.index
    tabla["segmento"] = seg["etiquetas"]
    tabla["nombre_segmento"] = tabla["segmento"].map(seg["nombres"])
    tabla["estado_motor"] = estados
    tabla["candidata"] = tabla.index.isin(candidatos)
    for m in METODOS:
        tabla["puntaje_" + m] = todas[m].round(2)
        tabla.loc[candidatos, "puntaje_" + m] = en_cola[m].round(2)
    tabla["prioridad"] = tabla["puntaje_" + elegido]
    orden = ordenar(en_cola[elegido], criterios.loc[candidatos, "saldo"])
    # Entero con nulos: las cuentas que no son candidatas no tienen posición.
    tabla["posicion"] = (pd.Series(np.arange(1, len(orden) + 1), index=orden)
                         .reindex(tabla.index).astype("Int64"))
    tabla["en_capacidad"] = tabla["posicion"].le(k).fillna(False).astype(bool)
    tabla[["pca_x", "pca_y"]] = seg["pca"].round(4).values
    tabla["valor_esperado"] = valor.round(0)

    perfiles = seg["perfiles"].copy()
    perfiles["prioridad_media"] = tabla.groupby("segmento")["prioridad"].mean()
    perfiles["en_capacidad"] = tabla.groupby("segmento")["en_capacidad"].sum()

    resumen = {
        "candidatos": int(len(candidatos)), "capacidad": int(k), "k": seg["k"],
        "silueta": seg["silueta"], "elegido": elegido,
        "detalle": {
            "metricas": metricas,
            "siluetas": {str(kk): v for kk, v in seg["siluetas"].items()},
            "segmentacion": {"algoritmo": seg["algoritmo"], "comparacion": seg["comparacion"]},
            "perfiles": perfiles.reset_index().to_dict(orient="records"),
            "criterios": config.CRITERIOS,
            "pesos_evaluacion": config.PESOS_EVALUACION,
        },
    }
    return resumen, tabla


def ejecutar(carga_id=None, ejecucion_id=None, usuario="sistema", guardar=True):
    """Lee la cartera (y la evaluación del motor), prioriza y guarda."""
    from datos import base_datos as bd

    errores = kd.validar()
    if errores:
        raise ValueError("La base de conocimiento difusa tiene errores: " + "; ".join(errores))

    # Se asegura que la base tenga el esquema al día antes de leer: una base
    # creada con una versión anterior no tendría las columnas nuevas.
    bd.crear_esquema()
    cartera = bd.leer_cartera(carga_id)
    if cartera.empty:
        raise LookupError("No hay cartera cargada para priorizar.")
    carga_id = int(cartera["carga_id"].iloc[0])
    evaluacion = bd.leer_evaluaciones(ejecucion_id) if ejecucion_id else None

    resumen, tabla = priorizar(cartera, evaluacion)
    resumen["carga_id"] = carga_id
    resumen["ejecucion_id"] = int(ejecucion_id) if ejecucion_id else None

    if guardar:
        resumen["priorizacion_id"] = bd.guardar_priorizacion(resumen, tabla, usuario)
        bd.registrar_evento(usuario, "PRIORIZAR", "Priorización {} sobre la carga {}: {} candidatas, "
                            "método elegido {}".format(resumen["priorizacion_id"], carga_id,
                                                       resumen["candidatos"], resumen["elegido"]))
    return resumen, tabla


def explicar_cuenta(cartera, credito_id, candidatos=None):
    """Detalle del razonamiento de los métodos para una cuenta.

    Se recalcula sobre el mismo conjunto de candidatas con el que se guardó la
    priorización: el saldo difuso es un percentil y TOPSIS compara contra la
    mejor y la peor cuenta, así que el resultado de una cuenta depende de con
    cuáles otras se compara.
    """
    criterios = crit.preparar(cartera)
    if candidatos is not None:
        criterios = criterios.loc[list(candidatos)]
    _, difuso = inferir_difuso(criterios, detalle=True)
    _, dist = topsis(criterios, detalle=True)
    i = criterios.index.get_loc(credito_id)
    grados = {v: {c: float(difuso["grados"][(v, c)][i]) for c in kd.VARIABLES[v]["conjuntos"]}
              for v in kd.VARIABLES}
    reglas = sorted(((r["id"], float(difuso["fuerzas"][r["id"]][i])) for r in kd.REGLAS_DIFUSAS),
                    key=lambda t: t[1], reverse=True)
    return {"criterios": criterios.loc[credito_id].to_dict(),
            "entradas": difuso["entradas"].loc[credito_id].to_dict(),
            "grados": grados, "reglas": reglas,
            "d_ideal": float(dist["d_ideal"].loc[credito_id]),
            "d_anti": float(dist["d_anti"].loc[credito_id])}


# ---------------------------------------------------------------------------
# 5. LÍNEA DE COMANDOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Segmentación y priorización de la cartera.")
    parser.add_argument("--carga", type=int, default=None)
    parser.add_argument("--ejecucion", type=int, default=None,
                        help="ejecución del motor de la que salen las cuentas contactables")
    parser.add_argument("--no-guardar", action="store_true")
    args = parser.parse_args()

    resumen, tabla = ejecutar(args.carga, args.ejecucion, usuario="terminal",
                              guardar=not args.no_guardar)
    print("Carga {} | candidatas {:,} | capacidad del día {:,}".format(
        resumen["carga_id"], resumen["candidatos"], resumen["capacidad"]))
    seg = resumen["detalle"]["segmentacion"]
    print("\n  {:<20} {:>3} {:>8} {:>10} {:>8} {:>7} {:>8}".format(
        "Segmentación", "k", "Silueta", "Calinski", "Davies", "Mínimo", "Puntaje"))
    for nombre, v in seg["comparacion"].items():
        print("  {:<20} {:>3} {:>8.3f} {:>10.1f} {:>8.3f} {:>6.1%} {:>8.3f}{}".format(
            segmentacion.ALGORITMOS[nombre], v["k"], v["silueta"], v["calinski"], v["davies"],
            v["minimo"], v["puntaje"], "  ← elegido" if nombre == seg["algoritmo"] else ""))
    print("Segmentos: {} (silueta {:.3f})".format(resumen["k"], resumen["silueta"]))
    for fila in resumen["detalle"]["perfiles"]:
        print("  {:<55} {:>6,} cuentas".format(fila["nombre"], fila["cuentas"]))
    print("\n  {:<20} {:>16} {:>9} {:>14} {:>8}".format(
        "Método", "Recaudo esperado", "Robustez", "Discriminación", "Puntaje"))
    for m, v in resumen["detalle"]["metricas"].items():
        print("  {:<20} {:>16,.0f} {:>9.3f} {:>14.3f} {:>8.3f}{}".format(
            METODOS[m], v["recaudo"], v["robustez"], v["discriminacion"], v["puntaje"],
            "  ← elegido" if m == resumen["elegido"] else ""))
    if "priorizacion_id" in resumen:
        print("\n  Guardada como priorización {}".format(resumen["priorizacion_id"]))
