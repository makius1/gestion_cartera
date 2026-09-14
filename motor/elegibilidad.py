# -*- coding: utf-8 -*-
"""
Motor de inferencia de elegibilidad de contacto.

Recibe la cartera de una carga y una fecha, y decide para cada cuenta:

  * si puede contactarse ese día (CONTACTABLE), si solo corresponde un
    recordatorio de compromiso (RECORDATORIO), si hay que esperar la fecha de un
    acuerdo (EN_ESPERA) o si está prohibido contactarla (BLOQUEADA);
  * por qué canales puede hacerse el contacto;
  * qué canal conviene usar;
  * y por qué: qué reglas se dispararon y cuál de ellas determinó el resultado.

El motor no contiene ninguna regla de cobranza. Las lee de base_conocimiento.py
y las aplica por fases, en encadenamiento hacia adelante: parte de los hechos
de la cuenta y va agregando conclusiones hasta llegar a una decisión. Es el
mismo esquema de la sesión 2, llevado a un caso de negocio.

Tratamiento de hechos desconocidos: si un dato de la cuenta está vacío, las
premisas que dependen de él no se cumplen. Para que eso nunca termine en un
contacto que viole la ley, la regla L3 bloquea toda cuenta a la que le falte la
información necesaria para verificar las demás.

Uso desde la terminal (la operación normal es desde la aplicación web):
    python -m motor.elegibilidad [--carga N] [--fecha AAAA-MM-DD] [--no-guardar]
    python -m motor.elegibilidad --validar
"""

import argparse
from collections import Counter
from datetime import date
from functools import lru_cache

import holidays
import pandas as pd

import config
from motor import base_conocimiento as bc

ESTADO_INICIAL = "CONTACTABLE"
ESTADOS = ["CONTACTABLE", "RECORDATORIO", "EN_ESPERA", "BLOQUEADA"]
NOMBRE_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ---------------------------------------------------------------------------
# 1. CALENDARIO
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _festivos(anio):
    """Festivos de Colombia de un año, calculados una sola vez.

    La librería aplica la Ley Emiliani: los festivos que se trasladan al lunes
    aparecen en el lunes correspondiente y no en la fecha original.
    """
    return holidays.country_holidays("CO", years=anio)


def diagnostico_fecha(fecha):
    """Describe si una fecha permite contacto y en qué horario."""
    festivos = _festivos(fecha.year)
    if fecha in festivos:
        return {"dia_habil": False, "motivo": "festivo: {}".format(festivos.get(fecha)),
                "horario": None}
    franja = config.HORARIO_HABIL.get(fecha.weekday())
    if franja is None:
        return {"dia_habil": False, "motivo": NOMBRE_DIA[fecha.weekday()], "horario": None}
    return {"dia_habil": True, "motivo": NOMBRE_DIA[fecha.weekday()],
            "horario": "{}:00 a {}:00".format(*franja)}


# ---------------------------------------------------------------------------
# 2. HECHOS
# ---------------------------------------------------------------------------
# Traduce una fila de la cartera al vocabulario que usan las reglas. Es el
# único lugar donde el motor conoce los nombres de las columnas de la base.

def _valor(fila, columna):
    """Valor de una columna como tipo nativo de Python, o None si está vacío."""
    valor = fila.get(columna)
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    if hasattr(valor, "item"):          # numpy.bool_, numpy.int64 → bool, int
        valor = valor.item()
    return valor


def _como_fecha(valor):
    if valor is None:
        return None
    return pd.Timestamp(valor).date()


