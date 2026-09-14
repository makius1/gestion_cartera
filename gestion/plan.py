# -*- coding: utf-8 -*-
"""
Plan de trabajo diario.

El supervisor reparte las cuentas del día entre los gestores a partir de la
última priorización. El reparto sigue tres reglas:

  1. Solo entran cuentas que el motor permite contactar en la fecha del plan.
     Se vuelven a evaluar con la fecha del plan, porque la priorización pudo
     hacerse para otro día y desde entonces cambió la historia de la cuenta.
  2. Entran las mejores según la priorización, hasta completar el cupo de
     todos los gestores (gestores × gestiones por gestor al día).
  3. Se reparten en serpentina: la primera cuenta al gestor 1, la segunda al 2
     y así hasta el último; en la siguiente vuelta el orden se invierte. Con un
     reparto en orden simple el gestor 1 siempre recibiría la mejor cuenta de
     cada vuelta; en serpentina todos reciben una mezcla equivalente de cuentas
     de alta y baja prioridad, y sus resultados se pueden comparar con justicia.

El avance del plan no se guarda: se calcula cruzando las asignaciones con las
gestiones registradas en la fecha del plan.
"""

import pandas as pd
from sqlalchemy import select

import config
from datos import base_datos as bd
from motor import elegibilidad as motor


def gestores_disponibles():
    """Usuarios activos con rol de gestor; si no hay, todos los activos."""
    with bd.obtener_motor().connect() as conexion:
        filas = conexion.execute(select(bd.usuarios.c.usuario, bd.usuarios.c.rol).where(
            bd.usuarios.c.activo.is_(True)).order_by(bd.usuarios.c.usuario)).fetchall()
    gestores = [f.usuario for f in filas if f.rol == "GESTOR"]
    return gestores or [f.usuario for f in filas]


def repartir_en_serpentina(cuentas, gestores):
    """Asigna cada cuenta (ya ordenada por prioridad) a un gestor en serpentina."""
    n = len(gestores)
    asignados, ordenes = [], []
    contador = {g: 0 for g in gestores}
    for i in range(len(cuentas)):
        vuelta, lugar = divmod(i, n)
        gestor = gestores[lugar if vuelta % 2 == 0 else n - 1 - lugar]
        contador[gestor] += 1
        asignados.append(gestor)
        ordenes.append(contador[gestor])
    return asignados, ordenes


def crear_plan(carga_id, priorizacion_id, fecha, gestores, cupo, usuario):
    """Crea el plan del día. Retorna (plan_id, resumen)."""
    if not gestores:
        raise ValueError("Seleccione al menos un gestor.")
    dia = motor.diagnostico_fecha(fecha)
    if not dia["dia_habil"]:
        raise ValueError("El {} no es hábil ({}): la Ley 2300 no permite gestiones salientes."
                         .format(fecha.isoformat(), dia["motivo"]))

    prioridades = bd.leer_prioridades(priorizacion_id)
    candidatas = prioridades[prioridades["candidata"]].sort_values("posicion")
    if candidatas.empty:
        raise LookupError("La priorización no tiene cuentas candidatas.")

    # Regla 1: nueva evaluación con la fecha del plan.
    cartera = bd.leer_cartera(carga_id)
    cartera = cartera[cartera["credito_id"].isin(candidatas["credito_id"])]
    evaluacion = motor.evaluar_cartera(cartera, fecha).set_index("credito_id")["estado"]
    permitidas = candidatas[candidatas["credito_id"].map(evaluacion) == "CONTACTABLE"]
    descartadas = len(candidatas) - len(permitidas)

    # Regla 2 y 3: las mejores, hasta el cupo, en serpentina.
    seleccion = permitidas.head(len(gestores) * cupo).reset_index(drop=True)
    if seleccion.empty:
        raise LookupError("Ninguna cuenta de la priorización se puede contactar el {}.".format(fecha))
    asignados, ordenes = repartir_en_serpentina(seleccion["credito_id"].tolist(), list(gestores))
    asignaciones = pd.DataFrame({
        "credito_id": seleccion["credito_id"], "gestor": asignados, "orden": ordenes,
        "posicion": seleccion["posicion"].astype("Int64"), "prioridad": seleccion["prioridad"]})

    plan_id = bd.guardar_plan({
        "fecha": fecha, "carga_id": int(carga_id), "priorizacion_id": int(priorizacion_id),
        "gestores": len(gestores), "cupo": int(cupo), "cuentas": len(asignaciones),
        "creado": config.ahora(), "creado_por": usuario[:40]}, asignaciones)
    bd.registrar_evento(usuario, "CREAR_PLAN", "plan {} para el {}: {} cuentas entre {} gestores "
                        "({} descartadas por el motor)".format(plan_id, fecha, len(asignaciones),
                                                               len(gestores), descartadas))
    return plan_id, {"cuentas": len(asignaciones), "descartadas": descartadas, "gestores": len(gestores)}


