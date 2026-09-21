# -*- coding: utf-8 -*-
"""
Prueba de la autorización por canal (issue #25, Ley 2300 artículo 2).

Comprueba las tres cosas de las que depende el motor:

  * que una cartera simulada quede con autorizaciones, y solo en los canales
    para los que el titular tiene dato de contacto;
  * que las columnas derivadas de `cartera` reflejen exactamente la tabla, que
    es lo que el motor va a leer;
  * que registrar o revocar una autorización cambie esas columnas y quede en la
    auditoría.

Escribe en la base, así que no corre contra Supabase.

Uso:
    python -m pruebas.prueba_autorizaciones
"""

import sys

import config
from datos import autorizaciones as az
from datos import base_datos as bd

if "supabase" in config.URL_BASE_DATOS:
    print("Esta prueba registra autorizaciones de prueba: no se ejecuta contra Supabase.")
    sys.exit(1)


def carga_de_prueba():
    """Reutiliza la carga más reciente; si no hay ninguna, simula una pequeña."""
    cargas = bd.listar_cargas()
    if cargas.empty:
        from datos.cargador import cargar
        from datos.generador import generar
        from datos.perfilador import cargar_perfil
        bd.registrar_carga(cargar(bruto=generar(cargar_perfil(), n=200, semilla=13)),
                           "SINTETICO", "prueba_autorizaciones", semilla=13)
        cargas = bd.listar_cargas()
    return int(cargas.iloc[0]["id"])


def prueba_simulacion(carga_id):
    """Simular deja autorizaciones solo donde hay dato de contacto."""
    az.simular(carga_id, usuario="prueba.autorizaciones")
    cartera = bd.leer_cartera(carga_id).drop_duplicates("cuenta_id")

    sin_celular = cartera[cartera["tiene_celular"] != True]              # noqa: E712
    if not sin_celular.empty:
        cuenta = sin_celular.iloc[0]["cuenta_id"]
        estados = az.leer(cuenta)
        assert estados["SMS"]["estado"] == "DESCONOCIDO", \
            "se registró autorización de SMS a un titular sin celular"
        assert estados["WHATSAPP"]["estado"] == "DESCONOCIDO", \
            "se registró autorización de WhatsApp a un titular sin celular"

    tabla = az.resumen(carga_id)
    assert (tabla["autorizado"] > 0).all(), "algún canal quedó sin ninguna autorización"
    print("  Simulación: {} canales con autorizaciones, solo donde hay dato de contacto".format(
        len(tabla)))


def prueba_columnas_derivadas(carga_id):
    """Las columnas de cartera reflejan la tabla: es lo que lee el motor."""
    cartera = bd.leer_cartera(carga_id).drop_duplicates("cuenta_id")
    revisadas = 0
    for fila in cartera.head(25).to_dict("records"):
        estados = az.leer(fila["cuenta_id"])
        for canal, columna in config.COLUMNA_AUTORIZACION.items():
            esperado = estados[canal]["estado"] == "AUTORIZADO"
            assert bool(fila[columna]) == esperado, \
                "{} de {}: tabla dice {} y la columna {}".format(
                    canal, fila["cuenta_id"], estados[canal]["estado"], fila[columna])
        revisadas += 1
    print("  Columnas derivadas: {} titulares con sus 4 canales coincidiendo".format(revisadas))


def prueba_registro_y_revocacion(carga_id):
    """Autorizar y revocar cambian la columna que lee el motor."""
    cuenta = bd.leer_cartera(carga_id).iloc[0]["cuenta_id"]
    columna = config.COLUMNA_AUTORIZACION["EMAIL"]

    def valor_en_cartera():
        cartera = bd.leer_cartera(carga_id)
        return bool(cartera[cartera["cuenta_id"] == cuenta].iloc[0][columna])

    az.registrar(cuenta, "EMAIL", "AUTORIZADO", "prueba.autorizaciones", origen="TITULAR")
    assert valor_en_cartera(), "autorizar no encendió la columna de cartera"

    az.registrar(cuenta, "EMAIL", "NO_AUTORIZADO", "prueba.autorizaciones", origen="TITULAR")
    assert not valor_en_cartera(), "revocar no apagó la columna de cartera"

    acciones = bd.leer_auditoria(10)["accion"].tolist()
    assert "AUTORIZACION_CANAL" in acciones, "el cambio no quedó en la auditoría"
    print("  Registro: autorizar y revocar mueven la columna y quedan en la auditoría")


def prueba_canal_invalido():
    """Un canal o un estado que no existen se rechazan antes de escribir."""
    for canal, estado in (("PALOMA", "AUTORIZADO"), ("EMAIL", "QUIZAS")):
        try:
            az.registrar("C0000000", canal, estado, "prueba.autorizaciones")
        except ValueError:
            continue
        raise AssertionError("se aceptó {} / {}".format(canal, estado))
    print("  Validación: se rechazan los canales y los estados desconocidos")


if __name__ == "__main__":
    bd.crear_esquema()
    carga = carga_de_prueba()
    prueba_simulacion(carga)
    prueba_columnas_derivadas(carga)
    prueba_registro_y_revocacion(carga)
    prueba_canal_invalido()
    print("Autorización por canal verificada.")
