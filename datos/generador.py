# -*- coding: utf-8 -*-
"""
Generación de carteras de prueba.

Dos modos, con garantías de privacidad distintas:

  SINTÉTICO   Crea una asignación desde cero a partir del perfil estadístico.
              Ningún registro corresponde a una persona real: las identidades
              son inventadas y los montos, las moras y los códigos se muestrean
              de las distribuciones del perfil. Es seguro compartirlo, subirlo
              a la nube o usarlo en una demostración pública.

  ENMASCARADO Toma la asignación real y reemplaza solo los datos de identidad:
              nombres, documentos, créditos, teléfonos, correos, direcciones y
              nombres de gestores. Los montos, las moras, los códigos y las
              fechas siguen siendo los reales. Sirve para pruebas internas que
              necesitan el comportamiento exacto de la cartera, pero NO es
              anónimo: quien tenga el archivo original puede cruzar los montos y
              las fechas y reidentificar a los titulares. Bajo la Ley 1581 sigue
              siendo dato personal y no debe salir de la empresa.

En ambos modos la salida tiene exactamente las mismas columnas que la
asignación real, de modo que todo el sistema la procesa sin saber la
diferencia, y una columna adicional ES_DEMO que la marca como no real.

Precauciones contra el uso accidental de datos de prueba en una campaña real:
  * Los documentos se generan en un rango de diez dígitos que empieza por 99,
    que no corresponde a cédulas expedidas.
  * Los correos usan el dominio .test, reservado por el estándar de internet
    para pruebas: no existe y ningún mensaje puede entregarse.
  * Los celulares usan el prefijo 399, fuera de los rangos que usan los
    operadores móviles en Colombia a la fecha de este desarrollo. Aun así,
    cualquier integración con un marcador o una pasarela de SMS debe rechazar
    los registros con ES_DEMO distinto de vacío.
"""

import argparse
import unicodedata
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import config
from datos.cargador import _clasificar_gestion, _normalizar_columnas, leer_bruto
from datos.perfilador import NIVELES, cargar_perfil, franja


# ---------------------------------------------------------------------------
# 1. MATERIA PRIMA PARA IDENTIDADES FICTICIAS
# ---------------------------------------------------------------------------

NOMBRES = [
    "ANDRES", "CAMILO", "SANTIAGO", "JUAN", "CARLOS", "LUIS", "JORGE", "DIEGO",
    "FELIPE", "SEBASTIAN", "JULIAN", "MIGUEL", "DAVID", "OSCAR", "RICARDO",
    "ALEJANDRO", "NICOLAS", "MAURICIO", "HERNAN", "FABIAN",
    "MARIA", "LAURA", "ANDREA", "PAOLA", "CAROLINA", "DANIELA", "NATALIA",
    "CATALINA", "VALENTINA", "SANDRA", "DIANA", "LUISA", "ANGELA", "MONICA",
    "JULIANA", "CLAUDIA", "PATRICIA", "LORENA", "XIMENA", "ADRIANA",
]

APELLIDOS = [
    "RODRIGUEZ", "GOMEZ", "GONZALEZ", "MARTINEZ", "GARCIA", "LOPEZ", "HERNANDEZ",
    "SANCHEZ", "RAMIREZ", "PEREZ", "DIAZ", "MUÑOZ", "ROJAS", "MORENO", "JIMENEZ",
    "TORRES", "VARGAS", "CASTRO", "RUIZ", "ORTIZ", "SUAREZ", "CARDENAS",
    "HERRERA", "MEDINA", "AGUILAR", "CASTILLO", "RIOS", "GUERRERO", "MENDOZA",
    "PARRA", "OSPINA", "CORTES", "RESTREPO", "CARDONA", "VALENCIA", "QUINTERO",
    "SALAZAR", "ARIAS", "BERMUDEZ", "CIFUENTES",
]

TIPOS_VIA = ["CALLE", "CARRERA", "DIAGONAL", "TRANSVERSAL", "AVENIDA"]

