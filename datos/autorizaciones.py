# -*- coding: utf-8 -*-
"""
Autorización del titular por canal (Ley 2300 de 2023, artículo 2).

La norma permite gestionar cobranza únicamente por los canales que el consumidor
autorizó antes para ese fin, y obliga a informárselos para que él elija. Hasta
ahora el sistema sabía si un canal EXISTE (tiene celular, tiene correo), pero no
si está PERMITIDO, que es lo que la ley exige.

Este módulo administra ese dato:

  * La verdad vive en la tabla `autorizaciones_canal`, una fila por titular y
    canal, con su estado, quién lo registró y cuándo.
  * El motor no consulta esa tabla: lee cuatro columnas derivadas de `cartera`
    (`autoriza_llamada`, `autoriza_whatsapp`, `autoriza_sms`, `autoriza_email`),
    igual que hoy lee `tiene_celular`. Este módulo es el que las mantiene al día.
  * Un canal sin fila se interpreta como DESCONOCIDO, y para el motor pesa igual
    que NO_AUTORIZADO: lo que no consta, no habilita. Es la misma precaución de
    la regla L3.

La ley prevé una excepción —cuando la entidad no tiene información actualizada
de canales autorizados y el operador reporta imposibilidad de entrega, dejando
constancia—, que este módulo no implementa: el sistema se queda con la lectura
conservadora.

Uso:
    python -m datos.autorizaciones --carga 1 --resumen
    python -m datos.autorizaciones --carga 1 --simular
"""

import argparse
import hashlib

import pandas as pd
from sqlalchemy import delete, insert, select, update

import config
from datos import base_datos as bd

# Cómo se muestra cada estado en pantalla. "Sin preguntar" y "No autorizó" pesan
# igual para el motor, pero no son lo mismo ante una reclamación: uno es un
# dato que falta y el otro una negativa que el titular dio y quedó registrada.
ETIQUETAS = {"AUTORIZADO": "Autorizó", "NO_AUTORIZADO": "No autorizó",
             "DESCONOCIDO": "Sin preguntar"}


def _validar(canal, estado):
    if canal not in config.CANALES:
        raise ValueError("Canal desconocido: {}".format(canal))
    if estado not in config.ESTADOS_AUTORIZACION:
        raise ValueError("Estado desconocido: {}. Válidos: {}".format(
            estado, ", ".join(config.ESTADOS_AUTORIZACION)))


def leer(cuenta_id):
    """Estado de cada canal para un titular.

    Devuelve los cuatro canales siempre: los que no tienen fila se reportan como
    DESCONOCIDO, para que quien consulte no tenga que distinguir entre "no hay
    dato" y "no autorizó".
    """
    bd.crear_esquema()
    with bd.obtener_motor().connect() as conexion:
        filas = conexion.execute(select(
            bd.autorizaciones_canal.c.canal, bd.autorizaciones_canal.c.estado,
            bd.autorizaciones_canal.c.origen, bd.autorizaciones_canal.c.actualizado,
            bd.autorizaciones_canal.c.actualizado_por
        ).where(bd.autorizaciones_canal.c.cuenta_id == cuenta_id)).fetchall()
    registradas = {f.canal: {"estado": f.estado, "origen": f.origen,
                             "actualizado": f.actualizado, "actualizado_por": f.actualizado_por}
                   for f in filas}
    return {canal: registradas.get(canal, {"estado": "DESCONOCIDO", "origen": None,
                                           "actualizado": None, "actualizado_por": None})
            for canal in sorted(config.CANALES)}


def registrar(cuenta_id, canal, estado, usuario, origen="GESTOR"):
    """Registra o cambia la autorización de un canal y actualiza la cartera.

    Se guarda incluso el NO_AUTORIZADO explícito: no es lo mismo que el titular
    haya dicho que no a que nunca se le haya preguntado, y esa diferencia es la
    que la entidad tiene que poder demostrar.
    """
    _validar(canal, estado)
    bd.crear_esquema()
    ahora = config.ahora()
    with bd.obtener_motor().begin() as conexion:
        condicion = ((bd.autorizaciones_canal.c.cuenta_id == cuenta_id) &
                     (bd.autorizaciones_canal.c.canal == canal))
        cambiadas = conexion.execute(update(bd.autorizaciones_canal).where(condicion).values(
            estado=estado, origen=origen, actualizado=ahora,
            actualizado_por=usuario[:40])).rowcount
        if not cambiadas:
            conexion.execute(insert(bd.autorizaciones_canal).values(
                cuenta_id=cuenta_id, canal=canal, estado=estado, origen=origen,
                actualizado=ahora, actualizado_por=usuario[:40]))
        _refrescar(conexion, [cuenta_id])

    bd.registrar_evento(usuario, "AUTORIZACION_CANAL",
                        "titular {} · canal {} · {} ({})".format(cuenta_id, canal, estado, origen))
    return leer(cuenta_id)


