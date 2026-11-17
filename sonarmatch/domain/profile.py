"""Perfil ponderado del usuario: pesos w_i, vector TF-IDF del perfil y perfil de géneros."""

from collections.abc import Sequence

import numpy as np
import scipy.sparse as sp

from sonarmatch.domain.indice import IndiceCatalogo, Vector
from sonarmatch.domain.models import EntradaPerfil, PerfilUsuario
from sonarmatch.domain.textos import normalizar_nombre


def pesos_normalizados(pesos_brutos: Sequence[float]) -> Vector:
    """w_i = log(1 + peso_i), normalizado para que Σ w_i = 1."""
    w = np.log1p(np.asarray(pesos_brutos, dtype=float))
    total = float(w.sum())
    if total <= 0:
        return np.full(len(w), 1.0 / len(w)) if len(w) else w
    return np.asarray(w / total, dtype=float)


def construir_perfil_desde_indices(
    indices: Sequence[int], pesos_brutos: Sequence[float], no_encontrados: Sequence[str] = ()
) -> PerfilUsuario:
    return PerfilUsuario(
        indices=tuple(indices),
        pesos_brutos=tuple(float(p) for p in pesos_brutos),
        pesos=tuple(float(x) for x in pesos_normalizados(pesos_brutos)),
        no_encontrados=tuple(no_encontrados),
    )


def construir_perfil(indice: IndiceCatalogo, entradas: Sequence[EntradaPerfil]) -> PerfilUsuario:
    """Empareja por nombre normalizado; los no encontrados se reportan y se ignoran."""
    indices: list[int] = []
    brutos: list[float] = []
    faltan: list[str] = []
    for e in entradas:
        i = indice.por_nombre.get(normalizar_nombre(e.nombre))
        if i is None:
            faltan.append(e.nombre)
        elif i not in indices:
            indices.append(i)
            brutos.append(e.peso)
    return construir_perfil_desde_indices(indices, brutos, faltan)


def perfil_sin(perfil: PerfilUsuario, posicion: int) -> PerfilUsuario:
    """Perfil sin el artista en ``posicion`` (pesos renormalizados)."""
    return construir_perfil_desde_indices(
        perfil.indices[:posicion] + perfil.indices[posicion + 1 :],
        perfil.pesos_brutos[:posicion] + perfil.pesos_brutos[posicion + 1 :],
        perfil.no_encontrados,
    )


def vector_perfil(indice: IndiceCatalogo, perfil: PerfilUsuario) -> Vector:
    """perfil = Σ w_i · tfidf(artista_i), normalizado L2 (vector denso de tamaño V)."""
    v = np.zeros(indice.tfidf.shape[1])
    if perfil.indices:
        w = sp.csr_matrix(np.asarray(perfil.pesos)[None, :])
        v = np.asarray((w @ indice.tfidf[list(perfil.indices)]).todense()).ravel()
    norma = float(np.linalg.norm(v))
    return v / norma if norma > 0 else v


def perfil_generos_base(indice: IndiceCatalogo, perfil: PerfilUsuario) -> Vector:
    """Distribución de géneros del perfil (Σ w_i · q_i, con q_i ya ponderado por confianza)."""
    p = np.zeros(len(indice.generos))
    if perfil.indices:
        w = sp.csr_matrix(np.asarray(perfil.pesos)[None, :])
        p = np.asarray((w @ indice.generos_artista[list(perfil.indices)]).todense()).ravel()
    total = float(p.sum())
    return p / total if total > 0 else p


def agregar_afinidades(p_base: Vector, afinidades: dict[int, float]) -> Vector:
    """Suma las afinidades inferidas por R1 (con su confianza) y renormaliza."""
    p = p_base.copy()
    for j, conf in afinidades.items():
        p[j] += conf
    total = float(p.sum())
    return p / total if total > 0 else p
