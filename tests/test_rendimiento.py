"""Benchmark: consulta < 3 s y contrafactual < 1,5 s sobre un grafo sintético de 5.000 nodos."""

import time

import numpy as np
import pytest

from sonarmatch.domain.counterfactual import Contrafactuales
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import (
    Artista,
    Catalogo,
    ContextoSocial,
    EntradaPerfil,
    Genero,
    MapeoEtiqueta,
    PerfilAmigo,
)
from sonarmatch.domain.pipeline import MotorRecomendacion

N, GRADO, N_ETIQUETAS, N_GENEROS = 5000, 25, 400, 120


def catalogo_sintetico(semilla: int = 0) -> Catalogo:
    rng = np.random.default_rng(semilla)
    etiquetas = [f"tag{k}" for k in range(N_ETIQUETAS)]
    artistas = tuple(
        Artista(
            id=i + 1,
            nombre=f"Artista {i}",
            oyentes=int(rng.lognormal(10, 2)),
            etiquetas=tuple(
                (etiquetas[t], float(rng.integers(1, 101)))
                for t in rng.choice(N_ETIQUETAS, size=20, replace=False)
            ),
        )
        for i in range(N)
    )
    aristas = {
        (min(u, v) + 1, max(u, v) + 1)
        for u in range(N)
        for v in rng.choice(N, size=GRADO // 2, replace=False)
        if u != v
    }
    generos = tuple(
        Genero(f"G{g}", f"genero {g}", f"género {g}", padres=(f"G{(g - 1) // 3}",) if g else ())
        for g in range(N_GENEROS)
    )
    mapeos = tuple(
        MapeoEtiqueta(etiquetas[t], f"G{t % N_GENEROS}", "exacto", 1.0) for t in range(N_ETIQUETAS)
    )
    similares = tuple((u, v, float(rng.uniform(0.05, 1))) for u, v in sorted(aristas))
    return Catalogo(artistas=artistas, similares=similares, generos=generos, mapeos=mapeos)


@pytest.mark.slow
def test_consulta_y_contrafactual_dentro_del_presupuesto() -> None:
    motor = MotorRecomendacion(IndiceCatalogo.construir(catalogo_sintetico()))
    rng = np.random.default_rng(1)
    for consulta in range(3):
        entrada = [
            EntradaPerfil(f"Artista {i}", float(1 + k % 5))
            for k, i in enumerate(rng.choice(N, size=20, replace=False))
        ]
        inicio = time.perf_counter()
        res = motor.recomendar(motor.perfil(entrada))
        consulta_s = time.perf_counter() - inicio
        assert len(res.recomendaciones) == 10
        assert consulta_s < 3.0, f"consulta {consulta}: {consulta_s:.2f} s"
        inicio = time.perf_counter()
        Contrafactuales(motor, res, None, None).efectos(res.recomendaciones[0].indice)
        cf_s = time.perf_counter() - inicio
        assert cf_s < 1.5, f"contrafactual {consulta}: {cf_s:.2f} s"


@pytest.mark.slow
def test_consulta_y_contrafactual_con_amigos_dentro_del_presupuesto() -> None:
    """20 artistas propios y 5 amigos de 20 artistas cada uno (hasta 120 semillas)."""
    motor = MotorRecomendacion(IndiceCatalogo.construir(catalogo_sintetico()))
    rng = np.random.default_rng(2)

    def perfil_al_azar() -> list[EntradaPerfil]:
        return [
            EntradaPerfil(f"Artista {i}", float(1 + k % 5))
            for k, i in enumerate(rng.choice(N, size=20, replace=False))
        ]

    for consulta in range(3):
        social = ContextoSocial(
            tuple(PerfilAmigo(f"amigo{k}", motor.perfil(perfil_al_azar())) for k in range(5)),
            0.25,
        )
        inicio = time.perf_counter()
        res = motor.recomendar(motor.perfil(perfil_al_azar()), social=social)
        consulta_s = time.perf_counter() - inicio
        assert len(res.recomendaciones) == 10
        assert consulta_s < 3.0, f"consulta social {consulta}: {consulta_s:.2f} s"
        inicio = time.perf_counter()
        efectos = Contrafactuales(motor, res, None, None, social).efectos(
            res.recomendaciones[0].indice
        )
        cf_s = time.perf_counter() - inicio
        assert len(efectos) == 20 + 1 + 5
        assert cf_s < 1.5, f"contrafactual social {consulta}: {cf_s:.2f} s"