# Texto de gestión por categoría. Cada plantilla contiene exactamente la
# palabra clave que el clasificador del cargador reconoce, de modo que al
# procesar la cartera sintética se obtiene la misma distribución de resultados
# que en la real. El texto libre real NO se copia nunca: puede contener nombres
# de titulares, de familiares o de gestores.
PLANTILLAS_GESTION = {
    "SIN_GESTION_REAL": "INACTIVO POR CLIENTES EN GENERAL",
    "ACUERDO":          "TITULAR ACEPTA ACUERDO DE PAGO",
    "BUZON":            "SE LLAMA AL TITULAR Y CAE A BUZON DE VOZ",
    "APAGADO":          "CELULAR APAGADO SE REINTENTA MAS TARDE",
    "NO_CONTESTA":      "SE LLAMA Y NO CONTESTA EL TITULAR",
    "CUELGA":           "TITULAR ATIENDE Y CUELGA LA LLAMADA",
    "MENSAJE_DEJADO":   "SE DEJA MENSAJE CON UN TERCERO",
    "CORREO_ENVIADO":   "SE ENVIA CORREO CON ESTADO DE CUENTA",
    "REINTENTAR":       "TITULAR INSISTE EN QUE LLAMEN OTRO DIA",
    "NUMERO_ERRADO":    "NUMERO EQUIVOCADO NO CORRESPONDE AL TITULAR",
    "FALLECIDO":        "UN FAMILIAR INFORMA QUE EL TITULAR FALLECIO",
    "OTRO":             "SE REALIZA SEGUIMIENTO A LA OBLIGACION",
}

MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5,
         "JUNIO": 6, "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9,
         "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}

FECHA_SIN_COMPROMISO = pd.Timestamp(config.FECHA_CENTINELA)

ORDEN_COLUMNAS = [
    "MES", "MES ASIG", "CEDULA", "CLIENTES", "TIPO DE PRODUCTO", "NOMBRE",
    "CREDITO", "ESTADO", "EXPEDIENTE", "FECHA DE GESTION", "LLAMAR EL", "CODIGO",
    "ASESOR CARSOFT", "GESTION", "PROYECCION", "ASESOR", "Monto Desembolso",
    "Max_cobranza", "Min_cobranza", "pago_total", "Valor Vencimiento",
    "DIAS MORA", "DIAS MORA HOY", "Rango Mora", "FRANJA K 3", "Telefono",
    "Celular 1", "CIUDAD", "tipo_prestamo", "SALDO", "email", "email_1",
    "CEDULA.1", "CREDITO.1", "VALOR PAGO", "FECHA DE PAGO", "ASESOR.1", "MEDIO",
    "DESCUENTO", "Rango Mora.1", "ES_DEMO",
]


# ---------------------------------------------------------------------------
# 2. FÁBRICA DE IDENTIDADES
# ---------------------------------------------------------------------------

def _sin_tildes(texto):
    """Quita tildes y eñes para construir direcciones de correo válidas."""
    normal = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normal if not unicodedata.combining(c)).replace("Ñ", "N")


