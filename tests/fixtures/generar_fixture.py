"""Genera tests/fixtures/catalogo_fixture.json (datos SINTÉTICOS para pruebas y demo sin API key).

Los nombres de artistas son reales para que la demo sea legible, pero oyentes, etiquetas,
pesos y similitudes son inventados a mano/semilla fija: no son datos de Last.fm.
Los identificadores de género (F01...) son sintéticos, no QID de Wikidata.

Uso: python tests/fixtures/generar_fixture.py
"""

import json
import random
from pathlib import Path

SALIDA = Path(__file__).with_name("catalogo_fixture.json")

# id, etiqueta en, etiqueta es, alias, padres
GENEROS: list[tuple[str, str, str, list[str], list[str]]] = [
    ("F01", "rock", "rock", ["rock music"], []),
    ("F02", "alternative rock", "rock alternativo", ["alternative", "alt rock"], ["F01"]),
    ("F03", "indie rock", "rock independiente", ["indie"], ["F02"]),
    ("F04", "dream pop", "dream pop", ["dreampop"], ["F03", "F35"]),
    ("F05", "shoegaze", "shoegaze", ["shoegazing"], ["F03", "F36"]),
    ("F06", "slowcore", "slowcore", ["sadcore"], ["F03"]),
    ("F07", "noise rock", "noise rock", [], ["F02"]),
    ("F08", "post-rock", "post-rock", ["post rock"], ["F02"]),
    ("F09", "heavy metal", "heavy metal", ["metal"], ["F01"]),
    ("F10", "thrash metal", "thrash metal", ["thrash"], ["F09"]),
    ("F11", "death metal", "death metal", [], ["F09"]),
    ("F12", "black metal", "black metal", [], ["F09"]),
    ("F13", "punk rock", "punk rock", ["punk"], ["F01"]),
    ("F14", "post-punk", "post-punk", ["post punk"], ["F13"]),
    ("F15", "gothic rock", "rock gótico", ["goth rock", "goth"], ["F14"]),
    ("F16", "electronic music", "música electrónica", ["electronic", "electronica"], []),
    ("F17", "ambient music", "música ambiental", ["ambient"], ["F16"]),
    ("F18", "dark ambient", "dark ambient", [], ["F17"]),
    ("F19", "house music", "house", ["house"], ["F16"]),
    ("F20", "deep house", "deep house", [], ["F19"]),
    ("F21", "techno", "techno", [], ["F16"]),
    ("F22", "intelligent dance music", "IDM", ["idm"], ["F16"]),
    ("F23", "trip hop", "trip hop", ["trip-hop"], ["F16", "F24"]),
    ("F24", "hip hop", "hip hop", ["hip-hop", "rap"], []),
    ("F25", "trap music", "trap", ["trap"], ["F24"]),
    ("F26", "alternative hip hop", "hip hop alternativo", ["underground hip-hop"], ["F24"]),
    ("F27", "jazz", "jazz", [], []),
    ("F28", "jazz fusion", "jazz fusión", ["fusion"], ["F27", "F01"]),
    ("F29", "bebop", "bebop", ["bop"], ["F27"]),
    ("F30", "folk music", "música folk", ["folk"], []),
    ("F31", "indie folk", "folk independiente", [], ["F30", "F03"]),
    ("F32", "folk rock", "folk rock", [], ["F30", "F01"]),
    ("F33", "pop music", "pop", ["pop"], []),
    ("F34", "indie pop", "pop independiente", [], ["F33", "F03"]),
    # Ciclo deliberado (como los que existen en P279 de Wikidata): F35 -> F04 -> F35
    ("F35", "ethereal wave", "ethereal wave", ["ethereal"], ["F04", "F15"]),
    # Segundo ciclo: F36 -> F05 -> F36
    ("F36", "noise pop", "noise pop", [], ["F05", "F07"]),
]

