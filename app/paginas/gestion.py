# -*- coding: utf-8 -*-
"""
Gestión de cuentas: el apartado de trabajo diario del gestor.

Flujo:
  1. Tomar una cuenta: la siguiente de la cola priorizada, o buscarla por
     crédito o titular.
  2. Revisar la obligación, su última gestión, su historial y lo que el motor
     permite hacer hoy con ella (estado, canales, horario).
  3. Registrar el resultado del contacto. El sistema valida la gestión contra
     las reglas G1 a G10 y, si pasa, actualiza la cartera en la misma
     transacción.
"""

from datetime import timedelta

import pandas as pd
import streamlit as st

import config
from app import comun
from datos import autorizaciones as aut
from datos import base_datos as bd
from gestion import operacion as op
from gestion import plan
from gestion import titulares as tit

comun.exigir("registrar_gestion")
comun.encabezado("Gestión de cuentas", "Registro del resultado de cada contacto con el titular")
usuario = comun.usuario_actual()["usuario"]

carga = comun.selector_carga("carga_gestion")
if carga is None:
    st.stop()
carga_id = int(carga["id"])
cartera = comun.cartera(carga_id)


def pesos_md(valor):
    """Monto para texto con formato: en Markdown dos signos $ en la misma línea
    se interpretan como una fórmula matemática, así que se escapan."""
    return comun.pesos(valor).replace("$", r"\$")


aviso = st.session_state.pop("aviso_gestion", None)
if aviso:
    st.success(aviso)


# ---------------------------------------------------------------------------
# 1. TOMAR UNA CUENTA
# ---------------------------------------------------------------------------

with st.container(border=True):
    c1, c2 = st.columns([3, 1])
    busqueda = c1.text_input("Buscar por crédito o titular",
                             placeholder="Seudónimo del crédito (K…) o del titular (C…)")
    c2.write("")
    if c2.button("Siguiente cuenta", icon=":material/skip_next:", use_container_width=True):
        # Libera antes de pedir una nueva: si el gestor abandonó la cuenta
        # anterior sin gestionarla, que no siga bloqueada el resto del tiempo
        # de la reserva.
        bd.liberar_reservas_de(usuario)
        # Primero el plan de trabajo del gestor; si no tiene plan hoy o ya lo
        # completó, la cola general de la última priorización.
        credito, orden, total = plan.siguiente_del_plan(carga_id, usuario)
        if credito is not None:
            st.session_state["gestion_credito"] = credito
            st.session_state["gestion_posicion"] = None
            st.session_state["gestion_origen"] = "Cuenta {} de {} de su plan de trabajo de hoy.".format(
                orden, total)
        else:
            # Sin plan: la cuenta sale de la cola general y queda reservada
            # para este gestor, para que otro que pida al mismo tiempo no
            # reciba la misma (ver docs/PLAN_DE_PRUEBAS.md).
            credito, posicion = op.siguiente_de_la_cola(carga_id, usuario)
            if credito is None:
                st.info("No hay cuentas pendientes: no existe una priorización para esta carga, "
                        "todas las cuentas de la cola ya se gestionaron hoy o están reservadas por "
                        "otros gestores en este momento.")
            else:
                st.session_state["gestion_credito"] = credito
                st.session_state["gestion_posicion"] = posicion
                st.session_state["gestion_origen"] = (
                    "Completó su plan de hoy; cuenta tomada de la cola general." if total
                    else "Cuenta tomada de la cola general (no tiene plan de trabajo hoy).")

    if busqueda.strip():
        texto = busqueda.strip().upper()
        encontradas = cartera[cartera["credito_id"].str.startswith(texto)
                              | cartera["cuenta_id"].str.startswith(texto)]
        if encontradas.empty:
            st.warning("No se encontró ninguna cuenta con ese seudónimo en esta carga.")
        elif len(encontradas) == 1:
            st.session_state["gestion_credito"] = encontradas.iloc[0]["credito_id"]
            st.session_state.pop("gestion_posicion", None)
        else:
            # Un titular puede tener varios créditos en la misma carga.
            elegido = st.selectbox("Créditos encontrados", encontradas["credito_id"].head(50).tolist())
            st.session_state["gestion_credito"] = elegido
            st.session_state.pop("gestion_posicion", None)

        # La búsqueda por seudónimo no pasa por la reserva de "Siguiente
        # cuenta": se avisa, pero no se bloquea, porque puede ser el propio
        # gestor volviendo a una cuenta que ya tenía abierta.
        credito_buscado = st.session_state.get("gestion_credito")
        if credito_buscado:
            reservada_por = bd.reserva_vigente_de(carga_id, credito_buscado)
            if reservada_por and reservada_por != usuario:
                st.warning("Esta cuenta está reservada por otro gestor en este momento; "
                           "puede estar trabajándola ahora mismo.")

