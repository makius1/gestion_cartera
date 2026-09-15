"""Crea en el repositorio los issues de una lista de tareas por área.

Por cada área crea primero sus pendientes y después un issue de revisión
general que enlaza esos pendientes, asignados al responsable del área. Si ya
existe un issue con el mismo título, no lo repite: se puede correr de nuevo
sin duplicar nada.

Lo ejecuta el flujo "Crear issues desde una lista" de GitHub Actions, con el
token temporal del propio flujo. Con --simular solo imprime lo que haría, y
así se puede revisar en cualquier equipo sin token.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def etiqueta_de(titulo):
    return "observacion" if titulo.startswith("Observación") else "mejora"


def cuerpo_tarea(tarea, area):
    lineas = ["**Área {}:** {} · responsable: {}".format(area["numero"], area["nombre"], area["responsable"]),
              "**Prioridad:** {}".format(tarea["prioridad"]), "",
              "## Qué se propone", "", tarea["que"], "",
              "## Para qué sirve", "", tarea["para_que"], "",
              "## Criterios de aceptación", ""]
    lineas += ["- [ ] " + c for c in tarea["criterios"]]
    if tarea.get("nota"):
        lineas += ["", "> " + tarea["nota"]]
    return "\n".join(lineas)


def cuerpo_revision(area, pendientes, repo, documento):
    enlace = "https://github.com/{}/blob/main/{}".format(repo, documento)
    lineas = ["Revisión general del **área {}: {}**, a cargo de {}.".format(
                  area["numero"], area["nombre"], area["responsable"]),
              "", "Carpetas: `{}`".format(area["carpetas"]),
              "", "Lo completo y lo pendiente del área está en [{}]({}).".format(documento, enlace),
              "", "## Revisión", "",
              "- [ ] Leer el código de las carpetas del área y anotar lo que no se entienda "
              "o no tenga comentarios que expliquen el porqué",
              "- [ ] Leer la sección del área en el README y en `docs/ALGORITMOS.md` y "
              "comprobar que coinciden con el código",
              "- [ ] Correr en el Codespace los comandos del área:"]
    for comando in area["comandos"]:
        lineas += ["  ```bash", "  " + comando, "  ```"]
    lineas += ["- [ ] Confirmar que lo marcado como completo en el documento de estado de verdad lo está",
               "- [ ] Registrar cada hallazgo como Error, Mejora o cambio u Observación y enlazarlo aquí",
               "", "## Pendientes del área", ""]
    lineas += ["- [ ] #{} {}".format(numero, titulo) for numero, titulo in pendientes]
    return "\n".join(lineas)


class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def _pedir(self, metodo, ruta, datos=None):
        solicitud = urllib.request.Request(
            API + ruta, method=metodo,
            data=json.dumps(datos).encode() if datos is not None else None,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(solicitud) as respuesta:
            return json.loads(respuesta.read() or "null")

    def titulos_existentes(self):
        titulos, pagina = {}, 1
        while True:
            lote = self._pedir("GET", "/repos/{}/issues?state=all&per_page=100&page={}".format(
                self.repo, pagina))
            # El listado de issues incluye los pull requests; se descartan.
            titulos.update({i["title"]: i["number"] for i in lote if "pull_request" not in i})
            if len(lote) < 100:
                return titulos
            pagina += 1

    def crear(self, titulo, cuerpo, etiqueta, responsable):
        numero = self._pedir("POST", "/repos/{}/issues".format(self.repo),
                             {"title": titulo, "body": cuerpo, "labels": [etiqueta]})["number"]
        if responsable:
            # Si el usuario todavía no aceptó la invitación, GitHub lo ignora
            # sin fallar; se puede asignar después desde el issue.
            self._pedir("POST", "/repos/{}/issues/{}/assignees".format(self.repo, numero),
                        {"assignees": [responsable]})
        # Pausa corta para no chocar con el límite de creación de contenido.
        time.sleep(1)
        return numero


class Simulador:
    """Imprime lo que se crearía, con números ficticios."""

    def __init__(self):
        self.siguiente = 1

    def titulos_existentes(self):
        return {}

    def crear(self, titulo, cuerpo, etiqueta, responsable):
        numero, self.siguiente = self.siguiente, self.siguiente + 1
        print("\n#{} [{}] -> {}\n{}\n{}".format(numero, etiqueta, responsable or "(sin asignar)",
                                                titulo, cuerpo))
        return numero


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archivo", default=".github/tareas/estado_inicial.json")
    parser.add_argument("--responsables", default="",
                        help="usuarios de GitHub por área, por ejemplo 1=usuario,2=otro")
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()

    with open(args.archivo, encoding="utf-8") as f:
        lista = json.load(f)
    usuarios = dict(par.split("=", 1) for par in args.responsables.split(",") if "=" in par)
    repo = os.environ.get("GITHUB_REPOSITORY", "makius1/gestion_cartera")

    if args.simular:
        destino = Simulador()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("Falta GITHUB_TOKEN. Para revisar sin crear nada, usar --simular.")
        destino = GitHub(repo, token)

    existentes = destino.titulos_existentes()
    creados = omitidos = 0

    def asegurar(titulo, cuerpo, etiqueta, responsable):
        nonlocal creados, omitidos
        if titulo in existentes:
            omitidos += 1
            print("Ya existe #{}: {}".format(existentes[titulo], titulo))
            return existentes[titulo]
        numero = destino.crear(titulo, cuerpo, etiqueta, responsable)
        existentes[titulo] = numero
        creados += 1
        if not args.simular:
            print("Creado #{}: {}".format(numero, titulo))
        return numero

    for area in lista["areas"]:
        responsable = usuarios.get(str(area["numero"]), "").strip()
        pendientes = []
        for tarea in (t for t in lista["tareas"] if t["area"] == area["numero"]):
            numero = asegurar(tarea["titulo"], cuerpo_tarea(tarea, area),
                              etiqueta_de(tarea["titulo"]), responsable)
            pendientes.append((numero, tarea["titulo"]))
        titulo = "Revisión general: área {}, {}".format(area["numero"], area["nombre"].lower())
        asegurar(titulo, cuerpo_revision(area, pendientes, repo, lista["documento"]),
                 "observacion", responsable)

    print("\n{} creados, {} ya existían.".format(creados, omitidos))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as error:
        sys.exit("GitHub respondió {}: {}".format(error.code, error.read().decode(errors="replace")))
