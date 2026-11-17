"""Limpieza de etiquetas e ingesta de punta a punta con fuentes simuladas."""

from pathlib import Path

import pytest

from sonarmatch.adapters.inbound import cli
from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import Genero
from sonarmatch.ingestion.limpieza import limpiar_etiquetas
from sonarmatch.ingestion.pipeline import ConfigIngesta, Ingesta, generos_alcanzables
from sonarmatch.ports.outbound import ArtistaFuente, SimilarFuente


def test_limpieza_de_etiquetas() -> None:
    crudas = [
        ("Shoegaze", 100),
        ("seen live", 90),
        ("shoegaze", 40),
        ("Dream Pop", 60),
        ("my favorite bands", 50),
        ("Slowdive", 30),
        ("4 of 5 stars", 20),
        ("1990", 5),
        ("albums I own", 10),
        ("90s", 10),
    ]
    assert limpiar_etiquetas(crudas, frozenset({"slowdive"})) == [
        ("shoegaze", 100.0),
        ("dream pop", 60.0),
        ("90s", 10.0),
    ]
    muchas = [(f"tag{i:02d}", i) for i in range(30)]
    limpias = limpiar_etiquetas(muchas)
    assert len(limpias) == 20
    assert limpias[0] == ("tag29", 29.0)


class FuenteFalsa:
    """Grafo pequeño: A-B-C-D-E en cadena + F aislado; G solo aparece como similar de E."""

    def __init__(self) -> None:
        self.llamadas: list[str] = []
        self.vecinos = {
            "A": [("B", 0.9), ("Fuera", 0.5)],
            "B": [("A", 0.9), ("C", 0.8)],
            "C": [("B", 0.8), ("D", 0.7)],
            "D": [("C", 0.7), ("E", 0.6)],
            "E": [("D", 0.6), ("G", 0.4)],
            "F": [],
            "G": [("E", 0.4)],
            "Fuera": [],
        }

    def top_artistas(self, pagina: int, limite: int) -> list[ArtistaFuente]:
        self.llamadas.append("chart")
        return [ArtistaFuente("A"), ArtistaFuente("F")] if pagina == 1 else []

    def top_artistas_etiqueta(self, etiqueta: str, pagina: int, limite: int) -> list[ArtistaFuente]:
        self.llamadas.append(f"tag:{etiqueta}")
        return [ArtistaFuente("a")]  # duplicado de A tras normalizar

    def similares(self, nombre: str, limite: int) -> list[SimilarFuente]:
        self.llamadas.append(f"sim:{nombre}")
        return [SimilarFuente(n, m) for n, m in self.vecinos.get(nombre, [])]

    def etiquetas(self, nombre: str) -> list[tuple[str, int]]:
        return [("Shoegaze" if nombre in "ABC" else "Thrash", 100), ("seen live", 80), (nombre, 50)]

    def info(self, nombre: str) -> ArtistaFuente | None:
        return ArtistaFuente(
            nombre, mbid=f"mb-{nombre}", oyentes=100 * len(nombre) + ord(nombre[0])
        )


class OntologiaFalsa:
    def generos_musicales(self) -> list[Genero]:
        return [
            Genero("Q1", "rock", "rock"),
            Genero("Q2", "shoegaze", "shoegaze"),
            Genero("Q3", "thrash metal", "thrash metal", ("thrash",)),
            Genero("Q4", "metal", "metal"),
            Genero("Q9", "jazz", "jazz"),
        ]

    def aristas_subclase(self) -> list[tuple[str, str]]:
        return [("Q2", "Q1"), ("Q3", "Q4"), ("Q4", "Q1"), ("Q9", "Q99")]


class DetallesFalsos:
    def __init__(self) -> None:
        self.pedidos: list[str] = []

    def detalles(self, mbid: str) -> tuple[str | None, int | None]:
        self.pedidos.append(mbid)
        return "GB", 1990


@pytest.fixture
def ingesta(tmp_path: Path) -> Ingesta:
    repo = RepositorioSQLite(tmp_path / "i.db")
    config = ConfigIngesta(
        objetivo=6,
        paginas_chart=2,
        etiquetas_semilla=("shoegaze",),
        mapeo_manual=tmp_path / "no.csv",
        reportes=tmp_path / "rep",
    )
    return Ingesta(repo, FuenteFalsa(), OntologiaFalsa(), DetallesFalsos(), config)


def test_ingesta_de_punta_a_punta(ingesta: Ingesta) -> None:
    resumen = ingesta.ejecutar()
    cat = ingesta.repo.cargar_catalogo()
    nombres = {a.nombre for a in cat.artistas}
    assert nombres == {"A", "F", "B", "Fuera", "C", "D"}  # BFS hasta el objetivo (6)
    assert resumen.artistas == 6
    por_nombre = {a.id: a.nombre for a in cat.artistas}
    aristas = {frozenset((por_nombre[u], por_nombre[v])) for u, v, _ in cat.similares}
    # solo aristas con ambos extremos en el catálogo (D-E y E-G quedan fuera)
    assert aristas == {frozenset(p) for p in [("A", "B"), ("A", "Fuera"), ("B", "C"), ("C", "D")]}
    etiquetas = {a.nombre: a.etiquetas for a in cat.artistas}
    assert etiquetas["A"] == (("shoegaze", 100.0),)  # sin "seen live" ni el nombre propio
    assert {a.pais for a in cat.artistas} == {"GB"}
    # ontología: shoegaze y thrash mapeados + ancestros; jazz no se guarda
    assert {g.id for g in cat.generos} == {"Q1", "Q2", "Q3", "Q4"}
    assert {(m.etiqueta, m.genero_id, m.metodo) for m in cat.mapeos} == {
        ("shoegaze", "Q2", "exacto"),
        ("thrash", "Q3", "alias"),
    }
    assert resumen.cobertura == pytest.approx(1.0)
    assert (ingesta.config.reportes / "mapeo_muestra.csv").exists()
    IndiceCatalogo.construir(cat)  # el catálogo ingerido es utilizable por el motor


def test_ingesta_es_reanudable_e_idempotente(ingesta: Ingesta) -> None:
    ingesta.ejecutar()
    antes = ingesta.repo.cargar_catalogo()
    ingesta.ejecutar()
    despues = ingesta.repo.cargar_catalogo()
    assert antes == despues


def test_ingesta_sin_musicbrainz(ingesta: Ingesta) -> None:
    ingesta.config.usar_musicbrainz = False
    ingesta.ejecutar()
    assert ingesta.detalles.pedidos == []


def test_generos_alcanzables_incluye_ancestros() -> None:
    generos = OntologiaFalsa().generos_musicales()
    res = generos_alcanzables(generos, OntologiaFalsa().aristas_subclase(), {"Q3"})
    assert {g.id: g.padres for g in res} == {"Q3": ("Q4",), "Q4": ("Q1",), "Q1": ()}


def test_cli_ingest_sin_claves_falla_con_mensaje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    assert cli.main(["ingest", "--db", str(tmp_path / "x.db")]) == 2
    assert "LASTFM_API_KEY" in caplog.text
