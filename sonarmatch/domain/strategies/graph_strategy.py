"""Estrategia principal: candidatos por PPR (+ R2), descartes por R5, puntaje combinado y MMR."""

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.diversity import DecisionMMR, mmr, similitudes
from sonarmatch.domain.indice import IndiceCatalogo, Vector
from sonarmatch.domain.models import TERMINOS, Recomendacion
from sonarmatch.domain.razonamiento import PerfilRazonado
from sonarmatch.domain.rules.catalog import FASE_CANDIDATOS
from sonarmatch.domain.rules.engine import Hecho
from sonarmatch.domain.scoring import combinar, s_grafo, s_onto, s_tags
from sonarmatch.domain.strategies.base import ResultadoEstrategia


@dataclass
class TrazaGrafo:
    candidatos: list[int]  # antes de descartes, orden ascendente de índice
    origen: dict[int, set[str]]  # "ppr" y/o "r2"
    descartes: dict[int, Hecho]  # hecho descartar(c) (su justificación está en la base)
    ranking_previo: list[int]  # tras descartes, por puntaje descendente (antes de MMR)
    puntajes: dict[int, float]
    crudos: dict[int, float]
    aportes: dict[int, dict[str, float]]
    terminos_crudos: dict[int, dict[str, float]]
    orden_mmr: list[int]  # orden completo producido por MMR
    decisiones_mmr: list[DecisionMMR] = field(default_factory=list)

    def posicion_previa(self, i: int) -> int | None:
        return self.ranking_previo.index(i) + 1 if i in self.puntajes else None


def candidatos_ppr(total: Vector, k: int, excluir: frozenset[int]) -> list[int]:
    """Top-K por PPR (solo nodos alcanzados, PPR > 0), sin la entrada del usuario."""
    orden = np.lexsort((np.arange(len(total)), -total))
    salida: list[int] = []
    for i in orden:
        if total[i] <= 0 or len(salida) >= k:
            break
        if int(i) not in excluir:
            salida.append(int(i))
    return salida


@dataclass
class EstrategiaGrafo:
    indice: IndiceCatalogo
    config: ConfigMotor
    id: Literal["grafo"] = "grafo"

    def recomendar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> list[Recomendacion]:
        return self.ejecutar(perfil, n, excluir).recomendaciones

    def ejecutar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> ResultadoEstrategia:
        traza = self.trazar(perfil, excluir)
        recs = [self.recomendacion(i, traza) for i in traza.orden_mmr[:n]]
        return ResultadoEstrategia(recs, list(traza.orden_mmr))

    def trazar(self, perfil: PerfilRazonado, excluir: frozenset[int]) -> TrazaGrafo:
        ix = self.indice
        total, _ = s_grafo(perfil.ppr, np.asarray(perfil.perfil.pesos))
        por_ppr = candidatos_ppr(total, self.config.top_k_ppr, excluir)
        origen: dict[int, set[str]] = {i: {"ppr"} for i in por_ppr}
        for i in perfil.candidatos_r2():
            if i not in excluir:
                origen.setdefault(i, set()).add("r2")
        candidatos = sorted(origen)
        descartes = self._descartes(perfil, candidatos)
        vivos = np.array([i for i in candidatos if i not in descartes], dtype=np.int64)
        terminos = {
            "s_tags": s_tags(ix, perfil.vector, vivos),
            "s_grafo": total[vivos] if vivos.size else np.zeros(0),
            "p_nov": ix.p_nov[vivos],
            "s_onto": s_onto(ix, perfil.p, vivos),
        }
        puntaje, aportes, crudo = combinar(terminos, perfil.pesos.por_termino())
        orden_local = [int(k) for k in np.lexsort((vivos, -puntaje))]
        ranking = [int(vivos[k]) for k in orden_local]
        lam = perfil.pesos.lambda_mmr if perfil.opciones.usar_mmr else 1.0
        decisiones: list[DecisionMMR] = []
        if orden_local:
            sim = similitudes(ix.tfidf[vivos[orden_local]])
            decisiones = mmr(puntaje[orden_local], sim, lam)
        orden_mmr = [ranking[d.elegido] for d in decisiones]
        pos = {int(i): k for k, i in enumerate(vivos)}
        return TrazaGrafo(
            candidatos=candidatos,
            origen=origen,
            descartes=descartes,
            ranking_previo=ranking,
            puntajes={i: float(puntaje[k]) for i, k in pos.items()},
            crudos={i: float(crudo[k]) for i, k in pos.items()},
            aportes={i: {t: float(aportes[t][k]) for t in TERMINOS} for i, k in pos.items()},
            terminos_crudos={
                i: {t: float(terminos[t][k]) for t in TERMINOS} for i, k in pos.items()
            },
            orden_mmr=orden_mmr,
            decisiones_mmr=decisiones,
        )

    def _descartes(self, perfil: PerfilRazonado, candidatos: list[int]) -> dict[int, Hecho]:
        """Fase "candidatos" del motor de reglas (R5); solo en esta estrategia."""
        if not perfil.opciones.usar_reglas:
            return {}
        for i in candidatos:
            perfil.base.agregar(Hecho("candidato", (i,)))
        perfil.contexto.candidatos = candidatos
        perfil.motor.ejecutar_fase(perfil.base, perfil.contexto, FASE_CANDIDATOS)
        return {
            int(h.args[0]): h
            for h in perfil.base.todos("descartar")
            if int(h.args[0]) in candidatos
        }

    def recomendacion(self, i: int, traza: TrazaGrafo) -> Recomendacion:
        a = self.indice.artistas[i]
        return Recomendacion(
            indice=i,
            artista_id=a.id,
            nombre=a.nombre,
            puntaje=traza.puntajes[i],
            puntaje_crudo=traza.crudos[i],
            oyentes=a.oyentes,
            estrategia=self.id,
            aportes=dict(traza.aportes[i]),
        )
