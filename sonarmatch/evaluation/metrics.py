"""Métricas de evaluación (funciones puras)."""

from collections.abc import Collection, Sequence

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from sonarmatch.domain.diversity import similitud_intra_lista


def precision_en_k(recomendados: Sequence[int], relevantes: Collection[int], k: int = 10) -> float:
    return sum(1 for r in recomendados[:k] if r in relevantes) / k


def recall_en_k(recomendados: Sequence[int], relevantes: Collection[int], k: int = 10) -> float:
    if not relevantes:
        return 0.0
    return sum(1 for r in recomendados[:k] if r in relevantes) / len(relevantes)


def percentiles_popularidad(oyentes: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Rango percentil (0..1] de cada artista por oyentes; empates comparten el mayor rango."""
    n = len(oyentes)
    if n == 0:
        return np.zeros(0)
    orden = np.sort(oyentes)
    return np.searchsorted(orden, oyentes, side="right").astype(np.float64) / n


def novedad(recomendados: Sequence[int], percentiles: npt.NDArray[np.float64]) -> float:
    """Popularidad media de lo recomendado (percentil de oyentes): menor es más nicho."""
    if not recomendados:
        return 0.0
    return float(np.mean(percentiles[list(recomendados)]))


def ils(recomendados: Sequence[int], tfidf: sp.csr_matrix) -> float:
    """Similitud intra-lista: coseno TF-IDF medio entre pares de la lista."""
    if len(recomendados) < 2:  # noqa: PLR2004 — con menos de dos elementos no hay pares
        return 0.0
    x = tfidf[list(recomendados)]
    return similitud_intra_lista(np.asarray((x @ x.T).todense(), dtype=np.float64))


def cobertura_catalogo(listas: Sequence[Sequence[int]], n_catalogo: int) -> float:
    if n_catalogo == 0:
        return 0.0
    return len({i for lista in listas for i in lista}) / n_catalogo


def percentil(valores: Sequence[float], q: float) -> float:
    return float(np.percentile(valores, q)) if valores else 0.0