class FabricaIdentidades:
    """Produce identidades ficticias únicas y coherentes entre sí.

    Coherentes significa que el correo de una persona se construye con su
    propio nombre, y que la misma persona conserva el mismo documento, nombre y
    teléfonos en todos sus créditos, como pasa en la cartera real.
    """

    def __init__(self, generador):
        self.rng = generador
        self._usados = {"cedula": set(), "credito": set(), "expediente": set()}

    def excluir(self, tipo, valores):
        """Marca valores como ya usados para que nunca se generen.

        Al enmascarar se excluyen todos los valores reales: sin esto, el sorteo
        aleatorio puede producir por azar un número de crédito que existe en la
        cartera real, y aunque quede asignado a otra cuenta, un dato real no
        debe aparecer en un archivo enmascarado.
        """
        self._usados[tipo].update(int(v) for v in pd.Series(valores).dropna())

    def _unico(self, tipo, minimo, maximo):
        while True:
            valor = int(self.rng.integers(minimo, maximo))
            if valor not in self._usados[tipo]:
                self._usados[tipo].add(valor)
                return valor

    def cedula(self):
        # Diez dígitos empezando por 99: fuera del rango de cédulas expedidas.
        return self._unico("cedula", 9_900_000_000, 9_999_999_999)

    def credito(self):
        return self._unico("credito", 90_000_000, 99_999_999)

    def expediente(self):
        return self._unico("expediente", 9_000_000, 9_999_999)

    def nombre(self):
        n1, n2 = self.rng.choice(NOMBRES, size=2, replace=False)
        a1, a2 = self.rng.choice(APELLIDOS, size=2, replace=False)
        return "{} {} {} {}".format(n1, n2, a1, a2)

    def telefono_fijo(self):
        # Formato nacional de diez dígitos para línea fija.
        return int("601000" + "{:04d}".format(int(self.rng.integers(0, 10_000))))

    def celular(self):
        return int("399" + "{:07d}".format(int(self.rng.integers(0, 10_000_000))))

    def correo(self, nombre, variante=0):
        partes = _sin_tildes(nombre).lower().split()
        base = "{}.{}".format(partes[0], partes[2]) if variante == 0 \
            else "{}{}".format(partes[1][0], partes[3])
        return "{}{}@correo.test".format(base, int(self.rng.integers(10, 99)))

    def direccion(self):
        via = self.rng.choice(TIPOS_VIA)
        return "{} {} # {} - {}".format(via, int(self.rng.integers(1, 180)),
                                        int(self.rng.integers(1, 120)),
                                        int(self.rng.integers(1, 99)))


# ---------------------------------------------------------------------------
# 3. MUESTREO A PARTIR DEL PERFIL
# ---------------------------------------------------------------------------

def _muestrear_cuantiles(cuantiles, n, rng):
    """Muestreo por transformada inversa sobre la distribución empírica.

    Se sortea un número uniforme entre 0 y 1 y se interpola en la tabla de
    cuantiles. El resultado reproduce la forma de la distribución real sin
    copiar ningún valor individual. Los extremos quedan acotados al 0.5 % y al
    99.5 %, de modo que tampoco se reproducen los casos atípicos, que son los
    más fáciles de reconocer.
    """
    return np.interp(rng.uniform(0, 1, n), NIVELES, cuantiles)


def _muestrear_categoria(frecuencias, n, rng):
    categorias = list(frecuencias.keys())
    pesos = np.array(list(frecuencias.values()), dtype=float)
    return rng.choice(categorias, size=n, p=pesos / pesos.sum())


def _redondear(valores, a=50):
    """Redondea montos al múltiplo de 50, como vienen en la cartera real."""
    return (np.round(np.asarray(valores, dtype=float) / a) * a).astype(np.int64)


def _hora(rng):
    return "{:02d}:{:02d}:{:02d}".format(int(rng.integers(7, 19)),
                                        int(rng.integers(0, 60)),
                                        int(rng.integers(0, 60)))


def _muestrear_por_grupo(grupos, tablas, tabla_global, rng):
    """Muestrea cada registro con la distribución de su grupo.

    Si el grupo no tiene distribución propia porque en la cartera real tenía
    muy pocos registros, se usa la global. Así se conservan las relaciones entre
    variables donde hay datos para sostenerlas, sin inventarlas donde no.
    """
    grupos = np.asarray(grupos)
    resultado = np.empty(len(grupos))
    for grupo in np.unique(grupos):
        filas = grupos == grupo
        resultado[filas] = _muestrear_cuantiles(tablas.get(str(grupo), tabla_global),
                                                filas.sum(), rng)
    return resultado


def _rango_mora(dias):
    """Rango de mora: se calcula sobre DIAS MORA HOY, como en el archivo real."""
    return pd.cut(dias, [-np.inf, 399, 539, 719, np.inf],
                  labels=["De 140 a 399", "De 400 a 539", "De 540 a 719", "Mayor a 720"]
                  ).astype(str)


def _nombres_gestores(cantidad, rng):
    """Nombres ficticios para los gestores, truncados a 25 caracteres como en
    el sistema de gestión real."""
    fabrica = FabricaIdentidades(rng)
    nombres = set()
    while len(nombres) < cantidad:
        nombres.add(fabrica.nombre()[:25])
    return sorted(nombres)


# ---------------------------------------------------------------------------
# 4. MODO SINTÉTICO
# ---------------------------------------------------------------------------