credito = st.session_state.get("gestion_credito")
if not credito or credito not in set(cartera["credito_id"]):
    st.info("Tome la siguiente cuenta de la cola o busque una por su seudónimo.")
    st.stop()

fila = cartera[cartera["credito_id"] == credito].iloc[0].to_dict()
decision = op.estado_hoy(fila)


# ---------------------------------------------------------------------------
# 2. LA CUENTA
# ---------------------------------------------------------------------------

posicion = st.session_state.get("gestion_posicion")
st.subheader("Crédito {} · titular {}".format(credito, fila["cuenta_id"]))
origen = st.session_state.get("gestion_origen")
if origen:
    st.caption(origen)
if posicion:
    st.caption("Posición {} en la cola priorizada del día.".format(comun.numero(posicion)))

obligacion, ultima, hoy = st.columns(3)
with obligacion.container(border=True):
    st.markdown("**Obligación**")
    st.markdown(
        "Saldo: **{}**  \nRango de negociación: {} a {}  \nDías de mora: {} ({})  \n"
        "Franja: {}  \nProducto: {} · {}".format(
            pesos_md(fila["saldo"]), pesos_md(fila["cobranza_min"]),
            pesos_md(fila["cobranza_max"]), comun.numero(fila["dias_mora"]), fila["rango_mora"],
            fila["franja"], fila["producto"], fila["ciudad"]))

with ultima.container(border=True):
    st.markdown("**Última gestión**")
    fecha = pd.Timestamp(fila["fecha_ultima_gestion"]).strftime("%Y-%m-%d") \
        if pd.notna(fila["fecha_ultima_gestion"]) else "sin registro"
    compromiso = "{} para el {}".format(pesos_md(fila["proyeccion"]),
                                         pd.Timestamp(fila["fecha_compromiso"]).strftime("%Y-%m-%d")) \
        if bool(fila["tiene_compromiso"]) and pd.notna(fila["fecha_compromiso"]) else "ninguno"
    # Además de los resultados del formulario, la asignación trae dos etiquetas
    # que el gestor no registra pero sí debe poder leer.
    etiquetas = {**config.RESULTADOS_GESTION, "SIN_GESTION_REAL": "Sin gestión real (solo registros "
                 "automáticos)", "OTRO": "Otro resultado"}
    st.markdown("Resultado: **{}**  \nCódigo: {}  \nFecha: {} · gestor: {}  \nCompromiso: {}  \n"
                "Meses en gestión: {}".format(
                    etiquetas.get(fila["resultado_gestion"], fila["resultado_gestion"]),
                    fila["codigo"], fecha, fila["gestor_ultimo"], compromiso,
                    comun.numero(fila["meses_en_gestion"] or 0)))

with hoy.container(border=True):
    st.markdown("**Hoy, según el motor**")
    color = {"CONTACTABLE": "green", "RECORDATORIO": "blue", "EN_ESPERA": "orange",
             "BLOQUEADA": "red"}[decision["estado"]]
    st.markdown(":{}[**{}**]".format(color, decision["estado"]))
    if decision["canal_recomendado"]:
        st.markdown("Canal recomendado: **{}**  \nPermitidos: {}".format(
            decision["canal_recomendado"], ", ".join(decision["canales_permitidos"])))
    if not decision["en_horario"]:
        st.markdown(":red[Fuera del horario de contacto: solo se pueden registrar gestiones entrantes.]")
    # Se leen las columnas derivadas de la cartera, que son las mismas que usa el
    # motor: así el gestor ve por qué un canal no aparece entre los permitidos.
    # Un valor vacío (carga anterior a la autorización por canal) cuenta como no
    # autorizado, igual que para el motor.
    autorizados = [canal for canal, columna in config.COLUMNA_AUTORIZACION.items()
                   if pd.notna(fila.get(columna)) and bool(fila.get(columna))]
    st.markdown("Autorizados por el titular: {}".format(", ".join(sorted(autorizados)) or "ninguno"))
    st.caption(decision["explicacion"])

# --- Titular y datos de contacto ------------------------------------------------
# Los cambios de contacto recalculan los canales de la cuenta: se limpia la
# caché y se vuelve a dibujar la pantalla para que el panel del motor los tome.

def _tras_cambio(mensaje):
    comun.limpiar_cache()
    st.session_state["aviso_gestion"] = mensaje
    st.rerun()