def construir_hechos(fila, fecha_objetivo, dia=None):
    """Hechos de una cuenta para la fecha evaluada."""
    dia = dia or diagnostico_fecha(fecha_objetivo)
    gestionada = bool(_valor(fila, "gestionada"))

    # Días desde el último contacto REAL. Los registros automáticos del sistema
    # (SIN_GESTION_REAL) no son contacto con el titular y no cuentan para la
    # frecuencia. Un contacto posterior a la fecha evaluada tampoco cuenta: pasa
    # cuando se evalúa una fecha del pasado.
    ultima = _como_fecha(_valor(fila, "fecha_ultima_gestion"))
    dias_desde_contacto = None
    if gestionada and ultima is not None:
        diferencia = (fecha_objetivo - ultima).days
        dias_desde_contacto = diferencia if diferencia >= 0 else None

    compromiso = _como_fecha(_valor(fila, "fecha_compromiso"))
    dias_para_compromiso = (compromiso - fecha_objetivo).days if compromiso else None

    canales = {c: _valor(fila, c) for c in ("tiene_celular", "tiene_fijo", "tiene_email")}

    # Sin la fecha del último contacto de una cuenta gestionada, o sin saber qué
    # canales tiene, el motor no puede verificar las demás reglas. Pasa con
    # cargas anteriores a la ampliación del esquema.
    datos_completos = (not (gestionada and ultima is None)
                       and all(v is not None for v in canales.values()))

    return {
        "dia_habil": dia["dia_habil"],
        "datos_completos": datos_completos,
        "dias_desde_contacto": dias_desde_contacto,
        "dias_para_compromiso": dias_para_compromiso,
        "codigo": _valor(fila, "codigo"),
        "resultado_gestion": _valor(fila, "resultado_gestion"),
        **canales,
    }


# ---------------------------------------------------------------------------
# 3. EQUIPARACIÓN DE PATRONES
# ---------------------------------------------------------------------------

def _cumple_premisa(valor, esperado):
    """Compara un hecho con lo que exige una premisa.

    Un hecho desconocido (None) nunca cumple una premisa: el motor no dispara
    reglas sobre información que no tiene.
    """
    if valor is None:
        return False
    if isinstance(esperado, tuple):
        operador, referencia = esperado
        if operador == "<":
            return valor < referencia
        if operador == "<=":
            return valor <= referencia
        if operador == ">":
            return valor > referencia
        if operador == ">=":
            return valor >= referencia
        if operador == "en":
            return valor in referencia
        if operador == "entre":
            return referencia[0] <= valor <= referencia[1]
        raise ValueError("Operador desconocido: {}".format(operador))
    return valor == esperado


def se_cumple(regla, hechos):
    """Una regla se dispara si TODAS sus premisas se cumplen (conjunción)."""
    return all(_cumple_premisa(hechos.get(h), v) for h, v in regla["condicion"].items())


# ---------------------------------------------------------------------------
# 4. INFERENCIA
# ---------------------------------------------------------------------------

def evaluar_cuenta(hechos):
    """Aplica la base de conocimiento a los hechos de una cuenta.

    Recorre las fases en orden. Cada fase puede cerrar el razonamiento: si una
    regla de bloqueo se dispara, la cuenta no se contacta y lo que digan las
    fases siguientes ya no importa. Esa es la jerarquía de la base de
    conocimiento: la ley está por encima de la estrategia comercial.

    Retorna un diccionario con el estado, los canales, la regla determinante y
    la traza completa del razonamiento.
    """
    hechos = dict(hechos)
    estado = ESTADO_INICIAL
    canales = list(bc.CANALES_POR_COSTO)
    traza = []
    determinante = None
    preferidos = None

    # --- Fase 1: bloqueos. Se evalúan TODAS las reglas y no solo la primera,
    # para que la explicación diga todos los motivos. La primera que se dispara
    # es la determinante.
    bloqueos = [r for r in bc.reglas_de_fase("bloqueos") if se_cumple(r, hechos)]
    for regla in bloqueos:
        traza.append(("bloqueos", regla))
    if bloqueos:
        return _resultado("BLOQUEADA", [], None, bloqueos[0], traza, hechos, [])

    # --- Fase 2: compromisos. Las reglas son excluyentes entre sí (sus rangos
    # de días no se solapan), así que a lo sumo se dispara una.
    for regla in bc.reglas_de_fase("compromisos"):
        if se_cumple(regla, hechos):
            traza.append(("compromisos", regla))
            estado = regla["efecto"]["estado"]
            preferidos = regla["efecto"].get("canales_preferidos")
            determinante = regla
            break
    if estado == "EN_ESPERA":
        return _resultado(estado, [], None, determinante, traza, hechos, [])

    # --- Fase 3: canales. Cada regla quita los canales que no se pueden usar.
    for regla in bc.reglas_de_fase("canales"):
        if se_cumple(regla, hechos):
            traza.append(("canales", regla))
            canales = [c for c in canales if c not in regla["efecto"]["quitar_canales"]]

    # --- Fase 4: cierre. El hecho derivado de la fase anterior se agrega a la
    # memoria de trabajo: así una regla puede razonar sobre conclusiones de
    # otras reglas, que es lo que distingue el encadenamiento de un filtro.
    hechos["canales_permitidos"] = len(canales)
    for regla in bc.reglas_de_fase("cierre"):
        if se_cumple(regla, hechos):
            traza.append(("cierre", regla))
            return _resultado("BLOQUEADA", [], None, regla, traza, hechos, [])

    # --- Fase 5: estrategia.
    if estado == "RECORDATORIO":
        canal = next((c for c in preferidos if c in canales), canales[0])
        return _resultado(estado, canales, canal, determinante, traza, hechos, [])

    # Conjunto de conflicto: todas las estrategias aplicables. Gana la de mayor
    # prioridad; las demás se conservan para la explicación.
    aplicables = sorted((r for r in bc.reglas_de_fase("estrategia") if se_cumple(r, hechos)),
                        key=lambda r: r["prioridad"], reverse=True)
    ganadora = aplicables[0]
    traza.append(("estrategia", ganadora))
    canal = ganadora["efecto"]["canal"]
    if canal not in canales:
        # El canal ideal no está disponible: se usa el más barato de los que
        # quedan. La lista ya viene ordenada por costo.
        canal = canales[0]
    return _resultado(ESTADO_INICIAL, canales, canal, ganadora, traza, hechos, aplicables[1:])


