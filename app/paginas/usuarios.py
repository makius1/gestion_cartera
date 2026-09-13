# -*- coding: utf-8 -*-
"""
Administración de usuarios (solo administradores).

Los usuarios no se eliminan: se desactivan. La bitácora de auditoría los sigue
nombrando, y debe poder saberse quién era cada uno. Tampoco se muestran ni se
envían contraseñas: el administrador asigna una contraseña inicial y se la
comunica a la persona por un medio aparte.
"""

import pandas as pd
import streamlit as st

from app import comun
from seguridad import autenticacion as auth

comun.exigir("gestionar_usuarios")
comun.encabezado("Usuarios", "Cuentas de acceso, roles y estado")
responsable = comun.usuario_actual()["usuario"]

st.markdown("""
| Rol | Puede |
|---|---|
| Gestor | Consultar el tablero, la cartera, los resultados del motor y la base de conocimiento |
| Supervisor | Lo anterior, más ejecutar el motor, generar cargas y revisar la auditoría |
| Administrador | Todo lo anterior, más administrar usuarios |
""")

tabla = auth.listar_usuarios()
vista = tabla.copy()
for columna in ("creado", "ultimo_ingreso", "bloqueado_hasta"):
    vista[columna] = pd.to_datetime(vista[columna]).dt.strftime("%Y-%m-%d %H:%M").fillna("—")
st.dataframe(vista.drop(columns=["id"]), hide_index=True, use_container_width=True,
             column_config={"usuario": "Usuario", "nombre": "Nombre", "rol": "Rol",
                            "activo": st.column_config.CheckboxColumn("Activo"),
                            "creado": "Creado", "ultimo_ingreso": "Último ingreso",
                            "intentos_fallidos": "Intentos fallidos",
                            "bloqueado_hasta": "Bloqueado hasta"})

aviso = st.session_state.pop("aviso_usuarios", None)
if aviso:
    st.success(aviso)

crear, modificar = st.tabs(["Crear usuario", "Modificar usuario"])

with crear:
    # El formulario conserva lo escrito si hay un error, para corregir sin
    # volver a digitar todo. Solo se limpia cuando el usuario se crea: cambiar la
    # clave del formulario hace que Streamlit lo dibuje de nuevo, vacío.
    version = st.session_state.setdefault("version_formulario_usuario", 0)
    with st.form("crear_usuario_{}".format(version)):
        c1, c2 = st.columns(2)
        usuario = c1.text_input("Usuario", help="Minúsculas, números, punto, guion o guion bajo.")
        nombre = c2.text_input("Nombre completo")
        rol = c1.selectbox("Rol", auth.ROLES)
        clave = c2.text_input("Contraseña inicial", type="password",
                              help="Al menos 10 caracteres, con letras y números.")
        if st.form_submit_button("Crear", type="primary"):
            try:
                auth.crear_usuario(usuario, nombre, rol, clave, creado_por=responsable)
                st.session_state["aviso_usuarios"] = "Usuario '{}' creado.".format(
                    auth.normalizar_usuario(usuario))
                st.session_state["version_formulario_usuario"] = version + 1
                st.rerun()
            except ValueError as error:
                st.error(str(error))

with modificar:
    elegido = st.selectbox("Usuario", tabla["usuario"].tolist())
    fila = tabla[tabla["usuario"] == elegido].iloc[0]
    c1, c2, c3 = st.columns(3)

    with c1:
        nuevo_rol = st.selectbox("Rol", auth.ROLES, index=auth.ROLES.index(fila["rol"]), key="rol_mod")
        if st.button("Cambiar rol", disabled=nuevo_rol == fila["rol"]):
            try:
                auth.cambiar_rol(elegido, nuevo_rol, responsable)
                st.session_state["aviso_usuarios"] = "'{}' ahora tiene el rol {}.".format(elegido, nuevo_rol)
                st.rerun()
            except ValueError as error:
                st.error(str(error))

    with c2:
        activo = bool(fila["activo"])
        st.markdown("Estado: **{}**".format("activo" if activo else "inactivo"))
        if st.button("Desactivar" if activo else "Activar"):
            try:
                auth.cambiar_estado(elegido, not activo, responsable)
                st.session_state["aviso_usuarios"] = "'{}' quedó {}.".format(
                    elegido, "inactivo" if activo else "activo")
                st.rerun()
            except ValueError as error:
                st.error(str(error))

    with c3:
        with st.form("restablecer", clear_on_submit=True):
            nueva = st.text_input("Nueva contraseña", type="password")
            if st.form_submit_button("Restablecer y desbloquear"):
                try:
                    auth.restablecer_clave(elegido, nueva, responsable)
                    st.success("Contraseña restablecida.")
                except ValueError as error:
                    st.error(str(error))
