# -*- coding: utf-8 -*-
"""
Segmentación de la cartera con tres algoritmos y selección del mejor.

Agrupa las cuentas que se parecen en saldo, contactabilidad, mora, margen y
antigüedad en gestión. Cada segmento pide una estrategia distinta: no se
trabaja igual una cuenta de saldo alto recién llegada que una de saldo bajo con
años de mora.

No se apuesta por un solo algoritmo. Se prueban tres, que entienden "grupo" de
maneras distintas:

  * K-Means: grupos compactos alrededor de un centro. Minimiza la distancia de
    cada cuenta al centro de su grupo.
  * Jerárquico de Ward: parte de cada cuenta como un grupo y va uniendo los dos
    grupos cuya fusión aumenta menos la varianza interna. Detecta grupos de
    formas menos regulares que K-Means.
  * Mezcla gaussiana: supone que la cartera es la suma de varias
    distribuciones normales y estima cada una con el algoritmo EM. Admite
    grupos alargados o de distinto tamaño.

Para cada algoritmo se elige el número de segmentos por silueta (con
preferencia por el menor si la diferencia es mínima), y entre los tres gana el
de mejor puntaje compuesto de silueta, Calinski-Harabasz y Davies-Bouldin.
"""

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

import config

ALGORITMOS = {"kmeans": "K-Means", "jerarquico": "Jerárquico de Ward", "gmm": "Mezcla gaussiana"}

# La silueta compara cada cuenta con todas las demás y el jerárquico de Ward
# guarda la distancia entre todos los pares: su costo crece con el cuadrado de
# la cartera. Sobre una muestra fija dan el mismo criterio en una fracción del
# tiempo y la memoria.
MUESTRA_SILUETA = 2000
MUESTRA_JERARQUICO = 3000


def _matriz(criterios):
    """Criterios transformados y estandarizados.

    El saldo y la mora tienen colas largas: unas pocas cuentas muy grandes o
    muy antiguas arrastrarían los grupos. El logaritmo las acerca al resto. La
    estandarización (media 0, desviación 1) evita que el saldo, medido en
    pesos, pese más que la contactabilidad, medida entre 0 y 1, solo por su
    escala.
    """
    x = criterios.copy()
    x["saldo"] = np.log1p(x["saldo"])
    x["dias_mora"] = np.log1p(x["dias_mora"])
    return StandardScaler().fit_transform(x.values)


# ---------------------------------------------------------------------------
# 1. LOS TRES ALGORITMOS
# ---------------------------------------------------------------------------

def _kmeans(matriz, k, semilla, _):
    return KMeans(n_clusters=k, n_init=10, random_state=semilla).fit_predict(matriz)


def _gmm(matriz, k, semilla, preparado):
    """El algoritmo EM itera sobre todas las cuentas hasta converger y es el más
    lento de los tres. Se ajusta sobre la misma muestra del jerárquico y luego
    se clasifica toda la cartera con el modelo ajustado: una muestra de miles
    de cuentas describe bien cinco dimensiones, y el tiempo baja a una fracción.
    """
    muestra, _ = preparado
    modelo = GaussianMixture(n_components=k, covariance_type="full", random_state=semilla)
    return modelo.fit(matriz[muestra]).predict(matriz)


def _preparar_jerarquico(matriz, semilla):
    """Árbol de Ward sobre una muestra, calculado una sola vez.

    El árbol completo contiene la segmentación para todos los k: cortarlo a
    distinta altura da 2, 3 o 6 grupos sin volver a calcular nada.
    """
    rng = np.random.default_rng(semilla)
    muestra = rng.choice(len(matriz), size=min(MUESTRA_JERARQUICO, len(matriz)), replace=False)
    return muestra, linkage(matriz[muestra], method="ward")


def _jerarquico(matriz, k, semilla, preparado):
    """Corta el árbol en k grupos y asigna el resto de la cartera al centro
    del grupo más cercano."""
    muestra, arbol = preparado
    etiquetas_muestra = fcluster(arbol, t=k, criterion="maxclust") - 1
    centros = np.array([matriz[muestra][etiquetas_muestra == g].mean(axis=0)
                        for g in range(etiquetas_muestra.max() + 1)])
    distancias = ((matriz[:, None, :] - centros[None, :, :]) ** 2).sum(axis=2)
    return distancias.argmin(axis=1)


FUNCIONES = {"kmeans": _kmeans, "jerarquico": _jerarquico, "gmm": _gmm}


# ---------------------------------------------------------------------------
# 2. MÉTRICAS Y SELECCIÓN
# ---------------------------------------------------------------------------

def _silueta(matriz, etiquetas, semilla):
    if len(set(etiquetas)) < 2:
        return -1.0
    return float(silhouette_score(matriz, etiquetas, sample_size=min(MUESTRA_SILUETA, len(matriz)),
                                  random_state=semilla))


def _elegir_k(siluetas):
    """Menor k cuya silueta queda a menos de la tolerancia de la mejor."""
    mejor = max(siluetas.values())
    return min(k for k, s in siluetas.items() if s >= mejor - config.TOLERANCIA_SILUETA)