def _resultado(estado, canales, canal, determinante, traza, hechos, descartadas):
    return {
        "estado": estado,
        "canales_permitidos": canales,
        "canal_recomendado": canal,
        "regla_determinante": determinante["id"] if determinante else None,
        "reglas": [regla["id"] for _, regla in traza],
        "traza": traza,
        "descartadas": descartadas,
        "hechos": hechos,
        "explicacion": explicar(estado, canales, canal, determinante, traza, descartadas),
    }


def explicar(estado, canales, canal, determinante, traza, descartadas):
    """Explicación en lenguaje natural, construida a partir de la traza.

    Es el módulo de explicación de un sistema experto: no solo dice qué decidió,
    sino por qué, citando la regla y su fundamento.
    """
    partes = []
    if estado == "BLOQUEADA":
        partes.append("No se contacta. Determina {} ({}): {}".format(
            determinante["id"], determinante["nombre"], determinante["fundamento"]))
        otras = [r for _, r in traza if r is not determinante]
        if otras:
            partes.append("También aplican: {}.".format(
                ", ".join("{} ({})".format(r["id"], r["nombre"]) for r in otras)))
        return " ".join(partes)[:1000]

    if estado == "EN_ESPERA":
        return "En espera. Determina {} ({}): {}".format(
            determinante["id"], determinante["nombre"], determinante["fundamento"])[:1000]

    quitadas = [r for fase, r in traza if fase == "canales"]
    if quitadas:
        partes.append("Restricciones: {}.".format(
            ", ".join("{} ({})".format(r["id"], r["nombre"]) for r in quitadas)))
    partes.append("Canales permitidos: {}.".format(", ".join(canales)))

    if estado == "RECORDATORIO":
        partes.append("Recordatorio por {}. Determina {} ({}): {}".format(
            canal, determinante["id"], determinante["nombre"], determinante["fundamento"]))
        return " ".join(partes)[:1000]

    ideal = determinante["efecto"]["canal"]
    if ideal == canal:
        partes.append("Canal recomendado: {} por {} ({}).".format(
            canal, determinante["id"], determinante["nombre"]))
    else:
        partes.append("{} ({}) recomienda {}, que no está permitido; se usa {}, el más "
                      "económico disponible.".format(determinante["id"],
                                                     determinante["nombre"], ideal, canal))
    if descartadas:
        partes.append("Otras estrategias aplicables, de menor prioridad: {}.".format(
            ", ".join(r["id"] for r in descartadas)))
    return " ".join(partes)[:1000]


# ---------------------------------------------------------------------------
# 5. EJECUCIÓN SOBRE UNA CARTERA
# ---------------------------------------------------------------------------

def evaluar_cartera(cartera, fecha_objetivo):
    """Evalúa todas las cuentas de una cartera. Retorna un DataFrame."""
    dia = diagnostico_fecha(fecha_objetivo)
    filas = []
    for fila in cartera.to_dict(orient="records"):
        r = evaluar_cuenta(construir_hechos(fila, fecha_objetivo, dia))
        filas.append({
            "credito_id": fila["credito_id"],
            "estado": r["estado"],
            "canal_recomendado": r["canal_recomendado"],
            "canales_permitidos": ",".join(r["canales_permitidos"]),
            "regla_determinante": r["regla_determinante"],
            "reglas": ",".join(r["reglas"])[:200],
            "explicacion": r["explicacion"],
        })
    return pd.DataFrame(filas)


