# -*- coding: utf-8 -*-
"""
Registro de gestiones de cobranza.

Es el apartado de trabajo del gestor: toma una cuenta (la siguiente de la cola
priorizada o una que busca), ve su estado legal del día, registra el resultado
del contacto y el sistema actualiza la cartera. Con eso se cierra el ciclo:

  * El motor de elegibilidad lee la nueva fecha de contacto y aplica la regla
    de frecuencia de la Ley 2300; si hubo acuerdo, aplica las de compromiso.
  * La priorización lee el nuevo resultado y ajusta la contactabilidad.
  * La historia de gestiones es la materia prima del modelo de propensión.

Antes de guardar, cada gestión pasa por reglas de validación. Unas protegen la
ley (no registrar un contacto que no se podía hacer) y otras la calidad del
dato (no registrar un acuerdo sin haber hablado con el titular). Se aplican en
el servidor, no solo en la pantalla: nadie puede saltárselas.
"""

from datetime import timedelta

import pandas as pd

import config
from datos import base_datos as bd
from motor import elegibilidad as motor

CANALES = ["LLAMADA", "WHATSAPP", "SMS", "EMAIL"]
SENTIDOS = {"SALIENTE": "Saliente: la casa de cobranza contacta",
            "ENTRANTE": "Entrante: el titular se comunica"}


# ---------------------------------------------------------------------------
# 1. ESTADO DE LA CUENTA HOY
# ---------------------------------------------------------------------------

def en_horario(momento):
    """True si el momento está dentro del horario de contacto de la Ley 2300.

    Si el horario ya da falso (festivo, domingo o fuera de la franja), no hace
    falta comprobar nada más. Si da verdadero, todavía depende de que el
    reloj de este servidor sea confiable (issue #51): un reloj atrasado podría
    hacer parecer "en horario" un momento que en la realidad ya no lo está.
    """
    franja = config.HORARIO_HABIL.get(momento.weekday())
    dia = motor.diagnostico_fecha(momento.date())
    if not (bool(franja) and dia["dia_habil"] and franja[0] <= momento.hour < franja[1]):
        return False
    return bd.reloj_confiable()


def estado_hoy(fila, momento=None):
    """Decisión del motor para esta cuenta en este momento."""
    momento = momento or config.ahora()
    decision = motor.evaluar_cuenta(motor.construir_hechos(fila, momento.date()))
    decision["en_horario"] = en_horario(momento)
    return decision


# ---------------------------------------------------------------------------
# 2. REGLAS DE VALIDACIÓN
# ---------------------------------------------------------------------------
# Cada regla retorna un mensaje si se incumple, o None si se cumple. Las de
# nivel "error" impiden guardar; las de nivel "aviso" se muestran y se guardan.

def _g1(g, fila, d, hoy):
    if g["sentido"] == "SALIENTE" and not d["en_horario"]:
        return ("Un contacto saliente solo puede hacerse en día hábil y dentro del horario "
                "permitido. Si el titular se comunicó, registre la gestión como entrante.")


def _g2(g, fila, d, hoy):
    if g["sentido"] == "SALIENTE" and d["estado"] == "BLOQUEADA":
        return "El motor bloquea hoy el contacto con esta cuenta: {}".format(d["explicacion"])


def _g3(g, fila, d, hoy):
    if (g["sentido"] == "SALIENTE" and d["estado"] in ("CONTACTABLE", "RECORDATORIO")
            and g["canal"] not in d["canales_permitidos"]):
        return "El canal {} no está permitido para esta cuenta. Permitidos: {}.".format(
            g["canal"], ", ".join(d["canales_permitidos"]) or "ninguno")


def _g4(g, fila, d, hoy):
    if g["sentido"] == "SALIENTE" and d["estado"] == "EN_ESPERA":
        return ("La cuenta tiene un compromiso vigente y la política es no contactarla antes "
                "de la fecha pactada. Se guardará, pero conviene justificarlo en la observación.")


def _g5(g, fila, d, hoy):
    sin_contacto = g["resultado"] not in config.RESULTADOS_CON_CONTACTO
    if sin_contacto and g["resultado"] != "FALLECIDO" and g["codigo"] != "POSIBLE LOCALIZACION":
        return ("Sin contacto con el titular el código solo puede ser POSIBLE LOCALIZACION: "
                "no se puede registrar una negociación con quien no se habló.")


def _g6(g, fila, d, hoy):
    acuerdo = g["codigo"] in config.CODIGOS_CON_COMPROMISO
    if acuerdo != (g["resultado"] == "ACUERDO"):
        return ("El resultado 'acuerdo de pago' y un código de compromiso ({}) van juntos: "
                "uno sin el otro deja la cuenta en un estado contradictorio."
                .format(", ".join(sorted(config.CODIGOS_CON_COMPROMISO))))


