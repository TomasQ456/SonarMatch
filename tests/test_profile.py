"""Perfil ponderado: pesos con logaritmo, vector TF-IDF y perfil de géneros."""

import math

import numpy as np
import pytest

from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import EntradaPerfil
from sonarmatch.domain.profile import (
    agregar_afinidades,
    construir_perfil,
    perfil_generos_base,
    perfil_sin,
    pesos_normalizados,
    vector_perfil,
)


def test_pesos_suman_uno_y_usan_logaritmo() -> None:
    w = pesos_normalizados([1, 5, 3])
    assert w.sum() == pytest.approx(1.0)
    esperado = np.log1p([1, 5, 3]) / np.log1p([1, 5, 3]).sum()
    assert w == pytest.approx(esperado)
    # El logaritmo comprime: un peso 5 vale menos de 5 veces un peso 1.
    assert w[1] / w[0] == pytest.approx(math.log(6) / math.log(2))
    assert w[1] / w[0] < 5


def test_pesos_iguales_dan_distribucion_uniforme() -> None:
    assert pesos_normalizados([4, 4, 4, 4]) == pytest.approx([0.25] * 4)


def test_pesos_degenerados() -> None:
    assert pesos_normalizados([0, 0]) == pytest.approx([0.5, 0.5])
    assert pesos_normalizados([]).size == 0


def test_construir_perfil_empareja_por_nombre_y_reporta_faltantes(indice: IndiceCatalogo) -> None:
    perfil = construir_perfil(
        indice,
        [
            EntradaPerfil("  slowdive ", 5),
            EntradaPerfil("No Existe", 3),
            EntradaPerfil("LOW", 2),
            EntradaPerfil("Slowdive", 1),  # duplicado tras normalizar: se ignora
        ],
    )
    assert [indice.nombre(i) for i in perfil.indices] == ["Slowdive", "Low"]
    assert perfil.no_encontrados == ("No Existe",)
    assert sum(perfil.pesos) == pytest.approx(1)


def test_perfil_sin_renormaliza(indice: IndiceCatalogo) -> None:
    perfil = construir_perfil(indice, [EntradaPerfil(n, 3) for n in ("Slowdive", "Low", "Lush")])
    sin = perfil_sin(perfil, 1)
    assert [indice.nombre(i) for i in sin.indices] == ["Slowdive", "Lush"]
    assert sin.pesos == pytest.approx((0.5, 0.5))


def test_vector_perfil_es_combinacion_normalizada(indice: IndiceCatalogo) -> None:
    perfil = construir_perfil(indice, [EntradaPerfil("Slowdive", 5), EntradaPerfil("Low", 1)])
    v = vector_perfil(indice, perfil)
    assert np.linalg.norm(v) == pytest.approx(1)
    w = np.asarray(perfil.pesos)
    crudo = (w[:, None] * indice.tfidf[list(perfil.indices)].toarray()).sum(axis=0)
    assert v == pytest.approx(crudo / np.linalg.norm(crudo))
    vacio = construir_perfil(indice, [EntradaPerfil("Nadie", 1)])
    assert not vector_perfil(indice, vacio).any()


def test_perfil_generos_y_afinidades(indice: IndiceCatalogo) -> None:
    perfil = construir_perfil(indice, [EntradaPerfil("Slowdive", 5), EntradaPerfil("Low", 5)])
    p = perfil_generos_base(indice, perfil)
    assert p.sum() == pytest.approx(1)
    assert p[indice.pos_genero["F05"]] > 0  # shoegaze
    j = indice.pos_genero["F02"]
    con = agregar_afinidades(p, {j: 0.5})
    assert con.sum() == pytest.approx(1)
    assert con[j] == pytest.approx(0.5 / 1.5)
