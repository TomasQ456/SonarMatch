"""Cadena de estrategias: Grafo → Contenido → Popularidad.

La siguiente estrategia se activa si:
1. menos de ``min_artistas_en_catalogo`` artistas del usuario están en el catálogo (se salta
   la principal),
2. la estrategia actual produce menos de n resultados, o
3. el puntaje combinado sin normalizar del n-ésimo resultado de la principal es menor que τ.

En los casos 2 y 3 se conservan los resultados ya obtenidos (en el caso 3, los de la principal
con puntaje crudo ≥ τ) y se completa con la siguiente estrategia, sin duplicar artistas.
La condición τ se aplica solo a la principal: el puntaje crudo de cada estrategia tiene otra
escala y τ se calibra para la combinación de la principal.
"""

from collections import Counter
from dataclasses import dataclass, field

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.models import Recomendacion
from sonarmatch.domain.razonamiento import PerfilRazonado
from sonarmatch.domain.strategies.base import EstrategiaRecomendacion
from sonarmatch.domain.strategies.graph_strategy import EstrategiaGrafo, TrazaGrafo


@dataclass
class ResultadoOrquestado:
    recomendaciones: list[Recomendacion]
    extendido: list[int]  # lista final + resto del orden MMR de la principal
    traza: TrazaGrafo | None
    activaciones: list[tuple[str, str]]  # (estrategia activada, motivo)


@dataclass
class Orquestador:
    grafo: EstrategiaGrafo
    respaldos: tuple[EstrategiaRecomendacion, ...]
    config: ConfigMotor
    estadisticas: Counter[str] = field(default_factory=Counter)

    def ejecutar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> ResultadoOrquestado:
        self.estadisticas["consultas"] += 1
        lista: list[Recomendacion] = []
        activaciones: list[tuple[str, str]] = []
        traza: TrazaGrafo | None = None
        resto_principal: list[int] = []
        usar_respaldo = perfil.opciones.usar_respaldo
        motivo: str | None = None
        if usar_respaldo and len(perfil.perfil.indices) < self.config.min_artistas_en_catalogo:
            motivo = "pocos_artistas"
        else:
            traza = self.grafo.trazar(perfil, excluir)
            principal = [self.grafo.recomendacion(i, traza) for i in traza.orden_mmr[:n]]
            resto_principal = traza.orden_mmr
            if len(principal) < n:
                motivo = "menos_de_n"
            elif principal[-1].puntaje_crudo < self.config.tau:
                motivo = "bajo_tau"
                principal = [r for r in principal if r.puntaje_crudo >= self.config.tau]
            lista.extend(principal)
        for estrategia in self.respaldos if usar_respaldo else ():
            if motivo is None:
                break
            activaciones.append((estrategia.id, motivo))
            self.estadisticas[f"activa_{estrategia.id}"] += 1
            self.estadisticas[f"motivo_{motivo}"] += 1
            usados = excluir | {r.indice for r in lista}
            nuevos = estrategia.recomendar(perfil, n - len(lista), usados)
            lista.extend(nuevos)
            motivo = "menos_de_n" if len(lista) < n else None
        en_lista = {r.indice for r in lista}
        extendido = [r.indice for r in lista] + [i for i in resto_principal if i not in en_lista]
        for r in lista:
            self.estadisticas[f"recs_{r.estrategia}"] += 1
        return ResultadoOrquestado(lista, extendido, traza, activaciones)
