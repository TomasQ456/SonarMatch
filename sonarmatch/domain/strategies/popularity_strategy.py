"""Respaldo 2 y línea base: los artistas más escuchados en las etiquetas dominantes del perfil.

Orden: oyentes (desc). Si no alcanzan, se completa con los más populares del catálogo.
El puntaje informado es la afinidad de etiquetas (S_tags), que no determina el orden.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np

from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import Recomendacion
from sonarmatch.domain.razonamiento import PerfilRazonado
from sonarmatch.domain.strategies.base import ResultadoEstrategia


def etiquetas_dominantes(indice: IndiceCatalogo, perfil: PerfilRazonado, n: int) -> list[str]:
    v = perfil.vector
    orden = [int(j) for j in np.lexsort((np.arange(len(v)), -v)) if v[j] > 0]
    return [indice.vocabulario[j] for j in orden[:n]]


@dataclass
class EstrategiaPopularidad:
    indice: IndiceCatalogo
    n_etiquetas: int = 3  # ConfigMotor.n_etiquetas_dominantes
    id: Literal["popularidad"] = "popularidad"

    def recomendar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> list[Recomendacion]:
        return self.ejecutar(perfil, n, excluir).recomendaciones

    def ejecutar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> ResultadoEstrategia:
        ix = self.indice
        pos_vocab = {t: j for j, t in enumerate(ix.vocabulario)}
        cols = [pos_vocab[t] for t in etiquetas_dominantes(ix, perfil, self.n_etiquetas)]
        por_popularidad = [int(i) for i in np.lexsort((np.arange(ix.n), -ix.oyentes))]
        if cols:
            tiene = np.asarray((ix.tfidf[:, cols] > 0).sum(axis=1)).ravel() > 0
            en_etiquetas = [i for i in por_popularidad if tiene[i]]
        else:
            en_etiquetas = []
        vistos = set(en_etiquetas)
        orden = en_etiquetas + [i for i in por_popularidad if i not in vistos]
        orden = [i for i in orden if i not in excluir]
        sims = (
            np.asarray(ix.tfidf @ perfil.vector, dtype=float).ravel()
            if ix.tfidf.shape[1]
            else np.zeros(ix.n)
        )
        recs = [
            Recomendacion(
                indice=i,
                artista_id=ix.artistas[i].id,
                nombre=ix.nombre(i),
                puntaje=float(sims[i]),
                puntaje_crudo=float(sims[i]),
                oyentes=ix.artistas[i].oyentes,
                estrategia=self.id,
                aportes={"s_tags": float(sims[i]), "s_grafo": 0.0, "p_nov": 0.0, "s_onto": 0.0},
            )
            for i in orden[:n]
        ]
        return ResultadoEstrategia(recs, orden)
