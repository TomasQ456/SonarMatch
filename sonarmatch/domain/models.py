"""Modelos del dominio (Python puro, sin infraestructura)."""

from dataclasses import dataclass, field
from typing import Literal

EstrategiaId = Literal["grafo", "contenido", "popularidad"]
MetodoMapeo = Literal["manual", "exacto", "alias", "difuso"]
TERMINOS: tuple[str, ...] = ("s_tags", "s_grafo", "p_nov", "s_onto")
# Claves de ``aportes``: el término de grafo se reparte en s_grafo (propio) y s_social (amigos).
CLAVES_APORTE: tuple[str, ...] = ("s_tags", "s_grafo", "s_social", "p_nov", "s_onto")


@dataclass(frozen=True)
class Artista:
    id: int
    nombre: str
    oyentes: int
    etiquetas: tuple[tuple[str, float], ...]  # (etiqueta, peso 0..100), ya limpias
    pais: str | None = None
    anio_inicio: int | None = None


@dataclass(frozen=True)
class Genero:
    id: str  # QID de Wikidata (o id sintético en el fixture)
    etiqueta_en: str
    etiqueta_es: str
    alias: tuple[str, ...] = ()
    padres: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapeoEtiqueta:
    etiqueta: str
    genero_id: str
    metodo: MetodoMapeo
    confianza: float


@dataclass(frozen=True)
class Catalogo:
    """Datos crudos del catálogo tal como los entrega el repositorio."""

    artistas: tuple[Artista, ...]
    similares: tuple[tuple[int, int, float], ...]  # (id origen, id destino, match 0..1)
    generos: tuple[Genero, ...] = ()
    mapeos: tuple[MapeoEtiqueta, ...] = ()


@dataclass(frozen=True)
class EntradaPerfil:
    nombre: str
    peso: float


@dataclass(frozen=True)
class PerfilUsuario:
    """Artistas del usuario presentes en el catálogo, con pesos w_i normalizados (Σ w_i = 1)."""

    indices: tuple[int, ...]  # índices internos en el catálogo
    pesos_brutos: tuple[float, ...]
    pesos: tuple[float, ...]  # w_i = log(1 + peso_i) / Σ
    no_encontrados: tuple[str, ...] = ()


@dataclass(frozen=True)
class Explicacion:
    aportes: dict[str, float]
    artistas_origen: tuple[str, ...]
    etiquetas_clave: tuple[str, ...]
    estrategia: EstrategiaId
    cadena_inferencia: tuple[str, ...]
    texto: str
    amigos_origen: tuple[str, ...] = ()  # amigos (con consentimiento) que más aportaron


@dataclass(frozen=True)
class Recomendacion:
    indice: int  # índice interno
    artista_id: int
    nombre: str
    puntaje: float  # 0..1 (combinación normalizada)
    puntaje_crudo: float  # combinación sin normalizar (condición τ del orquestador)
    oyentes: int
    estrategia: EstrategiaId
    explicacion: Explicacion | None = None
    aportes: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PerfilGuardado:
    """Perfil persistido de un usuario de SonarMatch (identificado solo por su apodo)."""

    id: int
    apodo: str
    artistas: tuple[EntradaPerfil, ...]
    comparte_gustos: bool = False  # consentimiento explícito para que lo usen sus amigos


@dataclass(frozen=True)
class PerfilAmigo:
    """Perfil de un amigo que comparte sus gustos (construido igual que el del usuario)."""

    apodo: str
    perfil: PerfilUsuario


@dataclass(frozen=True)
class ContextoSocial:
    """Amigos con consentimiento y β. El dominio nunca recibe amigos sin consentimiento."""

    amigos: tuple[PerfilAmigo, ...]
    beta: float

    @property
    def activo(self) -> bool:
        return self.beta > 0 and any(a.perfil.indices for a in self.amigos)

    def sin(self, apodo: str) -> "ContextoSocial":
        return ContextoSocial(tuple(a for a in self.amigos if a.apodo != apodo), self.beta)
