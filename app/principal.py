# -*- coding: utf-8 -*-
"""
Punto de entrada de la aplicación web.

    streamlit run app/principal.py

Flujo en cada interacción:
  1. Si no hay sesión, solo existe la pantalla de ingreso: las demás ni
     siquiera se registran en la navegación, así que no se pueden abrir
     escribiendo su dirección.
  2. Si hay sesión, se verifica la inactividad y que el usuario siga activo.
  3. Se arma el menú con las pantallas que el rol del usuario puede ver.
"""

import sys
from pathlib import Path

# Streamlit agrega al camino de importación la carpeta del archivo que ejecuta
# (app/), no la raíz del proyecto. Sin esta línea no se encontrarían config,
# datos, motor ni seguridad.
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import streamlit as st  # noqa: E402

from app import comun  # noqa: E402
from datos import base_datos as bd  # noqa: E402
from seguridad import autenticacion as auth  # noqa: E402

st.set_page_config(page_title="Gestión de Cartera", page_icon=":material/account_balance:",
                   layout="wide")


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------
# Si la base no responde (por ejemplo, porque el plan gratuito de Supabase
# pausó el proyecto), se muestra un mensaje claro y nada más. El detalle del
# error no se muestra: puede incluir datos de la conexión.

@st.cache_resource(show_spinner="Conectando con la base de datos...")
def _preparar_base():
    bd.crear_esquema()
    return True


try:
    _preparar_base()
except Exception:
    st.error("No fue posible conectar con la base de datos. Si la base está en "
             "Supabase, verifique que el proyecto no esté pausado y vuelva a intentar.")
    st.stop()


# ---------------------------------------------------------------------------
# Ingreso
# ---------------------------------------------------------------------------

def pantalla_ingreso():
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.title("Gestión de Cartera")
        st.caption("El sistema administra la información de la cartera asignada: la carga, "
                   "la depura, protege la identidad de los titulares con seudónimos, la "
                   "guarda con historial por mes y la convierte en decisiones auditables.")

        aviso = st.session_state.pop("aviso_salida", None)
        if aviso:
            st.info(aviso)

        if not auth.hay_usuarios():
            st.warning("No hay usuarios registrados. El administrador inicial se crea "
                       "una sola vez desde la terminal, con acceso a la base:\n\n"
                       "`python -m seguridad.autenticacion crear-admin`")
            return

        with st.form("ingreso"):
            usuario = st.text_input("Usuario", autocomplete="username")
            clave = st.text_input("Contraseña", type="password", autocomplete="current-password")
            enviar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)

        if enviar:
            if not usuario or not clave:
                st.error("Ingrese usuario y contraseña.")
                return
            with st.spinner("Verificando..."):
                datos, mensaje = auth.autenticar(usuario, clave)
            if datos is None:
                st.error(mensaje)
                return
            comun.iniciar_sesion(datos)
            st.rerun()


if not comun.controlar_sesion():
    st.navigation([st.Page(pantalla_ingreso, title="Ingreso", icon=":material/login:")]).run()
    st.stop()


# ---------------------------------------------------------------------------
# Menú según el rol
# ---------------------------------------------------------------------------
# Cada pantalla se asocia al permiso que exige. Solo se registran las
# permitidas; además, cada pantalla vuelve a verificar su permiso al abrirse.

PAGINAS = {
    "Operación": [
        ("paginas/tablero.py", "Tablero", ":material/dashboard:", "ver_tablero"),
        ("paginas/gestion.py", "Gestión de cuentas", ":material/support_agent:", "registrar_gestion"),
        ("paginas/plan.py", "Plan de trabajo", ":material/assignment_ind:", "ver_plan"),
        ("paginas/traza.py", "Traza de trabajo", ":material/timeline:", "ver_traza"),
        ("paginas/cartera.py", "Cartera", ":material/table_view:", "ver_cartera"),
        ("paginas/motor.py", "Motor de elegibilidad", ":material/rule:", "ver_motor"),
        ("paginas/priorizacion.py", "Priorización", ":material/sort:", "ver_priorizacion"),
        ("paginas/propension.py", "Propensión a pago", ":material/insights:", "ver_propension"),
    ],
    "Conocimiento": [
        ("paginas/conocimiento.py", "Base de conocimiento", ":material/menu_book:", "ver_conocimiento"),
        ("paginas/metodologia.py", "Metodología", ":material/functions:", "ver_conocimiento"),
        ("paginas/laboratorio.py", "Laboratorio de algoritmos", ":material/science:", "ver_laboratorio"),
    ],
    "Administración": [
        ("paginas/cargas.py", "Cargas", ":material/upload_file:", "gestionar_cargas"),
        ("paginas/obligaciones.py", "Obligación nueva", ":material/note_add:", "gestionar_obligaciones"),
        ("paginas/usuarios.py", "Usuarios", ":material/group:", "gestionar_usuarios"),
        ("paginas/auditoria.py", "Auditoría", ":material/history:", "ver_auditoria"),
    ],
    "Cuenta": [
        ("paginas/mi_cuenta.py", "Mi cuenta", ":material/person:", None),
    ],
}

menu = {}
for grupo, paginas in PAGINAS.items():
    visibles = [st.Page(ruta, title=titulo, icon=icono)
                for ruta, titulo, icono, permiso in paginas
                if permiso is None or comun.puede(permiso)]
    if visibles:
        menu[grupo] = visibles

usuario = comun.usuario_actual()
with st.sidebar:
    st.markdown("**{}**  \n{} · {}".format(usuario["nombre"], usuario["usuario"],
                                           usuario["rol"].capitalize()))
    if st.button("Cerrar sesión", icon=":material/logout:", use_container_width=True):
        comun.cerrar_sesion("Sesión cerrada correctamente.")
        st.rerun()

st.navigation(menu).run()
