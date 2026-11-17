"""Diversificación con Maximal Marginal Relevance (MMR).

Se elige iterativamente argmax_c [λ·puntaje(c) − (1−λ)·max_{s∈S} cos(tfidf(c), tfidf(s))].
Los empates se resuelven por el orden de entrada (el llamador entrega los candidatos en
un orden determinista), de modo que con λ = 1 el resultado es el orden estable por puntaje.
"""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

Vector = npt.NDArray[np.float64]


@dataclass(frozen=True)
class DecisionMMR:
    paso: int
    elegido: int  # posición dentro de los candidatos
    valor_mmr: float
    puntaje: float
    max_similitud: float  # con lo ya elegido (0 en el primer paso)


def similitudes(tfidf_candidatos: sp.csr_matrix) -> npt.NDArray[np.float64]:
    """Matriz de coseno entre candidatos (las filas TF-IDF ya están normalizadas L2)."""
    return np.asarray((tfidf_candidatos @ tfidf_candidatos.T).toarray(), dtype=float)


def mmr(
    puntajes: Vector, sim: npt.NDArray[np.float64], lam: float, k: int | None = None
) -> list[DecisionMMR]:
    """Devuelve las decisiones en orden; ``k=None`` ordena todos los candidatos."""
    n = len(puntajes)
    k = n if k is None else min(k, n)
    max_sim = np.zeros(n)
    elegido = np.zeros(n, dtype=bool)
    decisiones: list[DecisionMMR] = []
    for paso in range(k):
        valor = lam * puntajes - (1 - lam) * max_sim
        valor[elegido] = -np.inf
        j = int(np.argmax(valor))
        decisiones.append(
            DecisionMMR(paso + 1, j, float(valor[j]), float(puntajes[j]), float(max_sim[j]))
        )
        elegido[j] = True
        max_sim = np.maximum(max_sim, sim[:, j])
    return decisiones


def similitud_intra_lista(sim: npt.NDArray[np.float64]) -> float:
    """ILS: similitud media entre pares distintos."""
    n = sim.shape[0]
    if n < 2:  # noqa: PLR2004 — con menos de dos elementos no hay pares
        return 0.0
    return float((sim.sum() - np.trace(sim)) / (n * (n - 1)))