titular = tit.leer_titular(fila["cuenta_id"])
contactos = tit.leer_contactos(fila["cuenta_id"])
with st.expander("Titular y datos de contacto · {}".format(titular["nombre"] if titular else "sin directorio"),
                 expanded=True):
    izquierda, derecha = st.columns([1, 2])
    with izquierda:
        with st.form("titular_{}".format(fila["cuenta_id"])):
            nombre = st.text_input("Nombre", value=(titular or {}).get("nombre") or "")
            st.text_input("Documento", value=(titular or {}).get("documento_enmascarado") or "—",
                          disabled=True, help="Solo se guardan los cuatro últimos dígitos.")
            ciudad = st.text_input("Ciudad", value=(titular or {}).get("ciudad") or fila["ciudad"])
            if st.form_submit_button("Guardar titular"):
                try:
                    tit.actualizar_titular(fila["cuenta_id"], nombre, ciudad, usuario)
                except ValueError as error:
                    st.error(str(error))
                else:
                    _tras_cambio("Datos del titular actualizados.")

    with derecha:
        if contactos.empty:
            st.caption("El titular no tiene contactos en el directorio.")
        else:
            st.dataframe(contactos[["id", "tipo", "mostrado", "estado", "origen", "actualizado_por"]],
                         hide_index=True, use_container_width=True,
                         column_config={"id": "Id", "tipo": "Tipo", "mostrado": "Dato",
                                        "estado": "Estado", "origen": "Origen",
                                        "actualizado_por": "Actualizado por"})
            opciones = contactos["id"].tolist()
            etiqueta = dict(zip(contactos["id"], contactos["tipo"] + " " + contactos["mostrado"]))
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
            elegido = c1.selectbox("Contacto", opciones, format_func=etiqueta.get,
                                   label_visibility="collapsed")
            if c2.button("Mostrar", icon=":material/visibility:", use_container_width=True):
                # Ver el dato completo queda en la auditoría.
                st.info("{}: {}".format(etiqueta[elegido].split()[0], tit.revelar(elegido, usuario)))
            if c3.button("Válido", icon=":material/check:", use_container_width=True):
                tit.cambiar_estado_contacto(elegido, "VALIDO", usuario)
                _tras_cambio("Contacto marcado como válido.")
            if c4.button("Errado", icon=":material/block:", use_container_width=True):
                canales = tit.cambiar_estado_contacto(elegido, "ERRADO", usuario)
                _tras_cambio("Contacto marcado como errado. Canales de la cuenta: {}.".format(
                    ", ".join(t for t, c in tit.INDICADOR.items() if canales[c]) or "ninguno"))

        with st.form("nuevo_contacto_{}".format(fila["cuenta_id"]), clear_on_submit=True):
            c1, c2, c3 = st.columns([1, 2, 1])
            tipo = c1.selectbox("Tipo", list(tit.TIPOS), format_func=tit.TIPOS.get)
            valor = c2.text_input("Nuevo dato de contacto", placeholder="3001234567 o correo@dominio.com")
            c3.write("")
            if c3.form_submit_button("Agregar", use_container_width=True):
                try:
                    tit.agregar_contacto(fila["cuenta_id"], tipo, valor, usuario)
                except ValueError as error:
                    st.error(str(error))
                else:
                    _tras_cambio("Contacto agregado como válido.")

# --- Autorización del titular por canal (Ley 2300, artículo 2) ------------------
# El titular autoriza o revoca un canal hablando con el gestor, y el cambio tiene
# que quedar registrado en ese momento: con quién, cuándo y qué dijo. Registrar
# actualiza también las columnas de la cartera que lee el motor.

