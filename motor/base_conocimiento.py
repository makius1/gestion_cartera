# -*- coding: utf-8 -*-
"""
Base de conocimiento del motor de elegibilidad de contacto.

Contiene las reglas que deciden si una cuenta puede contactarse en una fecha
dada, por qué canales y cuál conviene usar. Las reglas son DATOS, no código: el
motor (elegibilidad.py) las recorre sin saber nada de cobranza ni de la Ley
2300. Es la separación central de un sistema experto, la misma de la sesión 2:
si cambia la normativa o la estrategia comercial, se modifica este archivo y el
motor no se toca.

Cada regla declara:
  id           Identificador corto que aparece en la traza de cada decisión.
  nombre       Título legible.
  fase         Momento del razonamiento en que se evalúa (ver FASES).
  fundamento   Por qué existe: una norma legal o una política del negocio. Es lo
               que se muestra cuando alguien pregunta por qué se bloqueó una
               cuenta.
  descripcion  La regla en lenguaje SI ... ENTONCES.
  condicion    Premisas sobre los hechos de la cuenta. Todas deben cumplirse
               (conjunción). Un valor directo se compara por igualdad; una tupla
               (operador, valor) aplica el operador.
  efecto       Qué produce la regla cuando se dispara.
  prioridad    Solo en la fase de estrategia: si varias reglas aplican, gana la
               de mayor prioridad. Es la resolución de conflictos de la sesión 2.

Los parámetros legales (días entre contactos, horarios) viven en config.py y
deben validarse con el área jurídica antes de operar.
"""

import config

# Orden del razonamiento. Cada fase usa los hechos que dejaron las anteriores.
# Dentro de la fase de bloqueos el orden también importa: la primera regla que
# se dispara es la que se informa como determinante. Van primero las causas más
# generales (el día) y las definitivas (la cuenta cerrada), y al final las que
# dependen del historial de la cuenta.
FASES = [
    ("bloqueos", "Restricciones legales y de negocio que impiden todo contacto"),
    ("compromisos", "Cuentas con un acuerdo de pago vigente"),
    ("canales", "Canales que no pueden usarse con esta cuenta"),
    ("cierre", "Cuentas que quedaron sin ningún canal utilizable"),
    ("estrategia", "Canal recomendado según la historia de la cuenta"),
]

# Canales del sistema, de menor a mayor costo. Cuando el canal recomendado no
# está permitido, se usa el más barato de los que queden.
CANALES_POR_COSTO = ["EMAIL", "SMS", "WHATSAPP", "LLAMADA"]

RESULTADOS_NO_LOCALIZADO = ["BUZON", "NO_CONTESTA", "APAGADO", "MENSAJE_DEJADO"]
RESULTADOS_RECHAZO = ["CUELGA", "REINTENTAR"]

