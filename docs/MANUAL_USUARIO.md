# Manual de usuario, por rol

Cómo usar la aplicación web del sistema de gestión de cartera, explicado
pantalla por pantalla según lo que ve cada rol. Verificado navegando la
aplicación completa con los tres roles sobre una carga de prueba.

## Ingresar al sistema

1. Abra la URL de la aplicación (https://gestion-cartera.streamlit.app o el
   Codespace/entorno local).
2. Escriba su usuario y contraseña, y presione **Ingresar**.
3. Si se equivoca 5 veces seguidas, el usuario queda bloqueado 15 minutos.
   Si no recuerda la contraseña, un administrador se la restablece desde la
   pantalla **Usuarios**, y eso también quita el bloqueo.
4. Por seguridad, la sesión se cierra sola tras 30 minutos sin actividad.
5. La contraseña debe tener al menos 10 caracteres, combinar letras y
   números, no contener el nombre de usuario y no ser una contraseña común.
   Puede cambiarla en cualquier momento desde **Mi cuenta**.

## Los tres roles

| Rol | Para quién es | Qué agrega sobre el anterior |
|---|---|---|
| **Gestor** | Quien llama o escribe a los titulares | Consultar el tablero, la cartera, los resultados del motor, la priorización, la propensión a pago y la base de conocimiento; registrar gestiones |
| **Supervisor** | Quien coordina el equipo de gestores | Ejecutar el motor de elegibilidad y la priorización, entrenar los modelos de propensión, crear el plan de trabajo del equipo, ver la traza de todos los gestores, cargar carteras, registrar obligaciones nuevas y revisar la auditoría |
| **Administrador** | Quien administra el sistema | Crear, modificar y bloquear usuarios, y presentar el sistema en el laboratorio de algoritmos |

Cada rol ve **todo** lo del rol anterior, más lo propio. El menú de la
izquierda solo muestra las pantallas a las que su rol tiene acceso.

---

## Rol Gestor

Ve estas pantallas, agrupadas bajo "Operación" y "Conocimiento":

### Tablero
Resumen del día: cuántas cuentas y qué saldo tiene la carga activa, cuánto
se ha comprometido frente a la meta de recaudo (1 % del saldo), qué
porcentaje de cuentas ya tuvo una gestión real, y el resultado de la última
ejecución del motor (cuántas cuentas quedaron contactables, en espera,
bloqueadas o con recordatorio).

### Gestión de cuentas
La pantalla de trabajo diario. Con el botón **Siguiente cuenta** toma la
próxima cuenta de su plan de trabajo (o de la cola general si no tiene plan
asignado para hoy); también puede buscar una cuenta puntual por su
seudónimo (`K...` para el crédito, `C...` para el titular). Muestra:

- La obligación: saldo, rango de negociación, días de mora, franja, producto.
- La última gestión registrada y qué dice el motor hoy para esa cuenta (por
  ejemplo, "en espera" porque hay un compromiso vigente).
- El titular y sus datos de contacto, enmascarados (solo se ven los últimos
  dígitos); puede marcarlos como válidos o errados, o agregar uno nuevo.
- La **autorización del titular por canal** (Ley 2300, artículo 2): una tabla
  con el estado de llamada, WhatsApp, SMS y correo, quién lo registró y
  cuándo. Si el titular autoriza o revoca un canal durante la gestión, se
  elige el canal y lo que dijo ("Autorizó", "No autorizó" o "Sin preguntar")
  y se pulsa **Registrar autorización**; el cambio queda en la auditoría y el
  panel del motor muestra los canales autorizados.
- El historial completo de gestiones anteriores.
- El formulario para **registrar la gestión**: canal, sentido (entrante o
  saliente), resultado del contacto, código de gestión y, si hubo acuerdo,
  el valor y la fecha del compromiso. El sistema valida automáticamente
  reglas de negocio (por ejemplo, no deja registrar un acuerdo sin un canal
  autorizado) antes de guardar.

### Plan de trabajo
Cuántas cuentas le tocan hoy, cuántas ya gestionó, cuántos contactos
efectivos y cuántos acuerdos lleva, con el valor acordado acumulado.

### Traza de trabajo
Qué hizo cada gestor y qué pasó con cada cuenta en un periodo, con vistas
"por gestor" y "por cuenta".

### Cartera
Todas las cuentas de la carga activa, seudonimizadas, con filtros por
franja de saldo, rango de mora, código, resultado de la última gestión, si
tiene gestión real y si tiene compromiso. Se puede descargar la selección
en CSV.

### Motor de elegibilidad
Los resultados de la última vez que se evaluó la cartera: cuántas cuentas
quedaron contactables, en espera, bloqueadas o con recordatorio, y el costo
estimado de contactar a las recomendadas. Con **¿Por qué?** se consulta una
cuenta puntual y aparece la cadena completa de reglas que decidieron su
estado, con el artículo de la Ley 2300 o 1581 que la sustenta.

### Priorización
En qué orden conviene trabajar la cartera del día: cuántas cuentas son
candidatas, la capacidad del día, en cuántos segmentos se dividió la
cartera y qué método de priorización se eligió (lógica difusa, TOPSIS o
ponderación simple) y por qué.

### Propensión a pago
Qué modelo quedó entrenado para predecir qué cuentas tienen más
probabilidad de pagar (regresión logística, árbol CART, bosque aleatorio o
Gradient Boosting), con sus métricas (AUC, KS, Brier, PSI) y la comparación
entre los cuatro candidatos. Si todavía no hay un modelo entrenado, la
pantalla lo indica.

