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

    if MARCADOR not in uri and not _separar(uri):
        hallazgos.append(("error",
            "No se reconoce la cadena. Debe tener la forma "
            "postgresql://usuario:contraseña@servidor:puerto/base"))

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


def _separar(uri):
    """Separa una cadena en (prefijo, usuario, contraseña, resto).

    Se busca la ÚLTIMA arroba y no la primera, porque una contraseña sin
    codificar puede contener arrobas y confundiría a un analizador de URL
    estándar.
    """
    coincide = re.match(r"^(postgres(?:ql)?://)([^:/@]+):(.*)@([^@]+)$", uri)
    return coincide.groups() if coincide else None


def trae_contrasena(uri):
    """True si la cadena ya incluye una contraseña real y no el marcador."""
    partes = _separar(uri)
    return bool(partes) and partes[2] not in ("", MARCADOR)


def construir(uri, contrasena=None):
    """Inserta la contraseña codificada y exige conexión cifrada.

    Acepta la cadena con el marcador más la contraseña aparte, o la cadena con
    la contraseña ya escrita. En el segundo caso la contraseña se decodifica y
    se vuelve a codificar, de modo que funciona igual si venía codificada o no.
    """
    if contrasena is not None:
        completa = uri.replace(MARCADOR, urllib.parse.quote(contrasena, safe=""))
    else:
        prefijo, usuario, clave, resto = _separar(uri)
        clave = urllib.parse.quote(urllib.parse.unquote(clave), safe="")
        completa = "{}{}:{}@{}".format(prefijo, usuario, clave, resto)
    if "sslmode=" not in completa:
        completa += ("&" if "?" in completa else "?") + "sslmode=require"
    return completa


def enmascarar(uri):
    """Versión imprimible de la cadena, con la contraseña oculta."""
    return re.sub(r"(://[^:/@]+:)[^@]+(@)", r"\1****\2", uri)


def diagnosticar(error):
    """Traduce los errores de conexión más comunes a una causa concreta.

    El mensaje original de la librería se recorta a su primera línea y se le
    quita cualquier rastro de la cadena de conexión antes de mostrarlo.
    """
    texto = str(error)
    causas = [
        ("password authentication failed",
         "contraseña incorrecta. Verifíquela o restablézcala en Supabase con "
         "'Reset database password'."),
        ("tenant or user not found",
         "el usuario no corresponde al pooler. Debe ser postgres.REFERENCIA, "
         "con el punto y la referencia del proyecto."),
        ("could not translate host name",
         "no se encuentra el servidor. Revise que el nombre del host esté bien copiado."),
        ("timeout",
         "la conexión no respondió. Puede ser la red o un firewall que bloquea el puerto 5432."),
        ("network is unreachable",
         "la red no alcanza el servidor. Si es la conexión directa, use el Session pooler."),
    ]
    for patron, causa in causas:
        if patron in texto.lower():
            return causa
    return enmascarar(texto.splitlines()[0]) if texto else type(error).__name__


def guardar_en_env(uri, ruta=RUTA_ENV):
    """Escribe o reemplaza DATABASE_URL en el archivo .env."""
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    lineas = [l for l in lineas if not l.strip().startswith("DATABASE_URL=")]
    lineas.append("DATABASE_URL=" + uri)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print("CONFIGURACIÓN DE LA BASE DE DATOS EXTERNA")
    print("-" * 60)
    uri = input("Pegue la cadena del Session pooler, con la contraseña o con {}:\n> "
                .format(MARCADOR)).strip()
    uri = uri.removeprefix("DATABASE_URL=").strip().strip('"').strip("'")

    hallazgos = analizar(uri)
    for nivel, mensaje in hallazgos:
        print("  {}: {}".format(nivel.upper(), mensaje))
    if any(nivel == "error" for nivel, _ in hallazgos):
        raise SystemExit(1)
    if hallazgos and input("  ¿Continuar de todos modos? (s/n): ").strip().lower() != "s":
        raise SystemExit(1)

    if trae_contrasena(uri):
        print("  La cadena ya incluye la contraseña: se usará esa.")
        completa = construir(uri)
    else:
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
        print("  FALLÓ: {}".format(diagnosticar(error)))
        raise SystemExit(1)

    print("  Motor           : {}".format(estado["motor"]))
    print("  Versión         : {}".format(estado["version"]))
    print("  Conexión cifrada: {}".format("sí (SSL)" if estado["ssl"] else "NO"))
    print("  Latencia        : {} ms".format(estado["latencia_ms"]))
    print("  Tablas          : {}".format(estado["tablas"] or "ninguna todavía"))
    print("\nListo. Siguiente paso: python -m datos.base_datos sintetica")
