"""Limpieza de etiquetas de Last.fm: minúsculas, sin etiquetas no musicales, top 20."""

import re
from collections.abc import Iterable

NO_MUSICALES = frozenset(
    {
        "seen live",
        "favorites",
        "favourites",
        "favorite",
        "favourite",
        "favorite artists",
        "favourite artists",
        "my favorite",
        "my favourite",
        "love",
        "loved",
        "love at first listen",
        "awesome",
        "amazing",
        "beautiful",
        "cool",
        "good",
        "great",
        "best",
        "albums i own",
        "spotify",
        "under 2000 listeners",
        "check out",
        "to listen",
        "want to see live",
        "music",
        "all",
        "other",
        "misc",
        "random",
    }
)
PATRONES_NO_MUSICALES = re.compile(
    r"(favou?rite|seen live|i own|i have seen|check out|to check|listened|"
    r"my top|best of|^\d+ of \d+ stars$|^\d+$)"
)
MAX_ETIQUETAS = 20


def normalizar_etiqueta(etiqueta: str) -> str:
    return " ".join(etiqueta.casefold().split())


def es_musical(etiqueta: str, nombres_artistas: frozenset[str]) -> bool:
    return (
        bool(etiqueta)
        and etiqueta not in NO_MUSICALES
        and etiqueta not in nombres_artistas
        and not PATRONES_NO_MUSICALES.search(etiqueta)
    )


def limpiar_etiquetas(
    etiquetas: Iterable[tuple[str, int]],
    nombres_artistas: frozenset[str] = frozenset(),
    maximo: int = MAX_ETIQUETAS,
) -> list[tuple[str, float]]:
    """Normaliza, descarta no musicales y nombres de artistas, fusiona duplicados (máximo
    peso) y conserva las ``maximo`` de mayor peso (desempate alfabético)."""
    mejores: dict[str, float] = {}
    for etiqueta, peso in etiquetas:
        t = normalizar_etiqueta(etiqueta)
        if es_musical(t, nombres_artistas):
            mejores[t] = max(mejores.get(t, 0.0), float(peso))
    orden = sorted(mejores.items(), key=lambda x: (-x[1], x[0]))
    return orden[:maximo]
