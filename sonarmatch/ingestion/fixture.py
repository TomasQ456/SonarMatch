"""Carga del catálogo sintético de tests/fixtures (demo y pruebas sin API key)."""

import json
from pathlib import Path

from sonarmatch.domain.models import Artista, Catalogo, Genero
from sonarmatch.ingestion.genre_mapping import mapear_etiquetas

RUTA_FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "catalogo_fixture.json"


def catalogo_desde_json(ruta: Path = RUTA_FIXTURE, umbral_difuso: float = 90.0) -> Catalogo:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    artistas = tuple(
        Artista(
            id=int(a["id"]),
            nombre=str(a["name"]),
            oyentes=int(a["listeners"]),
            etiquetas=tuple((str(t["tag"]), float(t["weight"])) for t in a["tags"]),
        )
        for a in datos["artists"]
    )
    generos = tuple(
        Genero(
            id=str(g["qid"]),
            etiqueta_en=str(g["label_en"]),
            etiqueta_es=str(g["label_es"]),
            alias=tuple(g["aliases"]),
            padres=tuple(g["parents"]),
        )
        for g in datos["genres"]
    )
    manual = {str(m["tag"]): str(m["qid"]) for m in datos.get("manual_mapping", [])}
    etiquetas = {t for a in artistas for t, _ in a.etiquetas}
    return Catalogo(
        artistas=artistas,
        similares=tuple(
            (int(e["src"]), int(e["dst"]), float(e["match"])) for e in datos["similar"]
        ),
        generos=generos,
        mapeos=tuple(mapear_etiquetas(etiquetas, generos, manual, umbral_difuso)),
    )
