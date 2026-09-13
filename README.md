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
    ├─ Motor de reglas de elegibilidad       (Ley 2300 de 2023)
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
   └─ Actions: mantener  ──────────►  consulta cada tres días    ◄── equipo local
```

Nada depende de un equipo encendido: la base vive en Supabase y los procesos
automáticos corren en los servidores de GitHub.

| Pieza | Qué hace |
|---|---|
| **Pruebas** | En cada envío, GitHub levanta un PostgreSQL temporal, genera una cartera ficticia, la carga y verifica que quedó completa. |
| **Sembrar base en Supabase** | Botón manual en la pestaña Actions: genera una cartera ficticia en GitHub y la carga directo en Supabase. |
| **Mantener activa la base** | Consulta la base cada tres días para reducir el riesgo de que el plan gratuito de Supabase la pause por inactividad. |
| **Codespaces** | Entorno de desarrollo en el navegador, con Python y las dependencias instaladas automáticamente. |

---

## Configurar la base externa en Supabase

**1. Crear el proyecto.** En [supabase.com](https://supabase.com), crear un
proyecto nuevo. Región recomendada: *South America (São Paulo)*, la más cercana
a Colombia. Guardar la contraseña de la base que se define al crearlo.

**2. Copiar la cadena de conexión del pooler.** En el proyecto, botón
**Connect** → **Session pooler** → copiar la URI. Tiene esta forma:

```
postgresql://postgres.REFERENCIA:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
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

Dos tablas:

| Tabla | Contenido |
|---|---|
| `cargas` | Una fila por carga: fecha, origen, cantidad de cuentas, saldo y meta de recaudo |
| `cartera` | Una fila por crédito y carga, con la cartera ya procesada |

La llave de `cartera` es el par (carga, crédito): **cada carga se conserva junto
a las anteriores** en lugar de reemplazarlas. Una cuenta aparece una vez por
cada mes en que fue asignada, que es lo que permite entrenar modelos con
historia.

El motor se elige por configuración: SQLite local si no se define
`DATABASE_URL`, o PostgreSQL si se define. El código es el mismo en ambos casos.

---

## Estructura

```
.
├── .github/workflows/
│   ├── pruebas.yml             Integración continua contra PostgreSQL
│   ├── sembrar_supabase.yml    Carga manual de la cartera ficticia en Supabase
│   └── mantener_activa.yml     Consulta periódica para evitar la pausa
├── .devcontainer/              Entorno de GitHub Codespaces
├── config.py                   Parámetros del negocio y normativa de contacto
├── datos/
│   ├── cargador.py             Carga, limpieza, seudonimización y derivación
│   ├── perfilador.py           Perfil estadístico y perfil de demostración
│   ├── perfil_demo.json        Perfil de demostración (datos agregados)
│   ├── generador.py            Generación de carteras ficticias
│   └── base_datos.py           Esquema, cargas históricas y consultas
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

Verificar la conexión con la base configurada:

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

---

## Estado del proyecto

| Fase | Módulo | Estado |
|---|---|---|
| 1 | Carga, limpieza y seudonimización | ✅ |
| 1b | Base de datos con historial de cargas | ✅ |
| 1c | Generación de carteras ficticias | ✅ |
| 1d | Base externa en Supabase y ejecución en GitHub | ✅ |
| 2 | Motor de reglas de elegibilidad de contacto | Pendiente |
| 3 | Segmentación y priorización | Pendiente |
| 4 | Modelo de propensión a compromiso de pago | Pendiente |
| 5 | Optimización de campañas y asignación | Pendiente |
| 6 | Tablero web | Pendiente |

---

## Autor

David Miller Aguilar Bayona — VIII Semestre, Ingeniería de Sistemas
