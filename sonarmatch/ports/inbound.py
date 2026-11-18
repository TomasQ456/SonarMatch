"""Contrato entre el backend y el frontend (puertos de entrada).

No modificar sin acuerdo: las solicitudes de cambio van en docs/SOLICITUDES_CONTRATO.md.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

Estrategia = Literal["grafo", "contenido", "popularidad"]
# A quién se refiere un efecto contrafactual: un artista del usuario, un amigo o todos los amigos.
TipoEfecto = Literal["artista", "amigo", "amigos"]


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
    beta: float = 0.25  # peso de los amigos en la personalización de PPR (0 = sin amigos)


@dataclass(frozen=True)
class SolicitudRecomendacion:
    artistas: tuple[EntradaArtista, ...]  # entre 5 y 20
    parametros: ParametrosMotor | None = None  # None = valores calibrados
    apodo: str | None = None  # si viene, se usan sus amigos que comparten gustos


@dataclass(frozen=True)
class RecomendacionDTO:
    artista_id: int
    nombre: str
    puntaje: float  # 0..1
    # claves: "s_tags", "s_grafo", "s_social", "p_nov", "s_onto" (ponderados, suman el puntaje;
    # s_grafo + s_social = término de grafo)
    aportes: dict[str, float]
    explicacion: str
    artistas_origen: tuple[str, ...]  # artistas del usuario que más aportaron
    etiquetas_clave: tuple[str, ...]
    estrategia: Estrategia
    oyentes: int
    cadena_inferencia: tuple[str, ...] = ()  # pasos legibles de las reglas que influyeron
    amigos_origen: tuple[str, ...] = ()  # apodos de amigos (con consentimiento) que más aportaron


@dataclass(frozen=True)
class RespuestaRecomendacion:
    recomendaciones: tuple[RecomendacionDTO, ...]  # exactamente 10 si el catálogo lo permite
    artistas_no_encontrados: tuple[str, ...]
    estrategias_usadas: dict[str, int] = field(default_factory=dict)
    latencia_ms: float = 0.0


@dataclass(frozen=True)
class EfectoContrafactual:
    artista_usuario: str  # nombre del artista, apodo del amigo o "todos tus amigos" (según tipo)
    posicion_original: int  # 1..10
    posicion_sin_artista: int | None  # None = queda fuera de los candidatos
    puntaje_sin_artista: float | None
    tipo: TipoEfecto = "artista"


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
    "no_conectado_ni_por_amigos",
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


@dataclass(frozen=True)
class PerfilDTO:
    apodo: str
    artistas: tuple[EntradaArtista, ...]
    comparte_gustos: bool  # consentimiento explícito; falso por defecto


@dataclass(frozen=True)
class AmigoDTO:
    apodo: str
    comparte_gustos: bool  # sus gustos solo se usan y se nombran si es verdadero


# menos de 5 o más de 20 artistas, pesos fuera de rango, duplicados
class ErrorEntradaInvalida(ValueError): ...


# apodo inválido o inexistente, autoamistad, amistad repetida o inexistente
class ErrorPerfil(ErrorEntradaInvalida): ...


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


class GestionarPerfiles(Protocol):
    def guardar_perfil(
        self, apodo: str, artistas: tuple[EntradaArtista, ...], comparte_gustos: bool
    ) -> PerfilDTO: ...
    def obtener_perfil(self, apodo: str) -> PerfilDTO: ...
    def agregar_amigo(self, apodo: str, apodo_amigo: str) -> None: ...
    def quitar_amigo(self, apodo: str, apodo_amigo: str) -> None: ...
    def listar_amigos(self, apodo: str) -> tuple[AmigoDTO, ...]: ...
