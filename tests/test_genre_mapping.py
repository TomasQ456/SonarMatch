"""Mapeo de etiquetas: prioridad manual > exacto > alias > difuso, umbral y cobertura."""

from pathlib import Path

import pytest

from sonarmatch.domain.models import Artista, Genero, MapeoEtiqueta
from sonarmatch.ingestion.genre_mapping import (
    clave,
    cobertura,
    leer_mapeo_manual,
    mapear_etiquetas,
    muestra_difusos,
)

GENEROS = (
    Genero("Q1", "shoegaze", "shoegaze", alias=("shoegazing",)),
    Genero("Q2", "dream pop", "dream pop", alias=("dreampop", "shoegaze")),
    Genero("Q3", "post-rock", "post-rock"),
    Genero("Q4", "electronic music", "música electrónica", alias=("electronic",)),
)


def _por_etiqueta(mapeos: list[MapeoEtiqueta]) -> dict[str, tuple[str, str]]:
    return {m.etiqueta: (m.genero_id, m.metodo) for m in mapeos}


def test_prioridad_manual_exacto_alias_difuso() -> None:
    mapeos = _por_etiqueta(
        mapear_etiquetas(
            [
                "shoegaze",
                "dreampop",
                "Post Rock",
                "música electrónica",
                "shoegazer",
                "4ad",
                "dream",
            ],
            GENEROS,
            manual={"4AD": "Q2", "dreampop": "Q1"},
        )
    )
    assert mapeos["dreampop"] == ("Q1", "manual")  # el manual gana al alias
    assert mapeos["4ad"] == ("Q2", "manual")
    assert mapeos["shoegaze"] == ("Q1", "exacto")  # el exacto gana al alias de Q2
    assert mapeos["Post Rock"] == ("Q3", "exacto")  # guiones y mayúsculas normalizados
    assert mapeos["música electrónica"] == ("Q4", "exacto")  # etiqueta en español
    assert mapeos["shoegazer"] == ("Q1", "difuso")
    assert "dream" not in mapeos  # 'dream' vs 'dream pop' queda bajo el umbral


def test_alias_y_confianzas() -> None:
    mapeos = {m.etiqueta: m for m in mapear_etiquetas(["electronic", "shoegazer"], GENEROS)}
    assert mapeos["electronic"].metodo == "alias"
    assert mapeos["electronic"].confianza == 0.95
    assert 0.9 <= mapeos["shoegazer"].confianza < 1


def test_umbral_difuso_configurable() -> None:
    assert not mapear_etiquetas(["shoegazer"], GENEROS, umbral_difuso=99)
    assert mapear_etiquetas(["dream"], GENEROS, umbral_difuso=70)[0].genero_id == "Q2"


def test_manual_con_genero_inexistente_se_ignora() -> None:
    mapeos = mapear_etiquetas(["shoegaze"], GENEROS, manual={"shoegaze": "Q999"})
    assert _por_etiqueta(mapeos)["shoegaze"] == ("Q1", "exacto")
    assert mapear_etiquetas(["x"], ()) == []


def test_cobertura_ponderada_por_peso() -> None:
    artistas = [
        Artista(1, "A", 1, (("shoegaze", 100.0), ("seen live", 50.0))),
        Artista(2, "B", 1, (("dream pop", 30.0), ("female vocalists", 20.0))),
    ]
    mapeos = mapear_etiquetas(["shoegaze", "dream pop"], GENEROS)
    assert cobertura(artistas, mapeos) == pytest.approx(130 / 200)
    assert cobertura([], mapeos) == 0


def test_leer_mapeo_manual(tmp_path: Path) -> None:
    ruta = tmp_path / "manual.csv"
    ruta.write_text("tag,qid,comentario\nDream-Pop,Q2,x\n,Q9,vacía\n", encoding="utf-8")
    assert leer_mapeo_manual(ruta) == {"dream pop": "Q2"}
    assert leer_mapeo_manual(tmp_path / "no.csv") == {}
    assert clave("  Post_Rock ") == "post rock"


def test_muestra_difusos_determinista() -> None:
    mapeos = [MapeoEtiqueta(f"t{i}", "Q1", "difuso", 0.9) for i in range(80)]
    mapeos.append(MapeoEtiqueta("exacta", "Q1", "exacto", 1.0))
    a = muestra_difusos(mapeos, GENEROS, n=50, semilla=1)
    assert len(a) == 50
    assert a == muestra_difusos(mapeos, GENEROS, n=50, semilla=1)
    assert all(f["genero"] == "shoegaze" for f in a)
    assert "exacta" not in {f["etiqueta"] for f in a}
    assert len(muestra_difusos(mapeos[:3], GENEROS)) == 3
