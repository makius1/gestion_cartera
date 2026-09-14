# -*- coding: utf-8 -*-
"""
Base de conocimiento difusa para la priorización de cuentas.

El experto de cobranza no razona con umbrales exactos: no dice "una cuenta con
saldo de 500.001 pesos es prioritaria y una de 499.999 no". Dice "saldo alto y
mora reciente, esa va primero". La lógica difusa representa ese razonamiento:
cada valor pertenece a varios conjuntos a la vez, en distinto grado, y las
reglas se combinan en lugar de excluirse.

Igual que en el motor de elegibilidad, el conocimiento vive aquí como datos y
el motor de inferencia (priorizacion.py) no sabe nada de cobranza. Es el mismo
esquema Mamdani de las sesiones 4 y 5: fuzzificación, reglas con MIN,
agregación con MAX y defuzzificación por centro de gravedad.

Formato de los conjuntos: ("tri", [a, b, c]) es triangular con pico en b;
("trap", [a, b, c, d]) es trapezoidal con meseta entre b y c.
"""

VARIABLES = {
    "saldo": {
        # Se usa la posición del saldo dentro de la cartera (percentil) y no el
        # monto: "alto" significa alto para esta asignación, sea de un cliente
        # con créditos pequeños o grandes.
        "descripcion": "Posición del saldo en la cartera (0 = el menor, 1 = el mayor)",
        "universo": (0.0, 1.0),
        "conjuntos": {
            "bajo":  ("trap", [0.00, 0.00, 0.20, 0.45]),
            "medio": ("tri",  [0.25, 0.50, 0.75]),
            "alto":  ("trap", [0.55, 0.80, 1.00, 1.00]),
        },
    },
    "dias_mora": {
        "descripcion": "Días de mora",
        "universo": (0.0, 3000.0),
        "conjuntos": {
            "temprana": ("trap", [0, 0, 300, 420]),
            "media":    ("tri",  [300, 540, 900]),
            "antigua":  ("trap", [720, 1200, 3000, 3000]),
        },
    },
    "contactabilidad": {
        "descripcion": "Probabilidad relativa de contacto efectivo",
        "universo": (0.0, 1.0),
        "conjuntos": {
            "baja":  ("trap", [0.00, 0.00, 0.45, 0.60]),
            "media": ("tri",  [0.45, 0.62, 0.80]),
            "alta":  ("trap", [0.70, 0.90, 1.00, 1.00]),
        },
    },
    "margen_pct": {
        "descripcion": "Margen negociable sobre el máximo de cobranza",
        "universo": (0.0, 0.30),
        "conjuntos": {
            "bajo": ("trap", [0.00, 0.00, 0.02, 0.06]),
            "alto": ("trap", [0.04, 0.09, 0.30, 0.30]),
        },
    },
    "meses_en_gestion": {
        "descripcion": "Meses que la cuenta lleva asignada sin resolverse",
        "universo": (0.0, 12.0),
        "conjuntos": {
            "pocos":  ("trap", [0, 0, 1, 2.5]),
            "muchos": ("trap", [2, 4, 12, 12]),
        },
    },
}

SALIDA = {
    "nombre": "prioridad",
    "descripcion": "Prioridad de gestión (0 a 100)",
    "universo": (0.0, 100.0),
    "conjuntos": {
        "baja":    ("trap", [0, 0, 15, 35]),
        "media":   ("tri",  [20, 45, 70]),
        "alta":    ("tri",  [55, 75, 90]),
        "urgente": ("trap", [80, 95, 100, 100]),
    },
}