def avance(plan):
    """Asignaciones del plan con su estado de gestión en la fecha del plan.

    `plan` es la fila del plan (con fecha, carga_id e id). Una cuenta cuenta
    como gestionada si tiene al menos una gestión ese día, de quien sea: si otro
    gestor la atendió, igual quedó trabajada.
    """
    asignaciones = bd.leer_asignaciones(int(plan["id"]))
    fecha = pd.Timestamp(plan["fecha"]).date()
    gestiones = bd.leer_gestiones(int(plan["carga_id"]))
    gestiones = gestiones[pd.to_datetime(gestiones["fecha"]).dt.date == fecha]
    ultima = gestiones.sort_values("fecha").groupby("credito_id").last()
    asignaciones["gestionada"] = asignaciones["credito_id"].isin(ultima.index)
    for columna in ("resultado", "codigo", "valor_acordado", "usuario"):
        asignaciones[columna] = asignaciones["credito_id"].map(ultima[columna]) if not ultima.empty else None
    asignaciones["contacto"] = asignaciones["resultado"].isin(config.RESULTADOS_CON_CONTACTO)
    asignaciones["acuerdo"] = asignaciones["codigo"].isin(config.CODIGOS_CON_COMPROMISO)
    return asignaciones


def resumen_por_gestor(asignaciones):
    tabla = asignaciones.groupby("gestor").agg(
        asignadas=("credito_id", "size"), gestionadas=("gestionada", "sum"),
        contactos=("contacto", "sum"), acuerdos=("acuerdo", "sum"),
        valor_acordado=("valor_acordado", lambda v: pd.to_numeric(v, errors="coerce").sum()))
    tabla["pendientes"] = tabla["asignadas"] - tabla["gestionadas"]
    tabla["cumplimiento"] = tabla["gestionadas"] / tabla["asignadas"]
    return tabla.reset_index()


def plan_del_dia(carga_id, fecha):
    """El plan más reciente de la carga para esa fecha, o None."""
    planes = bd.listar_planes(200)
    planes = planes[(planes["carga_id"] == carga_id)
                    & (pd.to_datetime(planes["fecha"]).dt.date == fecha)]
    return None if planes.empty else planes.iloc[0]


def siguiente_del_plan(carga_id, usuario, fecha=None):
    """Siguiente cuenta pendiente del gestor en el plan del día.

    Retorna (credito_id, orden, total) o (None, None, None) si el gestor no
    tiene plan ese día o ya lo completó.
    """
    fecha = fecha or config.hoy()
    plan = plan_del_dia(carga_id, fecha)
    if plan is None:
        return None, None, None
    propias = avance(plan)
    propias = propias[propias["gestor"] == usuario]
    pendientes = propias[~propias["gestionada"]].sort_values("orden")
    if pendientes.empty:
        return None, None, len(propias) or None
    return pendientes.iloc[0]["credito_id"], int(pendientes.iloc[0]["orden"]), len(propias)
