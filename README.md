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
la **Ley 1581 de 2012**. El sistema aplica tres reglas:

1. **Ningún dato entra al repositorio.** El `.gitignore` excluye todo archivo
   Excel, CSV y base de datos. Se versiona el código, no la información.
2. **La identidad no circula por el sistema.** El módulo de carga reemplaza la
   cédula por un seudónimo SHA-256 estable e irreversible, convierte teléfonos y
   correos en un conteo de canales disponibles, y elimina nombres y direcciones
   antes de cualquier análisis.
3. **La configuración sensible vive en `.env`**, fuera del control de versiones:
   rutas internas, nombres de clientes y credenciales.

---

## Estructura

```
.
├── config.py            Parámetros del negocio, normativa de contacto y rutas
├── datos/
│   └── cargador.py      Carga, limpieza, anonimización y variables derivadas
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

Perfilar una asignación:

```bash
python datos/cargador.py
```

Produce el diagnóstico de la cartera: saldo total, meta de recaudo y brecha,
cuentas gestionadas frente a no gestionadas, embudo de resultados de contacto,
compromisos por tipo de acuerdo, contactabilidad, antigüedad en gestión y margen
de negociación. Al final verifica que ninguna columna con datos personales haya
llegado a la salida.

---

## Estado del proyecto

| Fase | Módulo | Estado |
|---|---|---|
| 1 | Carga, limpieza y anonimización | ✅ |
| 2 | Motor de reglas de elegibilidad de contacto | Pendiente |
| 3 | Segmentación y priorización | Pendiente |
| 4 | Modelo de propensión a compromiso de pago | Pendiente |
| 5 | Optimización de campañas y asignación | Pendiente |
| 6 | Tablero web | Pendiente |

---

## Autor

David Miller Aguilar Bayona — VIII Semestre, Ingeniería de Sistemas
