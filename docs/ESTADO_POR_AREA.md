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
- Esquema de 15 tablas con historial de cargas, migración automática de
  columnas y Row Level Security en Supabase.
- Directorio de titulares y contactos separado de la analítica, con datos
  enmascarados.
- Completado de cargas anteriores al esquema actual (`datos/completar.py`).
- Autorización del titular por canal (Ley 2300, artículo 2): tabla propia,
  columnas derivadas en la cartera para el motor y autorizaciones simuladas en
  las cargas sintéticas (`datos/autorizaciones.py`).
- Confirmación obligatoria antes de que un comando escriba en una base
  remota (`--confirmar-remota`).
- Rechazo a seudonimizar contra una base remota sin `SEUDONIMO_CLAVE`
  definida: evita cuentas con seudónimos que no coinciden entre cargas.
- Respaldo semanal de la base compartida, con restauración verificada en cada
  ejecución (`.github/workflows/respaldar_base.yml`).
- Conexión optimizada: el esquema se verifica una vez por proceso y la conexión
  se comprueba solo tras un minuto de inactividad.
- Seguridad de acceso: claves con scrypt, bloqueo por intentos fallidos, cierre
  por inactividad, permisos por rol y auditoría.
- Pruebas automáticas en GitHub con PostgreSQL, Codespaces con los secretos del
  repositorio, flujos para sembrar y mantener activa la base.
- Reglas de protección de `main`, plantillas de *issues* y de *pull requests*,
  guía de trabajo en equipo.
- Aplicación publicada en Streamlit Community Cloud.
- Manual de usuario por rol (`docs/MANUAL_USUARIO.md`).

### Pendiente

Sin pendientes por ahora.

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

- Base de conocimiento de 21 reglas en fases (legales L, de negocio N, de
  contactabilidad C y de estrategia E), separada del motor y con validación.
- Encadenamiento hacia adelante con Modus Ponens, resolución de conflictos por
  prioridad y regla de precaución: un hecho desconocido nunca habilita un
  contacto.
- Ley 2300 de 2023 (días, horarios y frecuencia) con los festivos de Colombia.
- Módulo de explicación ("¿Por qué?") con la cadena de reglas y su fundamento.
- Simulador de hechos en la pantalla *Base de conocimiento*.
- Registro de cada ejecución y de la evaluación de cada cuenta.
- Pruebas unitarias de las 21 reglas, con un caso que dispara y uno que no
  cada una, y comprobación de cobertura si se agrega una regla nueva.
- Fundamento legal de cada regla revisado contra la Ley 2300 y la Ley 1581.
- Canal de contacto elegido con muestreo de Thompson sobre la respuesta
  observada, con reglas E1 a E5 y E9 como referencia cuando no hay historial.
- Simulación de historial de gestiones con causa conocida para entrenar el
  modelo (issue #11).
- Uso de la probabilidad de pago del modelo en la priorización, con
  comparación de recaudo esperado con y sin modelo (issue #13).
- Asignación óptima de cuentas a gestores con programación lineal entera,
  comparada contra la serpentina (issue #14).

### Pendiente

Sin pendientes por ahora.

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
- Fase 4: modelos de propensión a pagar (regresión logística, CART, bosque
  aleatorio y Gradient Boosting), validados por fecha y elegidos por AUC, KS,
  Brier y PSI.

### Pendiente

| Prioridad | Tarea |
|---|---|
| Alta | Fase 4: simular un historial de pagos con causas conocidas para entrenar (en revisión, PR #42) |
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
- Aplicación web con 14 pantallas y menú por rol.
- Prueba automática de las 14 pantallas con los tres roles, y plan de pruebas
  conjuntas.
- Reserva de la cuenta entregada por *Siguiente cuenta*, para que dos gestores
  sin plan no reciban la misma, con prueba de concurrencia real.
- Registrar obligaciones nuevas desde la aplicación, sin una carga completa.
- Cambiar el texto de la pantalla de ingreso por uno sobre la administración de la información.

### Comandos de revisión

```bash
DATABASE_URL="sqlite:///salidas/personal.db" python -m pruebas.prueba_aplicacion
```

```bash
python -m streamlit run app/principal.py
```