def comparar(matriz, semilla=config.SEMILLA):
    """Ejecuta los tres algoritmos y retorna (algoritmo_elegido, comparacion, etiquetas).

    comparacion tiene, por algoritmo: silueta por k, k elegido, silueta,
    Calinski-Harabasz, Davies-Bouldin, participación del segmento más pequeño,
    si es válido y su puntaje compuesto.
    """
    maximo = min(config.SEGMENTOS_MAXIMO, len(matriz) - 1)
    rango = range(config.SEGMENTOS_MINIMO, maximo + 1)
    preparado = _preparar_jerarquico(matriz, semilla)
    comparacion, particiones = {}, {}
    for nombre, funcion in FUNCIONES.items():
        etiquetas_k = {k: funcion(matriz, k, semilla, preparado) for k in rango}
        siluetas = {k: _silueta(matriz, e, semilla) for k, e in etiquetas_k.items()}
        k = _elegir_k(siluetas)
        etiquetas = etiquetas_k[k]
        tamanos = np.bincount(etiquetas) / len(etiquetas)
        comparacion[nombre] = {
            "siluetas": {str(kk): v for kk, v in siluetas.items()}, "k": int(k),
            "silueta": siluetas[k],
            "calinski": float(calinski_harabasz_score(matriz, etiquetas)),
            "davies": float(davies_bouldin_score(matriz, etiquetas)),
            "minimo": float(tamanos[tamanos > 0].min()),
        }
        comparacion[nombre]["valido"] = comparacion[nombre]["minimo"] >= config.PARTICIPACION_MINIMA_SEGMENTO
        particiones[nombre] = etiquetas

    # Puntaje compuesto: cada métrica se lleva a una escala relativa al mejor
    # (1 es el mejor de los tres). Davies-Bouldin se invierte porque en ella
    # menor es mejor.
    validos = [n for n, v in comparacion.items() if v["valido"]] or list(comparacion)
    mejor_sil = max(comparacion[n]["silueta"] for n in validos) or 1
    mejor_ch = max(comparacion[n]["calinski"] for n in validos) or 1
    mejor_db = min(comparacion[n]["davies"] for n in validos)
    pesos = config.PESOS_SEGMENTACION
    for nombre, v in comparacion.items():
        v["puntaje"] = (pesos["silueta"] * v["silueta"] / mejor_sil
                        + pesos["calinski"] * v["calinski"] / mejor_ch
                        + pesos["davies"] * mejor_db / v["davies"]) if v["valido"] else 0.0
    elegido = max(validos, key=lambda n: comparacion[n]["puntaje"])
    return elegido, comparacion, particiones[elegido]


# ---------------------------------------------------------------------------
# 3. SEGMENTACIÓN FINAL
# ---------------------------------------------------------------------------

# Cómo se describe cada criterio cuando el segmento está por encima o por
# debajo de la cartera.
RASGOS = {
    "saldo": ("saldo alto", "saldo bajo"),
    "contactabilidad": ("contacto alto", "contacto bajo"),
    "dias_mora": ("mora antigua", "mora reciente"),
    "margen_pct": ("margen amplio", "sin margen"),
    "meses_en_gestion": ("muchos meses en gestión", "recién asignada"),
}


def _nombrar(miembros, criterios):
    """Nombre del segmento con sus dos rasgos más distintivos.

    Para cada criterio se mide cuántas desviaciones estándar se aleja el
    promedio del segmento del promedio de la cartera, y se nombran los dos que
    más se alejan. Así el nombre dice en qué se diferencia el segmento, no en
    qué se parece a todos los demás.
    """
    distancia = (miembros.mean() - criterios.mean()) / criterios.std().replace(0, 1)
    principales = distancia.abs().sort_values(ascending=False)
    rasgos = [RASGOS[c][0 if distancia[c] > 0 else 1]
              for c in principales.index[:2] if principales[c] >= 0.25]
    texto = " · ".join(rasgos) if rasgos else "perfil promedio"
    return texto[0].upper() + texto[1:]


def segmentar(criterios, semilla=config.SEMILLA):
    """Segmenta la cartera. Retorna un diccionario con:

    etiquetas    segmento de cada cuenta (Serie indexada por crédito)
    nombres      nombre de cada segmento
    algoritmo    algoritmo elegido
    comparacion  métricas de los tres algoritmos
    k, silueta, siluetas   del algoritmo elegido
    perfiles     tabla con el perfil de cada segmento
    pca          coordenadas en dos dimensiones para graficar
    """
    matriz = _matriz(criterios)
    algoritmo, comparacion, crudas = comparar(matriz, semilla)

    # Se renumeran los segmentos por saldo mediano descendente: el segmento 1 es
    # siempre el de mayor saldo, con cualquier algoritmo y en cualquier ejecución.
    medianas = criterios.groupby(crudas)["saldo"].median().sort_values(ascending=False)
    orden = {viejo: nuevo for nuevo, viejo in enumerate(medianas.index, start=1)}
    etiquetas = pd.Series([orden[e] for e in crudas], index=criterios.index, name="segmento")

    perfiles = criterios.groupby(etiquetas).agg(
        cuentas=("saldo", "size"), saldo_total=("saldo", "sum"), saldo_mediano=("saldo", "median"),
        mora_mediana=("dias_mora", "median"), contactabilidad=("contactabilidad", "mean"),
        margen=("margen_pct", "mean"), meses=("meses_en_gestion", "mean"))
    nombres = {s: "S{} · {}".format(s, _nombrar(criterios[etiquetas == s], criterios))
               for s in perfiles.index}
    perfiles.insert(0, "nombre", perfiles.index.map(nombres))

    coordenadas = PCA(n_components=2, random_state=semilla).fit_transform(matriz)
    pca = pd.DataFrame(coordenadas, index=criterios.index, columns=["pca_x", "pca_y"])

    elegido = comparacion[algoritmo]
    return {"etiquetas": etiquetas, "nombres": nombres, "algoritmo": algoritmo,
            "comparacion": comparacion, "k": elegido["k"], "silueta": elegido["silueta"],
            "siluetas": {int(k): v for k, v in elegido["siluetas"].items()},
            "perfiles": perfiles, "pca": pca}
