"""PPR (contra NetworkX y linealidad), P_nov, S_tags, S_onto, normalización y combinación."""

import networkx as nx
import numpy as np
import pytest

from sonarmatch.domain.indice import IndiceCatalogo, construir_transicion, novedad
from sonarmatch.domain.models import TERMINOS, Catalogo
from sonarmatch.domain.scoring import combinar, minmax, ppr_columnas, s_grafo, s_onto, s_tags

ALFA, TOL, ITER = 0.85, 1e-6, 100


def _nx_desde_catalogo(indice: IndiceCatalogo, catalogo: Catalogo) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(range(indice.n))
    for u, v, m in catalogo.similares:
        g.add_edge(indice.por_id[u], indice.por_id[v], weight=m)
    return g


def _ppr(indice: IndiceCatalogo, semillas: list[int]) -> np.ndarray:
    return ppr_columnas(indice.transicion, indice.colgantes, semillas, ALFA, TOL, ITER)


@pytest.mark.parametrize("semilla", [0, 7, 20, 33, 48])
def test_ppr_coincide_con_networkx(
    indice: IndiceCatalogo, catalogo: Catalogo, semilla: int
) -> None:
    g = _nx_desde_catalogo(indice, catalogo)
    esperado = nx.pagerank(
        g, alpha=ALFA, personalization={semilla: 1}, nstart={semilla: 1}, tol=TOL, weight="weight"
    )
    r = _ppr(indice, [semilla])[:, 0]
    assert r == pytest.approx([esperado[i] for i in range(indice.n)], abs=1e-6)
    assert r.sum() == pytest.approx(1)


def test_ppr_vectorizado_es_lineal_y_coincide_con_networkx(
    indice: IndiceCatalogo, catalogo: Catalogo
) -> None:
    semillas = [3, 10, 25, 40]
    w = np.array([0.4, 0.3, 0.2, 0.1])
    cols = _ppr(indice, semillas)
    total, aportes = s_grafo(cols, w)
    assert aportes.sum(axis=1) == pytest.approx(total)
    g = _nx_desde_catalogo(indice, catalogo)
    pers = dict(zip(semillas, w, strict=True))
    esperado = nx.pagerank(g, alpha=ALFA, personalization=pers, tol=1e-10, weight="weight")
    assert total == pytest.approx([esperado[i] for i in range(indice.n)], abs=1e-5)


def test_ppr_es_cero_fuera_del_componente(indice: IndiceCatalogo) -> None:
    jazz = indice.por_nombre["miles davis"]
    r = _ppr(indice, [jazz])[:, 0]
    alcanzados = {indice.nombre(int(i)) for i in np.flatnonzero(r > 0)}
    assert alcanzados == {"Miles Davis", "Weather Report", "Charlie Parker"}


def test_columnas_independientes_del_lote(indice: IndiceCatalogo) -> None:
    """Condición del contrafactual: cada columna es idéntica se calcule sola o en lote."""
    lote = _ppr(indice, [1, 12, 30, 45])
    for k, s in enumerate([1, 12, 30, 45]):
        assert np.array_equal(lote[:, k], _ppr(indice, [s])[:, 0])


def test_ppr_con_nodo_colgante_igual_que_networkx() -> None:
    aristas = [(0, 1, 1.0), (1, 2, 0.5)]
    p, colgantes = construir_transicion(4, aristas)  # el nodo 3 no tiene aristas
    assert colgantes.tolist() == [False, False, False, True]
    g = nx.Graph()
    g.add_nodes_from(range(4))
    g.add_weighted_edges_from(aristas)
    for s in range(4):
        r = ppr_columnas(p, colgantes, [s], ALFA, TOL, ITER)[:, 0]
        esperado = nx.pagerank(g, alpha=ALFA, personalization={s: 1}, nstart={s: 1}, tol=TOL)
        assert r == pytest.approx([esperado[i] for i in range(4)], abs=1e-6)


def test_transicion_normalizada_y_simetrica() -> None:
    p, _ = construir_transicion(3, [(0, 1, 0.2), (1, 0, 0.8), (1, 2, 0.4), (2, 2, 1.0)])
    denso = p.toarray()
    assert denso.sum(axis=1) == pytest.approx([1, 1, 1])
    assert denso[1] == pytest.approx([0.8 / 1.2, 0, 0.4 / 1.2])  # máx. de ambos sentidos


def test_novedad_formula() -> None:
    oyentes = np.array([0.0, 9.0, 99.0])
    esperado = 1 - np.log1p(oyentes) / np.log(100)
    assert novedad(oyentes) == pytest.approx(esperado)
    assert novedad(oyentes)[2] == pytest.approx(0)
    assert novedad(np.zeros(2)) == pytest.approx([1, 1])


def test_s_tags_es_coseno(indice: IndiceCatalogo) -> None:
    v = indice.tfidf[0].toarray().ravel()
    sims = s_tags(indice, v, np.array([0, 1, 30]))
    assert sims[0] == pytest.approx(1)
    a, b = indice.tfidf[30].toarray().ravel(), v
    assert sims[2] == pytest.approx(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_s_onto_formula(indice: IndiceCatalogo) -> None:
    p = np.zeros(len(indice.generos))
    g1, g2 = indice.pos_genero["F05"], indice.pos_genero["F10"]  # shoegaze, thrash
    p[g1], p[g2] = 0.75, 0.25
    cands = np.arange(indice.n)
    valores = s_onto(indice, p, cands)
    for c in (0, 2, 20, 45):
        propios = indice.generos_artista[c].indices
        esperado = 0.75 * indice.wu_palmer[g1, propios].max()
        esperado += 0.25 * indice.wu_palmer[g2, propios].max()
        assert valores[c] == pytest.approx(esperado)
    assert not s_onto(indice, np.zeros(len(indice.generos)), cands).any()


def test_minmax() -> None:
    assert minmax(np.array([2.0, 4.0, 3.0])) == pytest.approx([0, 1, 0.5])
    assert minmax(np.array([5.0, 5.0])) == pytest.approx([0, 0])
    assert minmax(np.array([])).size == 0


def test_combinar_aportes_suman_el_puntaje() -> None:
    rng = np.random.default_rng(0)
    terminos = {t: rng.random(20) for t in TERMINOS}
    pesos = dict(zip(TERMINOS, (0.3, 0.35, 0.15, 0.2), strict=True))
    puntaje, aportes, crudo = combinar(terminos, pesos)
    assert sum(aportes.values()) == pytest.approx(puntaje)
    assert puntaje.max() <= 1 + 1e-12
    assert puntaje.min() >= 0
    assert crudo == pytest.approx(sum(pesos[t] * terminos[t] for t in TERMINOS))
    assert aportes["s_grafo"] == pytest.approx(0.35 * minmax(terminos["s_grafo"]))
