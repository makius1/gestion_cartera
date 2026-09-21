# -*- coding: utf-8 -*-
"""
Prueba del registro de obligaciones nuevas desde la aplicación (issue #17).

Cubre los tres criterios de aceptación del issue —tipos y formatos, misma
seudonimización que la carga, registro en auditoría— más los puntos donde
este registro podría dejar una cuenta en un estado que el resto del sistema
no sabe interpretar: sin eso, "no revienta nada" es una promesa sin probar.

Registra obligaciones y titulares de prueba: nunca corre contra la base del
proyecto en Supabase.

Uso:
    python -m pruebas.prueba_obligaciones
"""

import sys
from datetime import date

from sqlalchemy import insert, select

import config
from datos import base_datos as bd
from datos.cargador import _seudonimo
from gestion import obligaciones as ob

if "supabase" in config.URL_BASE_DATOS:
    print("Esta prueba crea obligaciones y titulares ficticios: no se ejecuta contra Supabase.")
    sys.exit(1)


def _carga_de_prueba():
    """Una carga vacía dedicada a estas pruebas, para no interferir con
    cargas reales ni con las de otras pruebas."""
    with bd.obtener_motor().begin() as conexion:
        carga_id = conexion.execute(insert(bd.cargas).values(
            fecha_carga=config.ahora(), origen="SINTETICO", archivo="prueba_obligaciones",
            registros=0, saldo_total=0, meta_recaudo=0, semilla=None)).inserted_primary_key[0]
    return carga_id


def _datos(**cambios):
    base = {
        "documento": "1015900001", "credito": "PRUEBA-0001", "nombre": "Titular de Prueba",
        "ciudad": "Bogotá", "producto": "LIBRE INVERSION", "codigo": "POSIBLE LOCALIZACION",
        "saldo": 1_200_000, "cobranza_min": 400_000, "cobranza_max": 900_000, "dias_mora": 145,
    }
    base.update(cambios)
    return base


def prueba_validaciones_rechazan_datos_malos():
    """Los mismos tipos y formatos que exige la carga (criterio 1 del issue)."""
    casos = [
        (dict(documento="abc"), "documento con letras"),
        (dict(credito="a"), "número de obligación demasiado corto"),
        (dict(saldo=-1), "saldo negativo"),
        (dict(cobranza_min=900_000, cobranza_max=400_000), "cobranza máxima menor que la mínima"),
        (dict(dias_mora=-5), "días de mora negativos"),
        (dict(nombre=""), "nombre vacío"),
        (dict(ciudad=""), "ciudad vacía"),
        (dict(codigo="CODIGO_QUE_NO_EXISTE"), "código fuera del catálogo"),
    ]
    for cambios, motivo in casos:
        errores = ob.validar(_datos(**cambios))
        assert errores, "no se detectó: {}".format(motivo)
    print("  Validación: cada dato mal formado se rechaza ({} casos)".format(len(casos)))


def prueba_registro_completo():
    """La cuenta queda en cartera con la misma seudonimización y las mismas
    reglas de franja y rango de mora que produciría la carga (criterio 2)."""
    carga_id = _carga_de_prueba()
    datos = _datos(documento="1015900002", credito="PRUEBA-0002")
    credito_id = ob.registrar_obligacion(carga_id, datos, [("CELULAR", "3011234567")], "prueba.obligaciones")

    assert credito_id == _seudonimo("PRUEBA-0002", "K"), "el seudónimo no coincide con el de la carga"

    fila = bd.leer_cartera(carga_id).set_index("credito_id").loc[credito_id]
    assert fila["cuenta_id"] == _seudonimo("1015900002", "C")
    assert fila["franja"] == "DE 700 MIL A 1 MILLON"     # cobranza_max = 900.000, misma regla de franja()
    assert fila["rango_mora"] == "De 140 a 399"           # dias_mora = 145, misma regla de _rango_mora()
    assert bool(fila["tiene_celular"]) and not bool(fila["tiene_fijo"])
    assert fila["canales_disponibles"] == 1
    assert bool(fila["gestionable"]) and not bool(fila["gestionada"])

    with bd.obtener_motor().connect() as conexion:
        titular = conexion.execute(select(bd.titulares).where(
            bd.titulares.c.cuenta_id == fila["cuenta_id"])).first()
    assert titular.documento_enmascarado == "******0002"
    print("  Registro: seudonimización, franja y rango de mora quedan iguales que en una carga")


def prueba_queda_en_auditoria():
    """El registro queda en la auditoría (criterio 3)."""
    carga_id = _carga_de_prueba()
    credito_id = ob.registrar_obligacion(carga_id, _datos(documento="1015900003", credito="PRUEBA-0003"), [],
                                         "prueba.obligaciones")
    with bd.obtener_motor().connect() as conexion:
        evento = conexion.execute(select(bd.auditoria).where(
            bd.auditoria.c.accion == "OBLIGACION_NUEVA",
            bd.auditoria.c.detalle.like("%{}%".format(credito_id)))).first()
    assert evento is not None, "no quedó registro en auditoria"
    print("  Auditoría: el registro de la obligación queda en la bitácora")


