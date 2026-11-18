"""Perfiles y amistades en SQLite, el servicio sobre SQLite y el cargador de user_friends.dat."""

import sqlite3
from pathlib import Path

import pytest

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite, guardar_catalogo
from sonarmatch.application.perfiles import ServicioPerfiles
from sonarmatch.bootstrap import crear_servicios
from sonarmatch.domain.models import EntradaPerfil
from sonarmatch.evaluation.datasets import leer_amigos_hetrec
from sonarmatch.ingestion.fixture import catalogo_desde_json
from sonarmatch.ports.inbound import AmigoDTO, EntradaArtista, ErrorPerfil

ARTISTAS = tuple(EntradaPerfil(n, 2.0) for n in ("A", "B", "C", "D", "E"))


@pytest.fixture
def repo(tmp_path: Path) -> RepositorioSQLite:
    r = RepositorioSQLite(tmp_path / "p.db")
    r.crear_esquema()
    return r


def test_guardar_y_releer_perfil_con_consentimiento_falso_por_defecto(
    repo: RepositorioSQLite,
) -> None:
    p = repo.guardar_perfil("ana_m", ARTISTAS, comparte_gustos=False)
    assert repo.obtener_perfil("ana_m") == p
    assert p.artistas == ARTISTAS
    assert p.comparte_gustos is False
    assert repo.obtener_perfil("nadie") is None
    with repo.conexion() as con:
        con.execute(
            "INSERT INTO perfiles (apodo, artistas_json, creado_en, actualizado_en) "
            "VALUES ('sin_flag', '[]', 0, 0)"
        )
    sin_flag = repo.obtener_perfil("sin_flag")
    assert sin_flag is not None
    assert sin_flag.comparte_gustos is False


def test_apodo_unico_actualiza_en_lugar_de_duplicar(repo: RepositorioSQLite) -> None:
    primero = repo.guardar_perfil("ana_m", ARTISTAS, comparte_gustos=False)
    segundo = repo.guardar_perfil("ana_m", ARTISTAS[:3], comparte_gustos=True)
    assert segundo.id == primero.id
    assert segundo.comparte_gustos is True
    assert len(segundo.artistas) == 3
    with repo.conexion() as con:
        assert con.execute("SELECT COUNT(*) FROM perfiles").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO perfiles (apodo, artistas_json, creado_en, actualizado_en) "
                "VALUES ('ANA_M', '[]', 0, 0)"
            )


def test_amistad_bidireccional_sin_duplicados_ni_autorrelacion(repo: RepositorioSQLite) -> None:
    a = repo.guardar_perfil("ana_m", ARTISTAS, comparte_gustos=True)
    b = repo.guardar_perfil("juanp", ARTISTAS, comparte_gustos=False)
    c = repo.guardar_perfil("luz", ARTISTAS, comparte_gustos=True)
    assert repo.agregar_amistad(b.id, a.id) is True
    assert repo.agregar_amistad(a.id, b.id) is False  # mismo par en otro sentido
    assert repo.agregar_amistad(a.id, a.id) is False
    assert repo.agregar_amistad(a.id, c.id) is True
    assert [p.apodo for p in repo.amigos(a.id)] == ["juanp", "luz"]
    assert [p.apodo for p in repo.amigos(b.id)] == ["ana_m"]
    with repo.conexion() as con:
        assert con.execute("SELECT COUNT(*) FROM amistades").fetchone() == (2,)
        with pytest.raises(sqlite3.IntegrityError):  # el esquema también impide la autorrelación
            con.execute("INSERT INTO amistades VALUES (?, ?, 0)", (a.id, a.id))
    assert repo.quitar_amistad(a.id, b.id) is True
    assert repo.quitar_amistad(b.id, a.id) is False
    assert [p.apodo for p in repo.amigos(b.id)] == []


def test_servicio_sobre_sqlite_y_crear_servicios_conecta_perfiles(tmp_path: Path) -> None:
    ruta = tmp_path / "catalogo.db"
    guardar_catalogo(RepositorioSQLite(ruta), catalogo_desde_json())
    servicios = crear_servicios(str(ruta))
    perfiles = servicios.perfiles
    nombres = servicios.catalogo.nombres_artistas()[:5]
    entrada = tuple(EntradaArtista(n, 4) for n in nombres)
    perfiles.guardar_perfil("Ana_M", entrada, comparte_gustos=True)
    perfiles.guardar_perfil("juanp", entrada, comparte_gustos=False)
    perfiles.agregar_amigo("juanp", "ana_m")
    assert perfiles.listar_amigos("ana_m") == (AmigoDTO("juanp", False),)
    assert perfiles.obtener_perfil("ANA_M").artistas == entrada
    with pytest.raises(ErrorPerfil):
        perfiles.agregar_amigo("ana_m", "juanp")
    assert isinstance(perfiles, ServicioPerfiles)
    assert [p.apodo for p in perfiles.amigos_que_comparten("juanp")] == ["ana_m"]


def test_leer_amigos_hetrec_simetriza_y_descarta_autorrelaciones(tmp_path: Path) -> None:
    (tmp_path / "user_friends.dat").write_bytes(
        b"userID\tfriendID\r\n2\t275\r\n275\t2\r\n2\t428\r\n7\t7\r\n9\t2\r\n"
    )
    amigos = leer_amigos_hetrec(tmp_path)
    assert amigos == {
        "2": frozenset({"275", "428", "9"}),
        "275": frozenset({"2"}),
        "428": frozenset({"2"}),
        "9": frozenset({"2"}),
    }


def test_leer_amigos_hetrec_exige_columnas(tmp_path: Path) -> None:
    (tmp_path / "user_friends.dat").write_text("a\tb\n1\t2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="friendID"):
        leer_amigos_hetrec(tmp_path)