REGLAS_DIFUSAS = [
    {"id": "D1", "si": {"saldo": "alto", "dias_mora": "temprana", "contactabilidad": "alta"},
     "entonces": "urgente",
     "fundamento": "Es el mejor caso posible: mucho por recuperar, deuda reciente y "
                   "titular localizable. Cada día de espera reduce la probabilidad de pago."},
    {"id": "D2", "si": {"saldo": "alto", "dias_mora": "temprana"}, "entonces": "alta",
     "fundamento": "La mora reciente se recupera mejor que la antigua; con saldo alto, "
                   "el impacto en la meta es inmediato."},
    {"id": "D3", "si": {"saldo": "alto", "dias_mora": "media"}, "entonces": "alta",
     "fundamento": "El saldo alto compensa una mora intermedia."},
    {"id": "D4", "si": {"saldo": "alto", "dias_mora": "antigua", "margen_pct": "alto"},
     "entonces": "media",
     "fundamento": "Una deuda antigua se mueve con descuento: si hay margen, vale la pena "
                   "intentarlo."},
    {"id": "D5", "si": {"saldo": "alto", "dias_mora": "antigua", "margen_pct": "bajo"},
     "entonces": "baja",
     "fundamento": "Deuda antigua sin margen para negociar: el esfuerzo rinde poco."},
    {"id": "D6", "si": {"saldo": "medio", "dias_mora": "temprana"}, "entonces": "alta",
     "fundamento": "La mora reciente es la más recuperable aunque el saldo sea intermedio."},
    {"id": "D7", "si": {"saldo": "medio", "dias_mora": "media"}, "entonces": "media",
     "fundamento": "Caso típico de la cartera: se trabaja en el orden normal."},
    {"id": "D8", "si": {"saldo": "medio", "dias_mora": "antigua"}, "entonces": "baja",
     "fundamento": "Saldo intermedio y deuda antigua: baja probabilidad y bajo impacto."},
    {"id": "D9", "si": {"saldo": "bajo", "dias_mora": "temprana"}, "entonces": "media",
     "fundamento": "Poco impacto en la meta, pero con buena probabilidad: sirve para "
                   "canales de bajo costo."},
    {"id": "D10", "si": {"saldo": "bajo", "dias_mora": "media"}, "entonces": "baja",
     "fundamento": "Poco impacto y probabilidad intermedia."},
    {"id": "D11", "si": {"saldo": "bajo", "dias_mora": "antigua"}, "entonces": "baja",
     "fundamento": "Poco impacto y baja probabilidad."},
    {"id": "D12", "si": {"contactabilidad": "baja"}, "entonces": "baja",
     "fundamento": "Si el titular no ha sido localizable, el gestor gasta su tiempo sin "
                   "lograr contacto. Esta regla compite con las de saldo y mora: la "
                   "agregación las combina en lugar de elegir una."},
    {"id": "D13", "si": {"contactabilidad": "alta", "margen_pct": "alto"}, "entonces": "alta",
     "fundamento": "Titular localizable y margen para ofrecer: condiciones para cerrar "
                   "un acuerdo."},
    {"id": "D14", "si": {"meses_en_gestion": "muchos", "contactabilidad": "baja"},
     "entonces": "baja",
     "fundamento": "Varios meses asignada sin lograr contacto: la estrategia actual no "
                   "funciona con esta cuenta."},
]


def validar():
    """Revisa la consistencia de la base difusa y retorna los errores.

    Además de revisar nombres y formatos, verifica la cobertura: cada
    combinación de saldo y mora debe tener al menos una regla. Si alguna
    combinación quedara sin regla, una cuenta con ese perfil no activaría nada y
    su prioridad saldría en cero sin que nadie lo decidiera.
    """
    errores = []
    vistos = set()
    for regla in REGLAS_DIFUSAS:
        if regla["id"] in vistos:
            errores.append("{}: id repetido".format(regla["id"]))
        vistos.add(regla["id"])
        for variable, conjunto in regla["si"].items():
            if variable not in VARIABLES:
                errores.append("{}: variable desconocida '{}'".format(regla["id"], variable))
            elif conjunto not in VARIABLES[variable]["conjuntos"]:
                errores.append("{}: conjunto '{}' no existe en {}".format(regla["id"], conjunto, variable))
        if regla["entonces"] not in SALIDA["conjuntos"]:
            errores.append("{}: conjunto de salida desconocido '{}'".format(regla["id"], regla["entonces"]))

    for nombre, variable in list(VARIABLES.items()) + [("salida", SALIDA)]:
        bajo, alto = variable["universo"]
        for conjunto, (forma, puntos) in variable["conjuntos"].items():
            if forma not in ("tri", "trap") or len(puntos) != (3 if forma == "tri" else 4):
                errores.append("{}.{}: forma mal definida".format(nombre, conjunto))
            elif puntos != sorted(puntos) or puntos[0] < bajo or puntos[-1] > alto:
                errores.append("{}.{}: puntos fuera de orden o del universo".format(nombre, conjunto))

    for saldo in VARIABLES["saldo"]["conjuntos"]:
        for mora in VARIABLES["dias_mora"]["conjuntos"]:
            cubre = any(r["si"].get("saldo") == saldo and r["si"].get("dias_mora") == mora
                        for r in REGLAS_DIFUSAS)
            if not cubre:
                errores.append("Sin regla para saldo {} y mora {}".format(saldo, mora))
    return errores
