"""Servicios falsos y deterministas para desarrollar y probar el frontend sin base de datos.

Cubren todos los valores de ``Estrategia`` y ``MotivoNo`` y devuelven cadenas de inferencia
no vacías. Ver docs/CONTRATO.md para los nombres que disparan cada motivo de "¿por qué no?".
"""

from dataclasses import dataclass, field
from typing import Literal

from sonarmatch.application.validation import normalizar_nombre, validar_solicitud
from sonarmatch.bootstrap import Servicios
from sonarmatch.ports.inbound import (
    ContrafactualDTO,
    EfectoContrafactual,
    Estrategia,
    MotivoNo,
    ParametrosMotor,
    PorQueNoDTO,
    RecomendacionDTO,
    RespuestaRecomendacion,
    SolicitudRecomendacion,
)

PARAMETROS_FALSOS = ParametrosMotor(a=0.3, b=0.35, c=0.15, d=0.2, lambda_mmr=0.7)

# Artistas de entrada típicos (el usuario los elige).
ENTRADA_FALSA: tuple[str, ...] = (
    "Beach House",
    "Cocteau Twins",
    "Slowdive",
    "My Bloody Valentine",
    "Mazzy Star",
    "Low",
    "Red House Painters",
    "Galaxie 500",
    "Grouper",
    "Julee Cruise",
    "Hope Sandoval",
    "Lush",
    "Ride",
    "Chapterhouse",
    "Pale Saints",
    "Codeine",
    "Duster",
    "Hum",
    "Swirlies",
    "Drop Nineteens",
    "Alvvays",
)

# Las 10 recomendaciones fijas: (nombre, oyentes, estrategia).
RECOMENDACIONES_FALSAS: tuple[tuple[str, int, Estrategia], ...] = (
    ("Wild Nothing", 412_000, "grafo"),
    ("Cigarettes After Sex", 2_100_000, "grafo"),
    ("Sweet Trip", 98_500, "grafo"),
    ("Medicine", 61_200, "grafo"),
    ("Souvlaki Sessions", 3_400, "grafo"),
    ("Starflyer 59", 45_000, "grafo"),
    ("Jessica Pratt", 310_000, "contenido"),
    ("Hatchie", 150_000, "contenido"),
    ("Radiohead", 7_800_000, "popularidad"),
    ("The Cure", 5_600_000, "popularidad"),
)

# Nombres del catálogo que disparan cada motivo de "¿por qué no?".
POR_QUE_NO_FALSO: dict[str, MotivoNo] = {
    "Sonic Youth": "no_conectado",
    "Metallica": "descartado_por_regla",
    "Deftones": "puntaje_insuficiente",
    "Whirr": "desplazado_por_diversidad",
}

CATALOGO_FALSO: tuple[str, ...] = (
    ENTRADA_FALSA + tuple(n for n, _, _ in RECOMENDACIONES_FALSAS) + tuple(POR_QUE_NO_FALSO)
)

_CADENA_R1_R2: tuple[str, ...] = (
    "R1: escuchas shoegaze y slowcore, subgéneros de rock alternativo → afinidad(rock alternativo)",
    "R2: afinidad(rock alternativo) → explorar(dream pop)",
)
_CADENA_R3: tuple[str, ...] = (
    "R3: la mediana de oyentes de tu perfil está bajo el percentil 25 → +0,1 a novedad",
)


def _aportes(puntaje: float, p: ParametrosMotor) -> dict[str, float]:
    total = p.a + p.b + p.c + p.d
    return {
        "s_tags": puntaje * p.a / total,
        "s_grafo": puntaje * p.b / total,
        "p_nov": puntaje * p.c / total,
        "s_onto": puntaje * p.d / total,
    }


def _origen(solicitud: SolicitudRecomendacion, i: int) -> tuple[str, ...]:
    nombres = [e.nombre for e in solicitud.artistas]
    return (nombres[i % len(nombres)], nombres[(i + 1) % len(nombres)])


def _recomendacion(
    solicitud: SolicitudRecomendacion, i: int, nombre: str, oyentes: int, estrategia: Estrategia
) -> RecomendacionDTO:
    p = solicitud.parametros or PARAMETROS_FALSOS
    puntaje = round(0.92 - 0.06 * i, 4)
    origen = _origen(solicitud, i)
    cadena = _CADENA_R1_R2 + (_CADENA_R3 if i % 2 == 0 else ())
    nombre_estrategia = {
        "grafo": "principal",
        "contenido": "contenido",
        "popularidad": "popularidad",
    }
    return RecomendacionDTO(
        artista_id=1000 + i,
        nombre=nombre,
        puntaje=puntaje,
        aportes=_aportes(puntaje, p),
        explicacion=(
            f"Recomendado porque está muy conectado con {origen[0]} y {origen[1]} "
            f"y comparte las etiquetas dream pop y shoegaze "
            f"(estrategia {nombre_estrategia[estrategia]})."
        ),
        artistas_origen=origen,
        etiquetas_clave=("dream pop", "shoegaze", "ethereal"),
        estrategia=estrategia,
        oyentes=oyentes,
        cadena_inferencia=cadena,
    )


