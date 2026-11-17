"""Ontología: ruptura de ciclos, profundidad, LCS con varios padres y Wu-Palmer a mano."""

import pytest

from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.ontology import RAIZ, AristaRota, Ontologia

# A (sin padre) → B, C ; B → D ; C → D (D tiene dos padres) ; D → E
# Ciclo X ↔ Y colgando de A: A → X, X → Y, Y → X
PADRES = {
    "A": [],
    "B": ["A"],
    "C": ["A"],
    "D": ["B", "C"],
    "E": ["D"],
    "X": ["A", "Y"],
    "Y": ["X"],
    "Z": [],
}


@pytest.fixture
def onto() -> Ontologia:
    return Ontologia.construir(PADRES, {"A": "Alfa"})


def test_rompe_ciclos_de_forma_determinista_y_registra(onto: Ontologia) -> None:
    # DFS lexicográfico desde las raíces A, Z: A→X→Y y Y→X es arista de retroceso.
    assert onto.aristas_rotas == (AristaRota("Y", "X"),)
    assert onto.padres["X"] == ("A",)
    otra = Ontologia.construir(dict(reversed(list(PADRES.items()))))
    assert otra.aristas_rotas == onto.aristas_rotas


def test_ciclo_sin_entrada_se_rompe_y_cuelga_de_la_raiz() -> None:
    o = Ontologia.construir({"P": ["Q"], "Q": ["P"]})
    assert o.aristas_rotas == (AristaRota("Q", "P"),)
    assert o.padres["P"] == (RAIZ,)
    assert o.profundidad == {RAIZ: 0, "P": 1, "Q": 2}


def test_profundidad_es_camino_mas_corto_desde_la_raiz(onto: Ontologia) -> None:
    assert onto.profundidad[RAIZ] == 0
    assert onto.profundidad["A"] == 1
    assert onto.profundidad["Z"] == 1
    assert onto.profundidad["D"] == 3
    assert onto.profundidad["E"] == 4
    assert onto.profundidad["Y"] == 3


def test_ancestros_y_lcs_con_varios_padres(onto: Ontologia) -> None:
    assert onto.ancestros("E") == {"E", "D", "B", "C", "A", RAIZ}
    assert onto.lcs("B", "C") == ("A",)
    assert onto.lcs("E", "D") == ("D",)
    assert onto.lcs("Z", "A") == (RAIZ,)
    assert onto.descendientes("B") == {"B", "D", "E"}


def test_wu_palmer_calculado_a_mano(onto: Ontologia) -> None:
    assert onto.wu_palmer("B", "B") == 1
    assert onto.wu_palmer("B", "C") == pytest.approx(2 * 1 / (2 + 2))
    assert onto.wu_palmer("E", "C") == pytest.approx(2 * 2 / (4 + 2))  # LCS = C (prof. 2)
    assert onto.wu_palmer("E", "D") == pytest.approx(2 * 3 / (4 + 3))
    assert onto.wu_palmer("Z", "E") == 0  # LCS = raíz virtual


def test_wu_palmer_se_acota_a_uno() -> None:
    # G cuelga de la raíz (prof. 2 por el camino corto) y de M (prof. 4); H es hijo de M.
    # Sin tope: 2·prof(M) / (prof(G) + prof(H)) = 8 / 7 > 1.
    o = Ontologia.construir(
        {"R": [], "M1": ["R"], "M2": ["M1"], "M": ["M2"], "G": ["M", "R"], "H": ["M"]}
    )
    assert (o.profundidad["G"], o.profundidad["H"], o.profundidad["M"]) == (2, 5, 4)
    assert o.wu_palmer("G", "H") == 1
    assert o.matriz_wu_palmer(["G", "H"])[0, 1] == 1


def test_matriz_coincide_con_funcion(onto: Ontologia) -> None:
    generos = onto.generos
    m = onto.matriz_wu_palmer(generos)
    for i, g in enumerate(generos):
        for j, h in enumerate(generos):
            assert m[i, j] == pytest.approx(onto.wu_palmer(g, h))
    assert onto.nombre("A") == "Alfa"
    assert onto.nombre("B") == "B"


def test_ontologia_del_fixture(indice: IndiceCatalogo) -> None:
    onto = indice.ontologia
    rotas = {(r.padre, r.hijo) for r in onto.aristas_rotas}
    assert rotas == {("F35", "F04"), ("F36", "F05")}
    assert onto.profundidad["F04"] == 4  # rock → alt → indie → dream pop
    assert indice.wu_palmer.shape == (len(indice.generos), len(indice.generos))
    i, j = indice.pos_genero["F04"], indice.pos_genero["F05"]
    assert indice.wu_palmer[i, j] == pytest.approx(2 * 3 / 8)  # dream pop ~ shoegaze
