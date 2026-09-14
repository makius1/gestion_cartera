# -*- coding: utf-8 -*-
"""
Configuración central del Sistema Inteligente de Gestión de Cobranza.

Todos los parámetros del negocio, las rutas y los umbrales viven aquí. Ningún
módulo define constantes por su cuenta: si cambia la meta de recaudo, la
capacidad de los gestores o la normativa de contacto, se modifica un solo
archivo y el sistema completo se adapta.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# HORA OFICIAL
# ---------------------------------------------------------------------------
# Los servidores en la nube (GitHub, Streamlit Cloud) trabajan en hora UTC. Si
# el sistema usara la hora del servidor, después de las 7 de la noche en
# Colombia ya sería "mañana" y el motor evaluaría el día equivocado. Colombia
# no tiene horario de verano, así que basta un desfase fijo de -5 horas, sin
# depender de bases de zonas horarias que en Windows no vienen instaladas.

ZONA_COLOMBIA = timezone(timedelta(hours=-5), "COT")


def ahora():
    """Fecha y hora oficial de Colombia, sin zona, lista para guardar."""
    return datetime.now(ZONA_COLOMBIA).replace(tzinfo=None)


def hoy():
    return ahora().date()


# ---------------------------------------------------------------------------
# RUTAS
# ---------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent
SALIDAS = RAIZ / "salidas"
SALIDAS.mkdir(exist_ok=True)

# Archivo de asignación del mes. La ruta real se define en el archivo .env,
# que no se versiona, para que ni las rutas de red internas ni el nombre del
# cliente queden escritos en el código. Si no se define, el sistema busca el
# archivo en datos/entrada/, carpeta que también está excluida del repositorio.
ARCHIVO_ASIGNACION = os.getenv(
    "ARCHIVO_ASIGNACION",
    str(RAIZ / "datos" / "entrada" / "asignacion.xlsx"),
)
HOJA_ASIGNACION = os.getenv("HOJA_ASIGNACION", "Asig")


# ---------------------------------------------------------------------------
# ORIGEN DE DATOS
# ---------------------------------------------------------------------------
# SQLite en local sin configurar nada. Con la variable DATABASE_URL definida
# (por ejemplo la cadena de Supabase) pasa a PostgreSQL en la nube sin tocar
# una línea de código.

URL_BASE_DATOS = os.getenv(
    "DATABASE_URL",
    "sqlite:///{}".format((SALIDAS / "cobranza.db").as_posix()),
)

TABLA_CARTERA = "cartera"


# ---------------------------------------------------------------------------
# META DE RECAUDO
# ---------------------------------------------------------------------------

META_PORCENTAJE = 0.01          # 1 % del saldo asignado


# ---------------------------------------------------------------------------
# NORMATIVA DE CONTACTO (Ley 2300 de 2023)
# ---------------------------------------------------------------------------
# Restricciones que el motor de reglas hace cumplir antes de autorizar
# cualquier envío. Se declaran como datos para poder ajustarlas si la
# reglamentación cambia, sin tocar el algoritmo que las evalúa.

DIAS_MINIMOS_ENTRE_CONTACTOS = 7
HORARIO_HABIL = {
    0: (7, 19),   # lunes
    1: (7, 19),
    2: (7, 19),
    3: (7, 19),
    4: (7, 19),   # viernes
    5: (8, 15),   # sábado
    6: None,      # domingo: prohibido
}

# Días antes de la fecha de un compromiso de pago en que se envía recordatorio.
# Antes de esa ventana la cuenta queda en espera, sin contacto.
DIAS_AVISO_COMPROMISO = 2


# ---------------------------------------------------------------------------
# CANALES DE CONTACTO
# ---------------------------------------------------------------------------
# Costo aproximado por envío y efectividad esperada. Son los parámetros que el
# optimizador usa para repartir el presupuesto de campaña. Hay que confirmarlos
# con el proveedor real antes de operar: aquí son estimaciones de trabajo.

CANALES = {
    "EMAIL":    {"costo": 1.0,   "tasa_respuesta": 0.010, "orden": 1},
    "SMS":      {"costo": 45.0,  "tasa_respuesta": 0.025, "orden": 2},
    "WHATSAPP": {"costo": 120.0, "tasa_respuesta": 0.060, "orden": 3},
    "LLAMADA":  {"costo": 900.0, "tasa_respuesta": 0.150, "orden": 4},
}

PRESUPUESTO_CAMPANA = 2_000_000     # COP disponibles para campañas del mes


# ---------------------------------------------------------------------------
# CAPACIDAD DE GESTIÓN
# ---------------------------------------------------------------------------

GESTIONES_POR_GESTOR_DIA = 80
DIAS_HABILES_MES = 22
NUMERO_GESTORES = 6             # gestores activos en la campaña


# ---------------------------------------------------------------------------
# SEGMENTACIÓN Y PRIORIZACIÓN
# ---------------------------------------------------------------------------

# Probabilidad relativa de lograr contacto efectivo según el resultado de la
# última gestión. Es conocimiento del experto de cobranza, no un dato de la
# cartera: quien colgó o pidió otro momento ya fue localizado; quien cae en
# buzón o tiene el teléfono apagado todavía no. Una cuenta sin gestión real
# queda en un punto intermedio porque su contactabilidad es desconocida.
CONTACTABILIDAD_RESULTADO = {
    "ACUERDO": 1.00,
    "REINTENTAR": 0.75,
    "CUELGA": 0.60,
    "CORREO_ENVIADO": 0.55,
    "MENSAJE_DEJADO": 0.50,
    "SIN_GESTION_REAL": 0.50,
    "OTRO": 0.40,
    "NO_CONTESTA": 0.30,
    "BUZON": 0.30,
    "APAGADO": 0.20,
    "NUMERO_ERRADO": 0.05,
    "FALLECIDO": 0.00,
}

# Criterios de priorización y su peso para TOPSIS y la ponderación simple. El
# sentido indica si conviene un valor alto (beneficio) o bajo (costo): una mora
# más antigua o más meses sin resolver reducen la probabilidad de recaudo.
CRITERIOS = {
    "saldo":            {"peso": 0.35, "sentido": "beneficio"},
    "contactabilidad":  {"peso": 0.25, "sentido": "beneficio"},
    "dias_mora":        {"peso": 0.20, "sentido": "costo"},
    "margen_pct":       {"peso": 0.10, "sentido": "beneficio"},
    "meses_en_gestion": {"peso": 0.10, "sentido": "costo"},
}

# Rango de segmentos que prueba K-Means. Se queda con el de mejor silueta, pero
# si un k menor queda a menos de la tolerancia del mejor, gana el menor: con
# siluetas casi iguales, menos segmentos son más fáciles de operar y explicar.
SEGMENTOS_MINIMO = 2
SEGMENTOS_MAXIMO = 6
TOLERANCIA_SILUETA = 0.01

# Peso de cada métrica en el puntaje con el que se elige el método óptimo:
# el recaudo esperado manda, pero un método que cambia su cola ante pequeñas
# variaciones de los datos, o que no logra desempatar cuentas, no es confiable.
PESOS_EVALUACION = {"recaudo": 0.60, "robustez": 0.25, "discriminacion": 0.15}
REPLICAS_ROBUSTEZ = 5
RUIDO_ROBUSTEZ = 0.10           # variación relativa máxima de los datos (±10 %)


# ---------------------------------------------------------------------------
# CLASIFICACIÓN DEL TEXTO DE GESTIÓN
# ---------------------------------------------------------------------------
# El campo GESTION es texto libre, pero su vocabulario es pequeño y repetitivo.
# Un diccionario ordenado por prioridad lo clasifica de forma determinista, sin
# depender de ningún servicio externo. El orden importa: se aplica la primera
# regla que coincide.

PATRONES_GESTION = [
    ("INACTIVO POR CLIENTES",  "SIN_GESTION_REAL"),
    ("ACUERDO",                "ACUERDO"),
    ("FALLECI",                "FALLECIDO"),
    ("EQUIVOCADO",             "NUMERO_ERRADO"),
    ("BUZON",                  "BUZON"),
    ("APAGADO",                "APAGADO"),
    ("NO CONTESTA",            "NO_CONTESTA"),
    ("CONTESTAN",              "NO_CONTESTA"),
    ("CUELGA",                 "CUELGA"),
    ("MENSAJE",                "MENSAJE_DEJADO"),
    ("CORREO",                 "CORREO_ENVIADO"),
    ("INSISTE",                "REINTENTAR"),
]
ETIQUETA_GESTION_POR_DEFECTO = "OTRO"

# Códigos de resultado que representan un compromiso de pago logrado.
CODIGOS_CON_COMPROMISO = {"DIFERIDO", "PAGO TOTAL", "POSIBLE NEGOCIACION", "DEBITO"}

# Códigos que sacan la cuenta de la gestión activa.
CODIGOS_EXCLUYENTES = {"FALLECIDO", "RECLAMACION", "CANCELACION"}

# Códigos que implican pago de contado frente a pago en cuotas. La distinción
# importa porque un contado entra completo en el mes y una cuota no.
CODIGOS_CONTADO = {"PAGO TOTAL", "DEBITO"}
CODIGOS_DIFERIDO = {"DIFERIDO", "POSIBLE NEGOCIACION"}


# ---------------------------------------------------------------------------
# VALORES CENTINELA
# ---------------------------------------------------------------------------
# La fecha 01/01/1999 en LLAMAR EL significa "sin compromiso pactado". Si no se
# convierte a nulo, cualquier cálculo de días daría 27 años y envenenaría los
# modelos.

FECHA_CENTINELA = "1999-01-01"


# ---------------------------------------------------------------------------
# SEGURIDAD DE ACCESO
# ---------------------------------------------------------------------------
# Controles de la aplicación web. Los valores siguen prácticas comunes de
# sistemas empresariales; se pueden endurecer sin tocar el código.

INTENTOS_MAXIMOS = 5            # intentos fallidos seguidos antes del bloqueo
MINUTOS_BLOQUEO = 15            # duración del bloqueo temporal
MINUTOS_INACTIVIDAD = 30        # la sesión se cierra sola tras este tiempo sin uso
LONGITUD_MINIMA_CLAVE = 10

# Roles del sistema y lo que cada uno puede hacer. El gestor consulta; el
# supervisor además opera (carga carteras y ejecuta el motor) y revisa la
# bitácora; el administrador además administra los usuarios.
PERMISOS = {
    "GESTOR": {"ver_tablero", "ver_cartera", "ver_motor", "ver_conocimiento",
               "ver_priorizacion"},
    "SUPERVISOR": {"ver_tablero", "ver_cartera", "ver_motor", "ver_conocimiento",
                   "ver_priorizacion", "ejecutar_motor", "ejecutar_priorizacion",
                   "gestionar_cargas", "ver_auditoria"},
    "ADMINISTRADOR": {"ver_tablero", "ver_cartera", "ver_motor", "ver_conocimiento",
                      "ver_priorizacion", "ejecutar_motor", "ejecutar_priorizacion",
                      "gestionar_cargas", "ver_auditoria", "gestionar_usuarios"},
}


# ---------------------------------------------------------------------------
# REPRODUCIBILIDAD
# ---------------------------------------------------------------------------

SEMILLA = 42