def resumir(resultados, carga_id, fecha_objetivo):
    """Cifras de la ejecución: estados, canales, reglas y costo estimado."""
    dia = diagnostico_fecha(fecha_objetivo)
    estados = resultados["estado"].value_counts()
    canales = resultados["canal_recomendado"].dropna().value_counts()
    reglas = Counter(r for lista in resultados["reglas"] for r in lista.split(",") if r)
    return {
        "carga_id": carga_id,
        "fecha_objetivo": fecha_objetivo,
        "dia_habil": dia["dia_habil"],
        "motivo_dia": dia["motivo"],
        "horario": dia["horario"],
        "total": len(resultados),
        **{e: int(estados.get(e, 0)) for e in ESTADOS},
        "canales": {c: int(n) for c, n in canales.items()},
        "reglas": dict(reglas.most_common()),
        "determinantes": resultados["regla_determinante"].value_counts().to_dict(),
        "costo_estimado": float(sum(config.CANALES[c]["costo"] * n for c, n in canales.items())),
    }


def ejecutar(carga_id=None, fecha_objetivo=None, usuario="sistema", guardar=True):
    """Ejecuta el motor sobre una carga y, si se pide, guarda el resultado.

    Sin carga, usa la más reciente. Sin fecha, usa el día de hoy en Colombia.
    Retorna (resumen, resultados).
    """
    from datos import base_datos as bd

    errores = bc.validar()
    if errores:
        raise ValueError("La base de conocimiento tiene errores: " + "; ".join(errores))

    fecha_objetivo = fecha_objetivo or config.hoy()
    # Esquema al día antes de leer: una base de una versión anterior no tendría
    # las columnas que el motor necesita.
    bd.crear_esquema()
    cartera = bd.leer_cartera(carga_id)
    if cartera.empty:
        raise LookupError("No hay cartera cargada para evaluar.")
    carga_id = int(cartera["carga_id"].iloc[0])

    resultados = evaluar_cartera(cartera, fecha_objetivo)
    resumen = resumir(resultados, carga_id, fecha_objetivo)

    if guardar:
        resumen["ejecucion_id"] = bd.guardar_ejecucion(resumen, resultados, usuario)
        bd.registrar_evento(usuario, "EJECUTAR_MOTOR", "Ejecución {} sobre la carga {} para el {}: "
                            "{} contactables de {}".format(resumen["ejecucion_id"], carga_id,
                                                           fecha_objetivo, resumen["CONTACTABLE"],
                                                           resumen["total"]))
    return resumen, resultados


# ---------------------------------------------------------------------------
# 6. LÍNEA DE COMANDOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motor de elegibilidad de contacto.")
    parser.add_argument("--carga", type=int, default=None)
    parser.add_argument("--fecha", type=date.fromisoformat, default=None)
    parser.add_argument("--no-guardar", action="store_true")
    parser.add_argument("--validar", action="store_true",
                        help="solo verifica la consistencia de la base de conocimiento")
    args = parser.parse_args()

    errores = bc.validar()
    print("Base de conocimiento: {} reglas, {}".format(
        len(bc.REGLAS), "sin errores" if not errores else "{} errores".format(len(errores))))
    for error in errores:
        print("  - " + error)
    if args.validar or errores:
        raise SystemExit(1 if errores else 0)

    resumen, resultados = ejecutar(args.carga, args.fecha, usuario="terminal",
                                   guardar=not args.no_guardar)
    print("Carga {} | {} ({}) | horario: {}".format(
        resumen["carga_id"], resumen["fecha_objetivo"], resumen["motivo_dia"],
        resumen["horario"] or "sin contacto"))
    for estado in ESTADOS:
        print("  {:<13}: {:>6,}".format(estado, resumen[estado]))
    print("  Canales      : {}".format(resumen["canales"]))
    print("  Determinantes: {}".format(resumen["determinantes"]))
    print("  Costo estimado del día: ${:,.0f}".format(resumen["costo_estimado"]))
    if "ejecucion_id" in resumen:
        print("  Guardada como ejecución {}".format(resumen["ejecucion_id"]))