def generar(perfil, n=None, semilla=config.SEMILLA, fecha_referencia=None):
    """Crea una asignación completamente ficticia a partir del perfil.

    El orden de generación respeta las dependencias del negocio: primero el
    código de gestión, porque de él dependen el estado, el texto de la gestión
    y la existencia de un compromiso de pago; después los montos, y al final
    los campos que se derivan de otros por regla (franja, rango de mora, fecha
    de compromiso).
    """
    rng = np.random.default_rng(semilla)
    n = n or perfil["n_registros"]
    hoy = pd.Timestamp(fecha_referencia or date.today())
    cat, cond, cuant, prop = (perfil["categoricas"], perfil["condicionales"],
                              perfil["cuantiles"], perfil["proporciones"])

    df = pd.DataFrame(index=range(n))

    # --- Código de gestión y lo que depende de él -------------------------
    df["CODIGO"] = _muestrear_categoria(cat["CODIGO"], n, rng)
    df["ESTADO"] = [_muestrear_categoria(cond["ESTADO|CODIGO"][c], 1, rng)[0]
                    for c in df["CODIGO"]]
    resultados = [_muestrear_categoria(cond["RESULTADO|CODIGO"][c], 1, rng)[0]
                  for c in df["CODIGO"]]
    df["GESTION"] = ["{} {}".format(_hora(rng), PLANTILLAS_GESTION[r]) for r in resultados]

    # --- Mes de asignación y mora condicionada a él ----------------------
    df["MES ASIG"] = _muestrear_categoria(cat["MES ASIG"], n, rng)
    df["MES"] = df["MES ASIG"].str.upper().map(MESES) + 101
    mora = np.empty(n)
    for mes in df["MES ASIG"].unique():
        filas = (df["MES ASIG"] == mes).to_numpy()
        tabla = cuant["DIAS MORA HOY|MES ASIG"].get(mes, cuant["DIAS MORA HOY"])
        mora[filas] = _muestrear_cuantiles(tabla, filas.sum(), rng)
    df["DIAS MORA HOY"] = np.round(mora).astype(int)
    desfase = _muestrear_cuantiles(cuant["DESFASE_MORA"], n, rng)
    df["DIAS MORA"] = np.clip(df["DIAS MORA HOY"] - np.round(desfase), 0, None).astype(int)

    # --- Montos ------------------------------------------------------------
    # El saldo se sortea según el código de gestión y el margen según la franja:
    # son las dos relaciones que más pesan en el recaudo proyectado.
    saldo = _redondear(_muestrear_por_grupo(df["CODIGO"], cuant["SALDO|CODIGO"],
                                            cuant["SALDO"], rng))
    df["SALDO"] = np.clip(saldo, 1_000, None)
    maximo = _redondear(df["SALDO"] * _muestrear_cuantiles(cuant["RATIO_MAX_SALDO"], n, rng))
    df["Max_cobranza"] = maximo
    margen = _muestrear_por_grupo(franja(maximo), cuant["MARGEN_PCT|FRANJA"],
                                  cuant["MARGEN_PCT"], rng)
    sin_margen = rng.uniform(size=n) < prop["SIN_MARGEN"]
    df["Min_cobranza"] = np.where(sin_margen, maximo, _redondear(maximo * (1 - margen)))
    df["pago_total"] = _redondear(maximo * _muestrear_cuantiles(cuant["RATIO_PAGO_TOTAL_MAX"], n, rng))
    df["Monto Desembolso"] = _redondear(df["SALDO"] * _muestrear_cuantiles(cuant["RATIO_DESEMBOLSO_SALDO"], n, rng))
    df["Valor Vencimiento"] = _redondear(df["SALDO"] * _muestrear_cuantiles(cuant["RATIO_VENCIMIENTO_SALDO"], n, rng))

    # --- Compromiso de pago -----------------------------------------------
    # Solo los códigos que en la cartera real generan proyección pueden tenerla,
    # y con la misma probabilidad. Así se conserva la regla de negocio de que un
    # contacto sin acuerdo nunca proyecta pago.
    proyeccion = np.zeros(n)
    for codigo, probabilidad in cond["PROYECTA|CODIGO"].items():
        filas = (df["CODIGO"] == codigo).to_numpy() & (rng.uniform(size=n) < probabilidad)
        if filas.sum() == 0:
            continue
        base = df["Min_cobranza"] if codigo == "PAGO TOTAL" else df["SALDO"]
        razon = _muestrear_cuantiles(cuant["PROYECCION|CODIGO"][codigo], filas.sum(), rng)
        proyeccion[filas] = base.to_numpy()[filas] * razon
    df["PROYECCION"] = _redondear(proyeccion)

    df["LLAMAR EL"] = [hoy + timedelta(days=int(rng.integers(0, 15))) if p > 0
                       else FECHA_SIN_COMPROMISO for p in df["PROYECCION"]]
    dias_gestion = _muestrear_cuantiles(cuant["DIAS_DESDE_GESTION"], n, rng)
    df["FECHA DE GESTION"] = [hoy - timedelta(days=int(d)) for d in dias_gestion]

    # --- Campos derivados por regla ---------------------------------------
    df["Rango Mora"] = _rango_mora(df["DIAS MORA HOY"])
    df["Rango Mora.1"] = df["Rango Mora"]
    df["FRANJA K 3"] = franja(df["Max_cobranza"])

    # --- Segmentación -----------------------------------------------------
    df["CIUDAD"] = _muestrear_categoria(cat["CIUDAD"], n, rng)
    df["TIPO DE PRODUCTO"] = _muestrear_categoria(cat["TIPO DE PRODUCTO"], n, rng)
    df["tipo_prestamo"] = _muestrear_categoria(cat["tipo_prestamo"], n, rng)
    df["CLIENTES"] = _muestrear_categoria(cat["CLIENTES"], n, rng).astype(int)

    # --- Identidades ficticias --------------------------------------------
    # Se crean menos titulares que créditos, en la misma proporción que en la
    # cartera real, para que algunas personas tengan dos obligaciones.
    fabrica = FabricaIdentidades(rng)
    n_titulares = max(1, int(round(n * prop["TITULARES_POR_CREDITO"])))
    titulares = []
    for _ in range(n_titulares):
        nombre = fabrica.nombre()
        titulares.append({
            "CEDULA": fabrica.cedula(), "NOMBRE": nombre,
            "Telefono": fabrica.telefono_fijo(), "Celular 1": fabrica.celular(),
            "email": fabrica.correo(nombre, 0), "email_1": fabrica.correo(nombre, 1),
        })
    asignacion = np.concatenate([np.arange(n_titulares),
                                 rng.integers(0, n_titulares, n - n_titulares)])
    rng.shuffle(asignacion)
    identidades = pd.DataFrame([titulares[i] for i in asignacion])
    for col in identidades.columns:
        df[col] = identidades[col].to_numpy()

    df.loc[rng.uniform(size=n) < prop["CELULAR_INVALIDO"], "Celular 1"] = 0
    df["email_1"] = df["email_1"].where(rng.uniform(size=n) >= prop["SIN_EMAIL_1"])

    df["CREDITO"] = [fabrica.credito() for _ in range(n)]
    df["EXPEDIENTE"] = [fabrica.expediente() for _ in range(n)]
    df["CEDULA.1"] = df["CEDULA"]
    df["CREDITO.1"] = df["CREDITO"]

    # --- Gestores ficticios -----------------------------------------------
    gestores = _nombres_gestores(perfil["gestores"]["cantidad"], rng)
    pesos = np.array(perfil["gestores"]["pesos"])
    df["ASESOR CARSOFT"] = rng.choice(gestores, size=n, p=pesos / pesos.sum())
    nombres_cortos = [g.split()[0] for g in gestores[:4]]
    con_asesor = rng.uniform(size=n) < prop["CON_ASESOR_ASIGNADO"]
    df["ASESOR"] = np.where(con_asesor, rng.choice(nombres_cortos, size=n), None)

    # --- Campos de pago: vacíos, como en una asignación del mes en curso ---
    for col in ["VALOR PAGO", "FECHA DE PAGO", "ASESOR.1", "MEDIO", "DESCUENTO"]:
        df[col] = np.nan

    df["ES_DEMO"] = "SI"
    return df[ORDEN_COLUMNAS]


