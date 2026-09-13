# -*- coding: utf-8 -*-
"""
Carga, limpieza y anonimización de la asignación mensual.

Es la puerta de entrada del sistema. Toma el archivo de asignación tal como lo
entrega la operación y produce una tabla lista para analizar, con tres
garantías:

  1. LIMPIEZA     -> tipos correctos, centinelas convertidos a nulo, categorías
                     unificadas. Ningún módulo posterior tiene que adivinar.
  2. ANONIMIZACIÓN-> los datos personales del titular no salen de aquí. Lo que
                     circula por el sistema son características, no identidades.
  3. DERIVACIÓN   -> las variables que el negocio necesita y el archivo no trae
                     explícitas: contactabilidad, antigüedad en gestión, tipo de
                     acuerdo, margen negociable.

La anonimización no es un adorno: la cartera contiene cédulas, nombres,
teléfonos, correos y direcciones de personas reales, protegidos por la Ley 1581
de 2012. El modelo no necesita saber QUIÉN es cada quien, sino CÓMO se comporta.
"""

import hashlib
import hmac
import os
import re
import secrets

import numpy as np
import pandas as pd

import config


# Columnas que identifican a una persona. Se usan para derivar características
# y luego se eliminan: no llegan a la tabla de trabajo ni a la base de datos.
COLUMNAS_IDENTIFICADORAS = [
    "CEDULA", "CEDULA.1", "NOMBRE", "CLIENTES",
    "Telefono", "Celular 1", "email", "email_1",
]


def _normalizar_columnas(df):
    """Unifica los nombres de columna del archivo original.

    El archivo trae nombres con saltos de línea internos y espacios dobles
    ("Monto\\nDesembolso", "COD  ACT"), lo que hace fallar cualquier acceso por
    nombre. Se normalizan una sola vez, aquí.
    """
    df.columns = [re.sub(r"\s+", " ", str(c).replace("\n", " ")).strip()
                  for c in df.columns]
    return df


def _clave_seudonimos():
    """Obtiene la clave secreta con la que se firman los seudónimos.

    Un hash simple de la cédula NO es irreversible: una cédula tiene como mucho
    diez dígitos, así que basta calcular el hash de los diez mil millones de
    valores posibles para encontrar la original, y eso toma minutos. Firmar con
    una clave secreta (HMAC) cierra esa puerta: sin la clave no se puede
    reproducir el cálculo, y con la misma clave el seudónimo sigue siendo estable
    entre meses.

    La clave vive en el archivo .env. Si no está definida, se genera una
    aleatoria para esta ejecución: los seudónimos siguen siendo irreversibles,
    pero dejan de ser comparables con los de otras cargas.
    """
    global _CLAVE_EFIMERA
    clave = os.getenv("SEUDONIMO_CLAVE")
    if clave:
        return clave.encode("utf-8")
    if _CLAVE_EFIMERA is None:
        print("  AVISO: SEUDONIMO_CLAVE no está definida en .env; se usa una clave")
        print("         temporal y los seudónimos no serán comparables entre cargas.")
        _CLAVE_EFIMERA = secrets.token_bytes(32)
    return _CLAVE_EFIMERA


_CLAVE_EFIMERA = None


def _seudonimo(valor, prefijo="C"):
    """Convierte un identificador en un seudónimo estable e irreversible.

    Se usa HMAC-SHA256 con la clave secreta del sistema: el mismo valor produce
    siempre el mismo código, lo que permite seguir una cuenta entre meses, pero
    sin la clave el código no permite recuperar el valor original.

    El prefijo distingue el tipo de identificador (C para titulares, K para
    créditos), para que un seudónimo nunca se confunda con otro.
    """
    texto = str(valor).strip().encode("utf-8")
    firma = hmac.new(_clave_seudonimos(), texto, hashlib.sha256).hexdigest()
    return prefijo + firma[:12].upper()


def _contar_canales(df):
    """Cuenta cuántos canales de contacto válidos tiene cada cuenta.

    Un teléfono se considera válido si es un número de más de seis dígitos, y
    un correo si contiene arroba. Se cuenta la CANTIDAD, no los valores: es la
    característica que predice la localizabilidad sin exponer el dato.
    """
    canales = pd.Series(0, index=df.index)

    for col in ["Telefono", "Celular 1"]:
        if col in df.columns:
            numero = pd.to_numeric(df[col], errors="coerce")
            canales += (numero.notna() & (numero > 999_999)).astype(int)

    for col in ["email", "email_1"]:
        if col in df.columns:
            texto = df[col].astype(str).str.strip()
            canales += (texto.str.contains("@", na=False)
                        & (texto.str.lower() != "nan")).astype(int)

    return canales


