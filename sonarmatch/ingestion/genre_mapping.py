"""Mapeo de etiquetas de Last.fm a géneros de la ontología.

Prioridad: 1) archivo manual (data/mapeo_manual.csv), 2) coincidencia exacta con la etiqueta
en inglés o español, 3) coincidencia con un alias, 4) coincidencia difusa con rapidfuzz
(umbral configurable, 90 por defecto). Cada mapeo guarda método y confianza.
Las etiquetas sin mapeo se siguen usando en TF-IDF.
"""

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz, process

from sonarmatch.domain.models import Artista, Genero, MapeoEtiqueta

CONFIANZA = {"manual": 1.0, "exacto": 1.0, "alias": 0.95}
_SEPARADORES = re.compile(r"[\s\-_/]+")


def clave(texto: str) -> str:
    """Normalización para comparar: minúsculas y guiones/espacios unificados."""
    return _SEPARADORES.sub(" ", texto.casefold()).strip()


def leer_mapeo_manual(ruta: Path) -> dict[str, str]:
    """CSV con columnas tag,qid[,comentario]. Devuelve {etiqueta normalizada: qid}."""
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8", newline="") as f:
        return {
            clave(fila["tag"]): fila["qid"].strip() for fila in csv.DictReader(f) if fila["tag"]
        }


def _indices(generos: Sequence[Genero]) -> tuple[dict[str, str], dict[str, str]]:
    exactos: dict[str, str] = {}
    alias: dict[str, str] = {}
    for g in sorted(generos, key=lambda x: x.id):
        for etiqueta in (g.etiqueta_en, g.etiqueta_es):
            if etiqueta:
                exactos.setdefault(clave(etiqueta), g.id)
        for a in g.alias:
            alias.setdefault(clave(a), g.id)
    return exactos, alias


def mapear_etiquetas(
    etiquetas: Iterable[str],
    generos: Sequence[Genero],
    manual: Mapping[str, str] | None = None,
    umbral_difuso: float = 90.0,
) -> list[MapeoEtiqueta]:
    manual = {clave(k): v for k, v in (manual or {}).items()}
    ids = {g.id for g in generos}
    exactos, alias = _indices(generos)
    nombres = sorted(set(exactos) | set(alias))
    destino = {**alias, **exactos}
    salida: list[MapeoEtiqueta] = []
    for etiqueta in sorted(set(etiquetas)):
        k = clave(etiqueta)
        if k in manual and manual[k] in ids:
            salida.append(MapeoEtiqueta(etiqueta, manual[k], "manual", CONFIANZA["manual"]))
        elif k in exactos:
            salida.append(MapeoEtiqueta(etiqueta, exactos[k], "exacto", CONFIANZA["exacto"]))
        elif k in alias:
            salida.append(MapeoEtiqueta(etiqueta, alias[k], "alias", CONFIANZA["alias"]))
        elif nombres:
            mejor = process.extractOne(k, nombres, scorer=fuzz.ratio, score_cutoff=umbral_difuso)
            if mejor is not None:
                nombre, puntaje, _ = mejor
                salida.append(
                    MapeoEtiqueta(etiqueta, destino[nombre], "difuso", round(puntaje / 100, 4))
                )
    return salida


def cobertura(artistas: Iterable[Artista], mapeos: Iterable[MapeoEtiqueta]) -> float:
    """Porcentaje (0..1) del peso total de etiquetas que quedó mapeado."""
    mapeadas = {m.etiqueta for m in mapeos}
    total = 0.0
    cubierto = 0.0
    for a in artistas:
        for t, w in a.etiquetas:
            total += w
            if t in mapeadas:
                cubierto += w
    return cubierto / total if total > 0 else 0.0


def muestra_difusos(
    mapeos: Iterable[MapeoEtiqueta], generos: Sequence[Genero], n: int = 50, semilla: int = 42
) -> list[dict[str, str]]:
    """n mapeos difusos al azar (semilla fija) para revisión manual."""
    etiquetas = {g.id: g.etiqueta_en for g in generos}
    difusos = sorted((m for m in mapeos if m.metodo == "difuso"), key=lambda m: m.etiqueta)
    idx = np.random.default_rng(semilla).choice(len(difusos), min(n, len(difusos)), replace=False)
    elegidos = [difusos[int(i)] for i in idx]
    return [
        {
            "etiqueta": m.etiqueta,
            "genero_id": m.genero_id,
            "genero": etiquetas.get(m.genero_id, ""),
            "confianza": f"{m.confianza:.2f}",
            "correcto": "",
        }
        for m in sorted(elegidos, key=lambda m: m.etiqueta)
    ]
