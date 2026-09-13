# -*- coding: utf-8 -*-
"""
Extracción del perfil estadístico de una asignación real.

El generador de datos sintéticos necesita saber CÓMO se comporta una cartera
real, pero no QUIÉN la compone. Este módulo lee la asignación y guarda solo
agregados:

  * Frecuencias de las variables categóricas (qué proporción de cuentas está en
    cada código de gestión, en cada mes de asignación, en cada ciudad...).
  * Distribuciones condicionales (cómo cambia el estado según el código).
  * Cuantiles de las variables numéricas (la forma de la distribución del
    saldo, de la mora, del margen de negociación...).

Ningún registro individual sale de aquí, y ninguna identidad. Por eso el
archivo resultante, perfil_cartera.json, se puede versionar y compartir: con él
cualquiera puede generar una cartera de prueba estadísticamente parecida a la
real sin haber visto nunca un dato real.

Como precaución adicional, los cuantiles se toman entre el 0.5 % y el 99.5 % y
no en los extremos exactos: el mínimo y el máximo de una columna corresponden a
personas concretas, y no hace falta exponerlos.
"""

import json
from datetime import date

import numpy as np
import pandas as pd

import config
from datos.cargador import leer_bruto, _clasificar_gestion


RUTA_PERFIL = config.RAIZ / "datos" / "perfil_cartera.json"

# Puntos de corte de los cuantiles: 100 valores entre el 0.5 % y el 99.5 %.
NIVELES = np.linspace(0.005, 0.995, 100)

# Una categoría con menos registros que esto no tiene cuantiles propios y usa
# los globales: con muy pocos datos, la distribución sería puro ruido.
MINIMO_POR_GRUPO = 30

CODIGOS_CON_PROYECCION = ["DIFERIDO", "PAGO TOTAL", "POSIBLE NEGOCIACION"]

ETIQUETAS_FRANJA = ["DE 0  A 100 MIL", "DE 100 A 300 MIL", "DE 300 MIL A 500 MIL",
                    "DE 500 MIL A 700 MIL", "DE 700 MIL A 1 MILLON", "MAS DE 1 MILLON"]
CORTES_FRANJA = [-np.inf, 100_000, 300_000, 500_000, 700_000, 1_000_000, np.inf]


def franja(maximo):
    """Franja de saldo según Max_cobranza, con la misma regla del archivo real
    (intervalos cerrados por la izquierda). Se verificó que reproduce el 100 %
    de las franjas originales."""
    return pd.cut(maximo, CORTES_FRANJA, labels=ETIQUETAS_FRANJA, right=False).astype(str)


def _cuantiles_por_grupo(valores, grupos):
    """Cuantiles de una variable dentro de cada grupo con suficientes datos."""
    resultado = {}
    for grupo in pd.unique(grupos):
        mascara = grupos == grupo
        if mascara.sum() >= MINIMO_POR_GRUPO:
            resultado[str(grupo)] = _cuantiles(valores[mascara])
    return resultado


def _cuantiles(serie):
    """Resume una variable numérica en 100 cuantiles."""
    serie = pd.to_numeric(serie, errors="coerce").dropna()
    if len(serie) == 0:
        return []
    return [round(float(v), 6) for v in np.quantile(serie, NIVELES)]


def _frecuencias(serie):
    """Proporción de registros en cada categoría, ordenada de mayor a menor."""
    conteo = serie.astype(str).str.strip().value_counts(normalize=True)
    return {str(k): round(float(v), 6) for k, v in conteo.items()}


def _condicional(df, columna_objetivo, columna_condicion):
    """Distribución de una columna dentro de cada categoría de otra."""
    resultado = {}
    for categoria, grupo in df.groupby(columna_condicion):
        resultado[str(categoria)] = _frecuencias(grupo[columna_objetivo])
    return resultado