# nombre, oyentes, [(etiqueta, peso 0-100)]
ARTISTAS: dict[str, list[tuple[str, int, list[tuple[str, int]]]]] = {
    "dream": [
        (
            "Beach House",
            1_900_000,
            [
                ("dream pop", 100),
                ("indie", 60),
                ("shoegaze", 25),
                ("female vocalists", 40),
                ("seen live", 20),
            ],
        ),
        (
            "Cocteau Twins",
            1_200_000,
            [
                ("dream pop", 100),
                ("ethereal", 80),
                ("shoegaze", 45),
                ("4ad", 30),
                ("female vocalists", 50),
            ],
        ),
        ("Slowdive", 1_000_000, [("shoegaze", 100), ("dream pop", 70), ("indie", 20), ("90s", 15)]),
        (
            "My Bloody Valentine",
            1_500_000,
            [("shoegaze", 100), ("noise pop", 40), ("alternative", 30), ("noise rock", 20)],
        ),
        (
            "Mazzy Star",
            1_300_000,
            [("dream pop", 90), ("alternative", 40), ("female vocalists", 60), ("slowcore", 20)],
        ),
        (
            "Lush",
            300_000,
            [("shoegaze", 100), ("dream pop", 60), ("4ad", 30), ("female vocalists", 30)],
        ),
        ("Ride", 450_000, [("shoegaze", 100), ("britpop", 30), ("indie", 20)]),
        ("Wild Nothing", 600_000, [("dream pop", 100), ("indie pop", 50), ("chillwave", 30)]),
        (
            "Cigarettes After Sex",
            2_200_000,
            [("dream pop", 100), ("slowcore", 30), ("ambient pop", 20)],
        ),
        ("Alvvays", 700_000, [("indie pop", 100), ("dream pop", 50), ("jangle pop", 40)]),
        ("Galaxie 500", 250_000, [("slowcore", 70), ("dream pop", 70), ("indie rock", 50)]),
        ("Pale Saints", 60_000, [("shoegaze", 100), ("dream pop", 50), ("4ad", 40)]),
    ],
    "slow": [
        ("Low", 600_000, [("slowcore", 100), ("indie rock", 40), ("sadcore", 30)]),
        ("Red House Painters", 200_000, [("slowcore", 100), ("sadcore", 50), ("indie folk", 20)]),
        ("Codeine", 70_000, [("slowcore", 100), ("indie rock", 30)]),
        ("Duster", 300_000, [("slowcore", 90), ("space rock", 50), ("indie rock", 40)]),
        (
            "Godspeed You! Black Emperor",
            800_000,
            [("post-rock", 100), ("experimental", 40), ("drone", 20)],
        ),
        ("Explosions in the Sky", 1_100_000, [("post-rock", 100), ("instrumental", 60)]),
        ("Mogwai", 900_000, [("post-rock", 100), ("instrumental", 40), ("shoegaze", 10)]),
        ("Sigur Rós", 1_600_000, [("post-rock", 100), ("ambient", 40), ("ethereal", 30)]),
    ],
    "metal": [
        ("Metallica", 4_000_000, [("thrash metal", 100), ("heavy metal", 80), ("metal", 60)]),
        ("Slayer", 1_400_000, [("thrash metal", 100), ("metal", 50)]),
        ("Megadeth", 1_700_000, [("thrash metal", 100), ("heavy metal", 60)]),
        ("Death", 500_000, [("death metal", 100), ("progressive death metal", 40)]),
        ("Cannibal Corpse", 600_000, [("death metal", 100), ("brutal death metal", 50)]),
        ("Mayhem", 400_000, [("black metal", 100), ("true norwegian black metal", 30)]),
        ("Darkthrone", 380_000, [("black metal", 100), ("raw black metal", 30)]),
    ],
    "goth": [
        ("Joy Division", 2_000_000, [("post-punk", 100), ("new wave", 40), ("80s", 30)]),
        ("The Cure", 3_200_000, [("post-punk", 80), ("new wave", 70), ("gothic rock", 50)]),
        (
            "Siouxsie and the Banshees",
            700_000,
            [("post-punk", 90), ("gothic rock", 70), ("female vocalists", 40)],
        ),
        ("Bauhaus", 600_000, [("gothic rock", 100), ("post-punk", 80)]),
        ("Interpol", 1_800_000, [("post-punk", 70), ("indie rock", 80)]),
    ],
    "electro": [
        ("Aphex Twin", 1_500_000, [("idm", 100), ("electronic", 70), ("ambient", 40)]),
        ("Boards of Canada", 1_100_000, [("idm", 90), ("electronic", 60), ("ambient", 50)]),
        ("Brian Eno", 1_200_000, [("ambient", 100), ("electronic", 40), ("experimental", 40)]),
        ("Burial", 700_000, [("dubstep", 80), ("electronic", 60), ("ambient", 30)]),
        ("Massive Attack", 2_300_000, [("trip-hop", 100), ("electronic", 60)]),
        (
            "Portishead",
            1_900_000,
            [("trip-hop", 100), ("female vocalists", 50), ("electronic", 40)],
        ),
        ("Larry Heard", 90_000, [("deep house", 100), ("house", 60), ("chicago house", 40)]),
        ("Richie Hawtin", 200_000, [("techno", 100), ("minimal", 60)]),
    ],
    "hiphop": [
        ("Madvillain", 900_000, [("hip-hop", 90), ("underground hip-hop", 100), ("abstract", 20)]),
        ("MF DOOM", 1_400_000, [("underground hip-hop", 100), ("hip-hop", 90), ("rap", 50)]),
        ("Kendrick Lamar", 4_500_000, [("hip-hop", 100), ("rap", 90), ("west coast", 40)]),
        ("Travis Scott", 3_800_000, [("trap", 100), ("hip-hop", 70), ("rap", 60)]),
        ("Run the Jewels", 900_000, [("hip-hop", 100), ("rap", 70), ("underground hip-hop", 40)]),
    ],
    "folk": [
        ("Bon Iver", 3_000_000, [("indie folk", 100), ("folk", 60), ("indie", 40)]),
        ("Fleet Foxes", 1_700_000, [("indie folk", 100), ("folk", 70), ("folk rock", 30)]),
        ("Nick Drake", 1_300_000, [("folk", 100), ("singer-songwriter", 80), ("folk rock", 20)]),
    ],
    # Componente desconectado del resto del grafo.
    "jazz": [
        ("Miles Davis", 2_000_000, [("jazz", 100), ("fusion", 50), ("trumpet", 30)]),
        ("Weather Report", 300_000, [("jazz fusion", 100), ("jazz", 60)]),
        ("Charlie Parker", 600_000, [("bebop", 100), ("jazz", 80), ("saxophone", 30)]),
    ],
}

