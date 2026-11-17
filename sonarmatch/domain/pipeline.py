"""Flujo completo de una consulta y su traza.

perfil → reglas fase "perfil" → candidatos (top-K PPR + R2) → reglas fase "candidatos" (R5)
→ puntuación con parámetros ajustados → MMR → (respaldos) → explicaciones.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.explanation import Explicador
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import EntradaPerfil, PerfilUsuario, Recomendacion
from sonarmatch.domain.orchestrator import Orquestador
from sonarmatch.domain.profile import construir_perfil
from sonarmatch.domain.razonamiento import OpcionesMotor, PerfilRazonado, Pesos, razonar_perfil
from sonarmatch.domain.scoring import Matriz, ppr_columnas
from sonarmatch.domain.strategies.content_strategy import EstrategiaContenido
from sonarmatch.domain.strategies.graph_strategy import EstrategiaGrafo, TrazaGrafo
from sonarmatch.domain.strategies.popularity_strategy import EstrategiaPopularidad


@dataclass
class ResultadoConsulta:
    perfil: PerfilRazonado
    recomendaciones: list[Recomendacion]
    extendido: list[int]
    traza: TrazaGrafo | None
    activaciones: list[tuple[str, str]] = field(default_factory=list)

    def posicion(self, indice: int) -> int | None:
        """Posición 1-based en la lista final extendida con el resto del orden de la principal."""
        try:
            return self.extendido.index(indice) + 1
        except ValueError:
            return None

    def reglas_disparadas(self) -> set[str]:
        return {d.regla_id for d in self.perfil.motor.disparos if d.conclusiones}


@dataclass
class MotorRecomendacion:
    indice: IndiceCatalogo
    config: ConfigMotor = field(default_factory=ConfigMotor)

    def __post_init__(self) -> None:
        self.grafo = EstrategiaGrafo(self.indice, self.config)
        self.contenido = EstrategiaContenido(self.indice)
        self.popularidad = EstrategiaPopularidad(self.indice, self.config.n_etiquetas_dominantes)
        self.orquestador = Orquestador(self.grafo, (self.contenido, self.popularidad), self.config)
        self.explicador = Explicador(self.indice, self.config)

    def perfil(self, entradas: Sequence[EntradaPerfil]) -> PerfilUsuario:
        return construir_perfil(self.indice, entradas)

    def ppr(self, perfil: PerfilUsuario) -> Matriz:
        if not perfil.indices:
            return np.zeros((self.indice.n, 0))
        return ppr_columnas(
            self.indice.transicion,
            self.indice.colgantes,
            list(perfil.indices),
            self.config.ppr_damping,
            self.config.ppr_tolerancia,
            self.config.ppr_max_iter,
        )

    def razonar(
        self,
        perfil: PerfilUsuario,
        parametros: Pesos | None = None,
        opciones: OpcionesMotor | None = None,
        ppr: Matriz | None = None,
    ) -> PerfilRazonado:
        return razonar_perfil(
            self.indice,
            self.config,
            perfil,
            self.ppr(perfil) if ppr is None else ppr,
            parametros,
            opciones or OpcionesMotor(),
        )

    def recomendar(
        self,
        perfil: PerfilUsuario,
        parametros: Pesos | None = None,
        opciones: OpcionesMotor | None = None,
        ppr: Matriz | None = None,
        explicar: bool = True,
    ) -> ResultadoConsulta:
        """Ejecuta el flujo completo. ``ppr`` permite reutilizar columnas ya calculadas."""
        pr = self.razonar(perfil, parametros, opciones, ppr)
        n = self.config.n_recomendaciones
        res = self.orquestador.ejecutar(pr, n, pr.entrada)
        motivo = res.activaciones[0][1] if res.activaciones else None
        recs = res.recomendaciones
        if explicar:
            recs = [self._con_explicacion(r, pr, res.traza, motivo) for r in recs]
        return ResultadoConsulta(pr, recs, res.extendido, res.traza, res.activaciones)

    def _con_explicacion(
        self, r: Recomendacion, pr: PerfilRazonado, traza: TrazaGrafo | None, motivo: str | None
    ) -> Recomendacion:
        exp = self.explicador.explicar(r, pr, traza, motivo)
        return Recomendacion(
            indice=r.indice,
            artista_id=r.artista_id,
            nombre=r.nombre,
            puntaje=r.puntaje,
            puntaje_crudo=r.puntaje_crudo,
            oyentes=r.oyentes,
            estrategia=r.estrategia,
            explicacion=exp,
            aportes=r.aportes,
        )
