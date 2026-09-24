# Algoritmos y modelos del sistema

Este documento explica cada algoritmo que usa el sistema: **qué hace dentro
del sistema, qué busca, qué método matemático aplica y qué decide o predice**.
Al final reúne la revisión de modelos usados en el sector financiero, su
compatibilidad con el proyecto y el modelo recomendado para el entrenamiento.

## Principio de diseño: ninguna decisión depende de un solo algoritmo

Cada proceso que el sistema automatiza pasa por **varios algoritmos** y se
queda con el mejor para la cartera del momento, según métricas explícitas. La
única excepción es la elegibilidad legal de contacto: una norma no se elige por
desempeño, se cumple, y por eso se resuelve con un sistema de reglas
determinista y auditable.

| Proceso | Algoritmos que compiten | Cómo se elige el mejor | Estado |
|---|---|---|---|
| Elegibilidad de contacto | Sistema experto con encadenamiento hacia adelante | No se elige: la ley es determinista | ✅ |
| Segmentación de la cartera | K-Means · Jerárquico de Ward · Mezcla gaussiana | Silueta, Calinski-Harabasz y Davies-Bouldin | ✅ |
| Número de segmentos | k = 2 a 6 en cada algoritmo | Silueta con principio de parsimonia | ✅ |
| Priorización de cuentas | Lógica difusa Mamdani · TOPSIS · Ponderación simple | Recaudo esperado, robustez y discriminación | ✅ |
| Reparto del plan de trabajo | Serpentina · Programación lineal entera (`scipy.optimize.milp`) | Valor asignado (recaudo esperado) contra la serpentina | ✅ |
| Propensión a pagar | Regresión logística · Árbol CART · Bosque aleatorio · Gradient Boosting | AUC, KS, Brier y estabilidad | ✅ |
| Canal de contacto | Reglas E1 a E5 y E9 · muestreo de Thompson sobre el historial de respuestas | Tasa de respuesta observada | ✅ |

---

## 1. Preparación de la información

### 1.1 Seudonimización con HMAC-SHA256

- **Dónde:** `datos/cargador.py` → `_seudonimo()`
- **Qué hace en el sistema:** reemplaza la cédula y el número de crédito por un
  código estable (`C…` para titulares, `K…` para créditos).
- **Qué busca:** que se pueda seguir una cuenta entre meses sin que la tabla de
  trabajo contenga identificadores personales.
- **Método:** código de autenticación de mensajes con clave (RFC 2104):

$$
\mathrm{HMAC}(K, m) = H\big((K \oplus \mathit{opad}) \,\|\, H((K \oplus \mathit{ipad}) \,\|\, m)\big)
$$

  con $H$ = SHA-256 y $K$ la clave secreta del archivo `.env`. Se conservan los
  primeros 12 dígitos hexadecimales (48 bits).
- **Por qué con clave:** una cédula tiene como mucho $10^{10}$ valores posibles;
  un SHA-256 sin clave se revierte probándolos todos en minutos. Sin $K$, el
  cálculo no se puede reproducir.
- **Límite conocido:** con 48 bits, la probabilidad de que dos titulares
  compartan código (paradoja del cumpleaños) es de aproximadamente
  $n^2 / 2^{49}$: menos de 0,2 % con un millón de titulares.

### 1.2 Clasificación del texto de la gestión

- **Dónde:** `datos/cargador.py` → `_clasificar_gestion()`, patrones en `config.PATRONES_GESTION`
- **Qué hace:** convierte el texto libre de la última gestión ("NO CONTESTA",
  "BUZON…") en una etiqueta (`NO_CONTESTA`, `BUZON`, `SIN_GESTION_REAL`…).
- **Método:** clasificador por reglas ordenadas, en el que gana la primera que
  coincide. Es determinista y no requiere entrenamiento, porque el vocabulario
  de las gestiones es pequeño y repetitivo.

### 1.3 Contactabilidad (o probabilidad de pago, si hay modelo entrenado)

- **Dónde:** `analisis/criterios.py` → `preparar()`, `analisis/propension.py` → `predecir()`
- **Qué hace:** estima, entre 0 y 1, la probabilidad de que la cuenta pague si
  se gestiona. Usada como criterio de priorización con el mismo peso (0,25)
  y la misma variable difusa que antes.
