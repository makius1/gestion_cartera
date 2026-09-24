# Estimación de esfuerzo y costo

Cuánto esfuerzo, tiempo y dinero costaría construir el sistema tal como está
en `main`, estimado con cuatro técnicas independientes y consolidado al final:

1. Puntos de historia con *Planning Poker*.
2. Análisis de puntos de función (FPA, IFPUG).
3. COCOMO II, modelo Post-Arquitectura.
4. Juicio de expertos con Wideband Delphi.

Aplica el mismo principio del sistema: **ninguna cifra depende de un solo
método**. Cada técnica mira el proyecto desde un ángulo distinto (valor para el
usuario, funcionalidad, tamaño del código y experiencia del equipo), y la
estimación final sale de compararlas.

La pregunta que responde es: *¿cuánto costaría que un equipo profesional
construyera este sistema desde cero, en condiciones normales de trabajo?* El
historial de git no registra horas, así que no se usa para calibrar.

---

## Supuestos comunes

| Supuesto | Valor | Nota |
|---|---|---|
| Equipo | 4 desarrolladores | Uno por área, como en [`ESTADO_POR_AREA.md`](ESTADO_POR_AREA.md) |
| Persona-mes (PM) | 152 horas | El valor estándar de COCOMO II |
| Salario de referencia | COP 5.500.000 al mes | Desarrollador Python semi-senior en Colombia; ajustable |
| Factor prestacional | 1,52 | Prestaciones sociales, seguridad social y parafiscales |
| Costo cargado por persona-mes | COP 8.360.000 | 5.500.000 × 1,52 |
| Costo por hora | COP 55.000 | 8.360.000 / 152 |
| *Sprint* | 2 semanas (10 días hábiles) | |
| Horas productivas por día | 6 | Descontadas reuniones, revisiones e interrupciones |
| Moneda | Pesos colombianos (COP) de 2026 | Sin IVA |

Si cambia el salario de referencia, todos los costos cambian en la misma
proporción: el esfuerzo en horas no depende de él.

## Tamaño medido del producto

| Carpeta | Líneas de código (SLOC) | Qué contiene |
|---|---:|---|
| `datos/` | 2.122 | Carga, seudonimización, simulación, base de datos, autorizaciones |
| `app/` | 1.919 | Aplicación web: 15 pantallas, ingreso y menú por rol |
| `motor/` | 736 | Base de conocimiento, motor de inferencia, muestreo de Thompson |
| `gestion/` | 619 | Gestiones, titulares, obligaciones, plan de trabajo |
| `decision/` | 423 | Lógica difusa, TOPSIS, ponderación |
| `analisis/` | 351 | Criterios, segmentación, propensión |
| `seguridad/` | 224 | Contraseñas, ingreso, usuarios y roles |
| `config.py` | 150 | Parámetros del negocio y de la ley |
| **Producto** | **6.544** | Base del cálculo de COCOMO II |
| `pruebas/` | 990 | Diez archivos de pruebas automáticas |
| `.github/` | 126 | Script de creación de *issues* (más 490 líneas de flujos YAML) |

Se cuentan las líneas lógicas de Python, con el analizador léxico de Python
(`tokenize`): sin líneas en blanco, comentarios ni *docstrings*. Otros
indicadores del alcance:

- 16 tablas.
- 21 reglas de elegibilidad, 14 reglas difusas y 10 reglas de validación.
- 15 algoritmos en la tabla de procesos de [`ALGORITMOS.md`](ALGORITMOS.md).
- 5 flujos de GitHub Actions.
- 7 documentos técnicos, contando este.

---

## 1. Puntos de historia y Planning Poker

### Cómo se estima

Cada historia de usuario recibe un número de la serie de Fibonacci (1, 2, 3,
5, 8, 13, 21), que mide su tamaño **relativo**: complejidad, cantidad de
trabajo e incertidumbre juntas. En *Planning Poker*:

1. El dueño del producto lee la historia y el equipo aclara dudas.
2. Cada integrante elige una carta en secreto y todos la muestran a la vez,
   para que nadie se ancle en la opinión de otro.
