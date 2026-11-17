"""Clientes HTTP con respuestas simuladas (sin red): éxito, error, límite de tasa y caché."""

from pathlib import Path

import pytest
import requests
import responses
from responses import matchers

from sonarmatch.adapters.outbound import lastfm_client, musicbrainz_client, wikidata_client
from sonarmatch.adapters.outbound.http_base import ClienteHTTP, FuenteError
from sonarmatch.adapters.outbound.lastfm_client import ClienteLastFM
from sonarmatch.adapters.outbound.musicbrainz_client import ClienteMusicBrainz
from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.adapters.outbound.wikidata_client import ClienteWikidata

LFM = lastfm_client.URL


class Reloj:
    def __init__(self) -> None:
        self.t = 0.0
        self.esperas: list[float] = []

    def ahora(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.esperas.append(s)
        self.t += s


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture
def repo(tmp_path: Path) -> RepositorioSQLite:
    r = RepositorioSQLite(tmp_path / "c.db")
    r.crear_esquema()
    return r


def http(reloj: Reloj, intervalo: float = 0.25) -> ClienteHTTP:
    return ClienteHTTP(
        intervalo, "SonarMatch-test/0.1", reintentos=3, dormir=reloj.dormir, reloj=reloj.ahora
    )


def lastfm(reloj: Reloj, repo: RepositorioSQLite | None = None) -> ClienteLastFM:
    return ClienteLastFM("CLAVE_SECRETA", http(reloj), repo)


SIMILARES = {
    "similarartists": {
        "artist": [
            {"name": "Slowdive", "match": "1", "mbid": "mb-1"},
            {"name": "Ride", "match": "0.42", "mbid": ""},
            {"name": "Raro", "match": "x"},
        ],
        "@attr": {"artist": "Lush"},
    }
}


@responses.activate
def test_lastfm_similares_exito_y_parametros(reloj: Reloj) -> None:
    responses.get(
        LFM,
        json=SIMILARES,
        match=[
            matchers.query_param_matcher(
                {
                    "method": "artist.getSimilar",
                    "format": "json",
                    "api_key": "CLAVE_SECRETA",
                    "artist": "Lush",
                    "limit": "50",
                    "autocorrect": "1",
                }
            ),
            matchers.header_matcher({"User-Agent": "SonarMatch-test/0.1"}),
        ],
    )
    sims = lastfm(reloj).similares("Lush", 50)
    assert [(s.nombre, s.match, s.mbid) for s in sims] == [
        ("Slowdive", 1.0, "mb-1"),
        ("Ride", 0.42, None),
    ]


@responses.activate
def test_lastfm_un_solo_elemento_llega_como_objeto(reloj: Reloj) -> None:
    responses.get(LFM, json={"toptags": {"tag": {"name": "Shoegaze", "count": 100}}})
    assert lastfm(reloj).etiquetas("X") == [("Shoegaze", 100)]


@responses.activate
def test_lastfm_info_top_y_etiqueta(reloj: Reloj) -> None:
    responses.get(
        LFM,
        json={
            "artist": {"name": "Lush", "mbid": "m", "stats": {"listeners": "300", "playcount": "9"}}
        },
        match=[matchers.query_param_matcher({"method": "artist.getInfo"}, strict_match=False)],
    )
    responses.get(
        LFM,
        json={
            "artists": {"artist": [{"name": "A", "listeners": "5", "playcount": "7", "mbid": ""}]}
        },
        match=[matchers.query_param_matcher({"method": "chart.getTopArtists"}, strict_match=False)],
    )
    responses.get(
        LFM,
        json={"topartists": {"artist": [{"name": "B", "mbid": "x"}, {"name": "C"}]}},
        match=[
            matchers.query_param_matcher(
                {"method": "tag.getTopArtists", "tag": "slowcore"}, strict_match=False
            )
        ],
    )
    c = lastfm(reloj)
    info = c.info("Lush")
    assert info is not None
    assert (info.oyentes, info.playcount, info.mbid) == (300, 9, "m")
    assert [a.nombre for a in c.top_artistas(1, 10)] == ["A"]
    assert c.top_artistas(1, 10)[0].oyentes == 5
    assert [a.nombre for a in c.top_artistas_etiqueta("slowcore", 1, 10)] == ["B", "C"]


@responses.activate
def test_lastfm_no_encontrado_es_vacio(reloj: Reloj) -> None:
    responses.get(LFM, json={"error": 6, "message": "The artist you supplied could not be found"})
    c = lastfm(reloj)
    assert c.similares("Nadie", 10) == []
    assert c.info("Nadie") is None


@responses.activate
def test_lastfm_error_fatal(reloj: Reloj) -> None:
    responses.get(LFM, json={"error": 10, "message": "Invalid API key"}, status=403)
    with pytest.raises(FuenteError, match="10"):
        lastfm(reloj).similares("Lush", 10)


@responses.activate
def test_lastfm_limite_de_tasa_reintenta_con_backoff(reloj: Reloj) -> None:
    responses.get(LFM, json={"error": 29, "message": "Rate Limit Exceeded"})
    responses.get(LFM, status=503)
    responses.get(LFM, json=SIMILARES)
    sims = lastfm(reloj).similares("Lush", 50)
    assert len(sims) == 2
    assert len(responses.calls) == 3
    assert [e for e in reloj.esperas if e >= 1] == [1.0, 2.0]  # backoff exponencial


@responses.activate
def test_lastfm_agota_reintentos(reloj: Reloj) -> None:
    responses.get(LFM, body=requests.ConnectionError("caída"))
    with pytest.raises(FuenteError, match="reintentos"):
        lastfm(reloj).similares("Lush", 50)
    assert len(responses.calls) == 4


@responses.activate
def test_respuesta_no_json_se_reintenta(reloj: Reloj) -> None:
    responses.get(LFM, body="<html>mantenimiento</html>")
    responses.get(LFM, json=SIMILARES)
    assert len(lastfm(reloj).similares("Lush", 50)) == 2


@responses.activate
def test_lastfm_usa_cache_y_no_guarda_la_clave(reloj: Reloj, repo: RepositorioSQLite) -> None:
    responses.get(LFM, json=SIMILARES)
    c = lastfm(reloj, repo)
    assert c.similares("Lush", 50) == c.similares("Lush", 50)
    assert len(responses.calls) == 1
    with repo.conexion() as con:
        claves = [k for (k,) in con.execute("SELECT key FROM api_cache")]
        cuerpo = " ".join(p for (p,) in con.execute("SELECT payload_json FROM api_cache"))
    assert claves == ["lastfm:artist.getSimilar:artist=Lush&autocorrect=1&limit=50"]
    assert "CLAVE_SECRETA" not in " ".join(claves) + cuerpo


@responses.activate
def test_limite_de_tasa_espacia_solicitudes(reloj: Reloj) -> None:
    responses.get(LFM, json=SIMILARES)
    c = lastfm(reloj)
    c.similares("A", 1)
    c.similares("B", 1)
    c.similares("C", 1)
    assert reloj.esperas == [0.25, 0.25]


@responses.activate
def test_musicbrainz_detalles_y_errores(reloj: Reloj, repo: RepositorioSQLite) -> None:
    url = musicbrainz_client.URL
    responses.get(
        url + "mb-1", json={"country": "US", "life-span": {"begin": "1964-05", "end": "1977"}}
    )
    responses.get(url + "mb-2", json={"country": None, "life-span": {}})
    responses.get(url + "mb-404", json={"error": "Not Found"}, status=404)
    c = ClienteMusicBrainz(http(reloj, intervalo=1.0), repo)
    assert c.detalles("mb-1") == ("US", 1964)
    assert c.detalles("mb-1") == ("US", 1964)  # caché
    assert c.detalles("mb-2") == (None, None)
    assert c.detalles("mb-404") == (None, None)
    assert len(responses.calls) == 3
    assert 1.0 in reloj.esperas  # 1 solicitud por segundo
    assert responses.calls[0].request.headers["User-Agent"] == "SonarMatch-test/0.1"


@responses.activate
def test_wikidata_generos_y_aristas(reloj: Reloj) -> None:
    pre = wikidata_client.PREFIJO
    responses.get(
        wikidata_client.URL,
        json={
            "results": {
                "bindings": [
                    {
                        "g": {"value": pre + "Q11399"},
                        "en": {"value": "rock music"},
                        "es": {"value": "rock"},
                        "aliases": {"value": "rock|rock and roll"},
                    },
                    {"g": {"value": pre + "Q11399"}, "en": {"value": "rock music"}},
                    {"g": {"value": pre + "Q1"}},
                ]
            }
        },
        match=[matchers.query_param_matcher({"query": wikidata_client.CONSULTA_GENEROS})],
    )
    responses.get(
        wikidata_client.URL,
        json={
            "results": {
                "bindings": [
                    {"hijo": {"value": pre + "Q2"}, "padre": {"value": pre + "Q11399"}},
                    {"hijo": {"value": pre + "Q3"}},
                ]
            }
        },
        match=[matchers.query_param_matcher({"query": wikidata_client.CONSULTA_ARISTAS})],
    )
    c = ClienteWikidata(http(reloj))
    generos = c.generos_musicales()
    assert [(g.id, g.etiqueta_en, g.etiqueta_es, g.alias) for g in generos] == [
        ("Q1", "", "", ()),
        ("Q11399", "rock music", "rock", ("rock", "rock and roll")),
    ]
    assert c.aristas_subclase() == [("Q2", "Q11399")]
    assert "sparql-results+json" in responses.calls[0].request.headers["Accept"]


def test_wikidata_respuesta_malformada() -> None:
    assert wikidata_client._filas("x") == []
    assert wikidata_client._filas({"results": {"bindings": "x"}}) == []
