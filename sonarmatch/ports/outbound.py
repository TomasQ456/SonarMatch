"""Puertos de salida: lo que el núcleo y la ingesta necesitan del exterior."""

from dataclasses import dataclass
from typing import Literal, Protocol

from sonarmatch.domain.models import Catalogo, EntradaPerfil, EstrategiaId, Genero, PerfilGuardado


@dataclass(frozen=True)
class ArtistaFuente:
    nombre: str
    mbid: str | None = None
    oyentes: int | None = None
    playcount: int | None = None


@dataclass(frozen=True)
class SimilarFuente:
    nombre: str
    match: float
    mbid: str | None = None


class RepositorioCatalogo(Protocol):
    def cargar_catalogo(self) -> Catalogo: ...


class RepositorioEvaluaciones(Protocol):
    def registrar_feedback(
        self, sesion_id: str, artista_id: int, valoracion: Literal[-1, 1], estrategia: EstrategiaId
    ) -> None: ...


class FuenteMetadatos(Protocol):
    """Fuente de artistas, similitudes y etiquetas (Last.fm)."""

    def top_artistas(self, pagina: int, limite: int) -> list[ArtistaFuente]: ...
    def top_artistas_etiqueta(
        self, etiqueta: str, pagina: int, limite: int
    ) -> list[ArtistaFuente]: ...
    def similares(self, nombre: str, limite: int) -> list[SimilarFuente]: ...
    def etiquetas(self, nombre: str) -> list[tuple[str, int]]: ...
    def info(self, nombre: str) -> ArtistaFuente | None: ...


class FuenteDetalles(Protocol):
    """País y año de inicio por MBID (MusicBrainz)."""

    def detalles(self, mbid: str) -> tuple[str | None, int | None]: ...


class FuenteOntologia(Protocol):
    """Géneros musicales y su jerarquía (Wikidata)."""

    def generos_musicales(self) -> list[Genero]: ...
    def aristas_subclase(self) -> list[tuple[str, str]]: ...


class RepositorioPerfiles(Protocol):
    """Perfiles por apodo único y amistades bidireccionales (sin duplicados ni autorrelaciones)."""

    def obtener_perfil(self, apodo: str) -> PerfilGuardado | None: ...
    def guardar_perfil(
        self, apodo: str, artistas: tuple[EntradaPerfil, ...], comparte_gustos: bool
    ) -> PerfilGuardado: ...
    def agregar_amistad(self, perfil_a: int, perfil_b: int) -> bool: ...  # False si ya existía
    def quitar_amistad(self, perfil_a: int, perfil_b: int) -> bool: ...  # False si no existía
    def amigos(self, perfil: int) -> list[PerfilGuardado]: ...