REGLAS = [
    # ------------------------------------------------------------------ bloqueos
    {
        "id": "L1",
        "nombre": "Día no hábil",
        "fase": "bloqueos",
        "fundamento": "Ley 2300 de 2023: el contacto de cobranza está prohibido "
                      "los domingos y festivos.",
        "descripcion": "SI la fecha es domingo o festivo ENTONCES no se contacta",
        "condicion": {"dia_habil": False},
        "efecto": {"estado": "BLOQUEADA"},
    },
    {
        "id": "N1",
        "nombre": "Gestión cerrada o en disputa",
        "fase": "bloqueos",
        "fundamento": "Política del negocio: una obligación cancelada ya no se "
                      "cobra, un titular fallecido no se contacta, y presionar "
                      "durante una reclamación formal puede considerarse cobro "
                      "indebido.",
        "descripcion": "SI el código es {} ENTONCES no se contacta".format(
            " o ".join(sorted(config.CODIGOS_EXCLUYENTES))),
        "condicion": {"codigo": ("en", sorted(config.CODIGOS_EXCLUYENTES))},
        "efecto": {"estado": "BLOQUEADA"},
    },
    {
        "id": "L3",
        "nombre": "Información de contacto incompleta",
        "fase": "bloqueos",
        # Regla de precaución. Sin estos datos las reglas L2 y C1-C3 no pueden
        # evaluarse, y un hecho desconocido nunca dispara una regla: la cuenta
        # quedaría contactable sin haber verificado la ley. Esta regla lo impide.
        "fundamento": "Principio de precaución: sin la fecha del último contacto o "
                      "sin saber qué canales tiene la cuenta, no se puede demostrar "
                      "que el contacto cumple la Ley 2300. Se debe recargar la cuenta.",
        "descripcion": "SI faltan la fecha del último contacto o los canales de la "
                       "cuenta ENTONCES no se contacta",
        "condicion": {"datos_completos": False},
        "efecto": {"estado": "BLOQUEADA"},
    },
    {
        "id": "L2",
        "nombre": "Frecuencia de contacto",
        "fase": "bloqueos",
        # La ley limita cuántas veces se puede contactar a un deudor por día y
        # por semana. El sistema aplica una lectura conservadora —un contacto
        # real por periodo— y el periodo se ajusta en config.py.
        "fundamento": "Ley 2300 de 2023: limita la frecuencia del contacto de "
                      "cobranza. Política conservadora: un contacto real por "
                      "periodo de {} días.".format(config.DIAS_MINIMOS_ENTRE_CONTACTOS),
        "descripcion": "SI hubo un contacto real hace menos de {} días ENTONCES no se "
                       "contacta".format(config.DIAS_MINIMOS_ENTRE_CONTACTOS),
        "condicion": {"dias_desde_contacto": ("<", config.DIAS_MINIMOS_ENTRE_CONTACTOS)},
        "efecto": {"estado": "BLOQUEADA"},
    },

    # --------------------------------------------------------------- compromisos
    {
        "id": "N3",
        "nombre": "Recordatorio de compromiso",
        "fase": "compromisos",
        "fundamento": "Estrategia: un compromiso incumplido es recaudo que ya "
                      "estaba contado. Un recordatorio corto antes de la fecha "
                      "cuesta casi nada y lo protege.",
        "descripcion": "SI hay compromiso de pago en los próximos {} días ENTONCES "
                       "enviar recordatorio".format(config.DIAS_AVISO_COMPROMISO),
        "condicion": {"dias_para_compromiso": ("entre", (0, config.DIAS_AVISO_COMPROMISO))},
        "efecto": {"estado": "RECORDATORIO", "canales_preferidos": ["WHATSAPP", "SMS"]},
    },
    {
        "id": "N4",
        "nombre": "Compromiso vigente",
        "fase": "compromisos",
        "fundamento": "Política del negocio: mientras un acuerdo está vigente no se "
                      "presiona al titular; se espera la fecha pactada.",
        "descripcion": "SI hay compromiso de pago dentro de más de {} días ENTONCES "
                       "esperar".format(config.DIAS_AVISO_COMPROMISO),
        "condicion": {"dias_para_compromiso": (">", config.DIAS_AVISO_COMPROMISO)},
        "efecto": {"estado": "EN_ESPERA"},
    },

    # ------------------------------------------------------------------ canales
    {
        "id": "C1",
        "nombre": "Sin celular",
        "fase": "canales",
        "fundamento": "Restricción técnica: SMS y WhatsApp requieren un celular.",
        "descripcion": "SI la cuenta no tiene celular ENTONCES no se usa SMS ni WhatsApp",
        "condicion": {"tiene_celular": False},
        "efecto": {"quitar_canales": ["SMS", "WHATSAPP"]},
    },
    {
        "id": "C2",
        "nombre": "Sin teléfono",
        "fase": "canales",
        "fundamento": "Restricción técnica: la llamada requiere algún teléfono.",
        "descripcion": "SI la cuenta no tiene celular ni fijo ENTONCES no se llama",
        "condicion": {"tiene_celular": False, "tiene_fijo": False},
        "efecto": {"quitar_canales": ["LLAMADA"]},
    },
    {
        "id": "C3",
        "nombre": "Sin correo",
        "fase": "canales",
        "fundamento": "Restricción técnica: el correo requiere una dirección válida.",
        "descripcion": "SI la cuenta no tiene correo ENTONCES no se usa EMAIL",
        "condicion": {"tiene_email": False},
        "efecto": {"quitar_canales": ["EMAIL"]},
    },
    {
        "id": "C4",
        "nombre": "Número errado",
        "fase": "canales",
        "fundamento": "Ley 1581 de 2012 (protección de datos personales): "
                      "contactar a un tercero que no es el titular expone la deuda "
                      "a quien no debe conocerla.",
        "descripcion": "SI el último contacto indicó número equivocado ENTONCES no se "
                       "usa ningún canal telefónico",
        "condicion": {"resultado_gestion": "NUMERO_ERRADO"},
        "efecto": {"quitar_canales": ["SMS", "WHATSAPP", "LLAMADA"]},
    },

    # ------------------------------------------------------------------- cierre
    {
        "id": "N2",
        "nombre": "Sin canal disponible",
        "fase": "cierre",
        "fundamento": "Restricción técnica: después de aplicar las restricciones no "
                      "queda ningún medio por el cual contactar la cuenta.",
        "descripcion": "SI no queda ningún canal permitido ENTONCES no se contacta",
        "condicion": {"canales_permitidos": 0},
        "efecto": {"estado": "BLOQUEADA"},
    },

    # --------------------------------------------------------------- estrategia
    {
        "id": "E1",
        "nombre": "Promesa incumplida",
        "fase": "estrategia",
        "prioridad": 100,
        "fundamento": "Estrategia: la fecha pactada pasó sin pago. Una llamada "
                      "permite reprogramar mientras el compromiso está reciente.",
        "descripcion": "SI la fecha del compromiso ya pasó ENTONCES llamar",
        "condicion": {"dias_para_compromiso": ("<", 0)},
        "efecto": {"canal": "LLAMADA"},
    },
    {
        "id": "E2",
        "nombre": "Contacto sin acuerdo",
        "fase": "estrategia",
        "prioridad": 90,
        "fundamento": "Estrategia: el titular ya fue localizado y no cerró. La "
                      "palanca no es el contacto sino la oferta, y se negocia mejor "
                      "por teléfono.",
        "descripcion": "SI el código es CONTACTO SIN ACUERDO ENTONCES llamar con oferta",
        "condicion": {"codigo": "CONTACTO SIN ACUERDO"},
        "efecto": {"canal": "LLAMADA"},
    },
    {
        "id": "E3",
        "nombre": "Cuenta nunca gestionada",
        "fase": "estrategia",
        "prioridad": 80,
        "fundamento": "Estrategia: una cuenta sin gestión real se despierta primero "
                      "con el canal más barato, que además filtra a quienes responden.",
        "descripcion": "SI la cuenta nunca tuvo gestión real ENTONCES enviar correo",
        "condicion": {"resultado_gestion": "SIN_GESTION_REAL"},
        "efecto": {"canal": "EMAIL"},
    },
    {
        "id": "E4",
        "nombre": "No localizado por teléfono",
        "fase": "estrategia",
        "prioridad": 70,
        "fundamento": "Estrategia: si el titular no contesta, un canal asíncrono no "
                      "exige que esté disponible en ese momento.",
        "descripcion": "SI el último intento cayó en buzón, no contestó o estaba "
                       "apagado ENTONCES escribir por WhatsApp",
        "condicion": {"resultado_gestion": ("en", RESULTADOS_NO_LOCALIZADO)},
        "efecto": {"canal": "WHATSAPP"},
    },
    {
        "id": "E5",
        "nombre": "Rechazo del contacto",
        "fase": "estrategia",
        "prioridad": 60,
        "fundamento": "Estrategia: si el titular colgó o pidió otro momento, un "
                      "mensaje corto es menos invasivo que insistir con llamadas.",
        "descripcion": "SI el titular colgó o pidió que llamaran otro día ENTONCES "
                       "enviar SMS",
        "condicion": {"resultado_gestion": ("en", RESULTADOS_RECHAZO)},
        "efecto": {"canal": "SMS"},
    },
    {
        "id": "E9",
        "nombre": "Estrategia por defecto",
        "fase": "estrategia",
        "prioridad": 0,
        "fundamento": "Estrategia: cuando ninguna otra regla aplica, se usa un canal "
                      "de bajo costo y alcance directo.",
        "descripcion": "SI ninguna otra estrategia aplica ENTONCES enviar SMS",
        # Sin premisas: siempre se cumple. Con all() sobre una lista vacía el
        # resultado es verdadero, la misma propiedad que se señaló en la sesión 2.
        "condicion": {},
        "efecto": {"canal": "SMS"},
    },
]


