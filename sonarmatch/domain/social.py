"""Dimensión social: semillas de PPR mezcladas con las de los amigos y reparto exacto del aporte.

Vector de personalización: s = (1 − β)·s_propio + β·s_amigos, con s_amigos el promedio de los
vectores de semillas de los amigos que comparten gustos (cada uno con Σ w = 1, construido igual
que el del usuario). Por linealidad del PPR,

    PPR(s) = (1 − β)·Σ_i w_i·PPR_i + (β / F)·Σ_f Σ_j w_fj·PPR_fj,

así que basta una columna de PPR por artista semilla distinto: las del usuario se reutilizan y
solo se calculan las de los artistas nuevos que aportan los amigos (el motor las cachea, y
también el vector agregado de cada amigo).

Reparto: el término de grafo de un candidato c (ya normalizado y ponderado por b) se divide en
proporción a la contribución sin normalizar: s_social(c) = término · social(c) / total(c) y
s_grafo(c) = término − s_social(c). Por amigo, igual con por_amigo[f](c). Así s_grafo + s_social
es exactamente el término de grafo y los aportes siguen sumando el puntaje.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from sonarmatch.domain.indice import Vector
from sonarmatch.domain.models import ContextoSocial, PerfilUsuario
from sonarmatch.domain.scoring import Matriz, s_grafo


@dataclass
class SemillasSociales:
    """Contribución de cada amigo al PPR, ya agregada: v_f = Σ_j w_fj·PPR_fj (vector N).

    Por linealidad basta un vector por amigo; sus columnas salen del caché del motor y el vector
    se reutiliza en todas las re-ejecuciones (contrafactuales) de la consulta.
    """

    contexto: ContextoSocial
    vectores_amigo: dict[str, Vector] = field(default_factory=dict)  # sin escalar por β / F

    @property
    def beta(self) -> float:
        return self.contexto.beta

    def pesos_amigo(self) -> dict[str, float]:
        """Factor β / F de cada amigo en el vector mezclado."""
        return {a: self.beta / len(self.vectores_amigo) for a in self.vectores_amigo}


@dataclass
class GrafoSocial:
    """PPR del vector mezclado, separado en la parte propia y la de cada amigo."""

    total: Vector
    propio: Vector
    social: Vector
    por_amigo: dict[str, Vector] = field(default_factory=dict)

    def fraccion_social(self, i: int) -> float:
        return float(self.social[i] / self.total[i]) if self.total[i] > 0 else 0.0

    def fracciones_amigos(self, i: int) -> dict[str, float]:
        if self.total[i] <= 0:
            return {}
        return {a: float(v[i] / self.total[i]) for a, v in self.por_amigo.items() if v[i] > 0}


def semillas_sociales(
    contexto: ContextoSocial | None, vector_amigo: Callable[[PerfilUsuario], Vector]
) -> SemillasSociales | None:
    """Devuelve None si no hay amigos activos (β = 0 o ninguno con artistas en el catálogo):
    el flujo es entonces exactamente el de un usuario sin amigos.

    ``vector_amigo`` da Σ_j w_fj·PPR_fj de un perfil (el motor lo calcula con columnas
    cacheadas: solo se calculan las semillas que no existían).
    """
    if contexto is None or not contexto.activo:
        return None
    vectores = {a.apodo: vector_amigo(a.perfil) for a in contexto.amigos if a.perfil.indices}
    return SemillasSociales(contexto, vectores)


def vector_de_perfil(perfil: PerfilUsuario, columnas: Callable[[Sequence[int]], Matriz]) -> Vector:
    """Σ_j w_j·PPR_j (por linealidad, el PPR con reinicio en el vector de semillas del perfil)."""
    total, _ = s_grafo(columnas(list(perfil.indices)), np.asarray(perfil.pesos))
    return total


def grafo_social(ppr: Matriz, pesos: Vector, sociales: SemillasSociales | None) -> GrafoSocial:
    """Sin amigos activos: total = Σ w_i·PPR_i, igual que antes de la dimensión social."""
    total, _ = s_grafo(ppr, pesos)
    if sociales is None:
        return GrafoSocial(total, total, np.zeros_like(total))
    propio = (1 - sociales.beta) * total
    factores = sociales.pesos_amigo()
    por_amigo = {a: factores[a] * v for a, v in sociales.vectores_amigo.items()}
    social = np.sum(list(por_amigo.values()), axis=0)
    return GrafoSocial(propio + social, propio, social, por_amigo)
