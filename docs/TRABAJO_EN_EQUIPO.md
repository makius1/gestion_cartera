# Trabajo en equipo

Cómo trabajan cuatro personas sobre el proyecto sin pisarse, con el mismo
código, el mismo entorno y los mismos datos, y cómo se hacen las pruebas
conjuntas.

## 1. Qué comparte el equipo

| Qué | Dónde | Cómo se mantiene igual para todos |
|---|---|---|
| Código | Repositorio `makius1/gestion_cartera` en GitHub | Todo cambio entra a `main` por *pull request* y solo si pasan las pruebas automáticas |
| Entorno de desarrollo | GitHub Codespaces | `.devcontainer/devcontainer.json` crea el mismo Python 3.11 con las mismas librerías para todos |
| Conexión a la base | Secretos de Codespaces del repositorio | `DATABASE_URL` y `SEUDONIMO_CLAVE` llegan solos a cada Codespace; nadie los copia a mano |
| Base de pruebas conjuntas | Supabase | Una sola base: todos ven las mismas cargas, gestiones, planes y usuarios |
| Aplicación de pruebas | Streamlit Community Cloud | Se publica desde `main`: una sola dirección, siempre con la última versión aprobada |
| Tareas y errores | *Issues* y *Projects* de GitHub | Cada tarea y cada error tiene responsable y estado |

La clave de seudónimos (`SEUDONIMO_CLAVE`) tiene que ser la misma para todos.
Con una clave distinta, las cuentas registradas por esa persona tendrían
códigos que no coinciden con los de la base.

---

## 2. Configuración inicial (una sola vez)

### Lo hace el dueño del repositorio

1. **Invitar a los integrantes:** *Settings → Collaborators → Add people*, con
   permiso de escritura (*Write*). Los secretos de Codespaces solo llegan a
   cuentas con ese permiso.
2. **Proteger la rama `main`:** *Settings → Branches → Add branch ruleset*,
   sobre `main`:
   - Exigir *pull request* antes de fusionar, con al menos 1 aprobación.
   - Exigir que pase la verificación **Pruebas**.
   - Impedir *force push* y borrado de la rama.
3. **Confirmar los secretos de Codespaces:** *Settings → Secrets and variables →
   Codespaces*, con `DATABASE_URL` y `SEUDONIMO_CLAVE`.
4. **Publicar la aplicación de pruebas** en Streamlit Community Cloud (pasos en
   el README), con los mismos dos secretos.
5. **Crear un usuario de la aplicación para cada integrante**, con un rol
   distinto para poder probar todos los flujos:

   | Integrante | Rol en la aplicación |
   |---|---|
   | 1 | Administrador |
   | 2 | Supervisor |
   | 3 | Gestor |
   | 4 | Gestor |

   Cada persona usa su propio usuario. Así la auditoría y la traza de trabajo
   muestran quién hizo cada cosa, igual que en una operación real.

### Lo hace cada integrante

1. Aceptar la invitación al repositorio (llega por correo).
2. En el repositorio: **Code → Codespaces → Create codespace on main**.
3. Cuando termine de crearse, verificar en la terminal:

   ```bash
   python -m datos.base_datos probar
   ```

   Debe decir *PostgreSQL en Supabase (pooler)* y mostrar las tablas con datos.
   Si dice *SQLite local*, el Codespace se creó antes de que existieran los
   secretos: reconstruirlo con `F1` → **Codespaces: Rebuild Container**.

---

## 3. Flujo de trabajo diario

Nadie trabaja directamente sobre `main`. Cada tarea va en su propia rama.

**Antes de empezar**, traer lo último:

```bash
git checkout main
```

```bash
git pull
```

**Crear la rama de la tarea**, con un nombre que diga qué se hace:

```bash
git checkout -b funcion/modelo-propension
```

| Prefijo | Para qué |
|---|---|
| `funcion/` | Una funcionalidad nueva |
| `correccion/` | Arreglar un error |
| `documentacion/` | Solo documentos |
| `pruebas/` | Solo pruebas |

**Trabajar y guardar por pasos.** Un commit por módulo o por caso, con un
mensaje impersonal que diga qué se hizo:

```bash
git add motor/base_conocimiento.py
```

```bash
git commit -m "Se agrega la regla de horario para los sabados"
```

**Subir la rama:**

```bash
git push -u origin funcion/modelo-propension
```

**Abrir el *pull request*** en GitHub (aparece un botón *Compare & pull
request*), llenar la plantilla y asignar a un compañero como revisor.

