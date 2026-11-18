"""Reglas R1–R7 declaradas como datos (umbrales en config.py).

Predicados usados:
- Iniciales (fase perfil): peso_genero(G) [confianza = peso en el perfil base],
  mediana_oyentes_perfil(m), percentil_oyentes(q, v),
  peso_genero_amigo(apodo, G) [solo amigos que comparten gustos y pesos ≥ θ₇].
- Derivados: afinidad(G), explorar(H), candidato_r2(c, H), ajuste(parametro, delta).
- Fase candidatos: candidato(c) [inicial], descartar(c) [derivado].
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo, Vector
from sonarmatch.domain.rules.engine import BaseHechos, Coincidencia, Disparo, Hecho, Regla
from sonarmatch.domain.textos import lista_natural

FASE_PERFIL = "perfil"
FASE_CANDIDATOS = "candidatos"


@dataclass
class ContextoReglas:
    indice: IndiceCatalogo
    config: ConfigMotor
    p_base: Vector  # perfil de géneros antes de R1
    vector_perfil: Vector  # TF-IDF del perfil (para elegir artistas en R2)
    entrada: frozenset[int]  # artistas del usuario (no se recomiendan)
    p_final: Vector | None = None  # perfil de géneros tras R1 (para R5)
    candidatos: list[int] = field(default_factory=list)


def _n(ctx: ContextoReglas, genero: object) -> str:
    return ctx.indice.ontologia.nombre(str(genero))


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def _num(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------- R1 afinidad_genero_padre
def _pesos_genero(base: BaseHechos) -> dict[str, Hecho]:
    """Peso efectivo de cada género: el mayor entre peso_genero y afinidad."""
    mejor: dict[str, Hecho] = {}
    for h in base.todos("peso_genero") + base.todos("afinidad"):
        g = str(h.args[0])
        if g not in mejor or h.confianza > mejor[g].confianza:
            mejor[g] = h
    return mejor


def _cond_r1(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    onto = ctx.indice.ontologia
    pesos = {g: h for g, h in _pesos_genero(base).items() if h.confianza >= ctx.config.theta1_r1}
    padres = sorted({p for g in pesos for p in onto.padres.get(g, ())})
    for padre in padres:
        if onto.profundidad.get(padre, 0) < ctx.config.min_profundidad_r1:
            continue
        hijos = [pesos[h] for h in onto.hijos[padre] if h in pesos]
        if len(hijos) >= ctx.config.min_subgeneros_r1:
            yield Coincidencia(tuple(hijos), (padre,))


def _acc_r1(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    conf = min(1.0, sum(p.confianza for p in c.premisas))
    return [Hecho("afinidad", (c.ligaduras[0],), conf)]


def _red_r1(d: Disparo, ctx: ContextoReglas) -> str:
    hijos = [_n(ctx, p.args[0]) for p in d.coincidencia.premisas]
    padre = _n(ctx, d.coincidencia.ligaduras[0])
    conf = min(1.0, sum(p.confianza for p in d.coincidencia.premisas))
    return (
        f"R1: tu perfil incluye {lista_natural(hijos)}, subgéneros de {padre} "
        f"→ afinidad({padre}) con confianza {conf:.2f}"
    )


# ---------------------------------------------------------------- R2 explorar_hermanos
def _en_perfil(base: BaseHechos, genero: str) -> bool:
    return (
        base.obtener("peso_genero", genero) is not None
        or base.obtener("afinidad", genero) is not None
    )


def _cond_r2(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    for h in base.todos("afinidad"):
        padre = str(h.args[0])
        for hijo in ctx.indice.ontologia.hijos.get(padre, ()):
            if not _en_perfil(base, hijo):
                yield Coincidencia((h,), (padre, hijo))


def artistas_de_genero(ctx: ContextoReglas, genero: str) -> list[int]:
    """Los M mejores artistas de ``genero`` por S_tags (excluye la entrada del usuario)."""
    j = ctx.indice.pos_genero.get(genero)
    if j is None:
        return []
    col = ctx.indice.generos_artista[:, j].toarray().ravel()
    miembros = [
        int(i)
        for i in np.flatnonzero(col >= ctx.config.pertenencia_genero_r2)
        if int(i) not in ctx.entrada
    ]
    if not miembros:
        return []
    sims = np.asarray(ctx.indice.tfidf[miembros] @ ctx.vector_perfil).ravel()
    orden = sorted(range(len(miembros)), key=lambda k: (-sims[k], miembros[k]))
    return [miembros[k] for k in orden[: ctx.config.m_r2]]


def _acc_r2(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    hijo = str(c.ligaduras[1])
    conf = c.premisas[0].confianza
    hechos = [Hecho("explorar", (hijo,), conf)]
    hechos += [Hecho("candidato_r2", (i, hijo), conf) for i in artistas_de_genero(ctx, hijo)]
    return hechos


def _red_r2(d: Disparo, ctx: ContextoReglas) -> str:
    padre = _n(ctx, d.coincidencia.ligaduras[0])
    hijo = _n(ctx, d.coincidencia.ligaduras[1])
    n_art = sum(1 for h in d.conclusiones if h.predicado == "candidato_r2")
    return (
        f"R2: afinidad({padre}) y {hijo} no está en tu perfil → explorar({hijo}) "
        f"({n_art} artistas candidatos)"
    )


# ---------------------------------------------------------------- R7 exploracion_social
def _cond_r7(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    por_genero: dict[str, list[Hecho]] = {}
    for h in base.todos("peso_genero_amigo"):
        if h.confianza >= ctx.config.theta7_r7:
            por_genero.setdefault(str(h.args[1]), []).append(h)
    for genero in sorted(por_genero):
        premisas = sorted(por_genero[genero], key=lambda h: str(h.args[0]))
        if len(premisas) >= ctx.config.min_amigos_r7 and not _en_perfil(base, genero):
            yield Coincidencia(tuple(premisas), (genero,))


def _acc_r7(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    genero = str(c.ligaduras[0])
    conf = min(1.0, sum(p.confianza for p in c.premisas) / len(c.premisas))
    hechos = [Hecho("explorar", (genero,), conf)]
    hechos += [Hecho("candidato_r2", (i, genero), conf) for i in artistas_de_genero(ctx, genero)]
    return hechos


def _red_r7(d: Disparo, ctx: ContextoReglas) -> str:
    amigos = [str(p.args[0]) for p in d.coincidencia.premisas]
    genero = _n(ctx, d.coincidencia.ligaduras[0])
    n_art = sum(1 for h in d.conclusiones if h.predicado == "candidato_r2")
    return (
        f"R7: {lista_natural(amigos)} escuchan {genero} → exploré {genero} "
        f"({n_art} artistas candidatos)"
    )


# ---------------------------------------------------------------- R3 / R4 popularidad del perfil
def _cond_percentil(base: BaseHechos, percentil: float, por_debajo: bool) -> Iterator[Coincidencia]:
    mediana = base.todos("mediana_oyentes_perfil")
    umbral = next(
        (h for h in base.todos("percentil_oyentes") if float(h.args[0]) == percentil), None
    )
    if not mediana or umbral is None:
        return
    m = float(mediana[0].args[0])
    v = float(umbral.args[1])
    if (m < v) if por_debajo else (m > v):
        yield Coincidencia((mediana[0], umbral))


def _cond_r3(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    return _cond_percentil(base, ctx.config.percentil_nicho_r3, por_debajo=True)


def _cond_r4(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    return _cond_percentil(base, ctx.config.percentil_mainstream_r4, por_debajo=False)


def _acc_r3(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    return [Hecho("ajuste", ("c", ctx.config.ajuste_c_r3))]


def _acc_r4(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    return [Hecho("ajuste", ("c", ctx.config.ajuste_c_r4))]


def _red_r3(d: Disparo, ctx: ContextoReglas) -> str:
    m, (q, v) = d.coincidencia.premisas[0].args[0], d.coincidencia.premisas[1].args
    return (
        f"R3: la mediana de oyentes de tus artistas ({_num(float(m))}) está bajo el percentil "
        f"{float(q):.0f} del catálogo ({_num(float(v))}) → perfil de nicho: "
        f"+{ctx.config.ajuste_c_r3:.2f} al peso de la novedad"
    )


def _red_r4(d: Disparo, ctx: ContextoReglas) -> str:
    m, (q, v) = d.coincidencia.premisas[0].args[0], d.coincidencia.premisas[1].args
    return (
        f"R4: la mediana de oyentes de tus artistas ({_num(float(m))}) supera el percentil "
        f"{float(q):.0f} del catálogo ({_num(float(v))}) → perfil mainstream: "
        f"{ctx.config.ajuste_c_r4:+.2f} al peso de la novedad"
    )


# ---------------------------------------------------------------- R5 genero_incompatible
def max_sim_con_perfil(ctx: ContextoReglas, candidato: int) -> float | None:
    """Mayor sim_wp entre los géneros del candidato y los del perfil; None si falta información."""
    if ctx.p_final is None:
        return None
    perfil = np.flatnonzero(ctx.p_final > 0)
    q = ctx.indice.generos_artista
    propios = q.indices[q.indptr[candidato] : q.indptr[candidato + 1]]
    if perfil.size == 0 or propios.size == 0:
        return None
    return float(np.max(ctx.indice.wu_palmer[np.ix_(propios, perfil)]))


def _cond_r5(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    for h in base.todos("candidato"):
        sim = max_sim_con_perfil(ctx, int(h.args[0]))
        if sim is not None and sim < ctx.config.theta5_r5:
            yield Coincidencia((h,), (round(sim, 6),))


def _acc_r5(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    return [Hecho("descartar", (c.premisas[0].args[0],))]


def _red_r5(d: Disparo, ctx: ContextoReglas) -> str:
    i = int(d.coincidencia.premisas[0].args[0])
    generos = sorted(ctx.indice.generos_de(i), key=lambda g: -ctx.indice.generos_de(i)[g])[:2]
    sim = float(d.coincidencia.ligaduras[0])
    return (
        f"R5: la mayor similitud Wu-Palmer entre los géneros de {ctx.indice.nombre(i)} "
        f"({lista_natural([_n(ctx, g) for g in generos])}) y los de tu perfil es "
        f"{sim:.2f} < {ctx.config.theta5_r5:.2f} → descartar({ctx.indice.nombre(i)})"
    )


# ---------------------------------------------------------------- R6 perfil_eclectico
def _cond_r6(base: BaseHechos, ctx: ContextoReglas) -> Iterator[Coincidencia]:
    principales = sorted(base.todos("peso_genero"), key=lambda h: (-h.confianza, h.args))[
        : ctx.config.generos_principales_r6
    ]
    if len(principales) < 2:  # noqa: PLR2004 — se necesitan al menos dos géneros para promediar
        return
    pos = ctx.indice.pos_genero
    sims = [
        ctx.indice.wu_palmer[pos[str(g.args[0])], pos[str(h.args[0])]]
        for g, h in combinations(principales, 2)
    ]
    media = float(np.mean(sims))
    if media < ctx.config.theta6_r6:
        yield Coincidencia(tuple(principales), (round(media, 6),))


def _acc_r6(c: Coincidencia, ctx: ContextoReglas) -> Iterable[Hecho]:
    return [Hecho("ajuste", ("lambda_mmr", ctx.config.ajuste_lambda_r6))]


def _red_r6(d: Disparo, ctx: ContextoReglas) -> str:
    generos = [_n(ctx, h.args[0]) for h in d.coincidencia.premisas]
    return (
        f"R6: tus géneros principales ({lista_natural(generos)}) tienen similitud media "
        f"{float(d.coincidencia.ligaduras[0]):.2f} < {ctx.config.theta6_r6:.2f} → perfil "
        f"ecléctico: {ctx.config.ajuste_lambda_r6:+.2f} a λ (más diversidad)"
    )


REGLAS: tuple[Regla[ContextoReglas], ...] = (
    Regla(
        "R1",
        "afinidad_genero_padre",
        "Si 2 o más subgéneros distintos de G pesan ≥ θ₁ en el perfil, se infiere afinidad(G) "
        "con confianza = suma de esos pesos (tope 1). No aplica a profundidad < 2.",
        FASE_PERFIL,
        _cond_r1,
        _acc_r1,
        _red_r1,
    ),
    Regla(
        "R2",
        "explorar_hermanos",
        "Si hay afinidad(G), se infiere explorar(H) para cada subgénero H de G fuera del perfil; "
        "los M mejores artistas de H por S_tags se agregan a los candidatos.",
        FASE_PERFIL,
        _cond_r2,
        _acc_r2,
        _red_r2,
    ),
    Regla(
        "R3",
        "perfil_nicho",
        "Si la mediana de oyentes del perfil está bajo el percentil 25 del catálogo: "
        "ajuste(c, +0,1).",
        FASE_PERFIL,
        _cond_r3,
        _acc_r3,
        _red_r3,
    ),
    Regla(
        "R4",
        "perfil_mainstream",
        "Si la mediana de oyentes del perfil supera el percentil 75 del catálogo: ajuste(c, -0,1).",
        FASE_PERFIL,
        _cond_r4,
        _acc_r4,
        _red_r4,
    ),
    Regla(
        "R5",
        "genero_incompatible",
        "Si la mayor sim_wp entre géneros del candidato y del perfil es < θ₅: descartar(c). "
        "Solo en la estrategia principal.",
        FASE_CANDIDATOS,
        _cond_r5,
        _acc_r5,
        _red_r5,
    ),
    Regla(
        "R6",
        "perfil_eclectico",
        "Si la sim_wp media entre los géneros principales del perfil es < θ₆: "
        "ajuste(lambda_mmr, −0,1).",
        FASE_PERFIL,
        _cond_r6,
        _acc_r6,
        _red_r6,
    ),
    Regla(
        "R7",
        "exploracion_social",
        "Si 2 o más amigos que comparten gustos tienen el género G con peso ≥ θ₇ y G no está en el "
        "perfil del usuario: explorar(G); los M mejores artistas de G por S_tags se agregan a los "
        "candidatos (como en R2).",
        FASE_PERFIL,
        _cond_r7,
        _acc_r7,
        _red_r7,
    ),
)