- **Con modelo entrenado (fase 4, issue #12):** la probabilidad sale del
  modelo elegido (regresión logística, CART, bosque aleatorio o
  HistGradientBoosting según el que ganó la comparación), calculada con la
  mora actual, el saldo y el canal que el motor recomienda hoy.
- **Sin modelo entrenado:** heurística del experto, sin cambios:

$$
\mathit{contactabilidad} = 0{,}7 \cdot r(\mathit{resultado}) + 0{,}3 \cdot \frac{\mathit{canales}}{4}
$$

- **Comparación:** cada priorización guarda las métricas (recaudo esperado,
  robustez, discriminación) con y sin el modelo, para poder ver cuánto
  cambia el recaudo esperado al usar la probabilidad real en vez de la
  regla del experto.
  
### 1.4 Perfil estadístico y simulación de carteras

- **Dónde:** `datos/perfilador.py` y `datos/generador.py`
- **Qué hace:** extrae de una asignación solo estadísticas agregadas y genera
  carteras completas con la misma forma, para dimensionar campañas, capacitar y
  verificar el sistema.
- **Métodos:**
  - *Cuantiles empíricos* en 100 niveles, entre el 0,5 % y el 99,5 %. Los
    extremos se recortan porque corresponden a personas identificables.
  - *Muestreo por transformada inversa:* si $U \sim \mathrm{Uniforme}(0,1)$,
    entonces $X = F^{-1}(U)$ tiene la distribución $F$. $F^{-1}$ se aproxima
    interpolando linealmente la tabla de cuantiles.
  - *Muestreo condicional:* $\mathit{saldo} \sim F_{\mathit{saldo} \mid \mathit{código}}$,
    $\mathit{mora} \sim F_{\mathit{mora} \mid \mathit{mes}}$ y
    $\mathit{margen} \sim F_{\mathit{margen} \mid \mathit{franja}}$, para conservar las
    relaciones que más pesan en el recaudo.
  - *Muestreo multinomial* para las variables categóricas.
- **Reproducibilidad:** con la misma semilla el generador produce exactamente la
  misma cartera. Eso permite reconstruir y completar una carga (`datos/completar.py`).

---

## 2. Motor de elegibilidad: sistema experto basado en reglas

- **Dónde:** base de conocimiento en `motor/base_conocimiento.py`, motor de
  inferencia en `motor/elegibilidad.py`
- **Qué hace:** decide, para cada cuenta y fecha, si se puede contactar
  (CONTACTABLE, RECORDATORIO, EN_ESPERA o BLOQUEADA), por qué canales, cuál
  conviene y qué regla lo determinó.
- **Qué busca:** cumplir la Ley 2300 de 2023 (días, horario y frecuencia del
  contacto de cobranza) y las políticas del negocio, dejando cada decisión
  explicada.
- **Método:** encadenamiento hacia adelante con *Modus Ponens*. Cada regla es
  $P_1 \wedge P_2 \wedge \dots \wedge P_n \Rightarrow C$: si todas las premisas
  se cumplen con los hechos de la cuenta, se agrega la conclusión $C$ a la
  memoria de trabajo.

  | Fase | Reglas | Tipo de razonamiento |
  |---|---|---|
  | 1. Bloqueos | L1, N1, L3, L2 | Si alguna se dispara, se detiene el razonamiento |
  | 2. Compromisos | N3, N4 | Mutuamente excluyentes por rango de días |
  | 3. Canales | C1 a C8 | Cada regla resta canales no disponibles o no autorizados |
  | 4. Cierre | N2 | Razona sobre el hecho que dejó la fase 3 (canales restantes) |
  | 5. Estrategia | E1 a E5 y E9 | Conjunto de conflicto; gana la de mayor prioridad |

- **Hechos desconocidos:** un dato vacío nunca cumple una premisa, como en una
  lógica de tres valores. Para que eso no termine en un contacto sin verificar
  la ley, la regla L3 bloquea toda cuenta con datos incompletos.
- **Autorización por canal:** las reglas C5 a C8 aplican el artículo 2 de la
  Ley 2300 de 2023 y eliminan LLAMADA, WHATSAPP, SMS o EMAIL cuando el
  consumidor no autorizó ese canal. Solo se aplican cuando
  `EXIGIR_AUTORIZACION_CANAL` está habilitado. El motor lee las columnas
  `autoriza_llamada`, `autoriza_whatsapp`, `autoriza_sms` y `autoriza_email`.
  Si la exigencia está activa y falta información de autorización, la cuenta
  se trata como incompleta y L3 impide el contacto por precaución.
- **Festivos:** calendario de Colombia con los traslados al lunes de la Ley
  Emiliani (librería `holidays`).
- **Qué decide:** el estado de la cuenta y el canal. No predice: aplica
  conocimiento.

---

## 3. Segmentación de la cartera

- **Dónde:** `analisis/segmentacion.py`
- **Qué hace:** agrupa las cuentas parecidas para asignar a cada grupo una
  estrategia.
- **Variables:** saldo, contactabilidad, días de mora, margen y meses en
  gestión. Saldo y mora pasan por $\log(1+x)$ para reducir sus colas largas, y
  todas se estandarizan con $z = (x - \mu)/\sigma$ para que ninguna pese solo
  por su escala.

### 3.1 K-Means (Lloyd, inicialización k-means++)

- **Busca:** $k$ centros que minimicen la inercia (suma de distancias al
  cuadrado de cada cuenta a su centro):

$$
J = \sum_{c=1}^{k} \sum_{x_i \in c} \lVert x_i - \mu_c \rVert^2
$$

- **Iteración:** (1) asignar cada cuenta al centro más cercano; (2) recalcular
  cada centro como el promedio de sus cuentas; repetir hasta que no cambie. Se
  corre 10 veces con distintos inicios y se queda la de menor $J$.
- **Supuesto:** grupos compactos y de forma aproximadamente esférica.

### 3.2 Jerárquico aglomerativo de Ward

- **Busca:** construir un árbol de fusiones. Parte de cada cuenta como un grupo
  y en cada paso une los dos grupos cuya fusión aumenta menos la varianza
  interna:

$$
\Delta(A, B) = \frac{|A|\,|B|}{|A| + |B|} \, \lVert \mu_A - \mu_B \rVert^2
$$

- **Ventaja:** un solo árbol contiene la segmentación para todos los valores de
  $k$; basta cortarlo a distinta altura.
- **Costo:** guarda la distancia entre todos los pares ($O(n^2)$ en memoria).
  Por eso se ajusta sobre una muestra de 3.000 cuentas, y el resto se asigna al
  centro del grupo más cercano.

### 3.3 Mezcla gaussiana (algoritmo EM)

- **Busca:** representar la cartera como la suma de $k$ distribuciones normales
  multivariadas:

$$
p(x) = \sum_{j=1}^{k} \pi_j \, \mathcal{N}(x \mid \mu_j, \Sigma_j)
$$

- **Iteración EM:**
  - *Paso E:* probabilidad de que la cuenta $i$ pertenezca al grupo $j$:
    $\gamma_{ij} = \dfrac{\pi_j \, \mathcal{N}(x_i \mid \mu_j,\Sigma_j)}{\sum_l \pi_l \, \mathcal{N}(x_i \mid \mu_l,\Sigma_l)}$.
  - *Paso M:* recalcular $\pi_j$, $\mu_j$ y $\Sigma_j$ ponderando cada cuenta
    por $\gamma_{ij}$.
- **Ventaja:** admite grupos alargados, inclinados o de distinto tamaño, porque
  cada grupo tiene su propia matriz de covarianza.

### 3.4 Cómo se elige el algoritmo y el número de segmentos

- **Silueta de cada cuenta**, donde $a$ es la distancia media a su propio grupo
  y $b$ la distancia media al grupo vecino más cercano:

$$
s(i) = \frac{b(i) - a(i)}{\max\{a(i), b(i)\}} \in [-1, 1]
$$

- **Calinski-Harabasz:** varianza entre grupos frente a varianza dentro de
  ellos (mayor es mejor):

$$
CH = \frac{\operatorname{tr}(B_k)/(k-1)}{\operatorname{tr}(W_k)/(n-k)}
$$

- **Davies-Bouldin:** parecido promedio entre cada grupo y su vecino más
  cercano, donde $s_i$ es la dispersión del grupo $i$ y $d_{ij}$ la distancia
  entre centros (menor es mejor):

$$
DB = \frac{1}{k}\sum_{i=1}^{k} \max_{j \ne i} \frac{s_i + s_j}{d_{ij}}
$$

- **Número de segmentos:** en cada algoritmo se prueba $k = 2 \dots 6$ y se toma
  el menor $k$ cuya silueta queda a menos de 0,01 de la mejor (principio de
  parsimonia).
- **Algoritmo ganador:**

$$
\mathit{Puntaje} = 0{,}50\,\frac{s}{s_{\max}} + 0{,}25\,\frac{CH}{CH_{\max}} + 0{,}25\,\frac{DB_{\min}}{DB}
$$

  Se descarta el algoritmo que deja un segmento con menos del 2 % de la cartera.
- **Visualización:** análisis de componentes principales (PCA). Las cuentas se
  proyectan sobre los dos vectores propios de la matriz de covarianza con mayor
  valor propio.

---

## 4. Priorización de cuentas

- **Dónde:** `decision/priorizacion.py` y `decision/conocimiento_difuso.py`
- **Qué hace:** ordena las cuentas contactables del día para que el equipo
  trabaje primero las que más aportan a la meta.

| Criterio | Peso | Sentido |
|---|---|---|
| Saldo | 0,35 | Beneficio (más es mejor) |
| Contactabilidad | 0,25 | Beneficio |
| Días de mora | 0,20 | Costo (menos es mejor) |
| Margen negociable | 0,10 | Beneficio |
| Meses en gestión | 0,10 | Costo |

### 4.1 Lógica difusa Mamdani

- **Busca:** razonar como el experto, con términos lingüísticos ("saldo alto",
  "mora temprana") en lugar de umbrales exactos.
- **Fuzzificación:** grado de pertenencia de cada dato a cada conjunto. Para un
  conjunto triangular $(a, b, c)$:

$$
\mu(x) = \max\left(0, \min\left(\frac{x-a}{b-a}, \frac{c-x}{c-b}\right)\right)
$$

  El trapezoidal $(a, b, c, d)$ agrega una meseta con grado 1 entre $b$ y $c$.
- **Evaluación de 14 reglas (D1 a D14):** la fuerza de la regla $r$ es el mínimo
  de sus premisas: $\alpha_r = \min_i \mu_{A_i}(x_i)$.
- **Implicación y agregación:** cada regla recorta su conjunto de salida y los
  recortes se unen punto a punto:

$$
\mu_{\mathit{agregada}}(y) = \max_r \min\big(\alpha_r, \mu_{B_r}(y)\big)
$$

- **Defuzzificación por centro de gravedad**, sobre 201 puntos entre 0 y 100:

$$
y^{*} = \frac{\sum_y y \, \mu_{\mathit{agregada}}(y)}{\sum_y \mu_{\mathit{agregada}}(y)}
$$

- **Implementación:** vectorizada como matrices (cuentas × puntos de salida), de
  modo que 5.000 cuentas se resuelven en milisegundos.

### 4.2 TOPSIS (Hwang y Yoon)

- **Busca:** la cuenta más parecida a una cuenta ideal y más distinta de la peor
  posible.
- **Pasos:** normalización vectorial $r_{ij} = x_{ij}/\sqrt{\sum_i x_{ij}^2}$;
  ponderación $v_{ij} = w_j r_{ij}$; ideal $A^{+}$ (mejor valor de cada
  criterio) y anti-ideal $A^{-}$; distancias euclidianas $d_i^{+}$ y $d_i^{-}$.
  El resultado es la cercanía relativa:

$$
C_i = \frac{d_i^{-}}{d_i^{+} + d_i^{-}} \in [0, 1]
$$

### 4.3 Ponderación simple (SAW)

- **Busca:** la suma ponderada de los criterios normalizados entre 0 y 1 (en los
  de costo se invierte la escala):

$$
S_i = \sum_j w_j \, \frac{x_{ij} - \min_j}{\max_j - \min_j}
$$

- **Papel:** es la línea base, lo que haría una hoja de cálculo. Si un método
  más elaborado no la supera, no se justifica.

### 4.4 Cómo se elige el método

- **Recaudo esperado por cuenta**, con la tasa de respuesta del canal que
  recomendó el motor (correo 1 %, SMS 2,5 %, WhatsApp 6 %, llamada 15 %):

$$
E_i = \mathit{piso\ de\ cobranza}_i \times \mathit{contactabilidad}_i \times \mathit{tasa}(\mathit{canal}_i)
$$

- **Recaudo@K:** suma de $E_i$ de las $K$ primeras cuentas de cada método, con
  $K$ = gestores × gestiones por gestor (6 × 80 = 480).
- **Robustez:** los datos se perturban ±10 % en 5 réplicas y se compara la cola
  original con la perturbada mediante el índice de Jaccard,
  $J(A, B) = |A \cap B| / |A \cup B|$.
- **Discriminación:** fracción de puntajes distintos dentro de la cola.
- **Puntaje del método:**

$$
0{,}60 \cdot \frac{\mathit{Recaudo@K}}{\max} + 0{,}25 \cdot \mathit{Robustez} + 0{,}15 \cdot \mathit{Discriminación}
$$

- **Hallazgo:** en las carteras probadas gana TOPSIS. La lógica difusa pierde
  porque las mesetas de sus conjuntos asignan el mismo grado a cientos de
  cuentas (discriminación cercana a 0,1). El sistema no lo supone: lo mide.

---

## 5. Plan de trabajo: reparto en serpentina

- **Dónde:** `gestion/plan.py` → `repartir_en_serpentina()`
- **Qué hace:** reparte las cuentas del día entre los gestores.
- **Pasos previos:** (1) nueva evaluación con el motor para la fecha del plan;
  (2) se toman las $n \times \mathit{cupo}$ mejores según la priorización.
- **Método:** con $n$ gestores y la cuenta de posición $i$ (empezando en 0), sea
  $v = \lfloor i/n \rfloor$ la vuelta y $l = i \bmod n$ el lugar. La cuenta va
  al gestor $l$ si $v$ es par y al gestor $n-1-l$ si $v$ es impar.
- **Propiedad:** en cada par de vueltas ($v$ par y $v+1$), el gestor $g$ recibe
  las posiciones $vn + g$ y $(v+1)n + (n-1-g)$, cuya suma, $2n(v+1) - 1$, no
  depende de $g$: todos reciben la misma suma de posiciones. Así nadie recibe
  siempre la mejor cuenta de cada vuelta y los resultados entre gestores se
  pueden comparar.
- **Asignación óptima (issue #14):** alternativa disponible con
  `gestion/plan.py` → `asignar_optimo()`, programación lineal entera con
  `scipy.optimize.milp` (ver sección 8.6). Ambos métodos se calculan siempre
  sobre el mismo universo de cuentas permitidas, de modo que cada plan guarda
  el valor esperado con serpentina y con el óptimo, y se puede comparar uno
  contra otro sin importar cuál se use para el reparto final.

---

## 6. Registro de gestiones: reglas de validación

- **Dónde:** `gestion/operacion.py`
- **Qué hace:** antes de guardar una gestión aplica diez reglas de restricción
  (G1 a G10): día y horario de la ley, bloqueos y canales del motor, coherencia
  entre resultado y código, banda de negociación y plazo del compromiso.
- **Método:** sistema de reglas de restricción. Las de nivel *error* impiden
  guardar; las de nivel *aviso* se registran. La gestión y la actualización de
  la cartera van en una transacción ACID: o se guardan las dos o ninguna.
- **Reloj confiable (issue #51):** la regla de horario (G1) depende de la hora
  del servidor donde corre la aplicación, no solo del código: si ese reloj se
  atrasa, un contacto fuera de horario real podría verse "en horario" y no
  rechazarse. Contra una base remota, `datos/base_datos.py → reloj_confiable()`
  compara la hora del servidor contra la de la base de datos antes de aceptar
  un horario como válido; si difieren más de 10 minutos, se rechaza por
  precaución, el mismo principio que ya usa L3 con un dato incompleto.

---

## 7. Seguridad

| Algoritmo | Dónde | Qué hace | Método |
|---|---|---|---|
| scrypt | `seguridad/autenticacion.py` | Guarda la contraseña de forma irreversible | Función de derivación con alto costo de memoria (RFC 7914): $N = 2^{15}$, $r = 8$, $p = 1$, sal aleatoria de 16 bytes, 64 bytes de salida. Probar millones de contraseñas exige memoria, no solo procesador |
| Comparación en tiempo constante | `hmac.compare_digest` | Verifica la contraseña | Compara todos los bytes aunque falle el primero, para no revelar cuántos coinciden por el tiempo de respuesta |
| Bloqueo por intentos | `autenticar()` | Frena la fuerza bruta | 5 intentos fallidos seguidos bloquean la cuenta 15 minutos |

---

## 8. Revisión de modelos financieros y compatibilidad con el proyecto

Modelos que la industria de crédito y cobranza usa para decisiones de este
tipo, evaluados frente a los datos y la arquitectura del proyecto.

| Modelo | Uso en finanzas | Qué predice o decide | Datos que exige | Compatible | Dónde entraría |
|---|---|---|---|---|---|
| **Regresión logística (scorecard)** | Estándar de la industria para puntajes de crédito y de cobranza por su interpretabilidad (Siddiqi) | Probabilidad de pago o de compromiso | Historial con resultado conocido | Sí (`scikit-learn`) | Fase 4 |
| **Árbol de decisión CART** | Segmentación de riesgo y reglas de política | Probabilidad y reglas SI-ENTONCES | Igual | Sí; sus reglas se pueden llevar a la base de conocimiento | Fase 4 |
| **Bosque aleatorio** | Modelos de riesgo con muchas variables | Probabilidad de pago | Igual | Sí | Fase 4 |
| **Gradient Boosting** | Mejor desempeño en datos tabulares financieros | Probabilidad de pago | Igual | Sí (`HistGradientBoostingClassifier`) | Fase 4 |
| **Cadenas de Markov (roll rates)** | Proyección de cartera entre tramos de mora | Probabilidad de pasar de un tramo a otro | Al menos tres cargas mensuales de la misma cartera | Sí: la llave (carga, crédito) guarda la historia | Tablero de proyección |
| **Análisis de supervivencia (Kaplan-Meier, Cox)** | Tiempo hasta el pago o la cura | Cuántos días faltan para el pago | Fechas de gestión y de pago | Sí, con la librería `lifelines` | Después de la fase 4 |
| **Muestreo de Thompson (bandido multibrazo)** | Elegir el canal o el mensaje que más responde, aprendiendo en operación | Canal óptimo por segmento | Resultado de cada contacto | Sí: las gestiones registran canal y resultado | Reemplazo de E1 a E5 y E9 |
| **Programación lineal entera** | Asignación de cuentas a gestores y de presupuesto a canales | Asignación que maximiza el recaudo esperado | Valor esperado y capacidades | Sí (`scipy.optimize.milp`) | Fase 5 |
| **Pérdida dado el incumplimiento (LGD)** | Provisiones y precio de venta de cartera | Porcentaje del saldo que se recupera | Pagos históricos por cuenta | Parcial: faltan pagos reales | Futuro |

### 8.1 Regresión logística

$$
P(\mathit{pago} = 1 \mid x) = \frac{1}{1 + e^{-(\beta_0 + \beta^{\top} x)}}
$$

Los coeficientes $\beta$ se estiman por máxima verosimilitud. Cada $\beta_j$
tiene lectura directa: $e^{\beta_j}$ es cuánto se multiplican las chances de
pago al aumentar una unidad de $x_j$. Con agrupación de variables por *Weight
of Evidence* se convierte en una tarjeta de puntaje, que es el formato que
esperan los auditores.

### 8.2 Árbol CART

Divide la cartera en cada nodo por la variable y el umbral que más reducen la
impureza de Gini, $G = 1 - \sum_c p_c^2$, o la entropía,
$H = -\sum_c p_c \log_2 p_c$ (ganancia de información, sesión 6). Cada hoja es
una regla SI-ENTONCES con su probabilidad: es el puente natural entre el
aprendizaje automático y la base de conocimiento del sistema experto.

### 8.3 Bosque aleatorio y Gradient Boosting

- **Bosque aleatorio:** promedia cientos de árboles, cada uno entrenado con una
  muestra con reemplazo y con un subconjunto aleatorio de variables. Así reduce
  la varianza del árbol individual.
- **Gradient Boosting:** suma árboles pequeños de forma secuencial. Cada uno se
  ajusta al gradiente del error de los anteriores:
  $F_m(x) = F_{m-1}(x) + \eta \, h_m(x)$.

### 8.4 Cadenas de Markov de tramos de mora

Con la matriz $P$ de probabilidades de pasar del tramo $i$ al tramo $j$ en un
mes, estimada de cargas consecutivas, la distribución de la cartera se proyecta
como $\pi_{t+1} = \pi_t P$. Responde cuánto saldo pasará a más de 720 días si no
se gestiona.

### 8.5 Muestreo de Thompson para el canal

La elección final del canal utiliza un bandido multibrazo con muestreo de
Thompson. Primero el motor aplica los bloqueos, compromisos y restricciones
legales y técnicas de las reglas L, N y C; Thompson **solo recibe los canales
que continúan permitidos**, por lo que nunca puede recuperar un canal eliminado
por el sistema experto.

Para cada canal se estima una distribución
$\mathrm{Beta}(1 + r, 1 + n)$, donde $r$ es el número de gestiones salientes
que obtuvieron respuesta real del titular y $n$ el número de gestiones
salientes sin respuesta. Se consideran respuestas los resultados definidos en
`RESULTADOS_CON_CONTACTO`; las gestiones entrantes no se usan para entrenar la
selección porque el sistema no eligió activamente su canal.

En cada decisión se toma una muestra de la distribución de cada canal permitido
y se recomienda el de mayor valor. La semilla se deriva de la semilla general,
el crédito y la fecha objetivo, de modo que una misma ejecución con la misma
historia sea reproducible.

Las reglas E1 a E5 y E9 se conservan como estrategia experta de referencia:
cuando existe historial, Thompson determina el canal final y el motor conserva
cuál habría recomendado la regla para permitir la comparación. Si todavía no
existen gestiones salientes, se mantiene temporalmente la recomendación de las
reglas E.

La primera implementación aprende por canal para toda la carga. La extensión
por segmento requiere que el segmento esté disponible antes de ejecutar el
motor; actualmente la segmentación ocurre en una etapa posterior.

### 8.6 Programación lineal entera para el plan

Con $x_{ig} \in \{0,1\}$ igual a 1 si la cuenta $i$ va al gestor $g$:

$$
\max \sum_{i,g} E_i \, x_{ig} \quad \text{sujeto a} \quad \sum_g x_{ig} \le 1, \qquad \sum_i x_{ig} \le \mathit{cupo}_g
$$

Se pueden agregar restricciones de equidad (mínimo valor por gestor) o de
especialidad (cierto segmento solo con gestores de experiencia).

---

## 9. Modelo recomendado para el entrenamiento (fase 4)

**Qué se entrena:** la probabilidad de que una cuenta logre un compromiso de
pago en los próximos 30 días si se gestiona. Reemplaza la contactabilidad
heurística dentro del recaudo esperado, y con ella mejora la priorización y el
plan.

**De dónde salen los datos:** de la tabla `gestiones`. Cada gestión registra la
cuenta, el canal, el resultado y si hubo acuerdo, junto con el estado de la
cuenta en ese momento. Mientras se acumula historia real, la simulación debe
agregar un comportamiento de pago con causa: una propensión latente por cuenta,
función de saldo, mora, contactabilidad y segmento, de la que dependa el
resultado de cada gestión simulada. Sin eso no hay nada que aprender.

**Candidatos, evaluados con el mismo principio del resto del sistema:**

| Modelo | Fortaleza | Debilidad |
|---|---|---|
| Regresión logística | Interpretable, estable, estándar regulatorio | Supone relaciones lineales en el logit |
| Árbol CART (profundidad 4 a 6) | Reglas legibles que alimentan la base de conocimiento | Inestable ante cambios pequeños en los datos |
| Bosque aleatorio | Robusto, poco sobreajuste | Menos interpretable |
| Gradient Boosting | Suele tener el mejor AUC en datos tabulares | Requiere más ajuste y es menos interpretable |

**Validación:**

- *Temporal:* entrenar con las cargas anteriores y evaluar en la más reciente,
  que es como se usará el modelo. Una partición aleatoria mezclaría meses y
  daría una precisión falsa.
- *Métricas:*
  - AUC-ROC: capacidad de ordenar.
  - Estadístico KS, $\max_s |F_1(s) - F_0(s)|$: la métrica clásica de scoring.
  - Puntaje de Brier, $\frac{1}{n}\sum_i (p_i - y_i)^2$: calibración, clave
    porque la probabilidad entra al cálculo de dinero.
  - Captura en el 20 % superior: cuánto del recaudo queda en la cola del día.
  - PSI: estabilidad de la población entre meses.
- *Selección:* puntaje compuesto de AUC, KS, Brier y estabilidad. Si la
  diferencia de AUC entre el mejor modelo y la regresión logística o el árbol
  es menor a 0,02, se elige el interpretable (parsimonia). En un sistema experto
  la explicación vale tanto como la precisión.

**Recomendación:** empezar con la **regresión logística como línea base** y el
**árbol CART como modelo explicable**, compararlos contra **Gradient Boosting**,
y llevar las reglas del árbol ganador a la base de conocimiento. El resultado
es un sistema experto híbrido: reglas legales deterministas, reglas aprendidas
de los datos y un modelo probabilístico para el valor esperado.

---

## Referencias

- Breiman, L., Friedman, J., Olshen, R. y Stone, C. (1984). *Classification and Regression Trees*. Wadsworth.
- Breiman, L. (2001). Random Forests. *Machine Learning*, 45, 5-32.
- Caliński, T. y Harabasz, J. (1974). A dendrite method for cluster analysis. *Communications in Statistics*, 3(1), 1-27.
- Davies, D. y Bouldin, D. (1979). A cluster separation measure. *IEEE Transactions on Pattern Analysis and Machine Intelligence*, 1(2), 224-227.
- Dempster, A., Laird, N. y Rubin, D. (1977). Maximum likelihood from incomplete data via the EM algorithm. *Journal of the Royal Statistical Society B*, 39(1), 1-38.
- Friedman, J. (2001). Greedy function approximation: a gradient boosting machine. *Annals of Statistics*, 29(5), 1189-1232.
- Hwang, C. y Yoon, K. (1981). *Multiple Attribute Decision Making: Methods and Applications*. Springer.
- Krawczyk, H., Bellare, M. y Canetti, R. (1997). *HMAC: Keyed-Hashing for Message Authentication* (RFC 2104). IETF.
- Mamdani, E. y Assilian, S. (1975). An experiment in linguistic synthesis with a fuzzy logic controller. *International Journal of Man-Machine Studies*, 7(1), 1-13.
- MacQueen, J. (1967). Some methods for classification and analysis of multivariate observations. *Proceedings of the 5th Berkeley Symposium*, 1, 281-297.
- Percival, C. y Josefsson, S. (2016). *The scrypt Password-Based Key Derivation Function* (RFC 7914). IETF.
- Rousseeuw, P. (1987). Silhouettes: a graphical aid to the interpretation and validation of cluster analysis. *Journal of Computational and Applied Mathematics*, 20, 53-65.
- Russell, S. y Norvig, P. (2021). *Artificial Intelligence: A Modern Approach* (4.ª ed.). Pearson.
- Siddiqi, N. (2017). *Intelligent Credit Scoring* (2.ª ed.). Wiley.
- Thomas, L., Crook, J. y Edelman, D. (2017). *Credit Scoring and Its Applications* (2.ª ed.). SIAM.
- Thompson, W. (1933). On the likelihood that one unknown probability exceeds another. *Biometrika*, 25(3-4), 285-294.
- Ward, J. (1963). Hierarchical grouping to optimize an objective function. *Journal of the American Statistical Association*, 58(301), 236-244.
- Congreso de Colombia. Ley 2300 de 2023 y Ley 1581 de 2012.