**Revisión:** GitHub corre las pruebas automáticas sobre la rama. El revisor lee
los cambios y los aprueba o pide ajustes. Con la aprobación y las pruebas en
verde, se fusiona a `main` y se borra la rama.

**Después de cada fusión**, todos traen `main` actualizado antes de seguir
(`git checkout main` y luego `git pull`), y los que tengan una rama abierta la
actualizan con:

```bash
git merge main
```

### Si aparece un conflicto

Git marca en el archivo las dos versiones entre `<<<<<<<` y `>>>>>>>`. Se deja
la versión correcta (o una mezcla de ambas), se borran las marcas y se
guarda:

```bash
git add archivo_con_conflicto.py
```

```bash
git commit -m "Se resuelve el conflicto con main en archivo_con_conflicto"
```

Si no está claro cuál versión es la correcta, se habla con quien hizo el otro
cambio antes de resolverlo.

---

## 4. Reparto sugerido por módulos

Cada persona es dueña de un área: la conoce a fondo, revisa los cambios que
otros hagan en ella y es a quien se consulta. Trabajar en el área de otro está
permitido, pero se avisa en el *issue* de la tarea.

| Integrante | Área | Carpetas |
|---|---|---|
| 1 | Datos, base de datos e infraestructura | `datos/`, `.github/`, `.devcontainer/` |
| 2 | Motor de elegibilidad y base de conocimiento | `motor/`, `docs/ALGORITMOS.md` sección 2 |
| 3 | Segmentación, priorización y modelos (fase 4) | `analisis/`, `decision/` |
| 4 | Gestión, plan de trabajo, aplicación web y pruebas | `gestion/`, `app/`, `pruebas/` |

*Pull requests* pequeños, de una tarea cada uno. Uno de cuarenta archivos no lo
revisa nadie con cuidado.

---

## 5. Bases de datos: compartida y personal

| Base | Para qué | Cómo se usa |
|---|---|---|
| **Supabase (compartida)** | Pruebas conjuntas y demostraciones | Es la que llega por defecto a cada Codespace |
| **SQLite (personal)** | Experimentos propios que no deben afectar a los demás | Anteponer `env -u DATABASE_URL` al comando |

Ejemplo, para correr la aplicación contra una base personal vacía:

```bash
env -u DATABASE_URL python -m streamlit run app/principal.py
```

Esto funciona mientras el Codespace no tenga un archivo `.env` con
`DATABASE_URL`: si lo tiene, el sistema tomaría la cadena de ese archivo. Con
los secretos de Codespaces ese archivo no hace falta.

Reglas sobre la base compartida:

- No se borran tablas ni registros a mano. Las cargas nuevas se suman a las
  anteriores, que es como el sistema guarda la historia.
- Los cambios de estructura solo agregan: el sistema crea las tablas y
  columnas nuevas solo, sin tocar las existentes.
- La prueba automática `python -m pruebas.prueba_aplicacion` crea usuarios de
  prueba y por eso se niega a correr contra Supabase. Se corre con la base
  personal (`env -u DATABASE_URL`) o la corre GitHub en cada *pull request*.

---

## 6. Pruebas conjuntas

Una sesión por semana, o antes de cada entrega, con los cuatro conectados a la
**aplicación de pruebas** (Streamlit Cloud), cada uno con su usuario.

1. Se fusiona a `main` lo que esté aprobado. Streamlit Cloud publica la versión
   nueva sola.
2. Se abre un *issue* llamado *"Sesión de pruebas AAAA-MM-DD"*.
3. Se recorre el [plan de pruebas](PLAN_DE_PRUEBAS.md). Cada caso tiene un rol
   responsable, y el escenario del día simulado se hace con los cuatro a la vez.
4. Cada resultado se marca en el *issue*. Cada falla se registra como un *issue*
   aparte con la plantilla de error, y se asigna al dueño del área.

---

## 7. Seguridad del equipo

- El archivo `.env` y cualquier contraseña nunca se suben al repositorio ni se
  pegan en chats o *issues*. Los secretos viven solo en GitHub y en Streamlit
  Cloud.
- En el proyecto solo hay carteras simuladas. Ningún integrante carga una
  asignación con datos de personas en la base compartida.
- Si un integrante deja el equipo: se le quita el acceso al repositorio, se
  desactiva su usuario en la aplicación (no se borra, para conservar la
  auditoría) y se cambia la contraseña de la base en Supabase, en los secretos
  de GitHub y en Streamlit Cloud.
