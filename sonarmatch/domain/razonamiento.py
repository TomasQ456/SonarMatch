"""Fase "perfil" del flujo: perfil numérico + reglas sobre el perfil + parámetros efectivos.

El resultado (``PerfilRazonado``) lo comparten todas las estrategias.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace

import numpy as np

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo, Vector
from sonarmatch.domain.models import TERMINOS, PerfilUsuario
from sonarmatch.domain.profile import agregar_afinidades, perfil_generos_base, vector_perfil
from sonarmatch.domain.rules.catalog import FASE_PERFIL, REGLAS, ContextoReglas
from sonarmatch.domain.rules.engine import BaseHechos, Disparo, Hecho, MotorReglas
from sonarmatch.domain.scoring import Matriz

PARAMETROS_PESO = ("a", "b", "c", "d")


@dataclass(frozen=True)
class Pesos:
    a: float
    b: float
    c: float
    d: float
    lambda_mmr: float

    @classmethod
    def desde_config(cls, cfg: ConfigMotor) -> "Pesos":
        return cls(cfg.a, cfg.b, cfg.c, cfg.d, cfg.lambda_mmr)

    def por_termino(self) -> dict[str, float]:
        return dict(zip(TERMINOS, (self.a, self.b, self.c, self.d), strict=True))

    def renormalizado(self) -> "Pesos":
        total = self.a + self.b + self.c + self.d
        if total <= 0:
            raise ValueError("a + b + c + d debe ser positivo")
        return replace(self, a=self.a / total, b=self.b / total, c=self.c / total, d=self.d / total)


def aplicar_ajustes(base: Pesos, ajustes: Iterable[tuple[str, float]]) -> Pesos:
    """Suma los ajustes por parámetro, acota a [0, 1] y renormaliza a + b + c + d = 1."""
    valores = {
        "a": base.a,
        "b": base.b,
        "c": base.c,
        "d": base.d,
        "lambda_mmr": base.lambda_mmr,
    }
    for parametro, delta in ajustes:
        valores[parametro] += delta
    acotados = {k: min(1.0, max(0.0, v)) for k, v in valores.items()}
    if sum(acotados[k] for k in PARAMETROS_PESO) <= 0:
        acotados.update({k: getattr(base, k) for k in PARAMETROS_PESO})
    return Pesos(**acotados).renormalizado()


def restringir_terminos(p: Pesos, terminos: frozenset[str]) -> Pesos:
    """Ablación: anula los pesos de los términos inactivos y renormaliza."""
    por = p.por_termino()
    nuevos = [por[t] if t in terminos else 0.0 for t in TERMINOS]
    if sum(nuevos) <= 0:
        return p
    return Pesos(nuevos[0], nuevos[1], nuevos[2], nuevos[3], p.lambda_mmr).renormalizado()


@dataclass(frozen=True)
class OpcionesMotor:
    usar_reglas: bool = True
    usar_mmr: bool = True
    usar_respaldo: bool = True
    terminos: frozenset[str] = frozenset(TERMINOS)


@dataclass
class PerfilRazonado:
    perfil: PerfilUsuario
    ppr: Matriz  # N × S (columnas alineadas con perfil.indices)
    vector: Vector  # TF-IDF del perfil
    p_base: Vector
    p: Vector  # perfil de géneros con afinidades de R1
    motor: MotorReglas[ContextoReglas]
    base: BaseHechos
    contexto: ContextoReglas
    pesos: Pesos  # efectivos (con ajustes de reglas si corresponde)
    pesos_usuario: bool
    opciones: OpcionesMotor

    @property
    def entrada(self) -> frozenset[int]:
        return frozenset(self.perfil.indices)

    def disparos_globales(self) -> list[Disparo]:
        """Disparos que ajustaron parámetros (R3, R4, R6): influyen en toda la lista."""
        return self.motor.cadena(self.base.todos("ajuste"))

    def candidatos_r2(self) -> dict[int, Hecho]:
        mejores: dict[int, Hecho] = {}
        for h in self.base.todos("candidato_r2"):
            i = int(h.args[0])
            if i not in mejores or h.confianza > mejores[i].confianza:
                mejores[i] = h
        return mejores


def hechos_iniciales(indice: IndiceCatalogo, perfil: PerfilUsuario, p_base: Vector) -> list[Hecho]:
    hechos = [
        Hecho("peso_genero", (indice.generos[j],), float(p_base[j]))
        for j in np.flatnonzero(p_base > 0)
    ]
    if perfil.indices:
        mediana = float(np.median(indice.oyentes[list(perfil.indices)]))
        hechos.append(Hecho("mediana_oyentes_perfil", (mediana,)))
    return hechos


def razonar_perfil(
    indice: IndiceCatalogo,
    cfg: ConfigMotor,
    perfil: PerfilUsuario,
    ppr: Matriz,
    parametros: Pesos | None,
    opciones: OpcionesMotor,
) -> PerfilRazonado:
    vec = vector_perfil(indice, perfil)
    p_base = perfil_generos_base(indice, perfil)
    ctx = ContextoReglas(indice, cfg, p_base, vec, frozenset(perfil.indices))
    base = BaseHechos(hechos_iniciales(indice, perfil, p_base))
    for q in (cfg.percentil_nicho_r3, cfg.percentil_mainstream_r4):
        base.agregar(Hecho("percentil_oyentes", (q, indice.percentil_oyentes(q))))
    motor = MotorReglas(REGLAS if opciones.usar_reglas else (), cfg.max_iteraciones_reglas)
    motor.ejecutar_fase(base, ctx, FASE_PERFIL)
    afinidades = {
        indice.pos_genero[str(h.args[0])]: h.confianza
        for h in base.todos("afinidad")
        if str(h.args[0]) in indice.pos_genero
    }
    p = agregar_afinidades(p_base, afinidades)
    ctx.p_final = p
    base_pesos = parametros.renormalizado() if parametros else Pesos.desde_config(cfg)
    if parametros is None:
        ajustes = [(str(h.args[0]), float(h.args[1])) for h in base.todos("ajuste")]
        base_pesos = aplicar_ajustes(base_pesos, ajustes)
    pesos = restringir_terminos(base_pesos, opciones.terminos)
    return PerfilRazonado(
        perfil=perfil,
        ppr=ppr,
        vector=vec,
        p_base=p_base,
        p=p,
        motor=motor,
        base=base,
        contexto=ctx,
        pesos=pesos,
        pesos_usuario=parametros is not None,
        opciones=opciones,
    )