def prueba_no_permite_duplicar_credito():
    """El mismo crédito no se puede registrar dos veces en la misma carga."""
    carga_id = _carga_de_prueba()
    datos = _datos(documento="1015900004", credito="PRUEBA-0004")
    ob.registrar_obligacion(carga_id, datos, [], "prueba.obligaciones")
    try:
        ob.registrar_obligacion(carga_id, datos, [], "prueba.obligaciones")
        raise AssertionError("dejó registrar el mismo crédito dos veces")
    except ValueError as error:
        assert "ya está registrada" in str(error)
    print("  Duplicados: el mismo crédito no se puede registrar dos veces en la misma carga")


def prueba_motor_no_bloquea_por_datos_incompletos():
    """Sin contactos, el motor evalúa la cuenta (no la bloquea por L3): cero
    contactos es un hecho conocido, no un dato que falta."""
    from motor import elegibilidad as motorleg

    carga_id = _carga_de_prueba()
    credito_id = ob.registrar_obligacion(carga_id, _datos(documento="1015900005", credito="PRUEBA-0005"), [],
                                         "prueba.obligaciones")
    _, resultado = motorleg.ejecutar(carga_id, fecha_objetivo=date(2026, 9, 15),
                                     usuario="prueba.obligaciones", guardar=False)
    fila = resultado[resultado["credito_id"] == credito_id].iloc[0]
    assert fila["regla_determinante"] != "L3", \
        "una obligación sin contactos quedó bloqueada por datos incompletos, no por falta de canales"
    print("  Motor: una obligación recién creada, incluso sin contactos, se evalúa (no queda "
          "bloqueada por L3)")


def prueba_titular_con_otro_credito_comparte_contacto():
    """Dos obligaciones de la misma persona, con el mismo celular: la segunda
    no debe fallar por "contacto duplicado", y ambas quedan con el canal."""
    carga_id = _carga_de_prueba()
    documento = "1015900006"
    ob.registrar_obligacion(carga_id, _datos(documento=documento, credito="PRUEBA-0006-A"),
                            [("CELULAR", "3021234567")], "prueba.obligaciones")
    credito_id_b = ob.registrar_obligacion(carga_id, _datos(documento=documento, credito="PRUEBA-0006-B"),
                                           [("CELULAR", "3021234567")], "prueba.obligaciones")

    fila_b = bd.leer_cartera(carga_id).set_index("credito_id").loc[credito_id_b]
    assert bool(fila_b["tiene_celular"]), \
        "la segunda obligación no quedó con el canal que ya tenía el titular"
    print("  Titular repetido: dos créditos con el mismo contacto no chocan entre sí")


def prueba_contacto_invalido_no_deja_nada_a_medias():
    """Un contacto mal formado, aunque venga después de uno válido en la
    lista, rechaza el registro completo: no debe quedar ni la cuenta ni el
    titular guardados a medias (antes se guardaban primero y se agregaban
    los contactos después, en pasos separados)."""
    carga_id = _carga_de_prueba()
    datos = _datos(documento="1015900007", credito="PRUEBA-0007")
    try:
        ob.registrar_obligacion(carga_id, datos, [("CELULAR", "3001112233"), ("EMAIL", "no-es-un-correo")],
                                "prueba.obligaciones")
        raise AssertionError("dejó registrar con un contacto inválido en la lista")
    except ValueError:
        pass

    credito_id = _seudonimo("PRUEBA-0007", "K")
    cuenta_id = _seudonimo("1015900007", "C")
    assert credito_id not in bd.leer_cartera(carga_id)["credito_id"].values, \
        "la cuenta quedó registrada a pesar del contacto inválido"
    with bd.obtener_motor().connect() as conexion:
        titular = conexion.execute(select(bd.titulares).where(
            bd.titulares.c.cuenta_id == cuenta_id)).first()
    assert titular is None, "el titular quedó registrado a pesar del contacto inválido"
    print("  Atomicidad: un contacto inválido no deja la cuenta ni el titular a medias")


if __name__ == "__main__":
    bd.crear_esquema()
    prueba_validaciones_rechazan_datos_malos()
    prueba_registro_completo()
    prueba_queda_en_auditoria()
    prueba_no_permite_duplicar_credito()
    prueba_motor_no_bloquea_por_datos_incompletos()
    prueba_titular_con_otro_credito_comparte_contacto()
    prueba_contacto_invalido_no_deja_nada_a_medias()
    print("Obligaciones nuevas verificadas.")