3. Si los votos difieren, explican su voto quien votó más alto y quien votó
   más bajo, porque ellos ven algo que los demás no ven.
4. Se vuelve a votar hasta llegar a consenso.

**Historia de referencia:** *HU02, seudonimización con HMAC* = **3 puntos**.
Todas las demás se comparan contra ella: "¿esto es más o menos que el doble
de la seudonimización?".

*Ejemplo del procedimiento* con la HU10, el motor de inferencia:

| Ronda | Votos | Discusión |
|---|---|---|
| 1 | 5 · 8 · 13 · 21 | Quien votó 5 lo veía como un recorrido de reglas. Quien votó 21 señaló las cinco fases, el corte al primer bloqueo, la resolución de conflictos, la explicación en lenguaje natural y el registro de cada ejecución. |
| 2 | 13 · 13 · 13 · 8 | Quien votó 8 aceptó que la explicación y el registro agregan trabajo real. |
| 3 | 13 · 13 · 13 · 13 | Consenso: **13** |

### Pila del producto

| Id | Historia de usuario | Puntos |
|---|---|---:|
| | **Épica 1. Datos e infraestructura** | **55** |
| HU01 | Como supervisor, quiero cargar y depurar la asignación mensual en Excel | 8 |
| HU02 | Como responsable de datos, quiero seudonimizar cédulas y créditos con clave | 3 |
| HU03 | Como equipo, quiero simular carteras realistas a partir de un perfil estadístico | 13 |
| HU04 | Como sistema, quiero guardar cada carga con historia en SQLite o PostgreSQL | 8 |
| HU05 | Como equipo, quiero una base compartida en Supabase protegida con RLS | 5 |
| HU06 | Como equipo, quiero pruebas, siembra, respaldo y mantenimiento automáticos en GitHub | 8 |
| HU07 | Como responsable de datos, quiero protecciones contra escribir en la base equivocada y contra un reloj errado | 5 |
| HU08 | Como sistema, quiero guardar qué canales autorizó cada titular | 5 |
| | **Épica 2. Motor de elegibilidad** | **37** |
| HU09 | Como experto, quiero declarar las 21 reglas con su fundamento legal | 8 |
| HU10 | Como supervisor, quiero saber qué cuentas se pueden contactar hoy y por qué | 13 |
| HU11 | Como sistema, quiero respetar días hábiles, festivos y horarios de la Ley 2300 | 3 |
| HU12 | Como supervisor, quiero que el canal se elija por la respuesta observada (Thompson) | 8 |
| HU13 | Como equipo, quiero una prueba de cada regla que dispara y otra que no | 5 |
| | **Épica 3. Analítica y decisión** | **61** |
| HU14 | Como analista, quiero criterios comunes de decisión por cuenta | 3 |
| HU15 | Como analista, quiero segmentar la cartera con tres algoritmos y elegir el mejor | 8 |
| HU16 | Como experto, quiero priorizar con reglas difusas lingüísticas | 8 |
| HU17 | Como supervisor, quiero comparar difuso, TOPSIS y ponderación y quedarme con el mejor | 8 |
| HU18 | Como gestor, quiero saber por qué una cuenta tiene su prioridad | 3 |
| HU19 | Como analista, quiero un historial de gestiones simulado con causa conocida | 5 |
| HU20 | Como analista, quiero entrenar y comparar cuatro modelos de propensión | 13 |
| HU21 | Como supervisor, quiero priorizar con la probabilidad del modelo y ver la diferencia | 5 |
| HU22 | Como supervisor, quiero un reparto óptimo de cuentas entre gestores | 8 |
| | **Épica 4. Gestión y aplicación web** | **72** |
| HU23 | Como gestor, quiero registrar el contacto con validaciones legales y de negocio | 13 |
| HU24 | Como gestor, quiero ver y corregir los datos de contacto del titular, enmascarados | 8 |
| HU25 | Como supervisor, quiero repartir las cuentas del día y ver el avance | 5 |
| HU26 | Como supervisor, quiero la traza por gestor y por cuenta | 5 |
| HU27 | Como gestor, quiero que otro gestor no reciba mi misma cuenta | 5 |
| HU28 | Como supervisor, quiero registrar una obligación suelta | 5 |
| HU29 | Como gestor, quiero registrar o revocar la autorización de un canal | 5 |
| HU30 | Como administrador, quiero ingreso seguro, roles y auditoría | 8 |
| HU31 | Como usuario, quiero las pantallas de consulta y administración | 13 |
| HU32 | Como equipo, quiero probar cada pantalla con cada rol en cada cambio | 5 |
| | **Épica 5. Documentación** | **8** |
| HU33 | Como equipo, quiero el README, los algoritmos, el manual y el plan de pruebas | 8 |
| | **Total** | **233** |