def _clasificar_gestion(serie):
    """Traduce el texto libre de gestión a una categoría cerrada.

    Recorre los patrones de configuración en orden y aplica el primero que
    coincide. Es determinista y reproducible: la misma nota produce siempre la
    misma etiqueta, lo que un modelo de lenguaje no garantiza y una auditoría
    sí exige.
    """
    texto = serie.astype(str).str.upper()
    etiquetas = pd.Series(config.ETIQUETA_GESTION_POR_DEFECTO, index=serie.index)
    asignadas = pd.Series(False, index=serie.index)

    for patron, etiqueta in config.PATRONES_GESTION:
        coincide = texto.str.contains(patron, regex=False, na=False) & ~asignadas
        etiquetas[coincide] = etiqueta
        asignadas |= coincide

    return etiquetas


def _meses_en_gestion(df):
    """Calcula cuántos meses lleva la cuenta rotando sin resolverse.

    Una cuenta asignada en abril que sigue en la asignación de septiembre lleva
    cinco meses de gestión infructuosa. Es una de las variables más predictivas
    y el archivo no la trae: hay que derivarla del mes de asignación original.
    """
    meses = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5,
             "JUNIO": 6, "JULIO": 7, "AGOSTO": 8, "SEPTIEMBRE": 9,
             "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}

    if "MES ASIG" not in df.columns:
        return pd.Series(0, index=df.index)

    numero_mes = df["MES ASIG"].astype(str).str.upper().str.strip().map(meses)
    mes_actual = numero_mes.max()          # el mes más reciente es el corriente
    return (mes_actual - numero_mes).fillna(0).astype(int)


def leer_bruto(ruta=None, hoja=None):
    """Lee el archivo de asignación sin transformarlo, con columnas normalizadas."""
    ruta = ruta or config.ARCHIVO_ASIGNACION
    hoja = hoja or config.HOJA_ASIGNACION
    return _normalizar_columnas(pd.read_excel(ruta, sheet_name=hoja))


def cargar(ruta=None, hoja=None, bruto=None):
    """Ejecuta el proceso completo y retorna la tabla lista para analizar.

    Acepta la ruta de un archivo o directamente un DataFrame ya leído, lo que
    permite procesar tanto la asignación real como una generada en memoria.
    """
    if bruto is None:
        bruto = leer_bruto(ruta, hoja)
    else:
        bruto = _normalizar_columnas(bruto.copy())
    df = pd.DataFrame(index=bruto.index)

    # --- Identidad seudonimizada ------------------------------------------
    # Tanto la cédula como el número de crédito identifican a una persona: el
    # número de crédito, cruzado con el sistema del originador, lleva directo
    # al titular. Por eso ninguno de los dos pasa en claro a la tabla de
    # trabajo.
    df["cuenta_id"] = bruto["CEDULA"].map(lambda v: _seudonimo(v, "C"))
    df["credito_id"] = bruto["CREDITO"].map(lambda v: _seudonimo(v, "K"))

    # --- Variables financieras --------------------------------------------
    for destino, origen in [("saldo", "SALDO"),
                            ("cobranza_min", "Min_cobranza"),
                            ("cobranza_max", "Max_cobranza"),
                            ("proyeccion", "PROYECCION"),
                            ("dias_mora", "DIAS MORA HOY")]:
        df[destino] = pd.to_numeric(bruto[origen], errors="coerce")

    df["proyeccion"] = df["proyeccion"].fillna(0)

    # Margen de negociación: cuánto se puede rebajar sin bajar del piso.
    df["margen_negociacion"] = (df["cobranza_max"] - df["cobranza_min"]).clip(lower=0)
    df["margen_pct"] = (df["margen_negociacion"] / df["cobranza_max"]).fillna(0)

    # --- Segmentación del negocio -----------------------------------------
    df["franja"] = bruto["FRANJA K 3"].astype(str).str.strip()
    df["rango_mora"] = bruto["Rango Mora"].astype(str).str.strip()
    df["ciudad"] = bruto["CIUDAD"].astype(str).str.strip().str.upper()
    df["producto"] = bruto["TIPO DE PRODUCTO"].astype(str).str.strip()
    df["estado"] = bruto["ESTADO"].astype(str).str.strip()
    df["codigo"] = bruto["CODIGO"].astype(str).str.strip().str.upper()
    df["gestor_ultimo"] = bruto["ASESOR CARSOFT"].astype(str).str.strip()

    # --- Variables derivadas ----------------------------------------------
    df["canales_disponibles"] = _contar_canales(bruto)
    df["resultado_gestion"] = _clasificar_gestion(bruto["GESTION"])
    df["meses_en_gestion"] = _meses_en_gestion(bruto)

    # Cuentas que nunca recibieron gestión humana real: el texto corresponde a
    # una actualización automática del sistema, no a un intento de contacto.
    df["gestionada"] = df["resultado_gestion"] != "SIN_GESTION_REAL"

    # --- Compromiso de pago: la variable objetivo -------------------------
    df["tiene_compromiso"] = (df["proyeccion"] > 0).astype(int)
    df["tipo_acuerdo"] = np.select(
        [df["codigo"].isin(config.CODIGOS_CONTADO),
         df["codigo"].isin(config.CODIGOS_DIFERIDO)],
        ["CONTADO", "DIFERIDO"],
        default="SIN_ACUERDO",
    )

    # Fecha pactada de pago. El centinela 01/01/1999 significa "sin compromiso"
    # y se convierte a nulo para no contaminar los cálculos de días.
    fecha = pd.to_datetime(bruto["LLAMAR EL"], errors="coerce")
    df["fecha_compromiso"] = fecha.where(
        fecha > pd.Timestamp(config.FECHA_CENTINELA) + pd.Timedelta(days=1))

    # --- Exclusiones ------------------------------------------------------
    df["gestionable"] = ~df["codigo"].isin(config.CODIGOS_EXCLUYENTES)

    return df


