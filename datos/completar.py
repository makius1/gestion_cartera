# -*- coding: utf-8 -*-
"""
Completa una carga a la que le faltan datos.

Las cargas registradas antes de que el esquema guardara los canales por tipo y
la fecha del último contacto quedaron con esas columnas vacías, y el motor las
bloquea completas por precaución (regla L3). Tampoco tienen directorio de
titulares ni contactos.

Una carga simulada se puede reconstruir de forma exacta: el simulador es
determinista, así que con la misma semilla, la misma cantidad de cuentas y la
misma fecha de referencia produce la misma asignación. Antes de escribir se
verifica que los créditos y los saldos coincidan uno a uno; si algo no
coincide, no se toca la base.

Una asignación real no se reconstruye: sus datos no se pueden inventar. Debe
volver a cargarse desde su archivo.

Uso:
    python -m datos.completar --carga 1
"""

import argparse

import pandas as pd

from datos import base_datos as bd
from datos.cargador import cargar, extraer_directorio
from datos.generador import generar
from datos.perfilador import cargar_perfil

COLUMNAS = ["tiene_celular", "tiene_fijo", "tiene_email", "fecha_ultima_gestion"]


def completar_carga(carga_id, usuario="sistema"):
    """Completa las columnas vacías de la carga y su directorio de titulares."""
    cargas = bd.listar_cargas()
    carga = cargas[cargas["id"] == carga_id]
    if carga.empty:
        raise LookupError("No existe la carga {}.".format(carga_id))
    carga = carga.iloc[0]
    if carga["origen"] != "SINTETICO" or pd.isna(carga["semilla"]):
        raise ValueError("Solo una carga simulada se puede reconstruir. Una asignación real "
                         "debe volver a cargarse desde su archivo.")

    bd.crear_esquema()
    bruto = generar(cargar_perfil(), n=int(carga["registros"]), semilla=int(carga["semilla"]),
                    fecha_referencia=pd.Timestamp(carga["fecha_carga"]).date())
    reconstruida = cargar(bruto=bruto).set_index("credito_id")
    actual = bd.leer_cartera(carga_id).set_index("credito_id")

    # Verificación: mismos créditos y mismos saldos. Si la reconstrucción no es
    # exacta (por ejemplo, porque cambió el perfil o la clave de seudónimos),
    # completar con ella mezclaría datos de dos carteras distintas.
    if set(actual.index) != set(reconstruida.index):
        raise ValueError("La reconstrucción no coincide con la carga: los créditos son distintos. "
                         "¿Cambió la clave de seudónimos o el perfil de referencia?")
    saldos = actual["saldo"].astype(float) == reconstruida.loc[actual.index, "saldo"].astype(float)
    if not saldos.all():
        raise ValueError("La reconstrucción no coincide: {} saldos distintos.".format((~saldos).sum()))

    tabla = reconstruida[COLUMNAS].reset_index()
    for booleana in COLUMNAS[:3]:
        tabla[booleana] = tabla[booleana].astype(bool)
    tabla["fecha_ultima_gestion"] = pd.to_datetime(tabla["fecha_ultima_gestion"]).dt.date
    vacias = int(actual[COLUMNAS].isna().any(axis=1).sum())
    bd.completar_columnas(carga_id, tabla, COLUMNAS)

    titulares, contactos = extraer_directorio(bruto)
    nuevos_titulares, nuevos_contactos = bd.registrar_directorio(titulares, contactos, "SINTETICO", usuario)
    resumen = {"carga_id": int(carga_id), "cuentas_completadas": vacias,
               "titulares_nuevos": nuevos_titulares, "contactos_nuevos": nuevos_contactos}
    bd.registrar_evento(usuario, "COMPLETAR_CARGA", "carga {}: {} cuentas completadas, {} titulares y "
                        "{} contactos nuevos".format(carga_id, vacias, nuevos_titulares, nuevos_contactos))
    return resumen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Completa una carga simulada a la que le faltan datos.")
    parser.add_argument("--carga", type=int, required=True)
    args = parser.parse_args()
    print("Base de datos: {}".format(bd.describir_motor()))
    resultado = completar_carga(args.carga, usuario="terminal")
    print("  Carga {carga_id}: {cuentas_completadas:,} cuentas completadas, {titulares_nuevos:,} "
          "titulares y {contactos_nuevos:,} contactos nuevos en el directorio".format(**resultado))
    print("  Cargas incompletas restantes: {}".format(sorted(bd.cargas_incompletas()) or "ninguna"))