### Velocidad y resultado

- **Capacidad por *sprint*:** 4 personas × 10 días × 6 horas = 240 horas.
- **Horas por punto:** la historia de referencia (3 puntos) toma unas 24 horas
  con diseño, código, pruebas y revisión, así que 1 punto ≈ **8 horas**.
- **Velocidad:** 240 / 8 = **30 puntos por *sprint***.

| Resultado | Valor |
|---|---:|
| Tamaño | 233 puntos |
| *Sprints* | 233 / 30 = 7,8 → **8 *sprints*** (16 semanas, unos 3,7 meses) |
| Esfuerzo | 233 × 8 = **1.864 horas** = 12,3 PM |
| Costo | 1.864 × 55.000 = **COP 102.520.000** |

La cifra más baja de las cuatro es esperable. Los puntos se piensan desde lo
que ve el usuario, y la infraestructura, la integración y la documentación
quedan subrepresentadas: una historia de "5 puntos" como la base en Supabase
esconde configuración, seguridad y respaldos.

---

## 2. Análisis de puntos de función (FPA)

Mide la funcionalidad que el sistema entrega al usuario, sin importar el
lenguaje, con el método IFPUG: cinco tipos de componentes, cada uno con una
complejidad según sus datos elementales (DET) y sus registros o archivos
referenciados (RET/FTR).

### Archivos lógicos internos (ILF)

Grupos de datos que el propio sistema mantiene. Dos tablas que siempre se
usan juntas cuentan como un solo archivo con dos registros (RET).

| ILF | RET | DET | Complejidad | Peso |
|---|---:|---|---|---:|
| Priorizaciones y prioridades | 2 | 20 a 50 | Media | 10 |
| Cartera | 1 | 20 a 50 | Baja | 7 |
| Ejecuciones del motor y evaluaciones | 2 | menos de 20 | Baja | 7 |
| Planes y asignaciones | 2 | menos de 20 | Baja | 7 |
| Cargas | 1 | menos de 20 | Baja | 7 |
| Modelos de propensión | 1 | menos de 20 | Baja | 7 |
| Gestiones | 1 | menos de 20 | Baja | 7 |
| Titulares y contactos | 2 | menos de 20 | Baja | 7 |
| Autorizaciones por canal | 1 | menos de 20 | Baja | 7 |
| Reservas | 1 | menos de 20 | Baja | 7 |
| Usuarios | 1 | menos de 20 | Baja | 7 |
| Auditoría | 1 | menos de 20 | Baja | 7 |
| **Subtotal** | | | | **87** |

Los DET salen de las columnas de cada tabla en `datos/base_datos.py`. La
cartera tiene 33 columnas, pero con un solo registro la matriz de IFPUG la
deja en complejidad baja: pasa a media solo con más de 50 datos elementales.

### Archivos de interfaz externa (EIF)

Datos que el sistema consulta, pero mantiene otro:

| EIF | Complejidad | Peso |
|---|---|---:|
| Calendario de festivos de Colombia (librería `holidays`) | Baja | 5 |
| Perfil estadístico de referencia (`perfil_demo.json`) | Baja | 5 |
| **Subtotal** | | **10** |

### Entradas externas (EI)

| Complejidad | Peso | Entradas | Puntos |
|---|---:|---|---:|
| Alta | 6 | Registrar carga desde Excel · registrar obligación · ejecutar el motor · ejecutar la priorización · crear el plan · registrar la gestión | 36 |
| Media | 4 | Simular cartera · completar carga · entrenar la propensión · agregar contacto · registrar autorización · reservar cuenta · crear usuario · ingresar · simular historial | 36 |
| Baja | 3 | Marcar contacto válido o errado · editar titular · cambiar rol o estado · restablecer contraseña · cambiar la contraseña propia | 15 |
| **Subtotal** | | 20 entradas | **87** |

