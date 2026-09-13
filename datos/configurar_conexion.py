# -*- coding: utf-8 -*-
"""
Configuración asistida de la conexión a la base de datos externa.

Toma la cadena de conexión tal como la entrega Supabase, con el marcador
[YOUR-PASSWORD], pide la contraseña sin mostrarla en pantalla y guarda la
cadena completa en el archivo .env. Resuelve de una vez los tres errores más
comunes al conectar:

  * Contraseñas con caracteres especiales (@ : / ? # % & + =) que rompen la
    cadena si no se codifican para URL.
  * Uso de la conexión directa, que en el plan gratuito solo funciona por IPv6
    y falla desde GitHub Actions y Codespaces.
  * Falta del parámetro que exige conexión cifrada.

La contraseña nunca se imprime, no queda en el historial de la terminal y solo
se escribe en .env, que está excluido del repositorio.

Uso:
    python -m datos.configurar_conexion
"""

import getpass
import re
import urllib.parse

import config

MARCADOR = "[YOUR-PASSWORD]"
RUTA_ENV = config.RAIZ / ".env"


def analizar(uri):
    """Revisa la cadena y retorna una lista de problemas y advertencias.

    Cada elemento es (nivel, mensaje), con nivel "error" o "aviso". Un error
    impide continuar; un aviso se muestra y se pide confirmación.
    """
    hallazgos = []
    partes = urllib.parse.urlsplit(uri)

    if partes.scheme not in ("postgresql", "postgres"):
        hallazgos.append(("error", "La cadena debe empezar por postgresql://"))
        return hallazgos

    if MARCADOR not in uri:
        hallazgos.append(("error",
            "Pegue la cadena tal como la entrega Supabase, con {} en lugar de "
            "la contraseña.".format(MARCADOR)))

    host = partes.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        hallazgos.append(("aviso",
            "Es la conexión DIRECTA. En el plan gratuito solo funciona por IPv6 "
            "y fallará desde GitHub Actions y Codespaces. Use el Session pooler."))
    elif "pooler.supabase.com" in host and partes.port == 6543:
        hallazgos.append(("aviso",
            "Es el Transaction pooler (puerto 6543). Se recomienda el Session "
            "pooler (puerto 5432), que admite todas las operaciones del sistema."))

    return hallazgos


def construir(uri, contrasena):
    """Inserta la contraseña codificada y exige conexión cifrada."""
    completa = uri.replace(MARCADOR, urllib.parse.quote(contrasena, safe=""))
    if "sslmode=" not in completa:
        completa += ("&" if "?" in completa else "?") + "sslmode=require"
    return completa


def enmascarar(uri):
    """Versión imprimible de la cadena, con la contraseña oculta."""
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1****\2", uri)


def guardar_en_env(uri, ruta=RUTA_ENV):
    """Escribe o reemplaza DATABASE_URL en el archivo .env."""
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    lineas = [l for l in lineas if not l.strip().startswith("DATABASE_URL=")]
    lineas.append("DATABASE_URL=" + uri)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print("CONFIGURACIÓN DE LA BASE DE DATOS EXTERNA")
    print("-" * 60)
    uri = input("Pegue la cadena del Session pooler (con {}):\n> ".format(MARCADOR)).strip()
    uri = uri.removeprefix("DATABASE_URL=").strip().strip('"').strip("'")

    hallazgos = analizar(uri)
    for nivel, mensaje in hallazgos:
        print("  {}: {}".format(nivel.upper(), mensaje))
    if any(nivel == "error" for nivel, _ in hallazgos):
        raise SystemExit(1)
    if hallazgos and input("  ¿Continuar de todos modos? (s/n): ").strip().lower() != "s":
        raise SystemExit(1)

    contrasena = getpass.getpass("Contraseña de la base (no se mostrará): ")
    if not contrasena:
        print("  No se ingresó contraseña.")
        raise SystemExit(1)

    completa = construir(uri, contrasena)
    guardar_en_env(completa)
    print("\n  Guardada en .env: {}".format(enmascarar(completa)))

    # Se prueba de inmediato con la cadena recién construida.
    config.URL_BASE_DATOS = completa
    from datos.base_datos import probar_conexion
    print("\nProbando la conexión...")
    try:
        estado = probar_conexion()
    except Exception as error:
        print("  FALLÓ: {}".format(str(error).splitlines()[0]))
        print("  Revise la contraseña. Si la olvidó, se restablece en Supabase con")
        print("  'Reset database password' y se vuelve a ejecutar este comando.")
        raise SystemExit(1)

    print("  Motor           : {}".format(estado["motor"]))
    print("  Versión         : {}".format(estado["version"]))
    print("  Conexión cifrada: {}".format("sí (SSL)" if estado["ssl"] else "NO"))
    print("  Latencia        : {} ms".format(estado["latencia_ms"]))
    print("  Tablas          : {}".format(estado["tablas"] or "ninguna todavía"))
    print("\nListo. Siguiente paso: python -m datos.base_datos sintetica")
