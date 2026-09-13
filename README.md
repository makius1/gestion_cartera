# Sistema Inteligente de Gestión de Cartera

Sistema experto de apoyo a la decisión para casas de cobranza. Toma la
asignación mensual de cartera y decide **qué cuentas trabajar, en qué orden,
por qué canal, con qué gestor y con qué oferta**, para maximizar el recaudo
esperado dentro de la capacidad operativa y las restricciones legales de
contacto.

Proyecto de la asignatura **Sistemas Expertos e Inteligencia Artificial**
(VIII Semestre, Ingeniería de Sistemas).

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
[1] CARGA, LIMPIEZA Y ANONIMIZACIÓN          ← implementado
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
regla. Los modelos de lenguaje, si se integran, quedan en el borde del sistema
(redacción de mensajes, resumen de notas) y nunca en la decisión.

---

## Protección de datos

Las asignaciones contienen datos personales de titulares reales, protegidos por
la **Ley 1581 de 2012**. El sistema aplica cuatro reglas:

1. **Ningún dato entra al repositorio.** El `.gitignore` excluye todo archivo
   Excel, CSV y base de datos. Se versiona el código, no la información.
2. **La identidad no circula por el sistema.** El módulo de carga reemplaza la
   cédula y el número de crédito por seudónimos firmados con HMAC-SHA256 y una
   clave secreta, convierte teléfonos y correos en un conteo de canales
   disponibles, y elimina nombres y direcciones antes de cualquier análisis.
   La firma con clave no es un detalle: un hash simple de una cédula se puede
   revertir probando los diez mil millones de valores posibles en minutos; sin
   la clave, no.
3. **La configuración sensible vive en `.env`**, fuera del control de versiones:
   rutas internas, nombres de clientes, credenciales y la clave de seudónimos.
4. **Los datos reales no suben a la nube por descuido.** La base de datos se
   niega a guardar una carga de origen REAL en un servidor remoto salvo
   confirmación explícita.

### Datos de prueba

El sistema ofrece dos formas de trabajar sin exponer la cartera real:

| Modo | Qué hace | ¿Puede salir de la empresa? |
|---|---|---|
| **Sintético** | Genera una cartera desde cero a partir de un perfil estadístico. Ningún registro corresponde a una persona real. | Sí: se puede compartir, subir a la nube o usar en una demostración. |
| **Enmascarado** | Toma la cartera real y reemplaza solo la identidad: nombres, documentos, créditos, teléfonos, correos, direcciones y gestores. Los montos, las moras y los códigos siguen siendo reales. | **No.** Quien tenga el archivo original puede reidentificar cruzando montos y fechas: sigue siendo dato personal. |

Los datos ficticios están diseñados para no poder usarse por error en una
campaña real: los documentos van en un rango que no corresponde a cédulas
expedidas, los correos usan el dominio `.test` reservado para pruebas, los
celulares usan el prefijo 399 y todo registro lleva la marca `ES_DEMO`.

---

## Estructura

```
.
├── config.py            Parámetros del negocio, normativa de contacto y rutas
├── datos/
│   ├── cargador.py      Carga, limpieza, seudonimización y variables derivadas
│   ├── perfilador.py    Perfil estadístico agregado de una asignación real
│   ├── generador.py     Carteras sintéticas y enmascarado de carteras reales
│   └── base_datos.py    Esquema, cargas históricas y consultas
├── .env.example         Plantilla de configuración local
├── .gitignore           Excluye datos, credenciales y entorno virtual
├── requirements.txt     Dependencias con versiones fijadas
└── README.md
```

---

## Instalación

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

Después:

```bash
pip install -r requirements.txt
```

Copiar `.env.example` como `.env` y definir la ruta del archivo de asignación.

---

## Uso

### Diagnóstico de una asignación

```bash
python datos/cargador.py
```

Produce el diagnóstico de la cartera: saldo total, meta de recaudo y brecha,
cuentas gestionadas frente a no gestionadas, embudo de resultados de contacto,
compromisos por tipo de acuerdo, contactabilidad, antigüedad en gestión y margen
de negociación. Al final verifica que ninguna columna con datos personales haya
llegado a la salida.

### Generar datos de prueba

Extraer el perfil estadístico de la asignación real (una sola vez):

```bash
python datos/perfilador.py
```

Generar una cartera sintética del mismo tamaño y compararla con la real:

```bash
python -m datos.generador --validar
```

Generar una cartera sintética de otro tamaño:

```bash
python -m datos.generador --registros 1000
```

Enmascarar la cartera real para pruebas internas:

```bash
python -m datos.generador --enmascarar
```

### Base de datos

Crear las tablas:

```bash
python -m datos.base_datos crear
```

Cargar una cartera sintética:

```bash
python -m datos.base_datos sintetica
```

Cargar la asignación real (solo en la base local):

```bash
python -m datos.base_datos real
```

Listar las cargas registradas:

```bash
python -m datos.base_datos cargas
```

Cada carga se conserva junto a las anteriores: la tabla `cartera` usa como
llave el par (carga, crédito), de modo que una cuenta aparece una vez por cada
mes en que fue asignada. Es lo que permite entrenar modelos con historia real.

---

## Estado del proyecto

| Fase | Módulo | Estado |
|---|---|---|
| 1 | Carga, limpieza y seudonimización | ✅ |
| 1b | Base de datos con historial de cargas | ✅ |
| 1c | Generación de datos sintéticos y enmascarado | ✅ |
| 2 | Motor de reglas de elegibilidad de contacto | Pendiente |
| 3 | Segmentación y priorización | Pendiente |
| 4 | Modelo de propensión a compromiso de pago | Pendiente |
| 5 | Optimización de campañas y asignación | Pendiente |
| 6 | Tablero web | Pendiente |

---

## Validación del generador sintético

Comparación de la cartera sintética contra la real, ambas procesadas por el
mismo cargador:

| Métrica | Diferencia |
|---|---|
| Saldo total | −0.7 % |
| Saldo mediano | −1.3 % |
| Mora mediana | 0.0 % |
| Cuentas nunca gestionadas | −3.7 % |
| Cuentas sin margen | −3.8 % |

La cantidad de compromisos de pago varía entre generaciones porque son apenas
el 1.5 % de las cuentas: en ocho generaciones con semillas distintas oscila
entre 93 y 130 y promedia exactamente lo mismo que la cartera real.

**Limitación conocida:** el margen de negociación promedio queda
sistemáticamente un 10 % por debajo del real. El generador conserva las
relaciones entre variables que más pesan en el recaudo —saldo según código,
mora según mes de asignación, margen según franja—, pero no todas; el margen
depende además de alguna variable que no se está condicionando.

---

## Autor

David Miller Aguilar Bayona — VIII Semestre, Ingeniería de Sistemas