# Puentes entre clusters: (a, b, match)
PUENTES: list[tuple[str, str, float]] = [
    ("Cocteau Twins", "Siouxsie and the Banshees", 0.45),
    ("Cocteau Twins", "Brian Eno", 0.20),
    ("Slowdive", "Mogwai", 0.35),
    ("Slowdive", "Sigur Rós", 0.30),
    ("Galaxie 500", "Low", 0.60),
    ("Mazzy Star", "Low", 0.30),
    ("Cigarettes After Sex", "Low", 0.25),
    ("Beach House", "Bon Iver", 0.25),
    ("Beach House", "Portishead", 0.20),
    ("Red House Painters", "Nick Drake", 0.35),
    ("Massive Attack", "Portishead", 0.95),
    ("Boards of Canada", "Sigur Rós", 0.25),
    ("Interpol", "Joy Division", 0.70),
    ("The Cure", "Wild Nothing", 0.30),
    ("Madvillain", "Burial", 0.15),
    ("Godspeed You! Black Emperor", "Brian Eno", 0.20),
    ("Bauhaus", "Mayhem", 0.10),
]

# Mapeos manuales del fixture (etiqueta -> id de género), equivalentes a data/mapeo_manual.csv.
MAPEO_MANUAL: list[tuple[str, str]] = [
    ("sadcore", "F06"),
    ("4ad", "F04"),
    ("chillwave", "F34"),
]


def main() -> None:
    rng = random.Random(20261117)
    artistas = []
    clusters: dict[str, list[int]] = {}
    for cluster, filas in ARTISTAS.items():
        for nombre, oyentes, etiquetas in filas:
            ident = len(artistas) + 1
            artistas.append(
                {
                    "id": ident,
                    "name": nombre,
                    "listeners": oyentes,
                    "playcount": oyentes * 25,
                    "tags": [{"tag": t, "weight": w} for t, w in etiquetas],
                }
            )
            clusters.setdefault(cluster, []).append(ident)
    por_nombre = {a["name"]: a["id"] for a in artistas}
    aristas: dict[tuple[int, int], float] = {}
    for ids in clusters.values():
        for i, u in enumerate(ids):
            for v in ids[i + 1 :]:
                if rng.random() < 0.55 or abs(ids.index(u) - ids.index(v)) == 1:
                    aristas[(u, v)] = round(rng.uniform(0.3, 1.0), 3)
    for a, b, m in PUENTES:
        u, v = sorted((por_nombre[a], por_nombre[b]))
        aristas[(u, v)] = m
    datos = {
        "nota": "Datos sintéticos para pruebas; no provienen de Last.fm ni de Wikidata.",
        "artists": artistas,
        "similar": [{"src": u, "dst": v, "match": m} for (u, v), m in sorted(aristas.items())],
        "genres": [
            {"qid": g, "label_en": en, "label_es": es, "aliases": al, "parents": pa}
            for g, en, es, al, pa in GENEROS
        ],
        "manual_mapping": [{"tag": t, "qid": q} for t, q in MAPEO_MANUAL],
    }
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(artistas)} artistas, {len(aristas)} aristas, {len(GENEROS)} géneros -> {SALIDA}")


if __name__ == "__main__":
    main()