# ---------------------------------------------------------------------------
# 5. MODO ENMASCARADO
# ---------------------------------------------------------------------------

# Cualquier columna cuyo nombre contenga uno de estos fragmentos se trata como
# dato de identidad. Detectar por nombre y no por una lista cerrada permite
# enmascarar también otras hojas del archivo, que traen hasta diez teléfonos,
# diez correos y varias direcciones por titular.
FRAGMENTOS_IDENTIDAD = {
    "telefono": "telefono_fijo", "tel_": "telefono_fijo", "celular": "celular",
    "email": "correo", "residencia": "direccion", "direcci": "direccion",
}


def enmascarar(bruto, semilla=config.SEMILLA):
    """Reemplaza los datos de identidad de una asignación real por ficticios.

    La sustitución es consistente: todos los créditos de un mismo titular
    reciben la misma identidad ficticia, y cada gestor real se reemplaza siempre
    por el mismo nombre ficticio. Así se conservan las relaciones de la cartera
    (quién tiene dos créditos, qué gestor lleva qué cuentas) sin exponer a nadie.
    """
    rng = np.random.default_rng(semilla)
    fabrica = FabricaIdentidades(rng)
    df = _normalizar_columnas(bruto.copy())

    # Ningún valor ficticio puede coincidir con uno real.
    fabrica.excluir("cedula", df["CEDULA"])
    fabrica.excluir("credito", df["CREDITO"])
    if "EXPEDIENTE" in df.columns:
        fabrica.excluir("expediente", df["EXPEDIENTE"])

    # --- Titulares --------------------------------------------------------
    ficticios = {}
    for cedula in df["CEDULA"].unique():
        nombre = fabrica.nombre()
        ficticios[cedula] = {"CEDULA": fabrica.cedula(), "NOMBRE": nombre}
    df["NOMBRE"] = df["CEDULA"].map(lambda c: ficticios[c]["NOMBRE"])

    for col in df.columns:
        clave = col.lower()
        tipo = next((t for frag, t in FRAGMENTOS_IDENTIDAD.items() if frag in clave), None)
        if tipo is None:
            continue
        vacios = df[col].isna()
        if tipo == "correo":
            valores = [fabrica.correo(n, i % 2) for i, n in enumerate(df["NOMBRE"])]
        else:
            valores = [getattr(fabrica, tipo)() for _ in range(len(df))]
        df[col] = pd.Series(valores, index=df.index).where(~vacios)

    for col in ["CEDULA", "CEDULA.1"]:
        if col in df.columns:
            df[col] = df[col].map(lambda c: ficticios.get(c, {}).get("CEDULA"))

    # --- Créditos y expedientes -------------------------------------------
    creditos = {c: fabrica.credito() for c in df["CREDITO"].unique()}
    for col in ["CREDITO", "CREDITO.1"]:
        if col in df.columns:
            df[col] = df[col].map(creditos)
    if "EXPEDIENTE" in df.columns:
        df["EXPEDIENTE"] = [fabrica.expediente() for _ in range(len(df))]

    # --- Gestores ---------------------------------------------------------
    reales = df["ASESOR CARSOFT"].astype(str).str.strip().unique()
    reemplazo = dict(zip(reales, _nombres_gestores(len(reales), rng)))
    df["ASESOR CARSOFT"] = df["ASESOR CARSOFT"].astype(str).str.strip().map(reemplazo)
    cortos = {}
    for col in ["ASESOR", "ASESOR.1"]:
        if col in df.columns:
            df[col] = df[col].map(lambda v: cortos.setdefault(v, fabrica.nombre().split()[0])
                                  if pd.notna(v) else v)

    # --- Texto libre de gestión -------------------------------------------
    # El texto real se descarta por completo: puede nombrar al titular, a un
    # familiar o al gestor. Se conserva la hora y se reemplaza el cuerpo por la
    # plantilla de la misma categoría, para no alterar la clasificación.
    categorias = _clasificar_gestion(df["GESTION"])
    horas = df["GESTION"].astype(str).str.extract(r"^(\d{1,2}:\d{2}:\d{2})")[0].fillna("00:00:00")
    df["GESTION"] = [h + " " + PLANTILLAS_GESTION[c] for h, c in zip(horas, categorias)]

    df["ES_DEMO"] = "ENMASCARADO"
    return df