def _g7(g, fila, d, hoy):
    if (g["resultado"] == "FALLECIDO") != (g["codigo"] == "FALLECIDO"):
        return "El resultado y el código de fallecimiento van juntos."


def _g8(g, fila, d, hoy):
    if g["codigo"] not in config.CODIGOS_CON_COMPROMISO:
        return None
    if not g.get("valor_acordado") or not g.get("fecha_compromiso"):
        return "Un acuerdo de pago requiere el valor acordado y la fecha del compromiso."
    piso = float(fila.get("cobranza_min") or 0)
    techo = max(float(fila.get("saldo") or 0), float(fila.get("cobranza_max") or 0))
    if float(g["valor_acordado"]) < piso:
        return ("El valor acordado ({}) está por debajo del mínimo autorizado para esta cuenta "
                "({}).".format(_pesos(g["valor_acordado"]), _pesos(piso)))
    if float(g["valor_acordado"]) > techo:
        return "El valor acordado supera el máximo cobrable de la cuenta ({}).".format(_pesos(techo))
    if not hoy <= g["fecha_compromiso"] <= hoy + timedelta(days=config.DIAS_MAXIMOS_COMPROMISO):
        return "La fecha del compromiso debe estar entre hoy y los próximos {} días.".format(
            config.DIAS_MAXIMOS_COMPROMISO)


def _g9(g, fila, d, hoy):
    proxima = g.get("fecha_proxima_gestion")
    minima = hoy + timedelta(days=config.DIAS_MINIMOS_ENTRE_CONTACTOS)
    if proxima and proxima < minima and g["codigo"] not in config.CODIGOS_CON_COMPROMISO:
        return ("La próxima gestión queda antes de {} días: la regla de frecuencia bloqueará ese "
                "contacto. La primera fecha permitida es el {}.".format(
                    config.DIAS_MINIMOS_ENTRE_CONTACTOS, minima.isoformat()))


def _g10(g, fila, d, hoy):
    if len((g.get("observacion") or "").strip()) < config.LONGITUD_MINIMA_OBSERVACION:
        return "La observación es obligatoria (al menos {} caracteres): es el soporte de la gestión.".format(
            config.LONGITUD_MINIMA_OBSERVACION)


REGLAS_GESTION = [
    {"id": "G1", "nivel": "error", "prueba": _g1,
     "fundamento": "Ley 2300 de 2023: días y horario del contacto de cobranza."},
    {"id": "G2", "nivel": "error", "prueba": _g2,
     "fundamento": "Ley 2300 de 2023 y reglas del motor de elegibilidad."},
    {"id": "G3", "nivel": "error", "prueba": _g3,
     "fundamento": "Canales permitidos por el motor (datos disponibles y número errado)."},
    {"id": "G4", "nivel": "aviso", "prueba": _g4,
     "fundamento": "Política del negocio: no presionar durante un compromiso vigente."},
    {"id": "G5", "nivel": "error", "prueba": _g5, "fundamento": "Calidad del dato."},
    {"id": "G6", "nivel": "error", "prueba": _g6, "fundamento": "Calidad del dato."},
    {"id": "G7", "nivel": "error", "prueba": _g7, "fundamento": "Calidad del dato."},
    {"id": "G8", "nivel": "error", "prueba": _g8,
     "fundamento": "Política del negocio: banda de negociación y plazo de los compromisos."},
    {"id": "G9", "nivel": "aviso", "prueba": _g9,
     "fundamento": "Ley 2300 de 2023: frecuencia de contacto."},
    {"id": "G10", "nivel": "error", "prueba": _g10, "fundamento": "Soporte documental de la gestión."},
]


def _pesos(valor):
    return "$ {:,.0f}".format(float(valor)).replace(",", ".")


def validar(gestion, fila, decision, hoy=None):
    """Aplica las reglas. Retorna (errores, avisos) como listas de (id, mensaje)."""
    hoy = hoy or config.hoy()
    errores, avisos = [], []
    for regla in REGLAS_GESTION:
        mensaje = regla["prueba"](gestion, fila, decision, hoy)
        if mensaje:
            (errores if regla["nivel"] == "error" else avisos).append((regla["id"], mensaje))
    return errores, avisos


# ---------------------------------------------------------------------------
# 3. REGISTRO
# ---------------------------------------------------------------------------