### Salidas externas (EO)

Salidas con datos calculados:

| Complejidad | Peso | Salidas | Puntos |
|---|---:|---|---:|
| Alta | 7 | Tablero frente a la meta · comparación de métodos de priorización · segmentación con PCA | 21 |
| Media | 5 | "¿Por qué?" del motor · explicación de la prioridad · comparación de modelos · avance del plan · traza por gestor · traza por cuenta · respaldo de la base · simulador de hechos | 40 |
| Baja | 4 | Descarga CSV de la cartera · exportación de la cartera simulada a Excel | 8 |
| **Subtotal** | | 13 salidas | **69** |

### Consultas externas (EQ)

Consultas sin cálculos:

| Complejidad | Peso | Consultas | Puntos |
|---|---:|---|---:|
| Media | 4 | Cartera con filtros · auditoría con filtros | 8 |
| Baja | 3 | Buscar cuenta · mostrar el dato completo de un contacto · cargas · usuarios · reglas de la base de conocimiento · autorizaciones del titular · mi cuenta · historial de gestiones · metodología | 27 |
| **Subtotal** | | 11 consultas | **35** |

**Puntos de función sin ajustar (PFSA):** 87 + 10 + 87 + 69 + 35 = **288**.

### Factor de ajuste

Las 14 características generales del sistema se califican de 0 (sin
influencia) a 5 (influencia esencial):

| # | Característica | Valor | Por qué |
|---:|---|---:|---|
| 1 | Comunicación de datos | 4 | Aplicación web contra una base remota |
| 2 | Procesamiento distribuido | 2 | Aplicación, base y CI en servicios distintos |
| 3 | Rendimiento | 3 | Priorización vectorizada de miles de cuentas |
| 4 | Configuración muy utilizada | 2 | Planes gratuitos con límites |
| 5 | Tasa de transacciones | 1 | Pocos usuarios simultáneos |
| 6 | Entrada de datos en línea | 5 | Toda la operación es en línea |
| 7 | Eficiencia para el usuario final | 4 | Siguiente cuenta, filtros, explicaciones |
| 8 | Actualización en línea | 4 | La gestión actualiza la cartera en la misma transacción |
| 9 | Procesamiento complejo | 5 | Inferencia, lógica difusa, optimización y aprendizaje automático |
| 10 | Reutilización | 3 | Criterios y parámetros comunes a todos los métodos |
| 11 | Facilidad de instalación | 3 | Codespaces y dependencias fijadas |
| 12 | Facilidad de operación | 4 | Respaldos, siembra y pruebas automáticos |
| 13 | Múltiples sitios | 1 | Una sola instalación |
| 14 | Facilidad de cambio | 4 | Reglas declaradas como datos y parámetros en `config.py` |
| | **Total (TDI)** | **45** | |

$$
\mathit{VAF} = 0{,}65 + 0{,}01 \times \mathit{TDI} = 0{,}65 + 0{,}45 = 1{,}10
$$

$$
\mathit{PF} = \mathit{PFSA} \times \mathit{VAF} = 288 \times 1{,}10 = 316{,}8 \approx 317
$$

### Resultado

Con una tasa de entrega de **8 horas por punto de función** (supuesto para un
desarrollo nuevo con un equipo pequeño y un lenguaje de alto nivel; los
valores usuales van de 5 a 15):

| Resultado | Valor |
|---|---:|
| Tamaño | 317 PF |
| Esfuerzo | 317 × 8 = **2.536 horas** = 16,7 PM |
| Costo | 2.536 × 55.000 = **COP 139.480.000** |

**Verificación cruzada:** 6.544 SLOC / 317 PF ≈ **21 líneas por punto de
función**. Es una proporción coherente con un lenguaje de alto nivel como
Python, apoyado en librerías (pandas, scikit-learn, SciPy, Streamlit) que
resuelven buena parte de cada función.

---