autorizaciones = aut.leer(fila["cuenta_id"])
with st.expander("Autorización del titular por canal", expanded=True):
    st.dataframe(pd.DataFrame([{
        "Canal": canal, "Estado": aut.ETIQUETAS[dato["estado"]], "Origen": dato["origen"] or "—",
        "Actualizado": dato["actualizado"], "Registrado por": dato["actualizado_por"] or "—"}
        for canal, dato in autorizaciones.items()]),
        hide_index=True, use_container_width=True,
        column_config={"Actualizado": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm")})
    if not config.EXIGIR_AUTORIZACION_CANAL:
        st.caption("La exigencia de autorización está apagada (EXIGIR_AUTORIZACION_CANAL en config.py): "
                   "lo que se registre aquí queda guardado y en la cartera, pero el motor todavía no "
                   "descarta canales por esta causa.")
    with st.form("autorizacion_{}".format(fila["cuenta_id"])):
        c1, c2, c3 = st.columns([1, 2, 1])
        canal_autorizacion = c1.selectbox("Canal a registrar", sorted(config.CANALES))
        estado_autorizacion = c2.radio("Qué dijo el titular", list(config.ESTADOS_AUTORIZACION),
                                       format_func=aut.ETIQUETAS.get, horizontal=True)
        c3.write("")
        if c3.form_submit_button("Registrar autorización", use_container_width=True):
            aut.registrar(fila["cuenta_id"], canal_autorizacion, estado_autorizacion, usuario)
            _tras_cambio("{}: {}.".format(canal_autorizacion,
                                          aut.ETIQUETAS[estado_autorizacion].lower()))

historial = bd.leer_gestiones(carga_id, credito)
with st.expander("Historial de gestiones ({})".format(len(historial)), expanded=not historial.empty):
    if historial.empty:
        st.caption("La cuenta no tiene gestiones registradas en el sistema.")
    else:
        st.dataframe(historial[["fecha", "usuario", "canal", "sentido", "resultado", "codigo",
                                "valor_acordado", "fecha_compromiso", "observacion"]],
                     hide_index=True, use_container_width=True,
                     column_config={
                         "fecha": st.column_config.DatetimeColumn("Fecha", format="YYYY-MM-DD HH:mm"),
                         "valor_acordado": st.column_config.NumberColumn("Valor acordado", format="$ %d"),
                         "observacion": st.column_config.TextColumn("Observación", width="large")})


# ---------------------------------------------------------------------------
# 3. REGISTRAR LA GESTIÓN
# ---------------------------------------------------------------------------

st.subheader("Registrar gestión")
hoy_fecha = config.hoy()
recomendado = decision["canal_recomendado"] or "LLAMADA"
resultados = list(config.RESULTADOS_GESTION)

with st.form("registrar_gestion_{}".format(credito)):
    c1, c2, c3 = st.columns(3)
    canal = c1.selectbox("Canal", op.CANALES, index=op.CANALES.index(recomendado))
    sentido = c2.selectbox("Sentido", list(op.SENTIDOS), format_func=op.SENTIDOS.get)
    resultado = c3.selectbox("Resultado del contacto", resultados,
                             format_func=config.RESULTADOS_GESTION.get,
                             index=resultados.index("NO_CONTESTA"))

    c1, c2, c3 = st.columns(3)
    codigo = c1.selectbox("Código de gestión", config.CODIGOS_GESTION)
    motivo = c2.selectbox("Motivo de no pago", config.MOTIVOS_NO_PAGO)
    proxima = c3.date_input("Próxima gestión", format="YYYY-MM-DD",
                            value=hoy_fecha + timedelta(days=config.DIAS_MINIMOS_ENTRE_CONTACTOS),
                            min_value=hoy_fecha)

    st.caption("Solo para acuerdos de pago (PAGO TOTAL, DEBITO, DIFERIDO, POSIBLE NEGOCIACION):")
    c1, c2 = st.columns(2)
    valor = c1.number_input("Valor acordado", min_value=0.0, step=1000.0, format="%.0f",
                            value=float(fila["cobranza_min"] or 0),
                            help="Entre {} (mínimo autorizado) y {}.".format(
                                comun.pesos(fila["cobranza_min"]),
                                comun.pesos(max(fila["saldo"] or 0, fila["cobranza_max"] or 0))))
    fecha_compromiso = c2.date_input("Fecha del compromiso", format="YYYY-MM-DD",
                                     value=hoy_fecha + timedelta(days=3), min_value=hoy_fecha,
                                     max_value=hoy_fecha + timedelta(days=config.DIAS_MAXIMOS_COMPROMISO))

    observacion = st.text_area("Observación", max_chars=500,
                               placeholder="Qué se habló, qué se ofreció y qué respondió el titular.")
    grabar = st.form_submit_button("Grabar gestión", type="primary", icon=":material/save:")

if grabar:
    datos = {"canal": canal, "sentido": sentido, "resultado": resultado, "codigo": codigo,
             "motivo_no_pago": motivo, "valor_acordado": valor, "fecha_compromiso": fecha_compromiso,
             "fecha_proxima_gestion": proxima, "observacion": observacion}
    try:
        gestion_id, avisos = op.registrar(carga_id, credito, datos, usuario)
    except ValueError as error:
        st.error("La gestión no se guardó:\n\n" + "\n".join(
            "- **{}**: {}".format(regla, mensaje) for regla, mensaje in error.args[0]))
    except LookupError as error:
        st.error(str(error))
    else:
        comun.limpiar_cache()
        texto = "Gestión {} registrada y cartera actualizada.".format(gestion_id)
        if avisos:
            texto += " Avisos: " + " ".join("{}: {}".format(r, m) for r, m in avisos)
        st.session_state["aviso_gestion"] = texto
        st.rerun()

with st.expander("Reglas de validación de la gestión"):
    st.dataframe(pd.DataFrame([{"Regla": r["id"], "Nivel": r["nivel"], "Fundamento": r["fundamento"]}
                               for r in op.REGLAS_GESTION]),
                 hide_index=True, use_container_width=True)