# ---------------------------------------------------------------------------
# 6. VALIDACIÓN: ¿SE PARECE LA CARTERA SINTÉTICA A LA REAL?
# ---------------------------------------------------------------------------

def comparar(real, sintetica):
    """Compara las dos carteras después de pasar ambas por el cargador.

    Es la prueba de que el generador sirve: si el sistema produce diagnósticos
    parecidos sobre las dos, los datos de prueba son representativos.
    """
    from datos.cargador import cargar

    a, b = cargar(bruto=real), cargar(bruto=sintetica)

    def fila(nombre, fa, fb, formato):
        va, vb = fa(a), fb(b)
        dif = (vb - va) / va if va else 0
        print("  {:<34} {:>16} {:>16} {:>+8.1%}".format(
            nombre, formato.format(va), formato.format(vb), dif))

    print("  {:<34} {:>16} {:>16} {:>8}".format("MÉTRICA", "REAL", "SINTÉTICA", "DIF"))
    print("  " + "-" * 76)
    fila("Cuentas", len, len, "{:,.0f}")
    fila("Saldo total", lambda d: d["saldo"].sum(), lambda d: d["saldo"].sum(), "${:,.0f}")
    fila("Saldo mediano", lambda d: d["saldo"].median(), lambda d: d["saldo"].median(), "${:,.0f}")
    fila("Mora mediana (días)", lambda d: d["dias_mora"].median(), lambda d: d["dias_mora"].median(), "{:,.0f}")
    fila("Cuentas con compromiso", lambda d: d["tiene_compromiso"].sum(), lambda d: d["tiene_compromiso"].sum(), "{:,.0f}")
    fila("Valor proyectado", lambda d: d["proyeccion"].sum(), lambda d: d["proyeccion"].sum(), "${:,.0f}")
    fila("Nunca gestionadas", lambda d: (~d["gestionada"]).sum(), lambda d: (~d["gestionada"]).sum(), "{:,.0f}")
    fila("Margen promedio", lambda d: d["margen_negociacion"].mean(), lambda d: d["margen_negociacion"].mean(), "${:,.0f}")
    fila("Cuentas sin margen", lambda d: (d["margen_negociacion"] <= 0).sum(), lambda d: (d["margen_negociacion"] <= 0).sum(), "{:,.0f}")


