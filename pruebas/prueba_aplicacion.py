# -*- coding: utf-8 -*-
"""
Prueba automática de la aplicación web, sin navegador.

Usa el simulador de Streamlit (AppTest) para abrir cada pantalla como la vería
un usuario de cada rol y comprueba que:
  * ninguna pantalla falla al cargarse;
  * cada rol solo puede abrir las pantallas que su permiso autoriza;
  * el ingreso rechaza una contraseña errónea y acepta la correcta.

Crea sus propios usuarios de prueba con contraseñas aleatorias, y por eso debe
correr contra una base desechable: la temporal de GitHub Actions o una SQLite
local. Nunca contra la base del proyecto en Supabase.

Streamlit imprime avisos de "missing ScriptRunContext" al usar la caché fuera
de un servidor. Son esperados en esta prueba y no indican ningún error.

Uso:
    python -m pruebas.prueba_aplicacion
"""

import secrets
import sys

from streamlit.testing.v1 import AppTest

import config
from datos import base_datos as bd
from seguridad import autenticacion as auth

if "supabase" in config.URL_BASE_DATOS:
    print("Esta prueba crea usuarios ficticios: no se ejecuta contra Supabase.")
    sys.exit(1)

PAGINAS = {
    "tablero": "ver_tablero", "cartera": "ver_cartera", "motor": "ver_motor",
    "conocimiento": "ver_conocimiento", "cargas": "gestionar_cargas",
    "usuarios": "gestionar_usuarios", "auditoria": "ver_auditoria", "mi_cuenta": None,
}
TIEMPO = 120   # segundos máximos por pantalla
# AppTest interpreta las rutas relativas desde este archivo, no desde la raíz.
APP = config.RAIZ / "app"


def asegurar_datos():
    """Garantiza al menos una carga y una ejecución del motor para mostrar."""
    if bd.listar_cargas().empty:
        from datos.cargador import cargar
        from datos.generador import generar
        from datos.perfilador import cargar_perfil
        bd.registrar_carga(cargar(bruto=generar(cargar_perfil(), n=800, semilla=3)),
                           "SINTETICO", "prueba_aplicacion", semilla=3)
    if bd.listar_ejecuciones(1).empty:
        from motor.elegibilidad import ejecutar
        ejecutar(usuario="prueba_aplicacion")


def usuario_de_prueba(rol):
    usuario = "prueba.{}.{}".format(rol.lower(), secrets.token_hex(3))
    clave = "Clave" + secrets.token_urlsafe(12) + "7"
    auth.crear_usuario(usuario, "Prueba " + rol.capitalize(), rol, clave, "prueba_aplicacion")
    return usuario, clave


def abrir(pagina, usuario):
    prueba = AppTest.from_file(str(APP / "paginas" / "{}.py".format(pagina)), default_timeout=TIEMPO)
    prueba.session_state["usuario"] = usuario
    prueba.session_state["ultima_actividad"] = config.ahora()
    prueba.session_state["ultima_revalidacion"] = config.ahora()
    return prueba.run()


def prueba_ingreso():
    usuario, clave = usuario_de_prueba("GESTOR")
    app = AppTest.from_file(str(APP / "principal.py"), default_timeout=TIEMPO).run()
    app.text_input[0].input(usuario)
    app.text_input[1].input("ContraseniaErronea123")
    app.button[0].click().run()
    assert any("incorrectos" in e.value for e in app.error), "no rechazó la contraseña errónea"

    app.text_input[1].input(clave)
    app.button[0].click().run()
    assert not app.exception, app.exception
    assert app.session_state["usuario"]["usuario"] == usuario, "no inició la sesión"
    print("  Ingreso: rechaza la clave errónea y acepta la correcta")


if __name__ == "__main__":
    bd.crear_esquema()
    asegurar_datos()
    prueba_ingreso()

    fallas = 0
    for rol in auth.ROLES:
        usuario, _ = usuario_de_prueba(rol)
        sesion = {"usuario": usuario, "nombre": "Prueba", "rol": rol, "ultimo_ingreso": None}
        for pagina, permiso in PAGINAS.items():
            resultado = abrir(pagina, sesion)
            permitido = permiso is None or auth.puede(rol, permiso)
            denegado = any("No tiene permiso" in e.value for e in resultado.error)
            ok = not resultado.exception and denegado != permitido
            fallas += not ok
            print("  {:<13} {:<13} {:<9} {}".format(
                rol, pagina, "permitida" if permitido else "denegada",
                "OK" if ok else "FALLA {}".format(
                    [e.value for e in resultado.exception] or "control de acceso")))
    if fallas:
        print("{} verificaciones fallaron".format(fallas))
        sys.exit(1)
    print("Todas las pantallas y permisos verificados.")
