# Plan de pruebas conjuntas

Casos que el equipo recorre en cada sesión de pruebas, sobre la aplicación
publicada y con la base compartida. Cada caso indica con qué rol se prueba y
qué resultado se espera. Cada sesión se registra en un *issue* con la plantilla
**Sesión de pruebas**, que trae la lista de casos para marcar; cada caso que
falle se registra además como un *issue* con la plantilla **Error**.

Las gestiones **salientes** solo se aceptan en día hábil entre las 7:00 y las
19:00, hora de Colombia (Ley 2300). Fuera de ese horario, los casos de gestión
se prueban como **entrantes**, salvo los que prueban justamente ese rechazo.

## 1. Acceso y seguridad

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| A1 | Cualquiera | Ingresar con usuario y contraseña correctos | Entra y ve el menú de su rol |
| A2 | Cualquiera | Ingresar con una contraseña errónea | "Usuario o contraseña incorrectos", sin decir si el usuario existe |
| A3 | Gestor | Revisar el menú | No aparecen Cargas, Usuarios ni Auditoría |
| A4 | Administrador | Desactivar a un gestor que tiene la sesión abierta | En menos de un minuto el gestor queda fuera con un aviso |
| A5 | Cualquiera | Dejar la sesión quieta 30 minutos | La sesión se cierra por inactividad |
| A6 | Administrador | Revisar **Auditoría** después de A1 a A5 | Aparecen los ingresos, el intento fallido y la desactivación |

## 2. Motor de elegibilidad

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| M1 | Supervisor | Ejecutar el motor para un domingo o un festivo | Todas las cuentas bloqueadas por la regla L1 |
| M2 | Supervisor | Ejecutar el motor para un día hábil | Mezcla de contactables, recordatorios, en espera y bloqueadas |
| M3 | Cualquiera | En los resultados, abrir "¿Por qué?" de una cuenta bloqueada por L2 | La cadena de reglas y el fundamento de la Ley 2300 |
| M4 | Cualquiera | En **Base de conocimiento → Simulador**, desmarcar "Tiene celular" | El motor deja de ofrecer SMS y WhatsApp |

## 3. Segmentación y priorización

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| P1 | Supervisor | Priorizar con la ejecución de M2 | Se guarda e indica el método elegido |
| P2 | Cualquiera | Pestaña *Segmentación* | Tabla de los tres algoritmos con silueta, Calinski-Harabasz y Davies-Bouldin, y el elegido marcado |
| P3 | Cualquiera | Pestaña *Comparación de métodos* | Las tres métricas de difuso, TOPSIS y ponderación, y el ganador |
| P4 | Cualquiera | "¿Por qué esta prioridad?" de la cuenta en la posición 1 | Grados de pertenencia, reglas difusas activadas y distancias de TOPSIS |

## 4. Plan de trabajo y gestión

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| G1 | Supervisor | Crear el plan de hoy con los dos gestores y 20 cuentas por gestor | 40 cuentas, 20 por gestor, repartidas en serpentina |
| G2 | Gestor | **Gestión de cuentas → Siguiente cuenta** | Entrega la cuenta 1 de **su** plan, no la del otro gestor |
| G3 | Gestor | Registrar una gestión saliente fuera de horario | Rechazada por la regla G1 |
| G4 | Gestor | Registrar un acuerdo con un valor por debajo del mínimo | Rechazado por la regla G8 |
| G5 | Gestor | Registrar un acuerdo válido | Se guarda; al volver a abrir la cuenta, el motor la muestra bloqueada por frecuencia (L2) |
| G6 | Gestor | En *Titular y datos de contacto*, marcar el celular como errado | El panel del motor deja de ofrecer SMS y WhatsApp |
| G7 | Gestor | Agregar un celular con formato inválido (por ejemplo, `12345`) | Rechazado con el formato esperado |
| G8 | Gestor | Pulsar **Mostrar** en un contacto | Se ve el dato completo y queda en la auditoría |

## 5. Traza y seguimiento

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| T1 | Supervisor | **Plan de trabajo** después de G2 a G5 | Avance por gestor con gestionadas, pendientes y cumplimiento |
| T2 | Gestor | **Traza de trabajo → Por gestor** | Solo ve sus propias gestiones |
| T3 | Supervisor | **Traza de trabajo → Por gestor** | Ve las del equipo, con primera y última hora de cada jornada |
| T4 | Cualquiera | **Traza de trabajo → Por cuenta** con la cuenta de G5 | Línea de tiempo: carga, motor, priorización, plan y gestión |

## 6. Escenario del día simulado (los cuatro a la vez)

1. **Supervisor:** ejecuta el motor para hoy, prioriza y crea el plan con los
   dos gestores.
2. **Gestores (dos personas, al mismo tiempo):** cada uno trabaja 10 cuentas de
   su plan con *Siguiente cuenta* y registra gestiones con resultados variados:
   no contesta, buzón, contacto sin acuerdo y al menos un acuerdo.
3. **Administrador:** mientras tanto, sigue el avance en **Plan de trabajo** y
   **Traza de trabajo**, y revisa la **Auditoría**.
4. **Al final, todos:** comprueban que ninguna cuenta quedó gestionada dos
   veces, que el cumplimiento del plan coincide con lo registrado y que las
   cuentas con acuerdo aparecen en espera o bloqueadas en una nueva ejecución
   del motor.

## 7. Cola general sin plan (dos gestores a la vez)

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| G9 | Dos gestores, al mismo tiempo | Ninguno tiene plan hoy; ambos pulsan **Siguiente cuenta** en el mismo instante | Cada uno recibe una cuenta distinta de la cola general; ninguna se repite |
| G10 | Gestor | Pide **Siguiente cuenta**, no la gestiona y sale de la pantalla; otro gestor pide **Siguiente cuenta** antes de que pase el tiempo de reserva | El segundo gestor recibe una cuenta distinta |
| G11 | Gestor | Pide **Siguiente cuenta**, espera más del tiempo de reserva sin gestionarla, y otro gestor pide **Siguiente cuenta** | El segundo gestor puede recibir esa misma cuenta: la reserva ya venció |

## 8. Obligación nueva (registro individual, sin carga completa)

| Id | Rol | Pasos | Resultado esperado |
|---|---|---|---|
| O1 | Supervisor | **Obligación nueva** con un dato mal formado (cédula con letras, cobranza máxima menor que la mínima, código fuera del catálogo) | El formulario marca el error puntual y no registra nada |
| O2 | Supervisor | Registra una obligación completa, con un celular | Aparece en **Cartera** de esa carga, con franja y rango de mora coherentes con el saldo y los días de mora ingresados |
| O3 | Supervisor | Intenta registrar el mismo documento y número de obligación otra vez | Se rechaza: "Esta obligación ya está registrada en esta carga" |
| O4 | Supervisor o Administrador | **Auditoría**, filtrada por `OBLIGACION_NUEVA` | Aparece el registro de O2, con usuario y hora |
| O5 | Supervisor | Ejecuta el motor sobre la carga después de O2 | La obligación nueva aparece evaluada (contactable o bloqueada por una regla de negocio), nunca bloqueada por L3 |
| O6 | Supervisor | Registra una segunda obligación del mismo titular de O2, con el mismo celular | No se rechaza por "contacto duplicado"; la nueva cuenta queda con el canal disponible |