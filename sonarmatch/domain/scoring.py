"""Términos del puntaje: S_tags, S_grafo (PPR), P_nov, S_onto; normalización y combinación."""

from collections.abc import Mapping

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from sonarmatch.domain.indice import IndiceCatalogo, Vector
from sonarmatch.domain.models import TERMINOS

Matriz = npt.NDArray[np.float64]
RANGO_MINIMO = 1e-15


def ppr_columnas(
    transicion: sp.csr_matrix,
    colgantes: npt.NDArray[np.bool_],
    semillas: list[int],
    damping: float,
    tolerancia: float,
    max_iter: int,
) -> Matriz:
    """Personalized PageRank por iteración de potencias, vectorizado sobre todas las semillas.

    Devuelve una matriz N × S: la columna s es el PPR con reinicio en la semilla s.
    r ← α·(Pᵀ r + masa_colgante · e_s) + (1 − α)·e_s  (igual que nx.pagerank: la masa de los
    nodos sin aristas vuelve a la personalización). Criterio de parada por columna, como
    NetworkX: ‖r − r_prev‖₁ < N·tol. Cada columna se congela al converger, de modo que su valor
    no depende de qué otras semillas se calculen en el mismo lote (lo que exige el contrafactual).
    """
    n, s = transicion.shape[0], len(semillas)
    e = np.zeros((n, s))
    e[semillas, np.arange(s)] = 1.0
    # Arranque en la semilla: los nodos inalcanzables quedan exactamente en 0 (NetworkX arranca
    # uniforme y deja un residuo del orden de la tolerancia en ellos).
    r = e.copy()
    activas = np.ones(s, dtype=bool)
    pt = sp.csr_matrix(transicion.T)
    for _ in range(max_iter):
        if not activas.any():
            break
        cols = np.flatnonzero(activas)
        r_act = r[:, cols]
        masa_colgante = r_act[colgantes].sum(axis=0)
        nuevo = damping * (pt @ r_act + e[:, cols] * masa_colgante) + (1 - damping) * e[:, cols]
        err = np.abs(nuevo - r_act).sum(axis=0)
        r[:, cols] = nuevo
        activas[cols[err < n * tolerancia]] = False
    return r


def s_grafo(ppr: Matriz, pesos: Vector) -> tuple[Vector, Matriz]:
    """Por linealidad, PPR del perfil = Σ w_i · PPR_i. Devuelve el total y los aportes N × S."""
    aportes = ppr * pesos[None, :]
    return aportes.sum(axis=1), aportes


def s_tags(indice: IndiceCatalogo, perfil_vec: Vector, candidatos: npt.NDArray[np.int64]) -> Vector:
    """Coseno entre el perfil (L2) y tfidf(c) (filas L2) = producto punto."""
    if indice.tfidf.shape[1] == 0:
        return np.zeros(len(candidatos))
    return np.asarray(indice.tfidf[candidatos] @ perfil_vec, dtype=float).ravel()


def s_onto(indice: IndiceCatalogo, p: Vector, candidatos: npt.NDArray[np.int64]) -> Vector:
    """S_onto(c) = Σ_g p_g · max_{h ∈ q_c} sim_wp(g, h)."""
    activos = np.flatnonzero(p > 0)
    salida = np.zeros(len(candidatos))
    if activos.size == 0:
        return salida
    sim = indice.wu_palmer[activos]  # |p| × G
    q = indice.generos_artista[candidatos]
    for k in range(len(candidatos)):
        h = q.indices[q.indptr[k] : q.indptr[k + 1]]
        if h.size:
            salida[k] = float(p[activos] @ sim[:, h].max(axis=1))
    return salida


def minmax(x: Vector) -> Vector:
    """Min-max sobre los candidatos de la consulta; si no hay rango, todos valen 0."""
    if x.size == 0:
        return x
    lo, hi = float(np.min(x)), float(np.max(x))
    if hi - lo <= RANGO_MINIMO:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def combinar(
    terminos: Mapping[str, Vector], pesos: Mapping[str, float]
) -> tuple[Vector, dict[str, Vector], Vector]:
    """puntaje = Σ peso_t · minmax(t). Devuelve (puntaje, aportes por término, puntaje crudo)."""
    n = len(next(iter(terminos.values())))
    aportes = {t: pesos[t] * minmax(terminos[t]) for t in TERMINOS}
    puntaje = np.zeros(n)
    crudo = np.zeros(n)
    for t in TERMINOS:
        puntaje += aportes[t]
        crudo += pesos[t] * terminos[t]
    return puntaje, aportes, crudo
