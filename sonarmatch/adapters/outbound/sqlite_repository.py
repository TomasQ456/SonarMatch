"""Persistencia en SQLite (biblioteca estándar). Todo el SQL es parametrizado."""

import json
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from sonarmatch.domain.models import (
    Artista,
    Catalogo,
    EntradaPerfil,
    EstrategiaId,
    Genero,
    MapeoEtiqueta,
    MetodoMapeo,
    PerfilGuardado,
)
from sonarmatch.domain.textos import normalizar_nombre

ESQUEMA = """
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL UNIQUE,
    mbid TEXT,
    listeners INTEGER NOT NULL DEFAULT 0,
    playcount INTEGER NOT NULL DEFAULT 0,
    country TEXT,
    begin_year INTEGER
);
CREATE TABLE IF NOT EXISTS artist_tags (
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    tag TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (artist_id, tag)
);
CREATE TABLE IF NOT EXISTS similar_artists (
    src_id INTEGER NOT NULL REFERENCES artists(id),
    dst_id INTEGER NOT NULL REFERENCES artists(id),
    match REAL NOT NULL CHECK (match >= 0 AND match <= 1),
    PRIMARY KEY (src_id, dst_id)
);
CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY,
    qid TEXT NOT NULL UNIQUE,
    label_en TEXT NOT NULL,
    label_es TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS genre_parents (
    child_id INTEGER NOT NULL REFERENCES genres(id),
    parent_id INTEGER NOT NULL REFERENCES genres(id),
    PRIMARY KEY (child_id, parent_id)
);
CREATE TABLE IF NOT EXISTS tag_genre (
    tag TEXT NOT NULL,
    genre_id INTEGER NOT NULL REFERENCES genres(id),
    method TEXT NOT NULL CHECK (method IN ('manual', 'exacto', 'alias', 'difuso')),
    confidence REAL NOT NULL,
    PRIMARY KEY (tag, genre_id)
);
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    artist_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
    strategy TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tags_artist ON artist_tags(artist_id);
CREATE TABLE IF NOT EXISTS perfiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apodo TEXT NOT NULL UNIQUE COLLATE NOCASE,
    artistas_json TEXT NOT NULL,
    comparte_gustos INTEGER NOT NULL DEFAULT 0 CHECK (comparte_gustos IN (0, 1)),
    creado_en REAL NOT NULL,
    actualizado_en REAL NOT NULL
);
-- Cada amistad se guarda una vez como par ordenado (a < b) y se lee en ambos sentidos:
-- así no hay duplicados (a, b)/(b, a) ni autorrelaciones.
CREATE TABLE IF NOT EXISTS amistades (
    perfil_a INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE,
    perfil_b INTEGER NOT NULL REFERENCES perfiles(id) ON DELETE CASCADE,
    creada_en REAL NOT NULL,
    PRIMARY KEY (perfil_a, perfil_b),
    CHECK (perfil_a < perfil_b)
);
CREATE INDEX IF NOT EXISTS idx_amistades_b ON amistades(perfil_b);
"""


