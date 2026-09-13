# Sistema Inteligente de Gestión de Cartera

[![Pruebas](https://github.com/makius1/gestion_cartera/actions/workflows/pruebas.yml/badge.svg)](https://github.com/makius1/gestion_cartera/actions/workflows/pruebas.yml)

Sistema experto de apoyo a la decisión para casas de cobranza. Toma la
asignación mensual de cartera y decide **qué cuentas trabajar, en qué orden,
por qué canal, con qué gestor y con qué oferta**, para maximizar el recaudo
esperado dentro de la capacidad operativa y las restricciones legales de
contacto.

Proyecto de la asignatura **Sistemas Expertos e Inteligencia Artificial**
(VIII Semestre, Ingeniería de Sistemas).

> **Administración de la información.** El sistema administra la información de
> la cartera asignada: la carga, la depura, protege la identidad de los
> titulares con seudónimos, la guarda con historial por mes y la convierte en
> decisiones auditables. El repositorio contiene solo el código: ninguna
> asignación ni dato de titulares se versiona.

---

## El problema

Una asignación mensual trae miles de cuentas en mora y una meta de recaudo
fija, con un equipo de gestores de capacidad limitada. En una cartera típica:

- Una parte importante de las cuentas **nunca recibe gestión humana real**,
  solo registros automáticos del sistema.
- Casi todas las cuentas tienen **varios canales de contacto disponibles**: el
  cuello de botella no es la falta de datos sino la falta de contacto efectivo.
- Un **pago de contado rinde bastante más en el mes** que un acuerdo diferido,
  lo que convierte el descuento negociable en una palanca de decisión.

El sistema convierte esa información en decisiones operativas.

---

## Arquitectura

```
ASIGNACIÓN (Excel / base de datos)
        │
[1] CARGA, LIMPIEZA Y SEUDONIMIZACIÓN        ← implementado
        │
[2] NÚCLEO DETERMINISTA
    ├─ Motor de reglas de elegibilidad       (Ley 2300 de 2023)   ← implementado
    ├─ Propensión a compromiso de pago       (árboles de decisión)
    ├─ Segmentación de la cartera            (K-Means)
    ├─ Priorización                          (lógica difusa + TOPSIS)
    ├─ Monto óptimo de negociación           (banda mínimo-máximo)
    └─ Asignación a gestores                 (optimización con capacidad)
        │
[3] ORQUESTADOR DIARIO DE COLAS POR CANAL
        │
[4] EJECUCIÓN MULTICANAL                     (correo, SMS, WhatsApp, llamada)
        │
[5] RETROALIMENTACIÓN                        (cada resultado reentrena el modelo)

APLICACIÓN WEB CON INGRESO Y ROLES                                ← implementado
```

El núcleo es **determinista y auditable**: toda decisión sobre a quién se
contacta, cuánto se ofrece y a quién se asigna se puede explicar regla por
regla.

---

## Infraestructura

```
   GitHub (código)                    Supabase (PostgreSQL)
   ├─ Actions: pruebas   ──────────►  base temporal de prueba
   ├─ Actions: sembrar   ──────────►  base externa del proyecto  ◄── Codespaces
   ├─ Actions: mantener  ──────────►  consulta cada tres días    ◄── equipo local
   └─ Streamlit Cloud    ──────────►  aplicación web con ingreso
```

Nada depende de un equipo encendido: la base vive en Supabase y los procesos
automáticos corren en los servidores de GitHub.

| Pieza | Qué hace |
|---|---|
| **Pruebas** | En cada envío, GitHub levanta un PostgreSQL temporal, genera una cartera ficticia, la carga, ejecuta el motor de elegibilidad y abre cada pantalla de la aplicación con cada rol. |
| **Sembrar base en Supabase** | Botón manual en la pestaña Actions: genera una cartera ficticia en GitHub y la carga directo en Supabase. |
| **Mantener activa la base** | Consulta la base cada tres días para reducir el riesgo de que el plan gratuito de Supabase la pause por inactividad. |
| **Codespaces** | Entorno de desarrollo en el navegador, con Python y las dependencias instaladas automáticamente. |
| **Streamlit Community Cloud** | Publica la aplicación web directamente desde este repositorio: cada envío a `main` la actualiza. |

---

## Configurar la base externa en Supabase

**1. Crear el proyecto.** En [supabase.com](https://supabase.com), crear un
proyecto nuevo con esta configuración:

| Opción | Valor | Motivo |
|---|---|---|
| Region | *Americas* | GitHub Actions y Codespaces corren en Estados Unidos: una región de América da la menor latencia a los procesos automáticos. |
| Database password | Solo letras y números, 20 caracteres o más | Los caracteres `@ : / ? # % & + =` rompen la cadena de conexión si no se codifican. |
| Enable Data API | Desmarcado | El sistema se conecta directo a PostgreSQL; la API REST no se usa y es superficie expuesta innecesaria. |
| Automatically expose new tables | Desmarcado | Evita que cada tabla nueva quede publicada en la API. |
| Enable automatic RLS | Marcado | Activa Row Level Security en toda tabla nueva: doble protección junto con la que aplica el sistema. |
| Connect GitHub | Sin conectar | Los flujos de Actions del repositorio ya administran la base. |

Guardar la contraseña: se necesita para la cadena de conexión.

**2. Copiar la cadena de conexión del pooler.** En el proyecto, botón
**Connect** → **Session pooler** → copiar la URI. Tiene esta forma:

```
postgresql://postgres.REFERENCIA:[YOUR-PASSWORD]@aws-0-REGION.pooler.supabase.com:5432/postgres
```

Reemplazar `[YOUR-PASSWORD]` por la contraseña y agregar `?sslmode=require` al
final.

> Use el **pooler** y no la conexión directa (`db.REFERENCIA.supabase.co`): en el
> plan gratuito la conexión directa solo funciona por IPv6, y GitHub Actions y
> Codespaces no tienen IPv6.

**3. Conectar desde el equipo local.** Pegar la cadena en el archivo `.env`
como `DATABASE_URL` y verificar:

```bash
python -m datos.base_datos probar
```

**4. Conectar desde GitHub.** En el repositorio: *Settings → Secrets and
variables → Actions → New repository secret*. Crear dos secretos:

| Secreto | Valor |
|---|---|
| `DATABASE_URL` | La cadena del pooler del paso 2 |
| `SEUDONIMO_CLAVE` | Una clave aleatoria (ver `.env.example`) |

Para Codespaces, crear los mismos secretos en *Settings → Secrets and variables
→ Codespaces*.

**5. Cargar la cartera ficticia.** Pestaña **Actions** → *Sembrar base en
Supabase* → **Run workflow**.

### Seguridad de la base

Al crear las tablas en PostgreSQL, el sistema activa **Row Level Security**.
Supabase publica cada tabla en una API REST accesible con la llave pública del
proyecto; con RLS activo y sin políticas definidas, esa API no devuelve ninguna
fila. El sistema se conecta como dueño de las tablas y no se ve afectado.

---

## Motor de elegibilidad de contacto

Decide, para cada cuenta y una fecha, si se puede contactar, por qué canales,
cuál conviene usar y **qué regla determinó el resultado**.

Es un sistema experto clásico: la **base de conocimiento**
(`motor/base_conocimiento.py`) declara las reglas como datos, y el **motor de
inferencia** (`motor/elegibilidad.py`) las aplica por fases con
encadenamiento hacia adelante, sin conocer ninguna regla de cobranza. Si cambia
la normativa, se modifica la base de conocimiento y el motor no se toca.

| Fase | Reglas | Qué decide |
|---|---|---|
| 1. Bloqueos | L1 día no hábil · N1 gestión cerrada · L3 información incompleta · L2 frecuencia | Si la cuenta **no** se puede contactar. Detiene el razonamiento: la ley está por encima de la estrategia. |
| 2. Compromisos | N3 recordatorio · N4 compromiso vigente | Si hay un acuerdo de pago que obliga a esperar o a recordar. |
| 3. Canales | C1 sin celular · C2 sin teléfono · C3 sin correo · C4 número errado | Qué canales no se pueden usar. |
| 4. Cierre | N2 sin canal disponible | Si no quedó ningún canal. |
| 5. Estrategia | E1 promesa incumplida · E2 contacto sin acuerdo · E3 nunca gestionada · E4 no localizado · E5 rechazo · E9 por defecto | Qué canal usar. Si varias aplican, gana la de mayor prioridad (resolución de conflictos). |

Cada regla declara su **fundamento**: la Ley 2300 de 2023 (días y frecuencia
del contacto de cobranza), la Ley 1581 de 2012 (protección de datos) o una
política del negocio. El resultado de cada cuenta trae una explicación en
lenguaje natural construida a partir de esa traza.

Dos decisiones de diseño:

- **Un hecho desconocido nunca dispara una regla.** Para que eso no termine en
  un contacto indebido por falta de datos, la regla L3 bloquea toda cuenta a la
  que le falte la información necesaria para verificar las demás.
- **Los festivos se calculan, no se escriben a mano.** La librería `holidays`
  aplica la Ley Emiliani, que traslada festivos al lunes.

Cada ejecución queda guardada con el resultado de cada cuenta: permite
demostrar después, ante una auditoría o una queja, que un contacto estaba
permitido el día en que se hizo y por qué.

> Los parámetros legales (días entre contactos, horarios) están en `config.py`
> y deben validarse con el área jurídica antes de operar.

---

## Aplicación web

La operación se hace desde el navegador, con ingreso por usuario y contraseña.
Cada rol ve solo las pantallas que le corresponden:

| Pantalla | Gestor | Supervisor | Administrador |
|---|:---:|:---:|:---:|
| Tablero: cartera frente a la meta | ✅ | ✅ | ✅ |
| Cartera: consulta con filtros y descarga | ✅ | ✅ | ✅ |
| Motor: resultados y explicación por cuenta | ✅ | ✅ | ✅ |
| Motor: ejecutar sobre una carga y una fecha | | ✅ | ✅ |
| Base de conocimiento y simulador de consulta | ✅ | ✅ | ✅ |
| Cargas: generar carteras ficticias | | ✅ | ✅ |
| Auditoría: bitácora de acciones | | ✅ | ✅ |
| Usuarios: crear, cambiar rol, desactivar, restablecer | | | ✅ |
| Mi cuenta: cambio de contraseña | ✅ | ✅ | ✅ |

### Seguridad de acceso

| Control | Implementación |
|---|---|
| Contraseñas | Nunca se guardan: se guarda su derivación con **scrypt** y sal aleatoria. Comparación en tiempo constante. |
| Política de contraseñas | Mínimo 10 caracteres, letras y números, sin el nombre de usuario ni contraseñas comunes. |
| Errores de ingreso | Mensaje único, exista o no el usuario, con un tiempo de respuesta equivalente. |
| Fuerza bruta | 5 intentos fallidos seguidos bloquean la cuenta 15 minutos. |
| Sesión | Se cierra sola tras 30 minutos sin actividad. El usuario se revalida contra la base cada minuto: si lo desactivan, pierde el acceso. |
| Control de acceso | El menú oculta lo no permitido y **cada pantalla vuelve a verificar el permiso**. |
| Auditoría | Ingresos, intentos fallidos, bloqueos, cargas, ejecuciones, descargas y cambios de usuarios quedan en una bitácora sin opción de edición. |
| Primer administrador | No se puede crear desde la web: se crea una vez desde la terminal, con acceso a la base. |
| Errores de la aplicación | No muestran detalle técnico al usuario. |

### Publicar la aplicación en Streamlit Community Cloud

1. En [share.streamlit.io](https://share.streamlit.io), ingresar con la cuenta
   de GitHub y crear una aplicación desde este repositorio.
2. Repositorio `makius1/gestion_cartera`, rama `main`, archivo principal
   `app/principal.py`. En *Advanced settings*, Python 3.11.
3. En *Secrets*, pegar las dos variables con sus valores reales, que nunca van
   al repositorio:

   ```toml
   DATABASE_URL = "postgresql://postgres.REFERENCIA:CONTRASEÑA@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require"
   SEUDONIMO_CLAVE = "la-misma-clave-de-los-secretos-de-GitHub"
   ```

4. Crear el primer administrador desde el equipo local, con el `.env`
   apuntando a Supabase:

   ```bash
   python -m seguridad.autenticacion crear-admin
   ```

5. Ingresar a la dirección que asigna Streamlit y crear los demás usuarios
   desde la pantalla **Usuarios**.

En el plan gratuito la aplicación se suspende tras un tiempo sin visitas y se
reactiva sola al abrirla; esa primera carga tarda unos segundos más.

---

## Datos ficticios

El generador crea una cartera desde cero a partir de `datos/perfil_demo.json`,
un perfil estadístico de demostración: frecuencias y cuantiles redondeados, con
etiquetas genéricas.

El muestreo conserva las relaciones que más pesan en el recaudo —el saldo según
el código de gestión, la mora según el mes de asignación, el margen según la
franja de saldo— y las reglas de negocio: solo los códigos de acuerdo generan
proyección de pago, la franja se deriva del máximo de cobranza y el rango de
mora de los días de mora.

Los datos están diseñados para no poder usarse por error en una campaña real:

- Los documentos van en un rango de diez dígitos que empieza por 99, que no
  corresponde a cédulas expedidas.
- Los correos usan el dominio `.test`, reservado para pruebas: ningún mensaje
  puede entregarse.
- Los celulares usan el prefijo 399.
- Todo registro lleva la marca `ES_DEMO`.

---

## Base de datos

| Tabla | Contenido |
|---|---|
| `cargas` | Una fila por carga: fecha, origen, cantidad de cuentas, saldo y meta de recaudo |
| `cartera` | Una fila por crédito y carga, con la cartera ya procesada |
| `ejecuciones_motor` | Una fila por ejecución del motor: quién, cuándo, sobre qué carga y para qué fecha |
| `evaluaciones` | El resultado de cada cuenta en cada ejecución, con sus reglas y su explicación |
| `usuarios` | Cuentas de acceso: rol, estado y derivación de la contraseña |
| `auditoria` | Bitácora de acciones del sistema |

La llave de `cartera` es el par (carga, crédito): **cada carga se conserva junto
a las anteriores** en lugar de reemplazarlas. Una cuenta aparece una vez por
cada mes en que fue asignada, que es lo que permite entrenar modelos con
historia.

El motor se elige por configuración: SQLite local si no se define
`DATABASE_URL`, o PostgreSQL si se define. El código es el mismo en ambos casos.
Cuando el esquema crece, las columnas nuevas se agregan solas a una base ya en
uso, sin tocar los datos existentes.

---

## Estructura

```
.
├── .github/workflows/
│   ├── pruebas.yml             Integración continua contra PostgreSQL
│   ├── sembrar_supabase.yml    Carga manual de la cartera ficticia en Supabase
│   └── mantener_activa.yml     Consulta periódica para evitar la pausa
├── .devcontainer/              Entorno de GitHub Codespaces
├── .streamlit/config.toml      Configuración de la aplicación web (sin secretos)
├── config.py                   Parámetros del negocio, normativa, seguridad y roles
├── datos/
│   ├── cargador.py             Carga, limpieza, seudonimización y derivación
│   ├── perfilador.py           Perfil estadístico y perfil de demostración
│   ├── perfil_demo.json        Perfil de demostración (datos agregados)
│   ├── generador.py            Generación de carteras ficticias
│   ├── base_datos.py           Esquema, cargas históricas, resultados y auditoría
│   └── configurar_conexion.py  Configuración asistida de la conexión a Supabase
├── motor/
│   ├── base_conocimiento.py    Reglas de elegibilidad con su fundamento
│   └── elegibilidad.py         Motor de inferencia y módulo de explicación
├── seguridad/
│   └── autenticacion.py        Contraseñas, ingreso, bloqueo, usuarios y roles
├── app/
│   ├── principal.py            Punto de entrada: ingreso y menú según el rol
│   ├── comun.py                Sesión, control de acceso, caché y formatos
│   └── paginas/                Una pantalla por archivo
├── pruebas/
│   └── prueba_aplicacion.py    Prueba automática de pantallas y permisos
├── .env.example                Plantilla de configuración
├── requirements.txt            Dependencias con versiones fijadas
└── README.md
```

---

## Instalación local

Requiere Python 3.10 o superior.

```bash
python -m venv .venv
```

En Windows:

```bash
.venv\Scripts\activate
```

En Linux o Codespaces:

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

---

## Uso

Abrir la aplicación web en el equipo local:

```bash
streamlit run app/principal.py
```

La primera vez, crear el administrador:

```bash
python -m seguridad.autenticacion crear-admin
```

Comandos de terminal para administración y pruebas. Verificar la conexión con
la base configurada:

```bash
python -m datos.base_datos probar
```

Generar una cartera ficticia y cargarla:

```bash
python -m datos.base_datos sintetica
```

Con otro tamaño o semilla:

```bash
python -m datos.base_datos sintetica --registros 10000 --semilla 7
```

Listar las cargas registradas:

```bash
python -m datos.base_datos cargas
```

Exportar una cartera ficticia a Excel, con las mismas columnas de una
asignación real:

```bash
python -m datos.generador
```

Ejecutar el motor de elegibilidad sobre la carga más reciente, para una fecha:

```bash
python -m motor.elegibilidad --fecha 2026-09-15
```

---

## Protección de datos

1. **Solo datos ficticios.** El proyecto no maneja ninguna cartera real.
2. **Ningún archivo de datos entra al repositorio.** El `.gitignore` excluye
   Excel, CSV y bases de datos.
3. **Seudonimización con clave.** Los identificadores se firman con HMAC-SHA256
   y una clave secreta. Un hash simple de un número de diez dígitos se puede
   revertir probando todos los valores posibles; sin la clave, no.
4. **Credenciales fuera del código.** Viven en `.env` en local y en los secretos
   de GitHub en la nube, nunca en el repositorio.
5. **Row Level Security** activo en todas las tablas de PostgreSQL.
6. **Datos reales solo en la base local.** La web solo genera carteras
   ficticias, y el sistema se niega a subir una cartera real a una base remota
   sin una confirmación explícita en el código.

---

## Estado del proyecto

| Fase | Módulo | Estado |
|---|---|---|
| 1 | Carga, limpieza y seudonimización | ✅ |
| 1b | Base de datos con historial de cargas | ✅ |
| 1c | Generación de carteras ficticias | ✅ |
| 1d | Base externa en Supabase y ejecución en GitHub | ✅ |
| 2 | Motor de reglas de elegibilidad de contacto | ✅ |
| 2b | Aplicación web con ingreso, roles y auditoría | ✅ |
| 3 | Segmentación y priorización | Pendiente |
| 4 | Modelo de propensión a compromiso de pago | Pendiente |
| 5 | Optimización de campañas y asignación | Pendiente |

---

## Autor

David Miller Aguilar Bayona — VIII Semestre, Ingeniería de Sistemas
