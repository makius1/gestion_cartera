# -*- coding: utf-8 -*-
"""
Prueba de la reserva de cuentas de "Siguiente cuenta" (issue #16).

Cubre lo que una prueba secuencial no puede probar: que dos gestores que
piden la cola general en el mismo instante reciben cuentas distintas. Para
eso lanza dos hilos con una barrera que los suelta al mismo tiempo, cada uno
con su propia conexión a la base — una prueba llamada una vez tras otra no
ejercita la condición de carrera que el issue describe.

Corre contra la base configurada en DATABASE_URL. Contra SQLite local puede
fallar por "database is locked" si el archivo no tiene un tiempo de espera
generoso: la integración continua la corre contra PostgreSQL real (ver
.github/workflows/pruebas.yml), que es donde esta prueba importa.

Uso:
    python -m pruebas.prueba_reservas
"""

import sys
import threading
from datetime import timedelta

from sqlalchemy import update

import config
from datos import base_datos as bd

# Esta prueba escribe: reserva cuentas, registra una gestión y, si la base está
# vacía, crea una carga. Contra la base compartida dejaría datos de prueba
# mezclados con los del equipo, así que se niega a correr ahí, igual que
# prueba_aplicacion.py.
if "supabase" in config.URL_BASE_DATOS:
    print("Esta prueba registra gestiones de prueba: no se ejecuta contra Supabase.")
    sys.exit(1)


def _carga_de_prueba():
    """Una carga con al menos dos cuentas, reutilizando la más reciente si
    ya existe (la deja crear_esquema/prueba_aplicacion, no la duplica)."""
    cargas = bd.listar_cargas()
    if cargas.empty:
        from datos.cargador import cargar
        from datos.generador import generar
        from datos.perfilador import cargar_perfil
        bd.registrar_carga(cargar(bruto=generar(cargar_perfil(), n=50, semilla=11)),
                           "SINTETICO", "prueba_reservas", semilla=11)
        cargas = bd.listar_cargas()
    carga_id = int(cargas.iloc[0]["id"])
    credito_id = bd.leer_cartera(carga_id).iloc[0]["credito_id"]
    return carga_id, credito_id


def prueba_concurrencia_real():
    """Dos hilos reservando la MISMA cuenta al mismo tiempo: solo uno gana."""
    carga_id, credito_id = _carga_de_prueba()
    bd.liberar_reservas_de("prueba.reservas.a")
    bd.liberar_reservas_de("prueba.reservas.b")
    bd.liberar_reserva(carga_id, credito_id)

    salida = threading.Barrier(2)
    resultados = {}

    def intentar(gestor):
        salida.wait()   # los dos hilos reservan en el mismo instante
        resultados[gestor] = bd.reservar_cuenta(carga_id, credito_id, gestor, minutos=20)

    hilos = [threading.Thread(target=intentar, args=(g,))
             for g in ("prueba.reservas.a", "prueba.reservas.b")]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    ganadores = [g for g, gano in resultados.items() if gano]
    assert len(ganadores) == 1, "los dos gestores reservaron la misma cuenta: {}".format(resultados)
    print("  Concurrencia: de dos gestores pidiendo la misma cuenta a la vez, solo uno la reserva")


def prueba_cola_reparte_distinto():
    """Dos gestores sin plan piden la cola general al mismo tiempo (G9 del
    plan de pruebas): deben recibir cuentas distintas."""
    from gestion import operacion as op

    carga_id, _ = _carga_de_prueba()
    priorizaciones = bd.listar_priorizaciones(200)
    priorizaciones = priorizaciones[priorizaciones["carga_id"] == carga_id]
    if priorizaciones.empty:
        print("  Cola: se omite (no hay priorización para la carga de prueba)")
        return

    for g in ("prueba.reservas.c", "prueba.reservas.d"):
        bd.liberar_reservas_de(g)

    salida = threading.Barrier(2)
    resultados = {}

    def pedir(gestor):
        salida.wait()
        credito, _ = op.siguiente_de_la_cola(carga_id, gestor)
        resultados[gestor] = credito

    hilos = [threading.Thread(target=pedir, args=(g,))
             for g in ("prueba.reservas.c", "prueba.reservas.d")]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    creditos = [c for c in resultados.values() if c is not None]
    assert len(creditos) == len(set(creditos)), \
        "dos gestores recibieron la misma cuenta de la cola: {}".format(resultados)
    print("  Cola general: dos gestores sin plan piden a la vez y reciben cuentas distintas")


def prueba_reserva_vencida():
    """Una reserva vencida se puede tomar; una vigente, no.

    reservar_cuenta() protege una reserva vigente incluso contra el propio
    gestor que la tiene (el UPDATE solo entra si `vence < ahora`), así que no
    hay forma de "adelantar" el vencimiento llamándola de nuevo con menos
    minutos. Para simular que pasó el tiempo, la prueba mueve `vence` al
    pasado directamente en la base, sin pasar por reservar_cuenta.
    """
    carga_id, credito_id = _carga_de_prueba()
    bd.liberar_reserva(carga_id, credito_id)

    assert bd.reservar_cuenta(carga_id, credito_id, "prueba.reservas.e", minutos=20), \
        "no se pudo tomar una cuenta libre"
    assert not bd.reservar_cuenta(carga_id, credito_id, "prueba.reservas.f", minutos=20), \
        "una reserva vigente de otro gestor se pudo robar"

    motor = bd.obtener_motor()
    with motor.begin() as conexion:
        conexion.execute(update(bd.reservas).where(
            bd.reservas.c.carga_id == carga_id, bd.reservas.c.credito_id == credito_id
        ).values(vence=config.ahora() - timedelta(minutes=1)))

    assert bd.reservar_cuenta(carga_id, credito_id, "prueba.reservas.f", minutos=20), \
        "una reserva vencida no se pudo tomar"
    print("  Vencimiento: una reserva vigente bloquea a otro gestor; una vencida se puede tomar")

    bd.liberar_reserva(carga_id, credito_id)


def prueba_libera_al_gestionar():
    """registrar_gestion libera la reserva en la misma transacción."""
    from gestion import operacion as op

    carga_id, credito_id = _carga_de_prueba()
    bd.liberar_reserva(carga_id, credito_id)
    bd.reservar_cuenta(carga_id, credito_id, "prueba.reservas.g", minutos=20)

    fila = bd.leer_cartera(carga_id).set_index("credito_id").loc[credito_id].to_dict()
    decision = op.estado_hoy(fila)
    datos = {
        "canal": "LLAMADA", "sentido": "ENTRANTE", "resultado": "CONTACTO_TITULAR",
        "codigo": "CONTACTO SIN ACUERDO", "motivo_no_pago": None, "valor_acordado": None,
        "fecha_compromiso": None, "fecha_proxima_gestion": None,
        "observacion": "Prueba automática de liberación de reserva.",
    }
    op.registrar(carga_id, credito_id, datos, "prueba.reservas.g")

    assert bd.reserva_vigente_de(carga_id, credito_id) is None, \
        "la reserva siguió vigente después de registrar la gestión"
    print("  Liberación: registrar la gestión libera la reserva de la cuenta")


if __name__ == "__main__":
    bd.crear_esquema()
    prueba_concurrencia_real()
    prueba_cola_reparte_distinto()
    prueba_reserva_vencida()
    prueba_libera_al_gestionar()
    print("Reservas de cuenta verificadas.")
