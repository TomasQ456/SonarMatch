"""Servicio de perfiles y amistades (puerto de entrada GestionarPerfiles).

Sin autenticación: el apodo identifica al usuario, de modo que quien conoce un apodo puede
sobrescribir ese perfil (limitación documentada del prototipo). Como no se puede comprobar
quién pregunta, ``obtener_perfil`` solo devuelve los artistas de un perfil que comparte sus
gustos; de uno privado devuelve el apodo y el consentimiento, sin artistas. El consentimiento
(``comparte_gustos``) también decide si los gustos de un perfil se usan y se nombran en las
recomendaciones de sus amigos; ``listar_amigos`` nunca expone artistas.
"""

from dataclasses import dataclass

from sonarmatch.application.validation import normalizar_apodo, validar_artistas
from sonarmatch.domain.models import EntradaPerfil, PerfilGuardado
from sonarmatch.ports.inbound import (
    AmigoDTO,
    EntradaArtista,
    ErrorEntradaInvalida,
    ErrorPerfil,
    PerfilDTO,
)
from sonarmatch.ports.outbound import RepositorioPerfiles


def a_perfil_dto(p: PerfilGuardado) -> PerfilDTO:
    return PerfilDTO(
        apodo=p.apodo,
        artistas=tuple(EntradaArtista(a.nombre, a.peso) for a in p.artistas),
        comparte_gustos=p.comparte_gustos,
    )


@dataclass
class ServicioPerfiles:
    repo: RepositorioPerfiles

    def guardar_perfil(
        self, apodo: str, artistas: tuple[EntradaArtista, ...], comparte_gustos: bool
    ) -> PerfilDTO:
        """Crea el perfil o reemplaza sus artistas y su consentimiento si el apodo ya existe."""
        clave = normalizar_apodo(apodo)
        try:
            validar_artistas(artistas)
        except ErrorEntradaInvalida as exc:
            raise ErrorPerfil(str(exc)) from exc
        entradas = tuple(EntradaPerfil(a.nombre.strip(), float(a.peso)) for a in artistas)
        return a_perfil_dto(self.repo.guardar_perfil(clave, entradas, bool(comparte_gustos)))

    def obtener_perfil(self, apodo: str) -> PerfilDTO:
        """Artistas solo si el perfil comparte sus gustos (sin autenticación no hay dueño)."""
        dto = a_perfil_dto(self._existente(apodo))
        return dto if dto.comparte_gustos else PerfilDTO(dto.apodo, (), False)

    def agregar_amigo(self, apodo: str, apodo_amigo: str) -> None:
        yo, amigo = self._pareja(apodo, apodo_amigo)
        if not self.repo.agregar_amistad(yo.id, amigo.id):
            raise ErrorPerfil(f"«{amigo.apodo}» ya está en tu lista de amigos.")

    def quitar_amigo(self, apodo: str, apodo_amigo: str) -> None:
        yo, amigo = self._pareja(apodo, apodo_amigo)
        if not self.repo.quitar_amistad(yo.id, amigo.id):
            raise ErrorPerfil(f"«{amigo.apodo}» no está en tu lista de amigos.")

    def listar_amigos(self, apodo: str) -> tuple[AmigoDTO, ...]:
        yo = self._existente(apodo)
        amigos = sorted(self.repo.amigos(yo.id), key=lambda p: p.apodo)
        return tuple(AmigoDTO(p.apodo, p.comparte_gustos) for p in amigos)

    def amigos_que_comparten(self, apodo: str) -> list[PerfilGuardado]:
        """Amigos con consentimiento (los únicos que usa el motor). ErrorPerfil si no existe."""
        yo = self._existente(apodo)
        return sorted(
            (p for p in self.repo.amigos(yo.id) if p.comparte_gustos), key=lambda p: p.apodo
        )

    def _existente(self, apodo: str) -> PerfilGuardado:
        clave = normalizar_apodo(apodo)
        perfil = self.repo.obtener_perfil(clave)
        if perfil is None:
            raise ErrorPerfil(f"No existe un perfil con el apodo «{clave}». Guárdalo primero.")
        return perfil

    def _pareja(self, apodo: str, apodo_amigo: str) -> tuple[PerfilGuardado, PerfilGuardado]:
        if normalizar_apodo(apodo) == normalizar_apodo(apodo_amigo):
            raise ErrorPerfil("No puedes agregarte a ti mismo como amigo.")
        return self._existente(apodo), self._existente(apodo_amigo)


class PerfilesNoDisponibles:
    """Implementación por defecto cuando no hay repositorio de perfiles: todo lanza ErrorPerfil."""

    MENSAJE = "La gestión de perfiles no está disponible en esta instalación."

    def guardar_perfil(
        self, apodo: str, artistas: tuple[EntradaArtista, ...], comparte_gustos: bool
    ) -> PerfilDTO:
        raise ErrorPerfil(self.MENSAJE)

    def obtener_perfil(self, apodo: str) -> PerfilDTO:
        raise ErrorPerfil(self.MENSAJE)

    def agregar_amigo(self, apodo: str, apodo_amigo: str) -> None:
        raise ErrorPerfil(self.MENSAJE)

    def quitar_amigo(self, apodo: str, apodo_amigo: str) -> None:
        raise ErrorPerfil(self.MENSAJE)

    def listar_amigos(self, apodo: str) -> tuple[AmigoDTO, ...]:
        raise ErrorPerfil(self.MENSAJE)