## 3. COCOMO II (modelo Post-Arquitectura)

Estima el esfuerzo a partir del tamaño del código y de las condiciones del
proyecto:

$$
\mathit{PM} = A \times \mathit{Tamaño}^{E} \times \prod_{i=1}^{17} \mathit{EM}_i
\qquad E = B + 0{,}01 \sum_{j=1}^{5} \mathit{SF}_j
$$

con $A = 2{,}94$, $B = 0{,}91$ y el tamaño en miles de líneas (**6,544
KSLOC**, medido arriba).

### Factores de escala

Afectan el exponente, es decir, cuánto crece el esfuerzo con el tamaño:

| Factor | Nivel | Valor | Por qué |
|---|---|---:|---|
| PREC · Precedentes | Nominal | 3,72 | Sistemas expertos conocidos, dominio de cobranza nuevo para el equipo |
| FLEX · Flexibilidad | Alto | 2,03 | Requisitos académicos con margen para decidir |
| RESL · Resolución de riesgos | Nominal | 4,24 | Arquitectura definida desde el inicio, riesgos atendidos por *issues* |
| TEAM · Cohesión del equipo | Alto | 2,19 | Áreas con dueño, revisión por *pull request* |
| PMAT · Madurez del proceso | Nominal | 4,68 | *Issues*, ramas, revisión y CI, equivalente a CMM nivel 2 |
| **Suma** | | **16,86** | |

$$
E = 0{,}91 + 0{,}01 \times 16{,}86 = 1{,}0786
$$

### Multiplicadores de esfuerzo

Se muestran solo los que no son nominales (1,00):

| Multiplicador | Nivel | Valor | Por qué |
|---|---|---:|---|
| DATA · Tamaño de la base | Alto | 1,14 | Carteras de miles de cuentas con historia, frente a 6.500 líneas de código |
| CPLX · Complejidad | Alto | 1,17 | Inferencia, lógica difusa, optimización lineal entera y modelos de aprendizaje |
| DOCU · Documentación | Alta | 1,11 | Documentación matemática, manual por rol, plan de pruebas |
| PVOL · Volatilidad de la plataforma | Baja | 0,87 | Python, Streamlit y PostgreSQL estables |
| PCON · Continuidad del personal | Alta | 0,90 | El mismo equipo de principio a fin |
| APEX · Experiencia en la aplicación | Baja | 1,10 | Primer sistema de cobranza del equipo |
| LTEX · Experiencia en lenguaje y herramientas | Alta | 0,91 | Python y Git conocidos |
| TOOL · Herramientas | Alto | 0,90 | Codespaces, GitHub Actions, pruebas automáticas |
| SITE · Desarrollo distribuido | Alto | 0,93 | Trabajo remoto con repositorio y tablero compartidos |

Los demás (RELY, RUSE, TIME, STOR, ACAP, PCAP, PLEX y SCED) quedan en
nominal.

$$
\mathit{EAF} = 1{,}14 \times 1{,}17 \times 1{,}11 \times 0{,}87 \times 0{,}90 \times 1{,}10 \times 0{,}91 \times 0{,}90 \times 0{,}93 = 0{,}971
$$

### Resultado

$$
\mathit{PM} = 2{,}94 \times 6{,}544^{1{,}0786} \times 0{,}971 = 22{,}30 \times 0{,}971 = 21{,}7
$$

$$
\mathit{TDEV} = 3{,}67 \times \mathit{PM}^{\,0{,}28 + 0{,}2\,(E - B)} = 3{,}67 \times 21{,}7^{0{,}3137} = 9{,}6 \text{ meses}
$$

| Resultado | Valor |
|---|---:|
| Esfuerzo | **21,7 PM** = 3.292 horas |
| Tiempo de desarrollo nominal | 9,6 meses |
| Personal promedio | 21,7 / 9,6 = 2,3 personas |
| Costo | 21,7 × 8.360.000 = **COP 181.074.000** |

