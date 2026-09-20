# -*- coding: utf-8 -*-
"""
Registro de obligaciones nuevas desde la aplicación (issue #17).

El supervisor puede dar de alta un crédito con su titular y contactos sin
pasar por una carga completa (archivo de asignación con las columnas del
originador). Sirve para el caso puntual: una obligación que llegó después del
corte del mes, o que se omitió por error.

No es un cargador alterno: reutiliza las mismas piezas que usa `datos/cargador.py`
para que una obligación registrada aquí sea indistinguible, para el resto del
sistema, de una que llegó en el archivo mensual:

  * MISMA SEUDONIMIZACIÓN -> `datos.cargador._seudonimo`, la misma función,
    no una reimplementación. Si mañana cambia la clave o el algoritmo, este
    módulo cambia solo con ella.
  * MISMAS REGLAS DE FRANJA Y RANGO DE MORA -> `datos.perfilador.franja` y la
    regla de `datos.generador._rango_mora`, verificadas contra el archivo
    real (ver sus propios docstrings).
  * MISMA VALIDACIÓN DE CONTACTOS -> `gestion.titulares.validar_contacto` y
    `agregar_contacto`, que además recalculan tiene_celular/tiene_fijo/
    tiene_email como lo haría cualquier alta desde la pantalla de titulares.

Los campos que en la carga masiva se derivan de estadísticas de la cartera
completa (perfiles de saldo y margen por franja, clasificación de texto libre
de gestión) no aplican a un registro de a uno: se piden directos en el
formulario o quedan en su valor neutro (sin compromiso, sin gestión previa).
"""

import re

from sqlalchemy import insert, select, update

import config
from datos import base_datos as bd
from datos.cargador import _seudonimo
from datos.generador import _rango_mora
from datos.perfilador import franja
from gestion import titulares as tit

LONGITUD_DOCUMENTO = (6, 10)     # cédula colombiana: seis a diez dígitos
LONGITUD_CREDITO = (4, 20)       # número de obligación del originador


def validar_documento(valor):
    valor = (valor or "").strip()
    minimo, maximo = LONGITUD_DOCUMENTO
    if not re.fullmatch(r"\d{%d,%d}" % (minimo, maximo), valor):
        return "El documento debe tener entre {} y {} dígitos.".format(minimo, maximo)
    return None


def validar_credito(valor):
    valor = (valor or "").strip()
    minimo, maximo = LONGITUD_CREDITO
    if not re.fullmatch(r"[A-Za-z0-9\-]{%d,%d}" % (minimo, maximo), valor):
        return "El número de obligación debe tener entre {} y {} caracteres (letras, números o guion).".format(
            minimo, maximo)
    return None


def validar_monto(valor, campo):
    if valor is None or valor < 0:
        return "{} debe ser un valor numérico mayor o igual a cero.".format(campo)
    return None


def validar_dias_mora(valor):
    if valor is None or valor < 0:
        return "Los días de mora deben ser un número entero mayor o igual a cero."
    return None


def validar(datos):
    """Valida un formulario completo. Retorna la lista de errores (vacía si
    todo está bien), con los mismos tipos y formatos que exige `cargar()`
    para el archivo de asignación."""
    errores = []
    error = validar_documento(datos.get("documento"))
    if error:
        errores.append(error)
    error = validar_credito(datos.get("credito"))
    if error:
        errores.append(error)
    for campo, etiqueta in [("saldo", "El saldo"), ("cobranza_min", "La cobranza mínima"),
                            ("cobranza_max", "La cobranza máxima")]:
        error = validar_monto(datos.get(campo), etiqueta)
        if error:
            errores.append(error)
    error = validar_dias_mora(datos.get("dias_mora"))
    if error:
        errores.append(error)
    if datos.get("cobranza_max") is not None and datos.get("cobranza_min") is not None \
            and datos["cobranza_max"] < datos["cobranza_min"]:
        errores.append("La cobranza máxima no puede ser menor que la mínima.")
    if not (datos.get("nombre") or "").strip():
        errores.append("El nombre del titular es obligatorio.")
    if not (datos.get("ciudad") or "").strip():
        errores.append("La ciudad es obligatoria.")
    if not (datos.get("producto") or "").strip():
        errores.append("El producto es obligatorio.")
    if datos.get("codigo") not in config.CODIGOS_GESTION:
        errores.append("El código debe ser uno de los que ya usa el sistema.")
    return errores


def existe_credito(carga_id, credito_id):
    with bd.obtener_motor().connect() as conexion:
        fila = conexion.execute(select(bd.cartera.c.credito_id).where(
            bd.cartera.c.carga_id == carga_id, bd.cartera.c.credito_id == credito_id)).first()
    return fila is not None


