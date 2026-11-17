"""Servicio de aplicación, bootstrap real y CLI sobre el fixture."""

from pathlib import Path

import pytest

from sonarmatch.adapters.inbound import cli
from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite, guardar_catalogo
from sonarmatch.application import recommend_service
from sonarmatch.bootstrap import Servicios, crear_servicios
from sonarmatch.config import ConfigMotor
from sonarmatch.domain.models import Catalogo
from sonarmatch.ports.inbound import (
    EntradaArtista,
    ErrorEntradaInvalida,
    ParametrosMotor,
    SolicitudRecomendacion,
)

SHOEGAZE = ("Slowdive", "Low", "Codeine", "Red House Painters", "My Bloody Valentine", "Lush")


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory, catalogo: Catalogo) -> Path:
    ruta = tmp_path_factory.mktemp("db") / "sm.db"
    guardar_catalogo(RepositorioSQLite(ruta), catalogo)
    return ruta


@pytest.fixture
def servicios(db: Path, tmp_path: Path) -> Servicios:
    return crear_servicios(str(db), str(tmp_path / "sin_calibrar.json"))


def _sol(
    nombres: tuple[str, ...] = SHOEGAZE, p: ParametrosMotor | None = None
) -> SolicitudRecomendacion:
    return SolicitudRecomendacion(
        tuple(EntradaArtista(n, 1 + i % 5) for i, n in enumerate(nombres)), p
    )


def test_recomendar_devuelve_dtos_del_contrato(servicios: Servicios) -> None:
    resp = servicios.recomendar.recomendar(_sol((*SHOEGAZE, "Nadie")))
    assert len(resp.recomendaciones) == 10
    assert resp.artistas_no_encontrados == ("Nadie",)
    assert resp.estrategias_usadas == {"grafo": 10}
    assert resp.latencia_ms > 0
    for r in resp.recomendaciones:
        assert sum(r.aportes.values()) == pytest.approx(r.puntaje)
        assert set(r.artistas_origen) <= set(SHOEGAZE)
        assert r.explicacion
        assert r.oyentes > 0


def test_cache_por_solicitud(servicios: Servicios) -> None:
    a = servicios.recomendar.recomendar(_sol())
    b = servicios.recomendar.recomendar(_sol())
    assert a == b  # misma latencia: viene del caché
    otra = servicios.recomendar.recomendar(_sol(p=ParametrosMotor(0.5, 0.5, 0, 0, 1.0)))
    assert otra.recomendaciones != a.recomendaciones


def test_cache_acotado(servicios: Servicios, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recommend_service, "TAMANO_CACHE", 2)
    for k in range(4):
        servicios.recomendar.recomendar(_sol(p=ParametrosMotor(0.25, 0.25, 0.25, 0.25, k / 4)))
    assert len(servicios.recomendar._cache) == 2


def test_validacion(servicios: Servicios) -> None:
    with pytest.raises(ErrorEntradaInvalida):
        servicios.recomendar.recomendar(_sol(SHOEGAZE[:4]))
    with pytest.raises(ErrorEntradaInvalida):
        servicios.explicar.contrafactual(_sol(SHOEGAZE[:4]), 1)


def test_contrafactual_y_por_que_no(servicios: Servicios) -> None:
    resp = servicios.recomendar.recomendar(_sol())
    rec = resp.recomendaciones[0]
    cf = servicios.explicar.contrafactual(_sol(), rec.artista_id)
    assert cf.nombre == rec.nombre
    assert {e.artista_usuario for e in cf.efectos} == set(SHOEGAZE)
    assert all(e.posicion_original == 1 for e in cf.efectos)
    assert cf.resumen
    with pytest.raises(ErrorEntradaInvalida, match="no está entre"):
        servicios.explicar.contrafactual(_sol(), 999_999)
    pq = servicios.explicar.por_que_no(_sol(), "Miles Davis")
    assert pq.motivo == "no_conectado"
    with pytest.raises(ErrorEntradaInvalida, match="sí fue recomendado"):
        servicios.explicar.por_que_no(_sol(), rec.nombre)


def test_catalogo_y_feedback(servicios: Servicios, db: Path) -> None:
    nombres = servicios.catalogo.nombres_artistas()
    assert len(nombres) == 51
    assert nombres == sorted(nombres, key=str.casefold)
    p = servicios.catalogo.parametros_por_defecto()
    assert (p.a, p.b, p.c, p.d, p.lambda_mmr) == (0.3, 0.35, 0.15, 0.2, 0.7)
    servicios.feedback.registrar("sesion-x", 3, -1, "contenido")
    assert ("sesion-x", 3, -1, "contenido") in RepositorioSQLite(db).feedback()
    with pytest.raises(ErrorEntradaInvalida):
        servicios.feedback.registrar("s", 3, 0, "grafo")


def test_bootstrap_errores(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ingest"):
        crear_servicios(str(tmp_path / "no.db"))
    vacia = tmp_path / "vacia.db"
    RepositorioSQLite(vacia).crear_esquema()
    with pytest.raises(FileNotFoundError, match="no tiene artistas"):
        crear_servicios(str(vacia))


def test_bootstrap_lee_parametros_calibrados(db: Path, tmp_path: Path) -> None:
    ruta = tmp_path / "cal.json"
    ConfigMotor(a=0.4, b=0.4, c=0.1, d=0.1, lambda_mmr=0.9).a_json(ruta)
    p = crear_servicios(str(db), str(ruta)).catalogo.parametros_por_defecto()
    assert (p.a, p.lambda_mmr) == (0.4, 0.9)


def test_cli_ingest_fixture_y_recommend(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "cli.db"
    assert cli.main(["ingest", "--fixture", "--db", str(ruta)]) == 0
    assert cli.main(["ingest", "--fixture", "--db", str(ruta)]) == 0  # idempotente
    args = ["recommend", *(f"{n}:4" for n in SHOEGAZE), "Nadie", "--db", str(ruta)]
    assert cli.main(args) == 0
    salida = capsys.readouterr().out
    assert "No encontrados: Nadie" in salida
    assert " 1. " in salida
    assert " 10. " in salida or "10. " in salida
    assert cli.main(["recommend", "Slowdive", "--db", str(ruta)]) == 2
    assert "Error" in capsys.readouterr().err


def test_cli_parseo_de_entradas() -> None:
    assert cli._parsear_entrada("AC/DC:5") == EntradaArtista("AC/DC", 5.0)
    assert cli._parsear_entrada("Sin peso") == EntradaArtista("Sin peso", 3.0)
    assert cli._parsear_entrada("Raro:x") == EntradaArtista("Raro:x", 3.0)