def _refrescar(conexion, cuentas):
    """Recalcula las columnas derivadas de cartera para esos titulares.

    Una sola consulta trae las autorizaciones de todos, y después se actualiza
    canal por canal en bloques: son cuatro sentencias por bloque en lugar de
    cuatro por titular, que contra una base en la nube es la diferencia entre
    segundos y minutos.
    """
    cuentas = list(dict.fromkeys(cuentas))
    if not cuentas:
        return
    autorizadas = {canal: set() for canal in config.CANALES}
    for inicio in range(0, len(cuentas), 1000):
        lote = cuentas[inicio:inicio + 1000]
        filas = conexion.execute(select(
            bd.autorizaciones_canal.c.cuenta_id, bd.autorizaciones_canal.c.canal
        ).where(bd.autorizaciones_canal.c.cuenta_id.in_(lote),
                bd.autorizaciones_canal.c.estado == "AUTORIZADO")).fetchall()
        for fila in filas:
            autorizadas[fila.canal].add(fila.cuenta_id)

    for inicio in range(0, len(cuentas), 1000):
        lote = cuentas[inicio:inicio + 1000]
        for canal, columna in config.COLUMNA_AUTORIZACION.items():
            con_permiso = [c for c in lote if c in autorizadas[canal]]
            sin_permiso = [c for c in lote if c not in autorizadas[canal]]
            for cuentas_lote, valor in ((con_permiso, True), (sin_permiso, False)):
                if cuentas_lote:
                    conexion.execute(update(bd.cartera).where(
                        bd.cartera.c.cuenta_id.in_(cuentas_lote)).values(**{columna: valor}))


def recalcular(carga_id, usuario="sistema"):
    """Vuelve a calcular las columnas derivadas de toda una carga."""
    bd.crear_esquema()
    with bd.obtener_motor().begin() as conexion:
        cuentas = conexion.execute(select(bd.cartera.c.cuenta_id).where(
            bd.cartera.c.carga_id == carga_id).distinct()).scalars().all()
        _refrescar(conexion, cuentas)
    return len(cuentas)


# ---------------------------------------------------------------------------
# SIMULACIÓN PARA CARTERAS SINTÉTICAS
# ---------------------------------------------------------------------------
# Una cartera simulada tiene que traer también autorizaciones simuladas: sin
# ellas, al encender EXIGIR_AUTORIZACION_CANAL el motor bloquearía todo.
#
# El sorteo no usa un generador aleatorio: deriva de un hash del titular y del
# canal, así que es estable. La misma cartera produce siempre las mismas
# autorizaciones, en cualquier equipo y las veces que se repita, que es la misma
# propiedad que ya tiene el simulador de carteras.

def _sorteo(cuenta_id, canal):
    """Número entre 0 y 1, estable para ese titular y ese canal."""
    firma = hashlib.sha256("{}|{}".format(cuenta_id, canal).encode("utf-8")).hexdigest()
    return int(firma[:8], 16) / 0xFFFFFFFF


def simular(carga_id, usuario="sistema"):
    """Genera autorizaciones simuladas para los titulares de una carga.

    Solo sortea los canales para los que el titular tiene dato de contacto: no
    tendría sentido registrar que autorizó el correo si no se le conoce ninguno.
    Los demás quedan sin fila, es decir, DESCONOCIDO.

    No sobrescribe lo que ya exista: si un gestor registró la autorización real
    de un titular, una simulación posterior no la deshace.
    """
    bd.crear_esquema()
    cartera = bd.leer_cartera(carga_id)
    if cartera.empty:
        raise LookupError("La carga {} no tiene cuentas.".format(carga_id))

    datos = cartera.drop_duplicates("cuenta_id")[
        ["cuenta_id", "tiene_celular", "tiene_fijo", "tiene_email"]]
    disponible = {
        "CELULAR": set(datos.loc[datos["tiene_celular"] == True, "cuenta_id"]),   # noqa: E712
        "FIJO": set(datos.loc[datos["tiene_fijo"] == True, "cuenta_id"]),         # noqa: E712
        "EMAIL": set(datos.loc[datos["tiene_email"] == True, "cuenta_id"]),       # noqa: E712
    }

    ahora = config.ahora()
    filas = []
    for cuenta_id in datos["cuenta_id"]:
        for canal, requisitos in config.REQUISITO_CANAL.items():
            if not any(cuenta_id in disponible[r] for r in requisitos):
                continue
            autoriza = _sorteo(cuenta_id, canal) < config.AUTORIZACION_SIMULADA[canal]
            filas.append({"cuenta_id": cuenta_id, "canal": canal,
                          "estado": "AUTORIZADO" if autoriza else "NO_AUTORIZADO",
                          "origen": "CARGA", "actualizado": ahora,
                          "actualizado_por": usuario[:40]})

    cuentas = datos["cuenta_id"].tolist()
    with bd.obtener_motor().begin() as conexion:
        ya_registradas = set()
        for inicio in range(0, len(cuentas), 1000):
            lote = cuentas[inicio:inicio + 1000]
            ya_registradas.update(tuple(f) for f in conexion.execute(select(
                bd.autorizaciones_canal.c.cuenta_id, bd.autorizaciones_canal.c.canal
            ).where(bd.autorizaciones_canal.c.cuenta_id.in_(lote))))

        nuevas = [f for f in filas if (f["cuenta_id"], f["canal"]) not in ya_registradas]
        for inicio in range(0, len(nuevas), 1000):
            conexion.execute(insert(bd.autorizaciones_canal), nuevas[inicio:inicio + 1000])
        _refrescar(conexion, cuentas)

    bd.registrar_evento(usuario, "AUTORIZACION_SIMULADA",
                        "carga {} · {} autorizaciones nuevas sobre {} titulares".format(
                            carga_id, len(nuevas), len(cuentas)))
    return len(nuevas), len(cuentas)


