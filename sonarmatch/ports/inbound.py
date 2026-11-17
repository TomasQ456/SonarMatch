"""Contrato entre el backend y el frontend (puertos de entrada).

No modificar sin acuerdo: las solicitudes de cambio van en docs/SOLICITUDES_CONTRATO.md.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Estrategia = Literal["grafo", "contenido", "popularidad"]


@dataclass(frozen=True)
class EntradaArtista:
    nombre: str
    peso: float  # 1..5


@dataclass(frozen=True)
class ParametrosMotor:
    a: float  # peso S_tags
    b: float  # peso S_grafo
    c: float  # peso P_nov
    d: float  # peso S_onto
    lambda_mmr: float


@dataclass(frozen=True)
class SolicitudRecomendacion:
    artistas: tuple[EntradaArtista, ...]  # entre 5 y 20
    parametros: ParametrosMotor | None = None  # None = valores calibrados


@dataclass(frozen=True)
class RecomendacionDTO:
    artista_id: int
    nombre: str
    puntaje: float  # 0..1
    # claves: "s_tags", "s_grafo", "p_nov", "s_onto" (ponderados, suman el puntaje)
    aportes: dict[str, float]
    explicacion: str
    artistas_origen: tuple[str, ...]  # artistas del usuario que más aportaron
    etiquetas_clave: tuple[str, ...]
    estrategia: Estrategia
    oyentes: int
    cadena_inferencia: tuple[str, ...] = ()  # pasos legibles de las reglas que influyeron


@dataclass(frozen=True)
class RespuestaRecomendacion:
    recomendaciones: tuple[RecomendacionDTO, ...]  # exactamente 10 si el catálogo lo permite
    artistas_no_encontrados: tuple[str, ...]
    estrategias_usadas: dict[str, int] = field(default_factory=dict)
    latencia_ms: float = 0.0


@dataclass(frozen=True)
class EfectoContrafactual:
    artista_usuario: str
    posicion_original: int  # 1..10
    posicion_sin_artista: int | None  # None = queda fuera de los candidatos
    puntaje_sin_artista: float | None


@dataclass(frozen=True)
class ContrafactualDTO:
    artista_id: int
    nombre: str
    efectos: tuple[EfectoContrafactual, ...]  # de mayor a menor impacto
    resumen: str


MotivoNo = Literal[
    "ya_en_entrada",
    "no_en_catalogo",
    "no_conectado",
    "descartado_por_regla",
    "puntaje_insuficiente",
    "desplazado_por_diversidad",
]


@dataclass(frozen=True)
class PorQueNoDTO:
    nombre: str
    motivo: MotivoNo
    posicion_previa_mmr: int | None  # si fue candidato
    aportes: dict[str, float]  # vacío si no fue candidato
    diferencia_con_decimo: float | None
    cadena_regla: tuple[str, ...]  # si fue descartado por una regla
    similar_a: str | None  # recomendado que lo desplazó por diversidad
    explicacion: str


# menos de 5 o más de 20 artistas, pesos fuera de rango, duplicados
class ErrorEntradaInvalida(ValueError): ...


class RecomendarArtistas(Protocol):
    def recomendar(self, solicitud: SolicitudRecomendacion) -> RespuestaRecomendacion: ...


class ConsultarCatalogo(Protocol):
    def nombres_artistas(self) -> list[str]: ...
    def parametros_por_defecto(self) -> ParametrosMotor: ...


class ExplicarRecomendacion(Protocol):
    def contrafactual(
        self, solicitud: SolicitudRecomendacion, artista_id: int
    ) -> ContrafactualDTO: ...
    def por_que_no(self, solicitud: SolicitudRecomendacion, nombre_artista: str) -> PorQueNoDTO: ...


class RegistrarFeedback(Protocol):
    def registrar(
        self, sesion_id: str, artista_id: int, valoracion: Literal[-1, 1], estrategia: Estrategia
    ) -> None: ...
