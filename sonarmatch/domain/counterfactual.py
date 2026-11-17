"""Explicaciones contrafactuales y diagnóstico "¿por qué no?".

Contrafactual "sin el artista i": se vuelve a ejecutar el flujo completo (reglas, candidatos,
puntuación, MMR y respaldos) con el perfil sin i y pesos renormalizados, reutilizando las
columnas de PPR ya calculadas (por linealidad, PPR del perfil reducido = Σ_{j≠i} w'_j·PPR_j y
cada columna no depende de las demás). Como es literalmente la misma ejecución, la posición
obtenida es exacta por construcción.

Posición: en la lista final (1..n) o, si quedó fuera, en el orden extendido con el resto del
orden MMR de la estrategia principal; None si ni siquiera es candidato.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from sonarmatch.domain.pipeline import MotorRecomendacion, ResultadoConsulta
from sonarmatch.domain.profile import perfil_sin
from sonarmatch.domain.razonamiento import OpcionesMotor, Pesos
from sonarmatch.domain.strategies.graph_strategy import TrazaGrafo
from sonarmatch.domain.textos import normalizar_nombre

FUERA = 10**6  # posición ficticia para ordenar "fuera de los candidatos"


@dataclass(frozen=True)
class Efecto:
    artista_usuario: str
    posicion_original: int
    posicion_sin_artista: int | None
    puntaje_sin_artista: float | None

    @property
    def impacto(self) -> int:
        nueva = FUERA if self.posicion_sin_artista is None else self.posicion_sin_artista
        return nueva - self.posicion_original


@dataclass
class Contrafactuales:
    """Ejecuciones "sin i" de una consulta (se calculan una vez y sirven a todas las recs)."""

    motor: MotorRecomendacion
    original: ResultadoConsulta
    parametros: Pesos | None
    opciones: OpcionesMotor | None
    _sin: dict[int, ResultadoConsulta] | None = None

    def ejecuciones(self) -> dict[int, ResultadoConsulta]:
        if self._sin is None:
            perfil = self.original.perfil.perfil
            ppr = self.original.perfil.ppr
            self._sin = {
                i: self.motor.recomendar(
                    perfil_sin(perfil, i),
                    self.parametros,
                    self.opciones,
                    ppr=np.delete(ppr, i, axis=1),
                    explicar=False,
                )
                for i in range(len(perfil.indices))
            }
        return self._sin

    def efectos(self, indice: int) -> list[Efecto]:
        """Efecto de quitar cada artista del usuario sobre la recomendación ``indice``."""
        original = self.original.posicion(indice)
        if original is None:
            raise ValueError("el artista no está entre los recomendados")
        perfil = self.original.perfil.perfil
        efectos = [
            Efecto(
                self.motor.indice.nombre(perfil.indices[i]),
                original,
                res.posicion(indice),
                puntaje_en(res, indice),
            )
            for i, res in self.ejecuciones().items()
        ]
        return sorted(efectos, key=lambda e: (-abs(e.impacto), -e.impacto, e.artista_usuario))


def puntaje_en(res: ResultadoConsulta, indice: int) -> float | None:
    for r in res.recomendaciones:
        if r.indice == indice:
            return r.puntaje
    if res.traza is not None:
        return res.traza.puntajes.get(indice)
    return None


def resumen_efectos(nombre: str, efectos: Sequence[Efecto]) -> str:
    if not efectos or all(e.impacto == 0 for e in efectos):
        return f"Quitar cualquiera de tus artistas no cambiaría la posición de {nombre}."
    e = efectos[0]
    if e.posicion_sin_artista is None:
        return (
            f"Sin {e.artista_usuario}, {nombre} dejaría de ser candidato "
            f"(hoy está en el puesto {e.posicion_original})."
        )
    verbo = "bajaría" if e.impacto > 0 else "subiría"
    return (
        f"Sin {e.artista_usuario}, {nombre} {verbo} del puesto {e.posicion_original} "
        f"al {e.posicion_sin_artista}."
    )


# --------------------------------------------------------------------- ¿por qué no?
Motivo = Literal[
    "ya_en_entrada",
    "no_en_catalogo",
    "no_conectado",
    "descartado_por_regla",
    "puntaje_insuficiente",
    "desplazado_por_diversidad",
]


@dataclass(frozen=True)
class Diagnostico:
    nombre: str
    motivo: Motivo
    posicion_previa_mmr: int | None
    aportes: dict[str, float]
    diferencia_con_decimo: float | None
    cadena_regla: tuple[str, ...]
    similar_a: str | None
    explicacion: str


class YaRecomendadoError(ValueError):
    """Se preguntó "¿por qué no?" por un artista que sí fue recomendado."""


def diagnosticar(
    motor: MotorRecomendacion,
    res: ResultadoConsulta,
    nombres_entrada: Sequence[str],
    nombre: str,
) -> Diagnostico:
    """Primer motivo que aplique, en el orden de la especificación."""
    clave = normalizar_nombre(nombre)
    if clave in {normalizar_nombre(n) for n in nombres_entrada}:
        return _diag(nombre, "ya_en_entrada", "Ya está entre los artistas que escuchas.")
    i = motor.indice.por_nombre.get(clave)
    if i is None:
        return _diag(nombre, "no_en_catalogo", "No está en el catálogo de SonarMatch.")
    nombre = motor.indice.nombre(i)
    for k, r in enumerate(res.recomendaciones, 1):
        if r.indice == i:
            raise YaRecomendadoError(f"{nombre} sí fue recomendado (puesto {k}).")
    traza = res.traza
    if traza is None or i not in traza.candidatos:
        return _diag(
            nombre,
            "no_conectado",
            f"{nombre} no está entre los {motor.config.top_k_ppr} artistas más conectados con "
            "los tuyos en el grafo de similitud (PPR) ni lo aportó la exploración de géneros (R2).",
        )
    if i in traza.descartes:
        pr = res.perfil
        cadena = pr.motor.redactar(pr.motor.cadena([traza.descartes[i]]), pr.contexto)
        return _diag(
            nombre,
            "descartado_por_regla",
            f"{nombre} era candidato, pero lo descartó una regla: sus géneros son incompatibles "
            "con los de tu perfil.",
            cadena_regla=cadena,
        )
    return _diag_candidato(motor, res, traza, i, nombre)


def _diag_candidato(
    motor: MotorRecomendacion, res: ResultadoConsulta, traza: TrazaGrafo, i: int, nombre: str
) -> Diagnostico:
    n = motor.config.n_recomendaciones
    previa = traza.posicion_previa(i)
    aportes = dict(traza.aportes[i])
    corte = traza.ranking_previo[min(n, len(traza.ranking_previo)) - 1]
    diferencia = traza.puntajes[corte] - traza.puntajes[i]
    bajo_tau = traza.crudos[i] < motor.config.tau
    if previa is None or previa > n or bajo_tau:
        detalle = (
            f"quedó en el puesto {previa} antes de diversificar, a {diferencia:.3f} del décimo"
            if not bajo_tau
            else f"su puntaje sin normalizar ({traza.crudos[i]:.3f}) es menor que el umbral τ"
        )
        return _diag(
            nombre,
            "puntaje_insuficiente",
            f"{nombre} fue candidato, pero {detalle}.",
            previa,
            aportes,
            diferencia,
        )
    recomendados = [r.indice for r in res.recomendaciones if r.estrategia == "grafo"]
    similar = _mas_similar(motor, i, recomendados)
    return _diag(
        nombre,
        "desplazado_por_diversidad",
        f"{nombre} tenía puntaje para entrar (puesto {previa} antes de diversificar), pero se "
        f"parece mucho a {similar}, que ya estaba en la lista, y se prefirió variedad (MMR).",
        previa,
        aportes,
        diferencia,
        similar_a=similar,
    )


def _mas_similar(motor: MotorRecomendacion, i: int, otros: list[int]) -> str | None:
    if not otros:
        return None
    sims = np.asarray((motor.indice.tfidf[otros] @ motor.indice.tfidf[i].T).toarray()).ravel()
    return motor.indice.nombre(otros[int(np.argmax(sims))])


def _diag(
    nombre: str,
    motivo: Motivo,
    explicacion: str,
    previa: int | None = None,
    aportes: dict[str, float] | None = None,
    diferencia: float | None = None,
    cadena_regla: tuple[str, ...] = (),
    similar_a: str | None = None,
) -> Diagnostico:
    return Diagnostico(
        nombre, motivo, previa, aportes or {}, diferencia, cadena_regla, similar_a, explicacion
    )
