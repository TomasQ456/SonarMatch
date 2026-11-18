"""Respaldo 1: similitud TF-IDF (coseno) entre el perfil y todo el catálogo."""

from dataclasses import dataclass
from typing import Literal

import numpy as np

from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import CLAVES_APORTE, Recomendacion
from sonarmatch.domain.razonamiento import PerfilRazonado
from sonarmatch.domain.strategies.base import ResultadoEstrategia


@dataclass
class EstrategiaContenido:
    indice: IndiceCatalogo
    id: Literal["contenido"] = "contenido"

    def recomendar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> list[Recomendacion]:
        return self.ejecutar(perfil, n, excluir).recomendaciones

    def ejecutar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> ResultadoEstrategia:
        if self.indice.tfidf.shape[1] == 0 or not perfil.vector.any():
            return ResultadoEstrategia([])
        sims = np.asarray(self.indice.tfidf @ perfil.vector, dtype=float).ravel()
        orden = [int(i) for i in np.lexsort((np.arange(len(sims)), -sims)) if sims[i] > 0]
        orden = [i for i in orden if i not in excluir]
        recs = [
            Recomendacion(
                indice=i,
                artista_id=self.indice.artistas[i].id,
                nombre=self.indice.nombre(i),
                puntaje=float(sims[i]),
                puntaje_crudo=float(sims[i]),
                oyentes=self.indice.artistas[i].oyentes,
                estrategia=self.id,
                aportes={**dict.fromkeys(CLAVES_APORTE, 0.0), "s_tags": float(sims[i])},
            )
            for i in orden[:n]
        ]
        return ResultadoEstrategia(recs, orden)