# ---------------------------------------------------------------------------
# 7. LÍNEA DE COMANDOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera carteras de prueba.")
    parser.add_argument("--registros", type=int, default=None,
                        help="cantidad de cuentas (por defecto, las del perfil)")
    parser.add_argument("--enmascarar", action="store_true",
                        help="enmascara la asignación real en lugar de generar una sintética")
    parser.add_argument("--validar", action="store_true",
                        help="compara la cartera sintética con la real")
    parser.add_argument("--salida", default=None, help="ruta del Excel de salida")
    args = parser.parse_args()

    if args.enmascarar:
        salida = args.salida or str(config.SALIDAS / "asignacion_enmascarada.xlsx")
        resultado = enmascarar(leer_bruto())
        print("Asignación real enmascarada: {:,} cuentas".format(len(resultado)))
        print("  AVISO: conserva montos, moras y fechas reales. No es anónima y")
        print("         no debe salir de la empresa.")
    else:
        perfil = cargar_perfil()
        destino = config.RAIZ / "datos" / "demo"
        destino.mkdir(exist_ok=True)
        salida = args.salida or str(destino / "asignacion_demo.xlsx")
        resultado = generar(perfil, n=args.registros)
        print("Asignación sintética generada: {:,} cuentas ficticias".format(len(resultado)))

    resultado.to_excel(salida, sheet_name=config.HOJA_ASIGNACION, index=False)
    print("  Guardada en: {}".format(salida))

    if args.validar and not args.enmascarar:
        print("\nVALIDACIÓN CONTRA LA CARTERA REAL")
        comparar(leer_bruto(), resultado)
