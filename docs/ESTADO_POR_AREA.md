# Estado del proyecto por área

Qué está completo y qué falta en cada área, con su responsable. Cada pendiente
tiene su *issue* en el tablero del equipo, y cada responsable tiene además un
*issue* de **revisión general** de su área. Este documento se actualiza en el
mismo *pull request* que cierra un pendiente.

| Área | Responsable | Rol en la aplicación | Carpetas |
|---|---|---|---|
| 1. Datos, base de datos e infraestructura | David | Administrador | `datos/`, `seguridad/`, `config.py`, `.github/`, `.devcontainer/` |
| 2. Motor de elegibilidad y base de conocimiento | Juan Pablo | Supervisor | `motor/`, `docs/ALGORITMOS.md` sección 2 |
| 3. Segmentación, priorización y modelos | Francy | Gestor | `analisis/`, `decision/` |
| 4. Gestión, plan de trabajo, aplicación web y pruebas | Sean | Gestor | `gestion/`, `app/`, `pruebas/` |

## Revisión general

La hace cada responsable sobre su área, antes de empezar sus pendientes:

1. Leer el código de sus carpetas y anotar lo que no se entienda o no tenga
   comentarios que expliquen el porqué.
2. Leer su sección del README y de `docs/ALGORITMOS.md`, y comprobar que
   coinciden con el código.
3. Correr en su Codespace los comandos de su área (abajo).
4. Confirmar que lo marcado aquí como completo de verdad lo está.
5. Registrar cada hallazgo como *issue* (**Error**, **Mejora o cambio** u
   **Observación**) y enlazarlo desde su *issue* de revisión.

Los comandos que escriben en la base se corren contra la base personal, para
no alterar la compartida. La forma de hacerlo es **definir** `DATABASE_URL`
apuntando a un archivo SQLite:

```bash
DATABASE_URL="sqlite:///salidas/personal.db" python -m datos.base_datos probar
```

Debe responder *SQLite local*. No sirve quitar la variable con
`env -u DATABASE_URL`: el sistema lee el archivo `.env` al arrancar y la
variable vuelve a quedar definida, con lo que el comando escribiría en la base
compartida sin avisar. En PowerShell, en Windows:

```powershell
$env:DATABASE_URL = "sqlite:///salidas/personal.db"
```

y al terminar, `Remove-Item Env:DATABASE_URL`.

---

## 1. Datos, base de datos e infraestructura — David

### Completo

- Carga, limpieza y seudonimización de identificadores con HMAC-SHA256.
- Simulador determinista de carteras a partir de un perfil, que reconstruye
  cualquier carga con su semilla.
- Esquema de 13 tablas con historial de cargas, migración automática de
  columnas y Row Level Security en Supabase.
- Directorio de titulares y contactos separado de la analítica, con datos
  enmascarados.
- Completado de cargas anteriores al esquema actual (`datos/completar.py`).
- Conexión optimizada: el esquema se verifica una vez por proceso y la conexión
  se comprueba solo tras un minuto de inactividad.
- Seguridad de acceso: claves con scrypt, bloqueo por intentos fallidos, cierre
  por inactividad, permisos por rol y auditoría.
- Pruebas automáticas en GitHub con PostgreSQL, Codespaces con los secretos del
  repositorio, flujos para sembrar y mantener activa la base.
- Reglas de protección de `main`, plantillas de *issues* y de *pull requests*,
  guía de trabajo en equipo.

### Pendiente

| Prioridad | Tarea |
|---|---|
| Alta | Publicar la aplicación en Streamlit Community Cloud |
| Alta | Crear en la aplicación el usuario de cada integrante con su rol |
| Alta | Cambiar la contraseña de la base y actualizar los secretos antes de publicar |
| Media | Preparar la base compartida y dirigir la primera sesión de pruebas conjuntas |

### Comandos de revisión

```bash
python -m datos.base_datos probar
```