class RepositorioSQLite:
    """Implementa RepositorioCatalogo, RepositorioEvaluaciones, RepositorioPerfiles y el caché."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = str(ruta)

    @contextmanager
    def conexion(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.ruta)
        try:
            con.execute("PRAGMA foreign_keys = ON")
            yield con
            con.commit()
        finally:
            con.close()

    def crear_esquema(self) -> None:
        with self.conexion() as con:
            con.executescript(ESQUEMA)

    # ------------------------------------------------------------------ escritura
    def guardar_artista(
        self,
        nombre: str,
        oyentes: int = 0,
        playcount: int = 0,
        mbid: str | None = None,
    ) -> int:
        """Inserta o actualiza por nombre normalizado y devuelve el id."""
        clave = normalizar_nombre(nombre)
        with self.conexion() as con:
            con.execute(
                "INSERT INTO artists (name, name_norm, mbid, listeners, playcount) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(name_norm) DO UPDATE SET "
                "mbid = COALESCE(excluded.mbid, artists.mbid), "
                "listeners = MAX(excluded.listeners, artists.listeners), "
                "playcount = MAX(excluded.playcount, artists.playcount)",
                (nombre, clave, mbid, oyentes, playcount),
            )
            fila = con.execute("SELECT id FROM artists WHERE name_norm = ?", (clave,)).fetchone()
        return int(fila[0])

    def actualizar_detalles(self, artista_id: int, pais: str | None, anio: int | None) -> None:
        with self.conexion() as con:
            con.execute(
                "UPDATE artists SET country = ?, begin_year = ? WHERE id = ?",
                (pais, anio, artista_id),
            )

    def guardar_etiquetas(self, artista_id: int, etiquetas: Iterable[tuple[str, float]]) -> None:
        with self.conexion() as con:
            con.execute("DELETE FROM artist_tags WHERE artist_id = ?", (artista_id,))
            con.executemany(
                "INSERT INTO artist_tags (artist_id, tag, weight) VALUES (?, ?, ?)",
                [(artista_id, t, w) for t, w in etiquetas],
            )

    def guardar_similares(self, aristas: Iterable[tuple[int, int, float]]) -> None:
        with self.conexion() as con:
            con.executemany(
                "INSERT INTO similar_artists (src_id, dst_id, match) VALUES (?, ?, ?) "
                "ON CONFLICT(src_id, dst_id) DO UPDATE SET match = excluded.match",
                list(aristas),
            )

    def guardar_generos(self, generos: Iterable[Genero]) -> None:
        generos = list(generos)
        with self.conexion() as con:
            con.executemany(
                "INSERT INTO genres (qid, label_en, label_es, aliases_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(qid) DO UPDATE SET label_en = excluded.label_en, "
                "label_es = excluded.label_es, aliases_json = excluded.aliases_json",
                [(g.id, g.etiqueta_en, g.etiqueta_es, json.dumps(list(g.alias))) for g in generos],
            )
            ids = dict(con.execute("SELECT qid, id FROM genres").fetchall())
            filas = [(ids[g.id], ids[p]) for g in generos for p in g.padres if p in ids]
            con.executemany(
                "INSERT OR IGNORE INTO genre_parents (child_id, parent_id) VALUES (?, ?)", filas
            )

    def guardar_mapeos(self, mapeos: Iterable[MapeoEtiqueta]) -> None:
        with self.conexion() as con:
            ids = dict(con.execute("SELECT qid, id FROM genres").fetchall())
            con.execute("DELETE FROM tag_genre")
            con.executemany(
                "INSERT OR REPLACE INTO tag_genre (tag, genre_id, method, confidence) "
                "VALUES (?, ?, ?, ?)",
                [
                    (m.etiqueta, ids[m.genero_id], m.metodo, m.confianza)
                    for m in mapeos
                    if m.genero_id in ids
                ],
            )

    def podar_aristas_fuera_del_catalogo(self) -> int:
        """Elimina aristas cuyos extremos no estén en artists. Devuelve cuántas borró."""
        with self.conexion() as con:
            cur = con.execute(
                "DELETE FROM similar_artists WHERE src_id NOT IN (SELECT id FROM artists) "
                "OR dst_id NOT IN (SELECT id FROM artists)"
            )
            return int(cur.rowcount)

    # ------------------------------------------------------------------ caché de API
    def cache_obtener(self, clave: str) -> object | None:
        with self.conexion() as con:
            fila = con.execute(
                "SELECT payload_json FROM api_cache WHERE key = ?", (clave,)
            ).fetchone()
        return None if fila is None else json.loads(fila[0])

    def cache_guardar(self, clave: str, payload: object) -> None:
        with self.conexion() as con:
            con.execute(
                "INSERT OR REPLACE INTO api_cache (key, payload_json, fetched_at) VALUES (?, ?, ?)",
                (clave, json.dumps(payload), time.time()),
            )

    # ------------------------------------------------------------------ lectura
    def contar_artistas(self) -> int:
        with self.conexion() as con:
            return int(con.execute("SELECT COUNT(*) FROM artists").fetchone()[0])

    def ids_por_nombre(self) -> dict[str, int]:
        with self.conexion() as con:
            return {n: int(i) for n, i in con.execute("SELECT name_norm, id FROM artists")}

    def cargar_catalogo(self) -> Catalogo:
        with self.conexion() as con:
            etiquetas: dict[int, list[tuple[str, float]]] = {}
            for aid, tag, w in con.execute(
                "SELECT artist_id, tag, weight FROM artist_tags "
                "ORDER BY artist_id, weight DESC, tag"
            ):
                etiquetas.setdefault(int(aid), []).append((str(tag), float(w)))
            artistas = tuple(
                Artista(int(i), str(n), int(o), tuple(etiquetas.get(int(i), ())), pais, anio)
                for i, n, o, pais, anio in con.execute(
                    "SELECT id, name, listeners, country, begin_year FROM artists ORDER BY id"
                )
            )
            similares = tuple(
                (int(u), int(v), float(m))
                for u, v, m in con.execute(
                    "SELECT src_id, dst_id, match FROM similar_artists ORDER BY src_id, dst_id"
                )
            )
            padres: dict[int, list[str]] = {}
            for hijo, qid_padre in con.execute(
                "SELECT gp.child_id, g.qid FROM genre_parents gp "
                "JOIN genres g ON g.id = gp.parent_id"
            ):
                padres.setdefault(int(hijo), []).append(str(qid_padre))
            generos = tuple(
                Genero(str(q), str(en), str(es), tuple(json.loads(al)), tuple(padres.get(gid, ())))
                for gid, q, en, es, al in con.execute(
                    "SELECT id, qid, label_en, label_es, aliases_json FROM genres ORDER BY qid"
                )
            )
            mapeos = tuple(
                MapeoEtiqueta(str(t), str(q), _metodo(str(m)), float(c))
                for t, q, m, c in con.execute(
                    "SELECT tg.tag, g.qid, tg.method, tg.confidence FROM tag_genre tg "
                    "JOIN genres g ON g.id = tg.genre_id ORDER BY tg.tag, g.qid"
                )
            )
        return Catalogo(artistas, similares, generos, mapeos)

    # ------------------------------------------------------------------ feedback
    def registrar_feedback(
        self, sesion_id: str, artista_id: int, valoracion: Literal[-1, 1], estrategia: EstrategiaId
    ) -> None:
        with self.conexion() as con:
            con.execute(
                "INSERT INTO feedback (session_id, artist_id, rating, strategy, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (sesion_id, artista_id, valoracion, estrategia, time.time()),
            )

    def feedback(self) -> list[tuple[str, int, int, str]]:
        with self.conexion() as con:
            return [
                (str(s), int(a), int(r), str(e))
                for s, a, r, e in con.execute(
                    "SELECT session_id, artist_id, rating, strategy FROM feedback ORDER BY id"
                )
            ]

    # ------------------------------------------------------------------ perfiles y amistades
    def obtener_perfil(self, apodo: str) -> PerfilGuardado | None:
        with self.conexion() as con:
            fila = con.execute(
                "SELECT id, apodo, artistas_json, comparte_gustos FROM perfiles WHERE apodo = ?",
                (apodo,),
            ).fetchone()
        return None if fila is None else _perfil(fila)

    def guardar_perfil(
        self, apodo: str, artistas: tuple[EntradaPerfil, ...], comparte_gustos: bool
    ) -> PerfilGuardado:
        ahora = time.time()
        datos = json.dumps([[a.nombre, a.peso] for a in artistas], ensure_ascii=False)
        with self.conexion() as con:
            con.execute(
                "INSERT INTO perfiles (apodo, artistas_json, comparte_gustos, creado_en, "
                "actualizado_en) VALUES (?, ?, ?, ?, ?) ON CONFLICT(apodo) DO UPDATE SET "
                "artistas_json = excluded.artistas_json, "
                "comparte_gustos = excluded.comparte_gustos, "
                "actualizado_en = excluded.actualizado_en",
                (apodo, datos, int(comparte_gustos), ahora, ahora),
            )
            fila = con.execute(
                "SELECT id, apodo, artistas_json, comparte_gustos FROM perfiles WHERE apodo = ?",
                (apodo,),
            ).fetchone()
        if fila is None:
            raise RuntimeError(f"No se pudo guardar el perfil {apodo!r}.")
        return _perfil(fila)

    def agregar_amistad(self, perfil_a: int, perfil_b: int) -> bool:
        if perfil_a == perfil_b:
            return False
        with self.conexion() as con:
            cursor = con.execute(
                "INSERT OR IGNORE INTO amistades (perfil_a, perfil_b, creada_en) VALUES (?, ?, ?)",
                (min(perfil_a, perfil_b), max(perfil_a, perfil_b), time.time()),
            )
            return cursor.rowcount == 1

    def quitar_amistad(self, perfil_a: int, perfil_b: int) -> bool:
        with self.conexion() as con:
            cursor = con.execute(
                "DELETE FROM amistades WHERE perfil_a = ? AND perfil_b = ?",
                (min(perfil_a, perfil_b), max(perfil_a, perfil_b)),
            )
            return cursor.rowcount == 1

    def amigos(self, perfil: int) -> list[PerfilGuardado]:
        with self.conexion() as con:
            filas = con.execute(
                "SELECT p.id, p.apodo, p.artistas_json, p.comparte_gustos FROM perfiles p "
                "JOIN amistades a ON (a.perfil_a = ? AND p.id = a.perfil_b) "
                "OR (a.perfil_b = ? AND p.id = a.perfil_a) ORDER BY p.apodo",
                (perfil, perfil),
            ).fetchall()
        return [_perfil(f) for f in filas]


def _perfil(fila: tuple[object, ...]) -> PerfilGuardado:
    ident, apodo, datos, comparte = fila
    artistas = tuple(EntradaPerfil(str(n), float(w)) for n, w in json.loads(str(datos)))
    return PerfilGuardado(int(str(ident)), str(apodo), artistas, bool(comparte))


def _metodo(valor: str) -> MetodoMapeo:
    metodos: dict[str, MetodoMapeo] = {
        "manual": "manual",
        "exacto": "exacto",
        "alias": "alias",
        "difuso": "difuso",
    }
    return metodos[valor]


def guardar_catalogo(repo: RepositorioSQLite, catalogo: Catalogo) -> None:
    """Vuelca un catálogo completo (p. ej. el fixture) a una base vacía conservando los ids."""
    repo.crear_esquema()
    with repo.conexion() as con:
        con.executemany(
            "INSERT INTO artists (id, name, name_norm, listeners, playcount, country, begin_year) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (a.id, a.nombre, normalizar_nombre(a.nombre), a.oyentes, 0, a.pais, a.anio_inicio)
                for a in catalogo.artistas
            ],
        )
        con.executemany(
            "INSERT INTO artist_tags (artist_id, tag, weight) VALUES (?, ?, ?)",
            [(a.id, t, w) for a in catalogo.artistas for t, w in a.etiquetas],
        )
    repo.guardar_similares(catalogo.similares)
    repo.guardar_generos(catalogo.generos)
    repo.guardar_mapeos(catalogo.mapeos)