COCOMO da la cifra más alta porque cuenta todo el ciclo de desarrollo
(diseño, código, integración y pruebas) y porque el código de este proyecto
es denso: una línea de pandas o SciPy hace el trabajo de muchas en otros
lenguajes. Su calendario de 9,6 meses supone la dotación óptima de 2,3
personas. Con 4 personas el calendario se acorta, pero no a la mitad: COCOMO
no admite comprimir por debajo del 75 % del nominal, y cada compresión
encarece el esfuerzo (multiplicador SCED).

---

## 4. Juicio de expertos: Wideband Delphi

### Cómo se estima

1. **Preparación:** el coordinador entrega a cada estimador la misma
   descripción del alcance: las cinco épicas, la arquitectura y los
   supuestos comunes.
2. **Reunión de arranque:** se discuten el alcance y los supuestos, sin dar
   cifras.
3. **Estimación individual y anónima** del esfuerzo total en horas, por
   épica.
4. **Reunión de revisión:** el coordinador muestra las cifras sin nombres. Se
   discuten las diferencias grandes y las tareas que alguien olvidó o
   sobrestimó.
5. Se repiten las rondas hasta que la dispersión (rango / media) baje del
   10 %.

El panel tiene cuatro estimadores, uno con el perfil de cada área (datos e
infraestructura, motor, analítica y gestión con aplicación web). Las rondas
que siguen son el ejercicio de estimación de este documento; si el equipo
repite la sesión, se reemplazan por sus cifras.

### Rondas

| Estimador | Ronda 1 | Ronda 2 | Ronda 3 |
|---|---:|---:|---:|
| A | 1.700 | 2.200 | 2.450 |
| B | 3.400 | 2.900 | 2.700 |
| C | 2.300 | 2.500 | 2.550 |
| D | 3.000 | 2.800 | 2.650 |
| **Media** | 2.600 | 2.600 | 2.588 |
| **Rango** | 1.700 | 700 | 250 |
| **Dispersión** | 65,4 % | 26,9 % | **9,7 %** |

Lo que cambió entre rondas:

- **De la 1 a la 2:** A no había contado los flujos de respaldo y restauración
  ni las pruebas de concurrencia de las reservas. B había sumado dos veces la
  lógica difusa, en la priorización y en la explicación.
- **De la 2 a la 3:** se acordó que la documentación matemática es trabajo
  propio y no un subproducto del código.

Con la dispersión por debajo del 10 %, el panel se detiene en la ronda 3.

### Consenso por épica (ronda 3)

| Épica | Horas |
|---|---:|
| 1. Datos e infraestructura | 620 |
| 2. Motor de elegibilidad | 430 |
| 3. Analítica y decisión | 640 |
| 4. Gestión y aplicación web | 760 |
| 5. Documentación | 140 |
| **Total** | **2.590** |

### Resultado con estimación de tres puntos (PERT)

Con el mínimo, la mediana y el máximo de la ronda final:

$$
E = \frac{O + 4M + P}{6} = \frac{2.450 + 4 \times 2.600 + 2.700}{6} = 2.592 \text{ horas}
$$

| Resultado | Valor |
|---|---:|
| Esfuerzo | **2.592 horas** = 17,1 PM |
| Costo | 2.592 × 55.000 = **COP 142.542.000** |

---

## 5. Consolidación

| Técnica | Mira | Horas | PM | Costo (COP) |
|---|---|---:|---:|---:|
| Puntos de historia | Valor para el usuario | 1.864 | 12,3 | 102.520.000 |
| Puntos de función | Funcionalidad entregada | 2.536 | 16,7 | 139.480.000 |
| COCOMO II | Tamaño del código y condiciones del proyecto | 3.292 | 21,7 | 181.074.000 |
| Wideband Delphi | Experiencia del equipo | 2.592 | 17,1 | 142.542.000 |

Las cuatro técnicas quedan entre 12 y 22 PM, y las dos que no parten del
código ni de las historias (FPA y Delphi) casi coinciden, entre 16,7 y 17,1
PM. La estimación final combina las cuatro con PERT: el optimista es la
menor, el pesimista la mayor y el más probable la mediana (16,9 PM, el
promedio de FPA y Delphi).

$$
\mathit{PM} = \frac{12{,}3 + 4 \times 16{,}9 + 21{,}7}{6} = 16{,}9 \text{ PM}
\qquad
\sigma = \frac{21{,}7 - 12{,}3}{6} = 1{,}6 \text{ PM}
$$