def perfilar(df):
    """Imprime el diagnóstico de la asignación cargada."""
    total = df["saldo"].sum()
    meta = total * config.META_PORCENTAJE

    print("=" * 76)
    print("PERFIL DE LA ASIGNACIÓN")
    print("=" * 76)
    print("  Cuentas              : {:>12,}".format(len(df)))
    print("  Titulares únicos     : {:>12,}".format(df["cuenta_id"].nunique()))
    print("  Saldo asignado       : ${:>15,.0f}".format(total))
    print("  Meta del {:.0%}          : ${:>15,.0f}".format(config.META_PORCENTAJE, meta))
    print("  Proyección actual    : ${:>15,.0f}  ({:.2%})".format(
        df["proyeccion"].sum(), df["proyeccion"].sum() / total))
    print("  Brecha               : ${:>15,.0f}".format(meta - df["proyeccion"].sum()))

    print("\n  --- Gestión real ---")
    print("  Cuentas gestionadas  : {:>6,} ({:.1%})".format(
        df["gestionada"].sum(), df["gestionada"].mean()))
    print("  Nunca gestionadas    : {:>6,} ({:.1%})  saldo ${:,.0f}".format(
        (~df["gestionada"]).sum(), (~df["gestionada"]).mean(),
        df.loc[~df["gestionada"], "saldo"].sum()))

    print("\n  --- Resultado del contacto ---")
    for etiqueta, n in df["resultado_gestion"].value_counts().items():
        print("    {:<20} {:>6,} ({:>5.1%})  saldo ${:>14,.0f}".format(
            etiqueta, n, n / len(df), df.loc[df["resultado_gestion"] == etiqueta, "saldo"].sum()))

    print("\n  --- Compromisos ---")
    for tipo, grupo in df[df["tiene_compromiso"] == 1].groupby("tipo_acuerdo"):
        print("    {:<12} {:>4} cuentas | proyectado ${:>12,.0f} | promedio ${:>10,.0f}".format(
            tipo, len(grupo), grupo["proyeccion"].sum(), grupo["proyeccion"].mean()))

    print("\n  --- Contactabilidad ---")
    for n, c in df["canales_disponibles"].value_counts().sort_index().items():
        print("    {} canal(es): {:>6,} cuentas ({:>5.1%})".format(n, c, c / len(df)))

    print("\n  --- Antigüedad en gestión ---")
    for m, c in df["meses_en_gestion"].value_counts().sort_index().items():
        saldo_m = df.loc[df["meses_en_gestion"] == m, "saldo"].sum()
        print("    {} mes(es): {:>6,} cuentas  saldo ${:>14,.0f}".format(m, c, saldo_m))

    print("\n  --- Margen de negociación ---")
    print("    promedio ${:,.0f} ({:.1%} del máximo)".format(
        df["margen_negociacion"].mean(), df["margen_pct"].mean()))
    print("    cuentas sin margen: {:,} ({:.1%})".format(
        (df["margen_negociacion"] <= 0).sum(), (df["margen_negociacion"] <= 0).mean()))
    print("=" * 76)


if __name__ == "__main__":
    cartera = cargar()
    perfilar(cartera)

    print("\nVerificación de anonimización:")
    sensibles = [c for c in cartera.columns
                 if any(p in c.lower() for p in
                        ["cedula", "nombre", "telefono", "celular", "email", "direccion"])]
    print("  columnas con datos personales en la salida: {}".format(sensibles or "ninguna"))
    print("  ejemplo de identificador seudonimizado: {}".format(cartera["cuenta_id"].iloc[0]))