OPERADORES = {"<", "<=", ">", ">=", "en", "entre"}
EFECTOS = {"estado", "canales_preferidos", "quitar_canales", "canal"}
ESTADOS = {"BLOQUEADA", "EN_ESPERA", "RECORDATORIO"}


def reglas_de_fase(fase):
    return [r for r in REGLAS if r["fase"] == fase]


def regla_por_id(identificador):
    return next((r for r in REGLAS if r["id"] == identificador), None)


def validar():
    """Revisa la consistencia de la base de conocimiento y retorna los errores.

    Cuando las reglas son datos, un error de escritura —un canal mal escrito,
    una fase que no existe, un id repetido— no rompe el programa: simplemente
    hace que la regla nunca se dispare, y nadie se entera. Esta verificación lo
    detecta antes de ejecutar. Se corre en la integración continua y al abrir
    la pantalla de la base de conocimiento.
    """
    errores = []
    fases = {nombre for nombre, _ in FASES}
    vistos = set()
    for regla in REGLAS:
        rid = regla.get("id", "?")
        if rid in vistos:
            errores.append("{}: id repetido".format(rid))
        vistos.add(rid)
        for campo in ("nombre", "fase", "fundamento", "descripcion", "condicion", "efecto"):
            if campo not in regla:
                errores.append("{}: falta el campo '{}'".format(rid, campo))
        if regla.get("fase") not in fases:
            errores.append("{}: fase desconocida '{}'".format(rid, regla.get("fase")))
        if regla.get("fase") == "estrategia" and "prioridad" not in regla:
            errores.append("{}: las reglas de estrategia necesitan prioridad".format(rid))

        for hecho, valor in regla.get("condicion", {}).items():
            if isinstance(valor, tuple) and valor[0] not in OPERADORES:
                errores.append("{}: operador desconocido '{}' en {}".format(rid, valor[0], hecho))

        efecto = regla.get("efecto", {})
        for clave in efecto:
            if clave not in EFECTOS:
                errores.append("{}: efecto desconocido '{}'".format(rid, clave))
        if "estado" in efecto and efecto["estado"] not in ESTADOS:
            errores.append("{}: estado desconocido '{}'".format(rid, efecto["estado"]))
        canales = list(efecto.get("quitar_canales", [])) + list(efecto.get("canales_preferidos", []))
        if "canal" in efecto:
            canales.append(efecto["canal"])
        for canal in canales:
            if canal not in CANALES_POR_COSTO:
                errores.append("{}: canal desconocido '{}'".format(rid, canal))

    # Debe existir una estrategia sin premisas: garantiza que toda cuenta
    # contactable reciba un canal aunque ninguna otra estrategia aplique.
    if not any(r["fase"] == "estrategia" and not r["condicion"] for r in REGLAS):
        errores.append("Falta una estrategia por defecto (sin condiciones)")
    return errores
