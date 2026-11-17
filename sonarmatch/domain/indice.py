"""Índice en memoria del catálogo: se construye una sola vez al arrancar.

Contiene la matriz TF-IDF de etiquetas, la matriz de transición del grafo de similitud,
la novedad de cada artista, la ontología, la distribución de géneros de cada artista y la
matriz Wu-Palmer entre los géneros usados.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer

from sonarmatch.domain.models import Artista, Catalogo
from sonarmatch.domain.ontology import Ontologia
from sonarmatch.domain.textos import normalizar_nombre

Vector = npt.NDArray[np.float64]


def _identidad(doc: Sequence[str]) -> Sequence[str]:
    return doc


def normalizar_filas_l2(m: sp.csr_matrix) -> sp.csr_matrix:
    normas = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
    inv = np.divide(1.0, normas, out=np.zeros_like(normas), where=normas > 0)
    return sp.csr_matrix(sp.diags(inv) @ m)


def construir_tfidf(artistas: Sequence[Artista]) -> tuple[sp.csr_matrix, list[str]]:
    """Cada artista es un documento de etiquetas ponderadas.

    TfidfVectorizer aporta el vocabulario y el IDF (sobre presencia de etiquetas); el TF es el
    peso de Last.fm de la etiqueta (0..100, se usa max(peso, 1)/100). Filas normalizadas L2.
    """
    docs = [[t for t, _ in a.etiquetas] for a in artistas]
    vectorizador = TfidfVectorizer(analyzer=_identidad, lowercase=False, norm=None)
    if not any(docs):
        return sp.csr_matrix((len(artistas), 0)), []
    presencia_idf = sp.csr_matrix(vectorizador.fit_transform(docs))
    vocab: dict[str, int] = vectorizador.vocabulary_
    filas, cols, datos = [], [], []
    for i, a in enumerate(artistas):
        for t, w in a.etiquetas:
            filas.append(i)
            cols.append(vocab[t])
            datos.append(max(w, 1.0) / 100.0)
    tf = sp.csr_matrix((datos, (filas, cols)), shape=presencia_idf.shape)
    tf.sum_duplicates()
    idf = np.asarray(vectorizador.idf_, dtype=float)
    tfidf = sp.csr_matrix(tf @ sp.diags(idf))
    nombres = [""] * len(vocab)
    for t, j in vocab.items():
        nombres[j] = t
    return normalizar_filas_l2(tfidf), nombres


def construir_transicion(
    n: int, aristas: Sequence[tuple[int, int, float]]
) -> tuple[sp.csr_matrix, npt.NDArray[np.bool_]]:
    """Grafo no dirigido con peso = match; matriz de transición normalizada por filas.

    Si una arista aparece en ambos sentidos se toma el mayor match. Devuelve también la
    máscara de nodos colgantes (sin aristas).
    """
    pesos: dict[tuple[int, int], float] = {}
    for u, v, m in aristas:
        if u == v or m <= 0:
            continue
        clave = (min(u, v), max(u, v))
        pesos[clave] = max(pesos.get(clave, 0.0), m)
    filas = [u for u, _ in pesos] + [v for _, v in pesos]
    cols = [v for _, v in pesos] + [u for u, _ in pesos]
    datos = list(pesos.values()) * 2
    adj = sp.csr_matrix((datos, (filas, cols)), shape=(n, n))
    grado = np.asarray(adj.sum(axis=1)).ravel()
    inv = np.divide(1.0, grado, out=np.zeros_like(grado), where=grado > 0)
    return sp.csr_matrix(sp.diags(inv) @ adj), grado == 0


def novedad(oyentes: npt.NDArray[np.float64]) -> Vector:
    """P_nov(c) = 1 - log(1 + oyentes_c) / log(1 + oyentes_max)."""
    maximo = float(np.max(oyentes)) if oyentes.size else 0.0
    if maximo <= 0:
        return np.ones_like(oyentes, dtype=float)
    return np.asarray(1.0 - np.log1p(oyentes) / np.log1p(maximo), dtype=float)


@dataclass
class IndiceCatalogo:
    artistas: tuple[Artista, ...]
    por_nombre: dict[str, int]  # nombre normalizado -> índice
    por_id: dict[int, int]  # id de artista -> índice
    tfidf: sp.csr_matrix  # N x V, filas L2
    vocabulario: list[str]
    transicion: sp.csr_matrix  # N x N, filas suman 1 (o 0 si colgante)
    colgantes: npt.NDArray[np.bool_]
    oyentes: Vector
    p_nov: Vector
    ontologia: Ontologia
    generos: list[str]  # todos los géneros de la ontología (columnas de generos_artista)
    pos_genero: dict[str, int]
    generos_artista: sp.csr_matrix  # N x G, filas suman 1 (o 0 si no hay etiquetas mapeadas)
    wu_palmer: npt.NDArray[np.float64]  # G x G
    mapeo: dict[str, list[tuple[str, float]]]  # etiqueta -> [(género, confianza)]

    @property
    def n(self) -> int:
        return len(self.artistas)

    @classmethod
    def construir(cls, catalogo: Catalogo) -> "IndiceCatalogo":
        artistas = tuple(sorted(catalogo.artistas, key=lambda a: a.id))
        por_id = {a.id: i for i, a in enumerate(artistas)}
        por_nombre: dict[str, int] = {}
        for i, a in enumerate(artistas):
            por_nombre.setdefault(normalizar_nombre(a.nombre), i)
        tfidf, vocab = construir_tfidf(artistas)
        aristas = [
            (por_id[u], por_id[v], m)
            for u, v, m in catalogo.similares
            if u in por_id and v in por_id
        ]
        transicion, colgantes = construir_transicion(len(artistas), aristas)
        oyentes = np.array([max(a.oyentes, 0) for a in artistas], dtype=float)
        ontologia = Ontologia.construir(
            {g.id: g.padres for g in catalogo.generos},
            {g.id: g.etiqueta_es or g.etiqueta_en for g in catalogo.generos},
        )
        mapeo: dict[str, list[tuple[str, float]]] = {}
        for m in catalogo.mapeos:
            if m.genero_id in ontologia.padres:
                mapeo.setdefault(m.etiqueta, []).append((m.genero_id, m.confianza))
        generos = ontologia.generos
        generos_artista = _generos_por_artista(artistas, mapeo, generos)
        return cls(
            artistas=artistas,
            por_nombre=por_nombre,
            por_id=por_id,
            tfidf=tfidf,
            vocabulario=vocab,
            transicion=transicion,
            colgantes=colgantes,
            oyentes=oyentes,
            p_nov=novedad(oyentes),
            ontologia=ontologia,
            generos=generos,
            pos_genero={g: j for j, g in enumerate(generos)},
            generos_artista=generos_artista,
            wu_palmer=ontologia.matriz_wu_palmer(generos),
            mapeo=mapeo,
        )

    def percentil_oyentes(self, q: float) -> float:
        return float(np.percentile(self.oyentes, q)) if self.n else 0.0

    def generos_de(self, indice: int) -> dict[str, float]:
        fila = self.generos_artista.getrow(indice)
        return {self.generos[j]: float(v) for j, v in zip(fila.indices, fila.data, strict=True)}

    def nombre(self, indice: int) -> str:
        return self.artistas[indice].nombre


def _generos_por_artista(
    artistas: Sequence[Artista], mapeo: dict[str, list[tuple[str, float]]], generos: list[str]
) -> sp.csr_matrix:
    """q_c: distribución de géneros por artista (peso de etiqueta x confianza del mapeo)."""
    pos = {g: j for j, g in enumerate(generos)}
    filas, cols, datos = [], [], []
    for i, a in enumerate(artistas):
        for t, w in a.etiquetas:
            for g, conf in mapeo.get(t, ()):
                filas.append(i)
                cols.append(pos[g])
                datos.append(max(w, 1.0) * conf)
    m = sp.csr_matrix((datos, (filas, cols)), shape=(len(artistas), len(generos)))
    m.sum_duplicates()
    sumas = np.asarray(m.sum(axis=1)).ravel()
    inv = np.divide(1.0, sumas, out=np.zeros_like(sumas), where=sumas > 0)
    return sp.csr_matrix(sp.diags(inv) @ m)
