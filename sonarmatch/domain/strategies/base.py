"""Interfaz común de las estrategias de recomendación."""

from dataclasses import dataclass, field
from typing import Protocol

from sonarmatch.domain.models import EstrategiaId, Recomendacion
from sonarmatch.domain.razonamiento import PerfilRazonado


@dataclass
class ResultadoEstrategia:
    recomendaciones: list[Recomendacion]
    extendido: list[int] = field(default_factory=list)  # orden completo de candidatos (índices)


class EstrategiaRecomendacion(Protocol):
    @property
    def id(self) -> EstrategiaId: ...

    def recomendar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> list[Recomendacion]: ...

    def ejecutar(
        self, perfil: PerfilRazonado, n: int, excluir: frozenset[int]
    ) -> ResultadoEstrategia: ...
