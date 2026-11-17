"""Carga de perfiles de evaluación.

Opción A: HetRec 2011 Last.fm 2K (GroupLens). Formato verificado sobre los archivos reales:
- ``artists.dat``: TSV UTF-8 con cabecera ``id, name, url, pictureURL``;
- ``user_artists.dat``: TSV con cabecera ``userID, artistID, weight`` (fin de línea CRLF);
  ``weight`` es el número de reproducciones del par usuario-artista.
Opción B: CSV con cabecera ``user_id,artist_name,peso``.

Los artistas se emparejan con el catálogo por nombre normalizado; los usuarios con menos de
``minimo`` artistas emparejados se descartan.

Decisión: las reproducciones de HetRec no están en la escala 1..5 de la interfaz; se
convierten a 1..5 con una escala lineal del rango dentro de cada usuario (el menos escuchado
recibe 1 y el más escuchado 5), para que los parámetros calibrados sirvan igual en la app.
El CSV ya trae pesos en esa escala y se acotan a [1, 5].
"""

import csv
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sonarmatch.domain.textos import normalizar_nombre

MINIMO_EMPAREJADOS = 8
PESO_MIN, PESO_MAX = 1.0, 5.0


@dataclass(frozen=True)
class PerfilEvaluacion:
    usuario: str
    artistas: tuple[tuple[int, float], ...]  # (índice en el catálogo, peso 1..5)


def pesos_por_rango(conteos: list[float]) -> list[float]:
    """1 + 4 · rango / (n − 1), redondeado; empates comparten el rango menor; n = 1 → 3."""
    n = len(conteos)
    if n == 1:
        return [3.0]
    ordenados = sorted(conteos)
    return [float(1 + round(4 * bisect_left(ordenados, c) / (n - 1))) for c in conteos]


def emparejar(
    filas: Iterable[tuple[str, str, float]],
    por_nombre: Mapping[str, int],
    minimo: int = MINIMO_EMPAREJADOS,
    escalar: bool = False,
) -> list[PerfilEvaluacion]:
    """Agrupa (usuario, nombre, peso) por usuario y conserva los emparejados con el catálogo."""
    por_usuario: dict[str, dict[int, float]] = defaultdict(dict)
    for usuario, nombre, peso in filas:
        indice = por_nombre.get(normalizar_nombre(nombre))
        if indice is not None:
            previo = por_usuario[usuario].get(indice, 0.0)
            por_usuario[usuario][indice] = max(previo, peso)
    perfiles = []
    for usuario in sorted(por_usuario, key=lambda u: (len(u), u)):
        items = sorted(por_usuario[usuario].items())
        if len(items) < minimo:
            continue
        valores = [p for _, p in items]
        if escalar:
            valores = pesos_por_rango(valores)
        else:
            valores = [min(PESO_MAX, max(PESO_MIN, v)) for v in valores]
        perfiles.append(
            PerfilEvaluacion(
                usuario, tuple((i, v) for (i, _), v in zip(items, valores, strict=True))
            )
        )
    return perfiles


def leer_hetrec(directorio: Path) -> list[tuple[str, str, float]]:
    nombres: dict[str, str] = {}
    with (directorio / "artists.dat").open(encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            nombres[fila["id"]] = fila["name"]
    salida = []
    with (directorio / "user_artists.dat").open(encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            nombre = nombres.get(fila["artistID"])
            if nombre is not None:
                salida.append((fila["userID"], nombre, float(fila["weight"])))
    return salida


def leer_csv(ruta: Path) -> list[tuple[str, str, float]]:
    with ruta.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        faltan = {"user_id", "artist_name", "peso"} - set(lector.fieldnames or ())
        if faltan:
            raise ValueError(f"{ruta}: faltan columnas {sorted(faltan)}")
        return [(fila["user_id"], fila["artist_name"], float(fila["peso"])) for fila in lector]


def cargar_perfiles(
    tipo: str, ruta: Path, por_nombre: Mapping[str, int], minimo: int = MINIMO_EMPAREJADOS
) -> list[PerfilEvaluacion]:
    if tipo == "hetrec":
        return emparejar(leer_hetrec(ruta), por_nombre, minimo, escalar=True)
    if tipo == "csv":
        return emparejar(leer_csv(ruta), por_nombre, minimo, escalar=False)
    raise ValueError(f"dataset desconocido: {tipo}")