def extraer_perfil(bruto):
    """Construye el perfil estadístico a partir de la asignación sin procesar."""
    df = bruto.copy()
    # Se conservan las mayúsculas originales para que la cartera generada sea
    # indistinguible en formato de la real. Solo la ciudad se lleva a
    # mayúsculas, porque en el archivo real viene escrita de formas distintas.
    for col in ["CODIGO", "ESTADO", "MES ASIG", "TIPO DE PRODUCTO", "tipo_prestamo"]:
        df[col] = df[col].astype(str).str.strip()
    df["CIUDAD"] = df["CIUDAD"].astype(str).str.strip().str.upper()

    saldo = pd.to_numeric(df["SALDO"], errors="coerce")
    maximo = pd.to_numeric(df["Max_cobranza"], errors="coerce")
    minimo = pd.to_numeric(df["Min_cobranza"], errors="coerce")
    proyeccion = pd.to_numeric(df["PROYECCION"], errors="coerce").fillna(0)
    mora_hoy = pd.to_numeric(df["DIAS MORA HOY"], errors="coerce")
    mora_asig = pd.to_numeric(df["DIAS MORA"], errors="coerce")

    df["RESULTADO"] = _clasificar_gestion(df["GESTION"])

    # --- Ciudades: solo las 30 más frecuentes ------------------------------
    # El resto se reparte entre esas treinta al generar. Una ciudad con dos o
    # tres cuentas, combinada con el saldo, podría señalar a una persona.
    ciudades = df["CIUDAD"].value_counts()
    top_ciudades = ciudades.head(30)
    frecuencia_ciudades = {str(k): round(float(v / top_ciudades.sum()), 6)
                           for k, v in top_ciudades.items()}

    # --- Mora condicionada al mes de asignación ----------------------------
    # Una cuenta asignada hace más meses acumula más días de mora. Guardar la
    # distribución por mes conserva esa relación, que se perdería si la mora se
    # generara de forma independiente.
    mora_por_mes = {}
    for mes, grupo in df.groupby("MES ASIG"):
        if len(grupo) >= MINIMO_POR_GRUPO:
            mora_por_mes[str(mes)] = _cuantiles(grupo["DIAS MORA HOY"])

    # --- Proyección: probabilidad y monto según el código ------------------
    proyecta = {}
    monto_proyeccion = {}
    for codigo in CODIGOS_CON_PROYECCION:
        mascara = df["CODIGO"] == codigo
        if mascara.sum() == 0:
            continue
        proyecta[codigo] = round(float((proyeccion[mascara] > 0).mean()), 6)
        con_valor = mascara & (proyeccion > 0)
        # El pago total se proyecta sobre el piso negociable; el diferido y la
        # posible negociación, sobre el saldo. Así lo muestran los datos.
        base = minimo if codigo == "PAGO TOTAL" else saldo
        monto_proyeccion[codigo] = _cuantiles(proyeccion[con_valor] / base[con_valor])

    # --- Gestores: cuántos hay y cómo se reparte la carga -----------------
    # Solo los pesos, nunca los nombres.
    carga_gestores = df["ASESOR CARSOFT"].astype(str).str.strip().value_counts(normalize=True)

    # --- Fechas de gestión, como días antes de la última ------------------
    fecha_gestion = pd.to_datetime(df["FECHA DE GESTION"], errors="coerce")
    dias_desde_gestion = (fecha_gestion.max() - fecha_gestion).dt.days

    margen = (maximo - minimo).clip(lower=0)
    con_margen = margen > 0

    # --- Relaciones que se perderían generando cada variable por separado --
    # En la cartera real los diferidos tienen saldos más altos que el promedio,
    # y el porcentaje de descuento depende de la franja. Si el saldo y el margen
    # se sortearan sin mirar el código y la franja, la cartera sintética
    # proyectaría menos recaudo y tendría menos margen que la real.
    saldo_por_codigo = _cuantiles_por_grupo(saldo, df["CODIGO"])
    franjas = franja(maximo)
    margen_pct = margen / maximo
    margen_por_franja = _cuantiles_por_grupo(margen_pct[con_margen], franjas[con_margen])

    celular = pd.to_numeric(df["Celular 1"], errors="coerce")

    return {
        "version": 1,
        "fecha_extraccion": date.today().isoformat(),
        "n_registros": int(len(df)),
        "categoricas": {
            "CODIGO": _frecuencias(df["CODIGO"]),
            "MES ASIG": _frecuencias(df["MES ASIG"]),
            "TIPO DE PRODUCTO": _frecuencias(df["TIPO DE PRODUCTO"]),
            "tipo_prestamo": _frecuencias(df["tipo_prestamo"]),
            "CLIENTES": _frecuencias(df["CLIENTES"]),
            "CIUDAD": frecuencia_ciudades,
        },
        "condicionales": {
            "ESTADO|CODIGO": _condicional(df, "ESTADO", "CODIGO"),
            "RESULTADO|CODIGO": _condicional(df, "RESULTADO", "CODIGO"),
            "PROYECTA|CODIGO": proyecta,
        },
        "cuantiles": {
            "SALDO": _cuantiles(saldo),
            "SALDO|CODIGO": saldo_por_codigo,
            "MARGEN_PCT|FRANJA": margen_por_franja,
            "DIAS MORA HOY": _cuantiles(mora_hoy),
            "DIAS MORA HOY|MES ASIG": mora_por_mes,
            "DESFASE_MORA": _cuantiles(mora_hoy - mora_asig),
            "RATIO_MAX_SALDO": _cuantiles(maximo / saldo),
            "MARGEN_PCT": _cuantiles(margen[con_margen] / maximo[con_margen]),
            "RATIO_PAGO_TOTAL_MAX": _cuantiles(pd.to_numeric(df["pago_total"], errors="coerce") / maximo),
            "RATIO_DESEMBOLSO_SALDO": _cuantiles(pd.to_numeric(df["Monto Desembolso"], errors="coerce") / saldo),
            "RATIO_VENCIMIENTO_SALDO": _cuantiles(pd.to_numeric(df["Valor Vencimiento"], errors="coerce") / saldo),
            "PROYECCION|CODIGO": monto_proyeccion,
            "DIAS_DESDE_GESTION": _cuantiles(dias_desde_gestion),
        },
        "proporciones": {
            "SIN_MARGEN": round(float((~con_margen).mean()), 6),
            "CELULAR_INVALIDO": round(float((celular.isna() | (celular <= 999_999)).mean()), 6),
            "SIN_EMAIL_1": round(float(df["email_1"].isna().mean()), 6),
            "CON_ASESOR_ASIGNADO": round(float(df["ASESOR"].notna().mean()), 6),
            # Proporción de titulares distintos sobre el total de créditos: indica
            # cuántas personas tienen más de una obligación en la asignación.
            "TITULARES_POR_CREDITO": round(float(df["CEDULA"].nunique() / len(df)), 6),
        },
        "gestores": {
            "cantidad": int(len(carga_gestores)),
            "pesos": [round(float(p), 6) for p in carga_gestores.values],
        },
    }


def guardar_perfil(perfil, ruta=RUTA_PERFIL):
    """Escribe el perfil en disco como JSON legible."""
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(perfil, archivo, ensure_ascii=False, indent=2)
    return ruta


def cargar_perfil(ruta=RUTA_PERFIL):
    """Lee un perfil previamente extraído."""
    with open(ruta, encoding="utf-8") as archivo:
        return json.load(archivo)


if __name__ == "__main__":
    print("Extrayendo perfil estadístico de la asignación real...")
    perfil = extraer_perfil(leer_bruto())
    ruta = guardar_perfil(perfil)

    print("  Registros analizados : {:,}".format(perfil["n_registros"]))
    print("  Códigos de gestión   : {}".format(len(perfil["categoricas"]["CODIGO"])))
    print("  Ciudades conservadas : {}".format(len(perfil["categoricas"]["CIUDAD"])))
    print("  Gestores (sin nombre): {}".format(perfil["gestores"]["cantidad"]))
    print("  Variables numéricas  : {}".format(len(perfil["cuantiles"])))
    print("  Guardado en          : {}".format(ruta.relative_to(config.RAIZ)))