def borrar(cuenta_id, usuario="sistema"):
    """Elimina las autorizaciones de un titular y deja sus canales en False.

    Se usa cuando el titular revoca todo o cuando hay que corregir un registro
    equivocado. La constancia de que existieron queda en la auditoría.
    """
    bd.crear_esquema()
    with bd.obtener_motor().begin() as conexion:
        borradas = conexion.execute(delete(bd.autorizaciones_canal).where(
            bd.autorizaciones_canal.c.cuenta_id == cuenta_id)).rowcount
        _refrescar(conexion, [cuenta_id])
    bd.registrar_evento(usuario, "AUTORIZACION_BORRADA",
                        "titular {} · {} canales".format(cuenta_id, borradas))
    return borradas


def resumen(carga_id):
    """Cuántos titulares de la carga autorizan cada canal."""
    bd.crear_esquema()
    cartera = bd.leer_cartera(carga_id)
    if cartera.empty:
        raise LookupError("La carga {} no tiene cuentas.".format(carga_id))
    titulares = cartera.drop_duplicates("cuenta_id")["cuenta_id"]
    total = len(titulares)

    with bd.obtener_motor().connect() as conexion:
        filas = conexion.execute(select(
            bd.autorizaciones_canal.c.cuenta_id, bd.autorizaciones_canal.c.canal,
            bd.autorizaciones_canal.c.estado
        ).where(bd.autorizaciones_canal.c.cuenta_id.in_(titulares.tolist()))).fetchall()

    registradas = pd.DataFrame(filas, columns=["cuenta_id", "canal", "estado"])
    salida = []
    for canal in sorted(config.CANALES):
        del_canal = registradas[registradas["canal"] == canal] if not registradas.empty \
            else registradas
        autorizados = int((del_canal["estado"] == "AUTORIZADO").sum()) if not del_canal.empty else 0
        negados = int((del_canal["estado"] == "NO_AUTORIZADO").sum()) if not del_canal.empty else 0
        salida.append({"canal": canal, "autorizado": autorizados, "no_autorizado": negados,
                       "desconocido": total - autorizados - negados,
                       "porcentaje_autorizado": autorizados / total if total else 0})
    return pd.DataFrame(salida)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--carga", type=int, required=True)
    parser.add_argument("--simular", action="store_true",
                        help="genera autorizaciones simuladas para los titulares sin registro")
    parser.add_argument("--recalcular", action="store_true",
                        help="vuelve a calcular las columnas derivadas de la cartera")
    parser.add_argument("--resumen", action="store_true")
    parser.add_argument("--confirmar-remota", action="store_true",
                        help="confirma que se quiere escribir en una base que no es la local")
    args = parser.parse_args()

    print("Base de datos: {}".format(bd.describir_motor()))
    # Consultar el resumen no escribe nada; simular y recalcular sí.
    if (args.simular or args.recalcular) and not bd.confirmar_escritura_remota(
            "modificar las autorizaciones de la carga {}".format(args.carga), args.confirmar_remota):
        raise SystemExit(2)

    if args.simular:
        nuevas, titulares = simular(args.carga, usuario="terminal")
        print("Carga {}: {:,} autorizaciones nuevas sobre {:,} titulares.".format(
            args.carga, nuevas, titulares))
    if args.recalcular:
        print("Carga {}: {:,} titulares recalculados.".format(
            args.carga, recalcular(args.carga, usuario="terminal")))
    if args.resumen or not (args.simular or args.recalcular):
        tabla = resumen(args.carga)
        print("\n  {:<10} {:>12} {:>15} {:>13} {:>10}".format(
            "Canal", "Autorizado", "No autorizado", "Desconocido", "% del total"))
        for fila in tabla.to_dict("records"):
            print("  {:<10} {:>12,} {:>15,} {:>13,} {:>9.1%}".format(
                fila["canal"], fila["autorizado"], fila["no_autorizado"],
                fila["desconocido"], fila["porcentaje_autorizado"]))
