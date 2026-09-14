# -*- coding: utf-8 -*-
"""
Segmentación de la cartera con K-Means.

Agrupa las cuentas que se parecen en saldo, contactabilidad, mora, margen y
antigüedad en gestión. Cada segmento pide una estrategia distinta: no se
trabaja igual una cuenta de saldo alto recién llegada que una de saldo bajo con
años de mora.

El número de segmentos no se fija a mano. Se prueba K-Means con varios valores
de k y se elige el de mejor coeficiente de silueta, que mide qué tan cerca está
cada cuenta de su propio segmento frente al segmento vecino (1 es separación
perfecta, 0 es frontera difusa, negativo es cuenta mal asignada).
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

import config

# La silueta compara cada cuenta con todas las demás: su costo crece con el
# cuadrado de la cartera. Sobre una muestra fija da el mismo criterio de
# decisión en una fracción del tiempo.
MUESTRA_SILUETA = 2000


def _matriz(criterios):
    """Criterios transformados y estandarizados para K-Means.

    El saldo y la mora tienen colas largas: unas pocas cuentas muy grandes o
    muy antiguas arrastrarían los centroides. El logaritmo las acerca al resto.
    La estandarización evita que el saldo, medido en pesos, pese más que la
    contactabilidad, medida entre 0 y 1, solo por su escala.
    """
    x = criterios.copy()
    x["saldo"] = np.log1p(x["saldo"])
    x["dias_mora"] = np.log1p(x["dias_mora"])
    return StandardScaler().fit_transform(x.values)


def elegir_k(matriz, semilla=config.SEMILLA):
    """Silueta para cada k del rango configurado. Retorna (k_elegido, siluetas).

    Principio de parsimonia: se toma el menor k cuya silueta queda a menos de
    la tolerancia de la mejor. Entre dos segmentaciones igual de buenas, la de
    menos segmentos es más fácil de operar y de explicar al equipo.
    """
    siluetas = {}
    maximo = min(config.SEGMENTOS_MAXIMO, len(matriz) - 1)
    for k in range(config.SEGMENTOS_MINIMO, maximo + 1):
        etiquetas = KMeans(n_clusters=k, n_init=10, random_state=semilla).fit_predict(matriz)
        siluetas[k] = float(silhouette_score(matriz, etiquetas,
                                             sample_size=min(MUESTRA_SILUETA, len(matriz)),
                                             random_state=semilla))
    mejor = max(siluetas.values())
    k = min(k for k, s in siluetas.items() if s >= mejor - config.TOLERANCIA_SILUETA)
    return k, siluetas


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

    etiquetas  segmento de cada cuenta (Serie indexada por crédito)
    nombres    nombre de cada segmento
    k          número de segmentos elegido
    siluetas   silueta obtenida con cada k probado
    perfiles   tabla con el perfil de cada segmento
    pca        coordenadas en dos dimensiones para graficar
    """
    matriz = _matriz(criterios)
    k, siluetas = elegir_k(matriz, semilla)
    modelo = KMeans(n_clusters=k, n_init=10, random_state=semilla).fit(matriz)

    # Se renumeran los segmentos por saldo mediano descendente: el segmento 1 es
    # siempre el de mayor saldo, en cualquier ejecución.
    medianas = criterios.groupby(modelo.labels_)["saldo"].median().sort_values(ascending=False)
    orden = {viejo: nuevo for nuevo, viejo in enumerate(medianas.index, start=1)}
    etiquetas = pd.Series([orden[e] for e in modelo.labels_], index=criterios.index, name="segmento")

    perfiles = criterios.groupby(etiquetas).agg(
        cuentas=("saldo", "size"), saldo_total=("saldo", "sum"), saldo_mediano=("saldo", "median"),
        mora_mediana=("dias_mora", "median"), contactabilidad=("contactabilidad", "mean"),
        margen=("margen_pct", "mean"), meses=("meses_en_gestion", "mean"))
    nombres = {s: "S{} · {}".format(s, _nombrar(criterios[etiquetas == s], criterios))
               for s in perfiles.index}
    perfiles.insert(0, "nombre", perfiles.index.map(nombres))

    coordenadas = PCA(n_components=2, random_state=semilla).fit_transform(matriz)
    pca = pd.DataFrame(coordenadas, index=criterios.index, columns=["pca_x", "pca_y"])

    return {"etiquetas": etiquetas, "nombres": nombres, "k": k, "siluetas": siluetas,
            "silueta": siluetas[k], "perfiles": perfiles, "pca": pca}