@dataclass
class RecomendadorFalso:
    llamadas: list[SolicitudRecomendacion] = field(default_factory=list)

    def recomendar(self, solicitud: SolicitudRecomendacion) -> RespuestaRecomendacion:
        validar_solicitud(solicitud)
        self.llamadas.append(solicitud)
        catalogo = {normalizar_nombre(n) for n in CATALOGO_FALSO}
        no_encontrados = tuple(
            e.nombre for e in solicitud.artistas if normalizar_nombre(e.nombre) not in catalogo
        )
        entrada = {normalizar_nombre(e.nombre) for e in solicitud.artistas}
        candidatos = [r for r in RECOMENDACIONES_FALSAS if normalizar_nombre(r[0]) not in entrada]
        recs = tuple(
            _recomendacion(solicitud, i, nombre, oyentes, estrategia)
            for i, (nombre, oyentes, estrategia) in enumerate(candidatos)
        )
        usadas: dict[str, int] = {}
        for r in recs:
            usadas[r.estrategia] = usadas.get(r.estrategia, 0) + 1
        return RespuestaRecomendacion(
            recomendaciones=recs,
            artistas_no_encontrados=no_encontrados,
            estrategias_usadas=usadas,
            latencia_ms=123.4,
        )


@dataclass
class CatalogoFalso:
    def nombres_artistas(self) -> list[str]:
        return sorted(CATALOGO_FALSO)

    def parametros_por_defecto(self) -> ParametrosMotor:
        return PARAMETROS_FALSOS


@dataclass
class ExplicadorFalso:
    llamadas_contrafactual: list[int] = field(default_factory=list)
    llamadas_por_que_no: list[str] = field(default_factory=list)

    def contrafactual(self, solicitud: SolicitudRecomendacion, artista_id: int) -> ContrafactualDTO:
        validar_solicitud(solicitud)
        self.llamadas_contrafactual.append(artista_id)
        posicion = artista_id - 1000 + 1
        nombre = next(
            (n for i, (n, _, _) in enumerate(RECOMENDACIONES_FALSAS) if i == posicion - 1),
            f"Artista {artista_id}",
        )
        efectos: list[EfectoContrafactual] = []
        for j, entrada in enumerate(solicitud.artistas):
            if j == 0:
                nueva: int | None = None
                puntaje: float | None = None
            else:
                nueva = min(10, posicion + (len(solicitud.artistas) - j) % 4)
                puntaje = round(0.9 - 0.05 * nueva, 4)
            efectos.append(EfectoContrafactual(entrada.nombre, posicion, nueva, puntaje))
        efectos.sort(
            key=lambda e: -(99 if e.posicion_sin_artista is None else e.posicion_sin_artista)
        )
        primero = efectos[0]
        return ContrafactualDTO(
            artista_id=artista_id,
            nombre=nombre,
            efectos=tuple(efectos),
            resumen=(
                f"Sin {primero.artista_usuario}, {nombre} saldría de la lista "
                f"(hoy está en el puesto {posicion})."
            ),
        )

    def por_que_no(self, solicitud: SolicitudRecomendacion, nombre_artista: str) -> PorQueNoDTO:
        validar_solicitud(solicitud)
        self.llamadas_por_que_no.append(nombre_artista)
        clave = normalizar_nombre(nombre_artista)
        entrada = {normalizar_nombre(e.nombre) for e in solicitud.artistas}
        fijos = {normalizar_nombre(k): v for k, v in POR_QUE_NO_FALSO.items()}
        motivo: MotivoNo
        if clave in entrada:
            motivo = "ya_en_entrada"
        elif clave not in {normalizar_nombre(n) for n in CATALOGO_FALSO}:
            motivo = "no_en_catalogo"
        else:
            motivo = fijos.get(clave, "puntaje_insuficiente")
        return _por_que_no(nombre_artista, motivo)


_TEXTOS_MOTIVO: dict[MotivoNo, str] = {
    "ya_en_entrada": "Ya está entre los artistas que escuchas.",
    "no_en_catalogo": "No está en el catálogo de SonarMatch.",
    "no_conectado": "No está conectado con tus artistas en el grafo de similitud.",
    "descartado_por_regla": "Lo descartó la regla R5: su género es incompatible con tu perfil.",
    "puntaje_insuficiente": "Fue candidato, pero su puntaje quedó por debajo del décimo.",
    "desplazado_por_diversidad": "Le alcanzaba el puntaje, pero es muy parecido a Wild Nothing.",
}


def _por_que_no(nombre: str, motivo: MotivoNo) -> PorQueNoDTO:
    candidato = motivo in ("puntaje_insuficiente", "desplazado_por_diversidad")
    return PorQueNoDTO(
        nombre=nombre,
        motivo=motivo,
        posicion_previa_mmr={"puntaje_insuficiente": 14, "desplazado_por_diversidad": 6}.get(motivo)
        if candidato
        else None,
        aportes=_aportes(0.41, PARAMETROS_FALSOS) if candidato else {},
        diferencia_con_decimo=0.07 if motivo == "puntaje_insuficiente" else None,
        cadena_regla=(
            (
                "R5: la mayor similitud Wu-Palmer entre thrash metal y tu perfil es 0,12 < 0,2 "
                "→ descartar(Metallica)",
            )
            if motivo == "descartado_por_regla"
            else ()
        ),
        similar_a="Wild Nothing" if motivo == "desplazado_por_diversidad" else None,
        explicacion=_TEXTOS_MOTIVO[motivo],
    )


@dataclass
class FeedbackFalso:
    registros: list[tuple[str, int, Literal[-1, 1], Estrategia]] = field(default_factory=list)

    def registrar(
        self, sesion_id: str, artista_id: int, valoracion: Literal[-1, 1], estrategia: Estrategia
    ) -> None:
        self.registros.append((sesion_id, artista_id, valoracion, estrategia))


def crear_servicios_falsos() -> Servicios:
    """Servicios deterministas que cumplen los cuatro protocolos del contrato."""
    return Servicios(
        recomendar=RecomendadorFalso(),
        catalogo=CatalogoFalso(),
        explicar=ExplicadorFalso(),
        feedback=FeedbackFalso(),
    )
