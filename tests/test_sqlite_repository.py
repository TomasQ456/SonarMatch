"""Repositorio SQLite sobre una base temporal."""

from pathlib import Path

import pytest

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite, guardar_catalogo
from sonarmatch.domain.models import Catalogo, Genero, MapeoEtiqueta


@pytest.fixture
def repo(tmp_path: Path) -> RepositorioSQLite:
    r = RepositorioSQLite(tmp_path / "t.db")
    r.crear_esquema()
    return r


def test_ida_y_vuelta_del_catalogo_completo(tmp_path: Path, catalogo: Catalogo) -> None:
    repo = RepositorioSQLite(tmp_path / "f.db")
    guardar_catalogo(repo, catalogo)
    leido = repo.cargar_catalogo()
    assert [(a.id, a.nombre, a.oyentes) for a in leido.artistas] == [
        (a.id, a.nombre, a.oyentes) for a in sorted(catalogo.artistas, key=lambda a: a.id)
    ]
    for a, b in zip(leido.artistas, sorted(catalogo.artistas, key=lambda a: a.id), strict=True):
        assert dict(a.etiquetas) == dict(b.etiquetas)
    assert set(leido.similares) == set(catalogo.similares)
    assert {(g.id, frozenset(g.padres)) for g in leido.generos} == {
        (g.id, frozenset(g.padres)) for g in catalogo.generos
    }
    assert set(leido.mapeos) == set(catalogo.mapeos)


def test_guardar_artista_hace_upsert_por_nombre_normalizado(repo: RepositorioSQLite) -> None:
    a = repo.guardar_artista("Beach House", oyentes=10, mbid=None)
    b = repo.guardar_artista("  beach   HOUSE", oyentes=5, mbid="mb-1", playcount=99)
    assert a == b
    assert repo.contar_artistas() == 1
    (artista,) = repo.cargar_catalogo().artistas
    assert artista.nombre == "Beach House"
    assert artista.oyentes == 10  # conserva el mayor
    repo.actualizar_detalles(a, "US", 2004)
    (artista,) = repo.cargar_catalogo().artistas
    assert (artista.pais, artista.anio_inicio) == ("US", 2004)
    assert repo.ids_por_nombre() == {"beach house": a}


def test_etiquetas_se_reemplazan_y_ordenan_por_peso(repo: RepositorioSQLite) -> None:
    i = repo.guardar_artista("X")
    repo.guardar_etiquetas(i, [("a", 10), ("b", 90)])
    repo.guardar_etiquetas(i, [("c", 5), ("d", 50)])
    assert repo.cargar_catalogo().artistas[0].etiquetas == (("d", 50.0), ("c", 5.0))


def test_similares_y_poda(repo: RepositorioSQLite) -> None:
    a, b = repo.guardar_artista("A"), repo.guardar_artista("B")
    repo.guardar_similares([(a, b, 0.5)])
    repo.guardar_similares([(a, b, 0.7)])  # actualiza
    assert repo.cargar_catalogo().similares == ((a, b, 0.7),)
    with repo.conexion() as con:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("INSERT INTO similar_artists VALUES (?, ?, ?)", (a, 999, 0.3))
    assert repo.podar_aristas_fuera_del_catalogo() == 1
    assert repo.cargar_catalogo().similares == ((a, b, 0.7),)


def test_match_fuera_de_rango_es_rechazado(repo: RepositorioSQLite) -> None:
    a, b = repo.guardar_artista("A"), repo.guardar_artista("B")
    with pytest.raises(Exception, match="CHECK"):
        repo.guardar_similares([(a, b, 1.5)])


def test_generos_y_mapeos(repo: RepositorioSQLite) -> None:
    repo.guardar_generos(
        [
            Genero("Q1", "rock", "rock", ("rock music",)),
            Genero("Q2", "indie", "", (), ("Q1", "Q404")),
        ]
    )
    repo.guardar_mapeos(
        [MapeoEtiqueta("indie", "Q2", "alias", 0.95), MapeoEtiqueta("x", "Q404", "exacto", 1)]
    )
    cat = repo.cargar_catalogo()
    assert {g.id: g.padres for g in cat.generos} == {"Q1": (), "Q2": ("Q1",)}
    assert cat.generos[0].alias == ("rock music",)
    assert cat.mapeos == (MapeoEtiqueta("indie", "Q2", "alias", 0.95),)


def test_cache_de_api(repo: RepositorioSQLite) -> None:
    assert repo.cache_obtener("k") is None
    repo.cache_guardar("k", {"a": [1, 2]})
    assert repo.cache_obtener("k") == {"a": [1, 2]}
    repo.cache_guardar("k", [3])
    assert repo.cache_obtener("k") == [3]


def test_feedback(repo: RepositorioSQLite) -> None:
    repo.registrar_feedback("s1", 7, 1, "grafo")
    repo.registrar_feedback("s1", 8, -1, "contenido")
    assert repo.feedback() == [("s1", 7, 1, "grafo"), ("s1", 8, -1, "contenido")]


def test_sql_parametrizado_resiste_inyeccion(repo: RepositorioSQLite) -> None:
    malicioso = "Robert'); DROP TABLE artists; --"
    i = repo.guardar_artista(malicioso)
    repo.guardar_etiquetas(i, [("x'; DELETE FROM artist_tags; --", 1.0)])
    cat = repo.cargar_catalogo()
    assert cat.artistas[0].nombre == malicioso
    assert repo.contar_artistas() == 1
