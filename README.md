# Sistema Inteligente de Gestión de Cartera

[![Pruebas](https://github.com/makius1/gestion_cartera/actions/workflows/pruebas.yml/badge.svg)](https://github.com/makius1/gestion_cartera/actions/workflows/pruebas.yml)

**Aplicación publicada:** https://gestion-cartera.streamlit.app — se despliega
desde `main` en cada fusión y requiere usuario y contraseña del sistema.

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
    ├─ Segmentación de la cartera            (K-Means · Ward · GMM)     ← implementado
    ├─ Priorización                          (lógica difusa + TOPSIS)   ← implementado
    ├─ Monto óptimo de negociación           (banda mínimo-máximo)
    └─ Asignación a gestores                 (optimización con capacidad)
        │
[3] ORQUESTADOR DIARIO DE COLAS POR CANAL
        │
[4] EJECUCIÓN MULTICANAL                     (correo, SMS, WhatsApp, llamada)
    ├─ Registro de gestiones del gestor                                 ← implementado
    ├─ Directorio de titulares y contactos                              ← implementado
    └─ Plan de trabajo diario y traza de trabajo                        ← implementado
        │
[5] RETROALIMENTACIÓN                        (cada resultado reentrena el modelo)

APLICACIÓN WEB CON INGRESO Y ROLES                                ← implementado
```

El núcleo es **determinista y auditable**: toda decisión sobre a quién se
contacta, cuánto se ofrece y a quién se asigna se puede explicar regla por
regla.

**Ninguna decisión depende de un solo algoritmo.** Cada proceso automatizado
compara varios y se queda con el mejor para la cartera del momento, según
métricas explícitas. El documento [`docs/ALGORITMOS.md`](docs/ALGORITMOS.md)
explica cada algoritmo (qué hace en el sistema, qué busca, qué método
matemático aplica y qué decide o predice), revisa los modelos que usa el
sector financiero y recomienda el modelo para el entrenamiento. La aplicación
lo muestra en la pantalla **Metodología**.

---

## Infraestructura

```
   GitHub (código)                    Supabase (PostgreSQL)
   ├─ Actions: pruebas   ──────────►  base temporal de verificación
   ├─ Actions: sembrar   ──────────►  base externa del proyecto  ◄── Codespaces
   ├─ Actions: mantener  ──────────►  consulta cada tres días    ◄── equipo local
   └─ Streamlit Cloud    ──────────►  aplicación web con ingreso
```

Nada depende de un equipo encendido: la base vive en Supabase y los procesos
automáticos corren en los servidores de GitHub.

| Pieza | Qué hace |
|---|---|
| **Pruebas** | En cada envío, GitHub levanta un PostgreSQL temporal, simula una cartera, la registra, ejecuta el motor de elegibilidad, segmenta y prioriza, registra gestiones y abre cada pantalla de la aplicación con cada rol. |
| **Sembrar base en Supabase** | Botón manual en la pestaña Actions: simula una cartera en GitHub y la registra directamente en Supabase. |
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

**5. Registrar la primera cartera.** Pestaña **Actions** → *Sembrar base en
Supabase* → **Run workflow**, o desde la pantalla **Cargas** de la aplicación.

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

## Segmentación y priorización

Ordena las cuentas contactables del día para que el equipo trabaje primero
las que más aportan a la meta. En lugar de apostar por un solo método, el
sistema **calcula tres y elige el óptimo para cada cartera con un puntaje
explícito**.

### Segmentación con tres algoritmos

Agrupa las cuentas por saldo, contactabilidad, mora, margen y meses en
gestión (`analisis/segmentacion.py`) con **K-Means**, **jerárquico de Ward** y
**mezcla gaussiana**. En cada uno, el número de segmentos (2 a 6) se elige por
el **coeficiente de silueta**, con preferencia por el menor si la diferencia es
de menos de 0,01. Entre los tres gana el de mejor puntaje compuesto de
silueta, Calinski-Harabasz y Davies-Bouldin, y se descarta el que deje un
segmento con menos del 2 % de la cartera. El ganador cambia según la cartera:
en unas gana K-Means y en otras Ward. Cada segmento se nombra por sus dos
rasgos más distintivos, por ejemplo *"Mora antigua · recién asignada"*.

### Tres métodos de priorización

| Método | Cómo decide | Dónde |
|---|---|---|
| **Lógica difusa (Mamdani)** | 14 reglas lingüísticas del experto (*"saldo alto y mora temprana → prioridad alta"*): fuzzificación, MIN, MAX y centro de gravedad, resuelto de forma vectorizada para toda la cartera | `decision/conocimiento_difuso.py` y `decision/priorizacion.py` |
| **TOPSIS** | Cercanía de cada cuenta a una cuenta ideal y lejanía de la peor, con los pesos de cada criterio | `decision/priorizacion.py` |
| **Ponderación simple** | Suma ponderada de criterios normalizados: la referencia de una hoja de cálculo | `decision/priorizacion.py` |

### Cómo se elige el método óptimo

| Métrica | Qué mide | Peso |
|---|---|---|
| Recaudo esperado | Lo que se espera recuperar trabajando, en el orden del método, las cuentas que caben en la capacidad del día (gestores × gestiones por gestor) | 0,60 |
| Robustez | Cuánto de la cola del día se mantiene si los datos varían ±10 % (índice de Jaccard en 5 réplicas) | 0,25 |
| Discriminación | Fracción de puntajes distintos en la cola: un método con muchos empates obliga a desempatar a ciegas | 0,15 |

El resultado queda guardado con las métricas de los tres métodos, los
segmentos y el puntaje de cada cuenta con cada método, de modo que siempre se
puede revisar por qué se eligió uno y cómo habría quedado la cola con otro.

---

## Gestión de cuentas

Es el apartado de trabajo diario del gestor (`gestion/operacion.py`). Toma la
**siguiente cuenta de la cola priorizada** o busca una por su seudónimo, ve la
obligación, la última gestión, el historial y **lo que el motor permite hacer
hoy** con ella, y registra el resultado del contacto.

Cada gestión pasa por reglas de validación antes de guardarse, en el servidor:

| Regla | Nivel | Qué verifica | Fundamento |
|---|---|---|---|
| G1 | Error | Un contacto saliente solo en día hábil y dentro del horario | Ley 2300 de 2023 |
| G2 | Error | No contactar una cuenta que el motor bloquea hoy (por ejemplo, por frecuencia) | Ley 2300 y motor |
| G3 | Error | El canal debe estar permitido para la cuenta | Motor de elegibilidad |
| G4 | Aviso | Contacto durante un compromiso vigente | Política del negocio |
| G5 | Error | Sin hablar con el titular, el código solo puede ser de localización | Calidad del dato |
| G6 | Error | Acuerdo de pago y código de compromiso van juntos | Calidad del dato |
| G7 | Error | Resultado y código de fallecimiento van juntos | Calidad del dato |
| G8 | Error | El valor acordado no baja del mínimo autorizado ni supera lo cobrable; la fecha, dentro de 30 días | Banda de negociación |
| G9 | Aviso | La próxima gestión no debe quedar antes del periodo de frecuencia | Ley 2300 de 2023 |
| G10 | Error | Observación obligatoria | Soporte de la gestión |

Un contacto **entrante** (el titular se comunica) se puede registrar cualquier
día: la ley regula el contacto que inicia la casa de cobranza.

La gestión y la actualización de la cartera van en **una sola transacción**, y
con eso se cierra el ciclo del sistema experto:

- El motor lee la nueva fecha de contacto: la regla de frecuencia bloquea el
  recontacto y, si hubo acuerdo, se aplican las reglas de compromiso.
- La priorización lee el nuevo resultado y ajusta la contactabilidad.
- La historia de gestiones es la materia prima del modelo de propensión.

---

## Directorio de titulares

La cartera de análisis nunca guarda nombres, documentos, teléfonos ni correos:
guarda seudónimos. Pero el gestor necesita saber a quién llamar. La identidad
y los contactos van en un **directorio aparte** (tablas `titulares` y
`contactos`), unido a la cartera solo por el seudónimo del titular:

- Del documento se guardan solo los cuatro últimos dígitos, suficientes para
  confirmar identidad al teléfono.
- Los contactos se muestran enmascarados (`399****71`). Ver el dato completo
  es una acción explícita que queda en la auditoría.
- El gestor agrega teléfonos y correos (con validación de formato), marca cada
  contacto como válido o errado y corrige nombre y ciudad. Cada cambio
  recalcula los canales de todas las cuentas del titular, y el motor los usa
  de inmediato.
- Un contacto errado no se borra: queda como evidencia para no volver a
  llamar a un tercero si el número llega en otra asignación.
- Una carga nueva agrega al directorio lo que falta, sin deshacer lo que un
  gestor ya corrigió.

### Completar cargas incompletas

Las cargas registradas antes de que existieran estos datos se completan desde
la pantalla **Cargas** o con `python -m datos.completar --carga N`. Una carga
simulada se reconstruye con su semilla, se verifica crédito por crédito y
saldo por saldo, y solo se llenan los datos vacíos.

---

## Plan de trabajo y traza

**Plan de trabajo.** El supervisor toma una priorización y reparte las
cuentas del día entre los gestores activos:

1. Las cuentas se vuelven a evaluar con el motor para la fecha del plan.
2. Entran las de mayor prioridad hasta completar el cupo del equipo.
3. Se reparten **en serpentina** (1, 2, 3… y luego …3, 2, 1): cada gestor
   recibe una mezcla equivalente de cuentas de alta y baja prioridad, y sus
   resultados se pueden comparar con justicia.

En la pantalla de gestión, *Siguiente cuenta* entrega primero la del plan del
gestor y, cuando lo completa, la de la cola general. El avance no se guarda:
se calcula cruzando las asignaciones con las gestiones del día.

La cuenta tomada de la **cola general queda reservada** para ese gestor durante
20 minutos, de modo que dos gestores sin plan que pidan al mismo tiempo reciban
cuentas distintas. La reserva se libera al registrar la gestión, al pedir otra
cuenta o al vencerse el tiempo. La exclusión la resuelve la base de datos con un
solo `INSERT ... ON CONFLICT ... DO UPDATE` condicionado al vencimiento, no con
una lectura seguida de una escritura, porque entre esas dos operaciones cabría
el segundo gestor. La búsqueda por seudónimo no reserva: solo avisa si la cuenta
está reservada por otra persona.

**Traza de trabajo.**

- *Por gestor*: gestiones por día con la primera y la última hora de la
  jornada, efectividad de contacto, acuerdos, valor comprometido y
  distribución por hora. El gestor ve la suya; el supervisor la del equipo.
- *Por cuenta*: la línea de tiempo completa (carga, decisiones del motor,
  priorizaciones, asignaciones al plan, gestiones y cambios del titular). Es
  lo que se presenta ante una auditoría o una queja.

---

## Aplicación web

La operación se hace desde el navegador, con ingreso por usuario y contraseña.
Cada rol ve solo las pantallas que le corresponden:

| Pantalla | Gestor | Supervisor | Administrador |
|---|:---:|:---:|:---:|
| Tablero: cartera frente a la meta | ✅ | ✅ | ✅ |
| Gestión de cuentas: cola del día, estado legal y registro del contacto | ✅ | ✅ | ✅ |
| Titular y datos de contacto: agregar, validar, marcar errados | ✅ | ✅ | ✅ |
| Plan de trabajo: ver el propio | ✅ | ✅ | ✅ |
| Plan de trabajo: crear y ver el del equipo | | ✅ | ✅ |
| Traza de trabajo: la propia | ✅ | ✅ | ✅ |
| Traza de trabajo: la del equipo | | ✅ | ✅ |
| Cartera: consulta con filtros y descarga | ✅ | ✅ | ✅ |
| Motor: resultados y explicación por cuenta | ✅ | ✅ | ✅ |
| Motor: ejecutar sobre una carga y una fecha | | ✅ | ✅ |
| Priorización: comparación de métodos, segmentos, cola del día y explicación por cuenta | ✅ | ✅ | ✅ |
| Priorización: ejecutar sobre una carga | | ✅ | ✅ |
| Base de conocimiento, reglas difusas y simulador de consulta | ✅ | ✅ | ✅ |
| Metodología: los algoritmos del sistema explicados | ✅ | ✅ | ✅ |
| Cargas: registrar, simular y completar carteras | | ✅ | ✅ |
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

La aplicación del equipo ya está publicada en
**https://gestion-cartera.streamlit.app**, desplegada desde `main`. Estos son
los pasos por si hay que volver a crearla o publicar una copia:

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

## Simulación de carteras

El módulo de simulación genera carteras completas a partir de
`datos/perfil_demo.json`, un perfil estadístico de referencia: frecuencias y
cuantiles redondeados, con etiquetas genéricas. Sirve para dimensionar
campañas, capacitar al equipo y verificar el sistema sin exponer ninguna
asignación.

El muestreo conserva las relaciones que más pesan en el recaudo —el saldo según
el código de gestión, la mora según el mes de asignación, el margen según la
franja de saldo— y las reglas de negocio: solo los códigos de acuerdo generan
proyección de pago, la franja se deriva del máximo de cobranza y el rango de
mora de los días de mora.

Los registros simulados nunca se confunden con los de una asignación:

- Los documentos van en un rango de diez dígitos que empieza por 99, que no
  corresponde a cédulas expedidas.
- Los correos usan el dominio reservado `.test`: ningún mensaje puede
  entregarse.
- Los celulares usan el prefijo 399.
- Todo registro simulado lleva la marca `ES_DEMO` y su carga queda con origen
  `SINTETICO`.

---

## Base de datos

| Tabla | Contenido |
|---|---|
| `cargas` | Una fila por carga: fecha, origen, cantidad de cuentas, saldo y meta de recaudo |
| `cartera` | Una fila por crédito y carga, con la cartera ya procesada |
| `ejecuciones_motor` | Una fila por ejecución del motor: quién, cuándo, sobre qué carga y para qué fecha |
| `evaluaciones` | El resultado de cada cuenta en cada ejecución, con sus reglas y su explicación |
| `priorizaciones` | Una fila por priorización: método elegido, segmentos, silueta y métricas de los tres métodos |
| `prioridades` | El segmento, los tres puntajes, la posición y si entra en la cola del día, por cuenta |
| `gestiones` | Cada contacto registrado por un gestor, con el estado que el motor asignaba a la cuenta en ese momento |
| `titulares` | Directorio: nombre, documento enmascarado y ciudad de cada titular |
| `contactos` | Teléfonos y correos de cada titular, con su estado (sin verificar, válido o errado) |
| `autorizaciones_canal` | Qué canales autorizó el titular para gestión de cobranza, con su origen y quién lo registró |
| `planes` y `plan_asignaciones` | Plan de trabajo del día y la cuenta asignada a cada gestor |
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
│   ├── sembrar_supabase.yml    Registro manual de una cartera simulada en Supabase
│   ├── mantener_activa.yml     Consulta periódica para evitar la pausa
│   └── crear_issues.yml        Creación de los issues de una lista de tareas por área
├── .github/tareas/             Listas de tareas por área y el script que las publica
├── .devcontainer/              Entorno de GitHub Codespaces
├── .streamlit/config.toml      Configuración de la aplicación web (sin secretos)
├── config.py                   Parámetros del negocio, normativa, seguridad y roles
├── datos/
│   ├── cargador.py             Carga, limpieza, seudonimización y derivación
│   ├── perfilador.py           Perfil estadístico de la asignación
│   ├── perfil_demo.json        Perfil estadístico de referencia (solo agregados)
│   ├── generador.py            Simulación y enmascarado de carteras
│   ├── base_datos.py           Esquema, cargas históricas, resultados y auditoría
│   ├── completar.py            Completado de cargas a las que les faltan datos
│   └── configurar_conexion.py  Configuración asistida de la conexión a Supabase
├── motor/
│   ├── base_conocimiento.py    Reglas de elegibilidad con su fundamento
│   └── elegibilidad.py         Motor de inferencia y módulo de explicación
├── docs/
│   ├── ALGORITMOS.md           Algoritmos, métodos matemáticos y modelos financieros
│   ├── TRABAJO_EN_EQUIPO.md    Flujo de trabajo del equipo con ramas y pull requests
│   ├── ESTADO_POR_AREA.md      Lo completo y lo pendiente de cada área, con su responsable
│   └── PLAN_DE_PRUEBAS.md      Casos para las sesiones de pruebas conjuntas
├── analisis/
│   ├── criterios.py            Criterios de decisión comunes a todos los métodos
│   └── segmentacion.py         K-Means, Ward y mezcla gaussiana con selección del óptimo
├── decision/
│   ├── conocimiento_difuso.py  Variables, conjuntos y reglas difusas
│   └── priorizacion.py         Difuso, TOPSIS, ponderación y selección del óptimo
├── gestion/
│   ├── operacion.py            Registro de gestiones y reglas de validación
│   ├── titulares.py            Directorio de titulares y datos de contacto
│   └── plan.py                 Plan de trabajo diario con reparto en serpentina
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

Comandos de terminal para administración. Verificar la conexión con la base
configurada:

```bash
python -m datos.base_datos probar
```

Simular una cartera y registrarla:

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

Exportar una cartera simulada a Excel, con la misma estructura de una
asignación:

```bash
python -m datos.generador
```

Ejecutar el motor de elegibilidad sobre la carga más reciente, para una fecha:

```bash
python -m motor.elegibilidad --fecha 2026-09-15
```

Segmentar y priorizar las cuentas contactables de una ejecución del motor:

```bash
python -m decision.priorizacion --ejecucion 1
```

---

## Trabajo en equipo

El equipo trabaja con ramas y *pull requests* sobre `main`, cada integrante en su
propio Codespace con el mismo entorno y la misma conexión a la base compartida.
La guía completa (configuración inicial, flujo diario, reparto por módulos, base
compartida y personal) está en [`docs/TRABAJO_EN_EQUIPO.md`](docs/TRABAJO_EN_EQUIPO.md),
y los casos de las sesiones de pruebas conjuntas en
[`docs/PLAN_DE_PRUEBAS.md`](docs/PLAN_DE_PRUEBAS.md).

Las observaciones, mejoras, cambios y errores se registran como *issues* de
GitHub con una plantilla para cada tipo, y se siguen en el tablero del equipo.
Cada commit que atiende uno lo menciona con su número (`#12`), y el *pull
request* que lo resuelve lo cierra al fusionarse.

---

## Protección de datos

1. **Ningún archivo de datos entra al repositorio.** El `.gitignore` excluye
   Excel, CSV y bases de datos.
2. **Seudonimización con clave.** Los identificadores se firman con HMAC-SHA256
   y una clave secreta. Un hash simple de un número de diez dígitos se puede
   revertir probando todos los valores posibles; sin la clave, no.
3. **Credenciales fuera del código.** Viven en `.env` en local y en los secretos
   de GitHub en la nube, nunca en el repositorio.
4. **Row Level Security** activo en todas las tablas de PostgreSQL.
5. **Asignaciones desde archivo solo en la base local.** El sistema se niega a
   enviar una asignación cargada desde archivo a una base remota sin una
   confirmación explícita en el código; desde la web solo se registran carteras
   simuladas.

---

## Estado del proyecto

| Fase | Módulo | Estado |
|---|---|---|
| 1 | Carga, limpieza y seudonimización | ✅ |
| 1b | Base de datos con historial de cargas | ✅ |
| 1c | Simulación y enmascarado de carteras | ✅ |
| 1d | Base externa en Supabase y ejecución en GitHub | ✅ |
| 2 | Motor de reglas de elegibilidad de contacto | ✅ |
| 2b | Aplicación web con ingreso, roles y auditoría | ✅ |
| 3 | Segmentación (K-Means, Ward, mezcla gaussiana) y priorización (difusa, TOPSIS, ponderación) con selección del óptimo | ✅ |
| 3b | Gestión de cuentas con reglas de validación y actualización de la cartera | ✅ |
| 3c | Directorio de titulares, plan de trabajo diario y traza de trabajo | ✅ |
| 4 | Modelo de propensión a compromiso de pago | Pendiente |
| 5 | Optimización de campañas y asignación | Pendiente |

El detalle de lo completo y lo pendiente en cada área, con su responsable, está
en [`docs/ESTADO_POR_AREA.md`](docs/ESTADO_POR_AREA.md).

---

## Autor

David Miller Aguilar Bayona — VIII Semestre, Ingeniería de Sistemas
