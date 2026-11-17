"""Catálogo de juguete con géneros controlados para probar reglas y estrategias a mano."""

from sonarmatch.domain.models import Artista, Catalogo, Genero, MapeoEtiqueta

# rock(1) → alt(2) → indie(3) → {dream, shoe, slow}(4); alt → post(3), noise(3)
# rock → heavy(2) → thrash(3);  electronic(1) → ambient(2)
GENEROS = (
    Genero("rock", "rock", "rock"),
    Genero("alt", "alternative rock", "rock alternativo", padres=("rock",)),
    Genero("indie", "indie rock", "indie rock", padres=("alt",)),
    Genero("dream", "dream pop", "dream pop", padres=("indie",)),
    Genero("shoe", "shoegaze", "shoegaze", padres=("indie",)),
    Genero("slow", "slowcore", "slowcore", padres=("indie",)),
    Genero("post", "post-rock", "post-rock", padres=("alt",)),
    Genero("noise", "noise rock", "noise rock", padres=("alt",)),
    Genero("heavy", "heavy metal", "heavy metal", padres=("rock",)),
    Genero("thrash", "thrash metal", "thrash metal", padres=("heavy",)),
    Genero("electronic", "electronic", "electrónica"),
    Genero("ambient", "ambient", "ambient", padres=("electronic",)),
)
ETIQUETA_GENERO = {g.etiqueta_en: g.id for g in GENEROS}

# nombre, oyentes, etiqueta principal
ARTISTAS = [
    ("Dream A", 1_000, "dream pop"),
    ("Dream B", 2_000, "dream pop"),
    ("Shoe A", 1_500, "shoegaze"),
    ("Shoe B", 3_000, "shoegaze"),
    ("Slow A", 800, "slowcore"),
    ("Slow B", 900, "slowcore"),
    ("Post A", 50_000, "post-rock"),
    ("Post B", 60_000, "post-rock"),
    ("Noise A", 70_000, "noise rock"),
    ("Thrash A", 900_000, "thrash metal"),
    ("Thrash B", 800_000, "thrash metal"),
    ("Ambient A", 500_000, "ambient"),
    ("Ambient B", 400_000, "ambient"),
    ("Big Pop", 5_000_000, "dream pop"),
    ("Alt A", 100_000, "alternative rock"),
    ("Heavy A", 200_000, "heavy metal"),
]


def catalogo_juguete(
    aristas: tuple[tuple[int, int, float], ...] | None = None,
) -> Catalogo:
    artistas = tuple(
        Artista(i + 1, nombre, oyentes, ((etiqueta, 100.0), ("guitar", 30.0)))
        for i, (nombre, oyentes, etiqueta) in enumerate(ARTISTAS)
    )
    if aristas is None:
        # cadena que conecta todo el catálogo
        aristas = tuple((i, i + 1, 0.5) for i in range(1, len(ARTISTAS)))
    mapeos = tuple(MapeoEtiqueta(t, g, "exacto", 1.0) for t, g in sorted(ETIQUETA_GENERO.items()))
    return Catalogo(artistas, aristas, GENEROS, mapeos)