```bash
DATABASE_URL="sqlite:///salidas/personal.db" python -m datos.base_datos sintetica --registros 2000
```

---

## 2. Motor de elegibilidad y base de conocimiento — Juan Pablo

### Completo

- Base de conocimiento de 17 reglas en fases (legales L, de negocio N, de
  contactabilidad C y de estrategia E), separada del motor y con validación.
- Encadenamiento hacia adelante con Modus Ponens, resolución de conflictos por
  prioridad y regla de precaución: un hecho desconocido nunca habilita un
  contacto.
- Ley 2300 de 2023 (días, horarios y frecuencia) con los festivos de Colombia.
- Módulo de explicación ("¿Por qué?") con la cadena de reglas y su fundamento.
- Simulador de hechos en la pantalla *Base de conocimiento*.
- Registro de cada ejecución y de la evaluación de cada cuenta.

### Pendiente

| Prioridad | Tarea |
|---|---|
| Media | Pruebas unitarias de cada regla: un caso que la dispara y uno que no |
| Media | Revisar el fundamento legal de cada regla contra el texto de la Ley 2300 y la Ley 1581 |
| Baja | Elegir el canal con muestreo de Thompson según la respuesta observada (después de la fase 4) |

### Comandos de revisión

```bash
python -m motor.elegibilidad --validar
```

```bash
python -m motor.elegibilidad --fecha 2026-09-15 --no-guardar
```

---

## 3. Segmentación, priorización y modelos — Francy

### Completo

- Criterios de priorización (saldo, contactabilidad, días de mora, margen y
  meses en gestión) y perturbación para medir robustez.
- Segmentación con K-Means, Ward y mezcla gaussiana, elegida por silueta,
  Calinski-Harabasz y Davies-Bouldin.
- Priorización con lógica difusa Mamdani (14 reglas), TOPSIS y ponderación
  simple, con selección del método por recaudo, robustez y discriminación.
- Explicación de la prioridad de cada cuenta.
- Documentación matemática de todos los algoritmos en `docs/ALGORITMOS.md`.

### Pendiente

| Prioridad | Tarea |
|---|---|
| Alta | Fase 4: simular un historial de pagos con causas conocidas para entrenar |
| Alta | Fase 4: entrenar y comparar regresión logística, CART, bosque aleatorio y Gradient Boosting |
| Media | Usar la probabilidad de pago como criterio de la priorización |
| Media | Fase 5: asignar cuentas a gestores con programación lineal entera (con Sean) |

### Comandos de revisión

```bash
python -c "from decision.conocimiento_difuso import validar; print(validar() or 'Sin errores')"
```

```bash
python -m decision.priorizacion --no-guardar
```

---

## 4. Gestión, plan de trabajo, aplicación web y pruebas — Sean

### Completo

- Registro de gestiones con 10 reglas de validación (G1 a G10) que actualizan la
  cartera y retroalimentan al motor.
- Titulares y datos de contacto: validación de formatos, enmascarado y consulta
  auditada del dato completo.
- Plan de trabajo diario repartido en serpentina y avance por gestor.
- Traza de trabajo por gestor y por cuenta.
- Aplicación web con 13 pantallas y menú por rol.
- Prueba automática de las 13 pantallas con los tres roles, y plan de pruebas
  conjuntas.
- Reserva de la cuenta entregada por *Siguiente cuenta*, para que dos gestores
  sin plan no reciban la misma, con prueba de concurrencia real.

### Pendiente

| Prioridad | Tarea |
|---|---|
| Media | Registrar obligaciones nuevas desde la aplicación, sin una carga |
| Baja | Cambiar el texto de la pantalla de ingreso por uno sobre la administración de la información |

### Comandos de revisión

```bash
DATABASE_URL="sqlite:///salidas/personal.db" python -m pruebas.prueba_aplicacion
```

```bash
python -m streamlit run app/principal.py
```