### Base de conocimiento
Las reglas del motor de elegibilidad, organizadas en las 5 fases en que se
evalúan (bloqueos legales, compromisos vigentes, canales permitidos,
cuentas sin canal y estrategia), cada una con su fundamento normativo o de
negocio. Incluye un simulador para probar qué decidiría el motor con
hechos hipotéticos.

### Metodología
Explica qué algoritmos usa cada proceso del sistema, cómo se elige el
mejor entre los que compiten, y por qué la elegibilidad legal es la única
decisión que no se elige por desempeño (se cumple, no se optimiza).

### Mi cuenta
Su usuario, rol y último ingreso, y el formulario para cambiar su propia
contraseña.

---

## Rol Supervisor

Ve todo lo del Gestor, más una sección "Administración" y estas
capacidades adicionales en pantallas que el Gestor solo consulta:

### Motor de elegibilidad y Priorización (con permiso de ejecutar)
Además de consultar resultados, aparece el formulario para lanzar una
**nueva ejecución**: elegir la carga y la fecha a evaluar. El sistema
avisa de una vez si esa fecha es hábil según la Ley 2300.

### Propensión a pago (con permiso de ejecutar)
Aparece el botón **Entrenar y comparar**, que corre los cuatro modelos
sobre el historial de gestiones de la carga elegida y guarda el ganador.

### Plan de trabajo (crear y ver el del equipo)
Elige la priorización, la fecha, los gestores y cuántas cuentas le tocan a
cada uno, y el **método de reparto**:

- **Serpentina:** 1, 2, 3… y en la siguiente vuelta …3, 2, 1, para que cada
  gestor reciba una mezcla pareja de cuentas de alta y baja prioridad.
- **Óptimo (recaudo máximo):** programación lineal entera que reparte las
  cuentas para obtener el mayor recaudo esperado total, respetando el cupo de
  cada gestor.

Sin importar el método elegido, el plan muestra el valor esperado con los dos
métodos y la diferencia entre ellos. Debajo aparece el avance de cada gestor.

### Traza de trabajo (la del equipo)
En la vista "por gestor" ve las gestiones de todo el equipo y puede filtrar
uno o varios gestores.

### Cargas
Genera una cartera sintética nueva (a partir del perfil estadístico de
referencia, con su directorio de titulares) y consulta el historial de
cargas registradas. También permite completar cargas antiguas a las que
les falten columnas de contacto.

### Obligación nueva
Registra un crédito individual con su titular y contactos, sin necesidad
de una carga completa — útil para agregar una cuenta suelta. Advierte
explícitamente: es un proyecto académico, solo con datos simulados.

### Auditoría
Quién hizo qué y cuándo: ingresos, ingresos fallidos, creación de
usuarios, ejecuciones del motor, priorizaciones, planes creados, etc.
Filtrable por usuario, acción y periodo, con un conteo por tipo de evento.

---

## Rol Administrador

Ve todo lo del Supervisor, más:

### Usuarios
Crea cuentas de acceso nuevas (usuario, nombre, rol y contraseña inicial),
modifica el rol de una cuenta existente, la bloquea o reactiva, y le
restablece la contraseña. Es la única pantalla desde la que se administran
los tres roles.

### Laboratorio de algoritmos
Una página completa para presentar el sistema: cada motor y algoritmo
funciona en vivo con las mismas reglas, pesos y fórmulas del código, sobre
cuentas de ejemplo. Tiene doce pestañas:

- **Mapa del sistema:** quién llama a quién, de la pantalla a la tabla.
- **Las 21 reglas:** la base de conocimiento por fase, con los bloqueos y el
  estado al que lleva cada fase, filtros, búsqueda y el botón *Probar en el
  motor*; además, las 14 reglas difusas y las 10 de validación.
- **Motor de elegibilidad:** cada premisa evaluada, fase por fase.
- **Thompson, Lógica difusa, TOPSIS y árbitro, Segmentación, Propensión y
  Plan de trabajo:** cada algoritmo funcionando con controles.
- **Gestión G1–G10:** las reglas de validación, la transacción y la reserva
  de cuentas con dos gestores a la vez.
- **Seudónimos:** el HMAC calculado en vivo.
- **Seguridad y roles:** el bloqueo por intentos fallidos y la matriz de
  permisos de las 16 pantallas.

No lee ni escribe en la base de datos: es material de demostración.

---

Los casos puntuales para la sesión de pruebas conjuntas (qué probar, con qué
rol y qué resultado se espera) están en
[`docs/PLAN_DE_PRUEBAS.md`](PLAN_DE_PRUEBAS.md).

## Notas para quien haga las pruebas conjuntas

- Todas las pantallas de los tres roles se probaron en vivo contra una
  carga de 1.500 cuentas simuladas, con 6 semanas de historial de
  gestiones, priorización, plan de trabajo y un modelo de propensión ya
  entrenado: no se encontró ninguna pantalla rota. Además, la prueba
  automática abre las 16 pantallas con los tres roles en cada *pull request*.
- Las cuentas de cada integrante se crean desde la pantalla **Usuarios**.
- "Simular una cartera" y "Completar datos de contacto" (pantalla
  **Cargas**) muestran en pantalla el error si falta la clave de seudónimos
  contra una base remota, en vez de fallar en silencio (#37).
- Para probar la pantalla **Propensión a pago** hace falta historial de
  gestiones en la carga: en una cartera simulada se genera con
  `python -m datos.generador --historial --carga N`.