**Estimación final: 16,9 PM ± 1,6** (entre 15,3 y 18,5 PM), unas **2.569
horas**.

### Presupuesto

| Concepto | Costo (COP) |
|---|---:|
| Desarrollo: 16,9 PM × 8.360.000 | 141.273.000 |
| Contingencia (10 %) | 14.127.000 |
| Infraestructura durante el desarrollo | 0 |
| Licencias de software | 0 |
| **Total** | **155.400.000** |

**Calendario de referencia:** 4 personas durante **5 meses**: 20 PM de
capacidad para cubrir los 18,6 PM que suman la estimación y la contingencia.
Frente a COCOMO es un calendario comprimido: para 16,9 PM su calendario
nominal es de 8,9 meses con unas 2 personas, y no admite bajar del 75 % (6,7
meses) sin encarecer el esfuerzo. Los 5 meses son viables porque el trabajo se
reparte en cuatro áreas separadas por carpetas, cada una con dueño, que
avanzan en paralelo con poca coordinación entre sí; si esa independencia
fallara, el plan realista sería de unos 7 meses.

### Costos no laborales

| Recurso | Uso en el proyecto | Costo académico | Costo de referencia en producción |
|---|---|---:|---|
| GitHub (repositorio, Actions, Codespaces) | Código, CI y entorno de desarrollo | 0 | 0 en repositorio público; los minutos adicionales de Codespaces se cobran por uso |
| Supabase (PostgreSQL) | Base compartida | 0 (plan gratuito) | Plan Pro, USD 25 al mes |
| Streamlit Community Cloud | Aplicación publicada | 0 | 0 para aplicaciones públicas; una aplicación privada necesita otro alojamiento |
| Python y librerías | Todo el sistema | 0 | 0 (código abierto) |

El plan gratuito basta para un proyecto académico. En producción, lo mínimo
sería la base en un plan pago (por respaldos gestionados y porque no se pausa
por inactividad) y un alojamiento privado para la aplicación.

---

## 6. Por qué las técnicas difieren

- **Los puntos de historia** estiman lo que el equipo cree que puede hacer. Son
  buenos para planear *sprints*, pero subestiman el trabajo que no se ve en
  la pantalla.
- **Los puntos de función** no dependen del lenguaje, y por eso sirven para
  comparar con otros proyectos. No ven la complejidad algorítmica: un
  "ejecutar la priorización" pesa lo mismo con uno o con tres métodos.
- **COCOMO II** es el más reproducible: cualquiera que mida el mismo código
  obtiene el mismo tamaño. Pero en un lenguaje tan expresivo como Python cada
  línea carga mucho trabajo, y el modelo se calibró con proyectos en otros
  lenguajes.
- **Wideband Delphi** incorpora lo que ningún modelo ve (el dominio, los
  riesgos, lo que ya salió mal), a costa de depender de quién opine.

Por eso se usan las cuatro, como el sistema usa varios algoritmos en cada
decisión: la coincidencia entre FPA y Delphi, y el hecho de que las cuatro
queden en el mismo orden de magnitud, respaldan la cifra final.

---

## Referencias

- Albrecht, A. (1979). Measuring application development productivity. *Proceedings of the Joint SHARE/GUIDE/IBM Application Development Symposium*, 83-92.
- Boehm, B. (1981). *Software Engineering Economics*. Prentice Hall.
- Boehm, B., Abts, C., Brown, A., Chulani, S., Clark, B., Horowitz, E., Madachy, R., Reifer, D. y Steece, B. (2000). *Software Cost Estimation with COCOMO II*. Prentice Hall.
- Cohn, M. (2005). *Agile Estimating and Planning*. Prentice Hall.
- Grenning, J. (2002). *Planning Poker or How to Avoid Analysis Paralysis while Release Planning*. Renaissance Software Consulting.
- IFPUG (2010). *Function Point Counting Practices Manual*, versión 4.3.1. International Function Point Users Group.
- Wiegers, K. (2000). Stop promising miracles. *Software Development*, febrero de 2000.