def cambios_en_cartera(gestion, usuario, hoy):
    """Nuevo estado de la cuenta después de la gestión.

    Se traduce al mismo vocabulario que el cargador deriva de la asignación,
    para que el motor y la priorización lo lean sin distinción.
    """
    codigo = gestion["codigo"]
    compromiso = codigo in config.CODIGOS_CON_COMPROMISO
    if codigo in config.CODIGOS_CONTADO:
        tipo = "CONTADO"
    elif codigo in config.CODIGOS_DIFERIDO:
        tipo = "DIFERIDO"
    else:
        tipo = "SIN_ACUERDO"
    return {
        "resultado_gestion": gestion["resultado"],
        "codigo": codigo,
        "fecha_ultima_gestion": hoy,
        "gestionada": True,
        "gestor_ultimo": usuario[:40],
        "tiene_compromiso": compromiso,
        "tipo_acuerdo": tipo,
        "fecha_compromiso": gestion["fecha_compromiso"] if compromiso else None,
        "proyeccion": float(gestion["valor_acordado"]) if compromiso else 0,
        "gestionable": codigo not in config.CODIGOS_EXCLUYENTES,
    }


def registrar(carga_id, credito_id, datos, usuario, momento=None):
    """Valida y guarda una gestión. Retorna (gestion_id, avisos).

    La validación se repite aquí aunque la pantalla ya la haya hecho: la regla
    vale por lo que hace el servidor, no por lo que muestra el navegador.
    """
    momento = momento or config.ahora()
    hoy = momento.date()
    cartera = bd.leer_cartera(carga_id)
    fila = cartera[cartera["credito_id"] == credito_id]
    if fila.empty:
        raise LookupError("La cuenta {} no existe en la carga {}.".format(credito_id, carga_id))
    fila = fila.iloc[0].to_dict()

    decision = estado_hoy(fila, momento)
    errores, avisos = validar(datos, fila, decision, hoy)
    if errores:
        raise ValueError(errores)

    gestion = {
        "fecha": momento, "usuario": usuario[:40], "carga_id": int(carga_id),
        "credito_id": credito_id, "canal": datos["canal"], "sentido": datos["sentido"],
        "resultado": datos["resultado"], "codigo": datos["codigo"],
        "motivo_no_pago": datos.get("motivo_no_pago"),
        "valor_acordado": datos.get("valor_acordado") if datos["codigo"] in config.CODIGOS_CON_COMPROMISO else None,
        "fecha_compromiso": datos.get("fecha_compromiso") if datos["codigo"] in config.CODIGOS_CON_COMPROMISO else None,
        "fecha_proxima_gestion": datos.get("fecha_proxima_gestion"),
        "observacion": datos["observacion"].strip()[:500],
        "estado_motor": decision["estado"],
    }
    gestion_id = bd.registrar_gestion(gestion, cambios_en_cartera(datos, usuario, hoy))
    bd.registrar_evento(usuario, "REGISTRAR_GESTION", "gestión {} · carga {} · {} · {} · {}".format(
        gestion_id, carga_id, credito_id, datos["resultado"], datos["codigo"]))
    return gestion_id, avisos


def siguiente_de_la_cola(carga_id, usuario, hoy=None):
    """Siguiente cuenta de la última priorización de la carga que aún no se
    gestionó hoy, reservada para `usuario`. Retorna (credito_id, posicion) o
    (None, None).

    Dos gestores sin plan de trabajo pueden pedir la cola al mismo tiempo y
    ver la misma primera cuenta: por eso no basta con leer y devolver la
    primera pendiente, hay que reservarla. Si la reserva falla (otro gestor
    la tiene vigente), se prueba con la siguiente, hasta un tope de intentos
    para no recorrer la cola completa si está casi toda reservada.
    """
    hoy = hoy or config.hoy()
    priorizaciones = bd.listar_priorizaciones(200)
    priorizaciones = priorizaciones[priorizaciones["carga_id"] == carga_id]
    if priorizaciones.empty:
        return None, None
    cola = bd.leer_prioridades(int(priorizaciones.iloc[0]["id"]))
    cola = cola[cola["candidata"]].sort_values("posicion")
    gestiones = bd.leer_gestiones(carga_id)
    hechas_hoy = set(gestiones.loc[pd.to_datetime(gestiones["fecha"]).dt.date == hoy, "credito_id"])
    pendientes = cola[~cola["credito_id"].isin(hechas_hoy)]
    for _, fila in pendientes.head(config.INTENTOS_MAXIMOS_RESERVA).iterrows():
        if bd.reservar_cuenta(carga_id, fila["credito_id"], usuario, config.MINUTOS_RESERVA_CUENTA):
            return fila["credito_id"], int(fila["posicion"])
    return None, None
