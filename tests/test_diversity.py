"""MMR: λ = 1 ordena por puntaje; λ bajo aumenta la diversidad."""

import numpy as np
import pytest

from sonarmatch.domain.diversity import mmr, similitud_intra_lista


def _caso() -> tuple[np.ndarray, np.ndarray]:
    # 0,1,2 son casi idénticos y con puntaje alto; 3,4 distintos y algo peores.
    puntajes = np.array([1.0, 0.95, 0.9, 0.7, 0.6])
    sim = np.eye(5)
    for i in range(3):
        for j in range(3):
            sim[i, j] = 1.0 if i == j else 0.95
    return puntajes, sim


def test_lambda_uno_equivale_a_ordenar_por_puntaje() -> None:
    rng = np.random.default_rng(1)
    puntajes = rng.random(30)
    puntajes[5] = puntajes[9]  # empate: gana el primero
    sim = rng.random((30, 30))
    orden = [d.elegido for d in mmr(puntajes, sim, lam=1.0)]
    assert orden == list(np.argsort(-puntajes, kind="stable"))


def test_lambda_bajo_aumenta_la_diversidad() -> None:
    puntajes, sim = _caso()
    puros = [d.elegido for d in mmr(puntajes, sim, lam=1.0, k=3)]
    diversos = [d.elegido for d in mmr(puntajes, sim, lam=0.3, k=3)]
    assert puros == [0, 1, 2]
    assert diversos == [0, 3, 4]
    ils = similitud_intra_lista
    assert ils(sim[np.ix_(diversos, diversos)]) < ils(sim[np.ix_(puros, puros)])


def test_decisiones_registran_valor_y_similitud() -> None:
    puntajes, sim = _caso()
    d = mmr(puntajes, sim, lam=0.5, k=2)
    assert d[0].max_similitud == 0
    assert d[0].valor_mmr == pytest.approx(0.5)
    assert d[1].valor_mmr == pytest.approx(
        0.5 * puntajes[d[1].elegido] - 0.5 * sim[d[1].elegido, 0]
    )


def test_orden_completo_es_permutacion() -> None:
    puntajes, sim = _caso()
    assert sorted(d.elegido for d in mmr(puntajes, sim, lam=0.7)) == list(range(5))
    assert mmr(np.array([]), np.zeros((0, 0)), lam=0.7) == []


def test_ils() -> None:
    assert similitud_intra_lista(np.array([[1.0]])) == 0
    assert similitud_intra_lista(np.array([[1, 0.5], [0.5, 1]])) == pytest.approx(0.5)