def registrar_obligacion(carga_id, datos, contactos, usuario):
    """Da de alta un crédito con su titular y contactos, sin pasar por una
    carga completa.

    `datos` trae documento, credito, nombre, ciudad, producto, codigo, saldo,
    cobranza_min, cobranza_max, dias_mora (ya validados con `validar()`).
    `contactos` es una lista de (tipo, valor) — puede ir vacía, la cuenta
    queda registrada igual, solo que el motor la bloqueará por L3 hasta que
    tenga al menos la certeza de qué canales tiene (aunque sea ninguno: lo
    importante es que conste, no que sea sí).

    Retorna el credito_id (seudónimo) asignado.
    """
    errores = validar(datos)
    if errores:
        raise ValueError(" ".join(errores))

    cuenta_id = _seudonimo(datos["documento"], "C")
    credito_id = _seudonimo(datos["credito"], "K")

    if existe_credito(carga_id, credito_id):
        raise ValueError("Esta obligación ya está registrada en esta carga.")

    cobranza_min, cobranza_max = datos["cobranza_min"], datos["cobranza_max"]
    margen_negociacion = max(cobranza_max - cobranza_min, 0)
    margen_pct = (margen_negociacion / cobranza_max) if cobranza_max else 0
    tipo_acuerdo = ("CONTADO" if datos["codigo"] in config.CODIGOS_CONTADO else
                    "DIFERIDO" if datos["codigo"] in config.CODIGOS_DIFERIDO else "SIN_ACUERDO")

    with bd.obtener_motor().begin() as conexion:
        conexion.execute(insert(bd.cartera).values(
            carga_id=carga_id, credito_id=credito_id, cuenta_id=cuenta_id,
            saldo=datos["saldo"], cobranza_min=cobranza_min, cobranza_max=cobranza_max,
            proyeccion=0, margen_negociacion=margen_negociacion, margen_pct=margen_pct,
            dias_mora=datos["dias_mora"],
            franja=franja_de(cobranza_max), rango_mora=rango_mora_de(datos["dias_mora"]),
            ciudad=datos["ciudad"].strip().upper()[:60], producto=datos["producto"].strip()[:30],
            estado="ACTIVO", codigo=datos["codigo"], gestor_ultimo=None,
            canales_disponibles=0, resultado_gestion="SIN_GESTION_REAL", meses_en_gestion=0,
            gestionada=False, gestionable=datos["codigo"] not in config.CODIGOS_EXCLUYENTES,
            tiene_compromiso=False, tipo_acuerdo=tipo_acuerdo, fecha_compromiso=None,
            # Se afirman en False, no se dejan nulas: la regla L3 del motor
            # bloquea toda cuenta cuyos canales no consten. Cero contactos es
            # un hecho conocido (no tiene), distinto de un hecho desconocido.
            tiene_celular=False, tiene_fijo=False, tiene_email=False,
            fecha_ultima_gestion=None,
        ))

        # Directorio del titular, con el mismo recorte a cuatro dígitos que
        # usa `datos.cargador.extraer_directorio` para el documento. No se
        # reutiliza `titulares.actualizar_titular` porque esa función no
        # toca documento_enmascarado (no lo necesita: en su caso el titular
        # ya existe desde la carga).
        valores_titular = {
            "nombre": datos["nombre"].strip()[:120],
            "documento_enmascarado": "******" + datos["documento"].strip()[-4:],
            "ciudad": datos["ciudad"].strip().upper()[:60],
            "actualizado": config.ahora(), "actualizado_por": usuario[:40],
        }
        actualizado = conexion.execute(update(bd.titulares).where(
            bd.titulares.c.cuenta_id == cuenta_id).values(**valores_titular))
        if actualizado.rowcount == 0:
            conexion.execute(insert(bd.titulares).values(cuenta_id=cuenta_id, **valores_titular))

    with bd.obtener_motor().connect() as conexion:
        ya_registrados = {(fila.tipo, fila.valor) for fila in conexion.execute(
            select(bd.contactos.c.tipo, bd.contactos.c.valor).where(
                bd.contactos.c.cuenta_id == cuenta_id))}

    for tipo, valor in contactos:
        # Si el titular ya tiene este mismo dato de otra obligación suya (muy
        # común: dos créditos, un solo celular), no se vuelve a agregar.
        # agregar_contacto rechazaría el duplicado con un error, y no es un
        # error real, es la misma persona.
        if (tipo, valor) in ya_registrados:
            continue
        # Por lo demás, valida con el mismo formato que usa la carga
        # (gestion.titulares.validar_contacto) y recalcula tiene_celular/
        # tiene_fijo/tiene_email por su cuenta.
        tit.agregar_contacto(cuenta_id, tipo, valor, usuario)

    # Se llama siempre, aunque no se haya agregado ningún contacto nuevo: si
    # el titular ya tenía contactos de otra obligación suya, esta cuenta
    # nueva también debe quedar con tiene_celular/tiene_fijo/tiene_email en
    # su valor real, no en el False por defecto con el que se insertó.
    tit.actualizar_indicadores(cuenta_id)

    with bd.obtener_motor().begin() as conexion:
        indicadores = conexion.execute(select(
            bd.cartera.c.tiene_celular, bd.cartera.c.tiene_fijo, bd.cartera.c.tiene_email
        ).where(bd.cartera.c.carga_id == carga_id, bd.cartera.c.credito_id == credito_id)).first()
        conexion.execute(update(bd.cartera).where(
            bd.cartera.c.carga_id == carga_id, bd.cartera.c.credito_id == credito_id
        ).values(canales_disponibles=sum(bool(v) for v in indicadores)))

    bd.registrar_evento(usuario, "OBLIGACION_NUEVA", "carga {} · credito {} · titular {} · {} contacto(s)".format(
        carga_id, credito_id, cuenta_id, len(contactos)))

    return credito_id


def franja_de(cobranza_max):
    """Franja de saldo de un único valor, con la misma regla de la carga."""
    return franja([cobranza_max])[0]


def rango_mora_de(dias_mora):
    """Rango de mora de un único valor, con la misma regla de la carga."""
    return _rango_mora([dias_mora])[0]
