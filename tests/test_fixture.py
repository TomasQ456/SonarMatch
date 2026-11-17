"""El fixture sintético cumple lo que necesitan las pruebas y la demo."""

from typing import Any

import networkx as nx


def test_fixture_tamano_y_aristas_validas(datos_fixture: dict[str, Any]) -> None:
    ids = {a["id"] for a in datos_fixture["artists"]}
    assert 45 <= len(ids) <= 60
    assert all(e["src"] in ids and e["dst"] in ids for e in datos_fixture["similar"])
    assert all(0 < e["match"] <= 1 for e in datos_fixture["similar"])


def test_fixture_tiene_componente_desconectado(datos_fixture: dict[str, Any]) -> None:
    g = nx.Graph((e["src"], e["dst"]) for e in datos_fixture["similar"])
    assert nx.number_connected_components(g) >= 2


def test_ontologia_fixture_tiene_ciclo_y_varios_niveles(datos_fixture: dict[str, Any]) -> None:
    generos = datos_fixture["genres"]
    assert len(generos) >= 30
    g = nx.DiGraph((p, x["qid"]) for x in generos for p in x["parents"])
    assert not nx.is_directed_acyclic_graph(g)
    assert any(len(x["parents"]) >= 2 for x in generos)
    sin_ciclos = g.copy()
    sin_ciclos.remove_nodes_from(["F35", "F36"])
    assert nx.dag_longest_path_length(sin_ciclos) >= 3
