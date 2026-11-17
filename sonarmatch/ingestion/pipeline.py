"""Ingesta por lotes que puebla SQLite.

1. Semillas: chart.getTopArtists y tag.getTopArtists sobre una lista variada de etiquetas.
2. Expansión en anchura con artist.getSimilar hasta el objetivo (≈5.000 artistas).
3. Por artista: artist.getTopTags (limpias, top 20) y artist.getInfo (oyentes, MBID).
4. Aristas: getSimilar de cada artista del catálogo; solo se guardan si ambos extremos están.
5. MusicBrainz: país y año de inicio por MBID (1 solicitud/s), opcional.
6. Wikidata: géneros, mapeo de etiquetas y ancestros; cobertura y muestra para revisión.

Reanudable: toda respuesta de API queda en ``api_cache``; al relanzar, las llamadas ya hechas
se leen del caché y no se repiten.
"""

import csv
import logging
import os
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sonarmatch.adapters.outbound.http_base import ClienteHTTP
from sonarmatch.adapters.outbound.lastfm_client import ClienteLastFM
from sonarmatch.adapters.outbound.musicbrainz_client import INTERVALO_MB, ClienteMusicBrainz
from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.adapters.outbound.wikidata_client import ClienteWikidata
from sonarmatch.domain.models import Genero
from sonarmatch.domain.ontology import Ontologia
from sonarmatch.domain.textos import normalizar_nombre
from sonarmatch.ingestion.genre_mapping import (
    cobertura,
    leer_mapeo_manual,
    mapear_etiquetas,
    muestra_difusos,
)
from sonarmatch.ingestion.limpieza import limpiar_etiquetas
from sonarmatch.ports.outbound import FuenteDetalles, FuenteMetadatos, FuenteOntologia

log = logging.getLogger(__name__)

ETIQUETAS_SEMILLA: tuple[str, ...] = (
    "rock", "pop", "hip-hop", "electronic", "jazz", "folk", "metal", "classical", "indie",
    "punk", "soul", "blues", "country", "reggae", "latin", "ambient", "shoegaze", "dream pop",
    "slowcore", "post-rock", "math rock", "emo", "screamo", "black metal", "doom metal",
    "post-punk", "darkwave", "coldwave", "krautrock", "psychedelic", "idm", "drum and bass",
    "dub", "footwork", "vaporwave", "city pop", "bossa nova", "cumbia", "afrobeat", "k-pop",
    "j-rock", "bluegrass", "noise", "free jazz", "lo-fi", "trip-hop", "grunge", "riot grrrl",
)  # fmt: skip


@dataclass
class ConfigIngesta:
    objetivo: int = 5000
    paginas_chart: int = 4
    por_pagina_chart: int = 100
    por_etiqueta: int = 50
    similares_por_artista: int = 50
    etiquetas_semilla: tuple[str, ...] = ETIQUETAS_SEMILLA
    usar_musicbrainz: bool = True
    umbral_difuso: float = 90.0
    mapeo_manual: Path = Path("data/mapeo_manual.csv")
    reportes: Path = Path("reports")


@dataclass
class ResumenIngesta:
    artistas: int = 0
    aristas: int = 0
    generos: int = 0
    mapeos: int = 0
    cobertura: float = 0.0
    ciclos_rotos: int = 0
    metodos: dict[str, int] = field(default_factory=dict)


@dataclass
class Ingesta:
    repo: RepositorioSQLite
    fuente: FuenteMetadatos
    ontologia: FuenteOntologia
    detalles: FuenteDetalles | None = None
    config: ConfigIngesta = field(default_factory=ConfigIngesta)

    def ejecutar(self) -> ResumenIngesta:
        self.repo.crear_esquema()
        nombres = self.descubrir()
        ids = self.poblar_artistas(nombres)
        aristas = self.poblar_aristas(nombres, ids)
        if self.config.usar_musicbrainz and self.detalles is not None:
            self.poblar_detalles(self.detalles)
        resumen = self.poblar_ontologia()
        resumen.artistas, resumen.aristas = len(ids), aristas
        log.info("ingesta completa: %s", resumen)
        return resumen

    # ------------------------------------------------------------------ 1 y 2
    def semillas(self) -> list[str]:
        c = self.config
        nombres: list[str] = []
        for pagina in range(1, c.paginas_chart + 1):
            nombres += [a.nombre for a in self.fuente.top_artistas(pagina, c.por_pagina_chart)]
        for etiqueta in c.etiquetas_semilla:
            nombres += [
                a.nombre for a in self.fuente.top_artistas_etiqueta(etiqueta, 1, c.por_etiqueta)
            ]
        return nombres

    def descubrir(self) -> list[str]:
        """BFS desde las semillas por artist.getSimilar hasta alcanzar el objetivo."""
        objetivo = self.config.objetivo
        vistos: dict[str, str] = {}
        cola: deque[str] = deque()
        for n in self.semillas():
            clave = normalizar_nombre(n)
            if n and clave not in vistos and len(vistos) < objetivo:
                vistos[clave] = n
                cola.append(n)
        while cola and len(vistos) < objetivo:
            actual = cola.popleft()
            for s in self.fuente.similares(actual, self.config.similares_por_artista):
                clave = normalizar_nombre(s.nombre)
                if s.nombre and clave not in vistos:
                    vistos[clave] = s.nombre
                    cola.append(s.nombre)
                    if len(vistos) >= objetivo:
                        break
            if len(vistos) % 500 == 0:
                log.info("descubiertos %d artistas", len(vistos))
        return list(vistos.values())

    # ------------------------------------------------------------------ 3
    def poblar_artistas(self, nombres: Sequence[str]) -> dict[str, int]:
        claves = frozenset(normalizar_nombre(n) for n in nombres)
        ids: dict[str, int] = {}
        for k, nombre in enumerate(nombres, 1):
            info = self.fuente.info(nombre)
            artista_id = self.repo.guardar_artista(
                nombre,
                oyentes=(info.oyentes or 0) if info else 0,
                playcount=(info.playcount or 0) if info else 0,
                mbid=info.mbid if info else None,
            )
            etiquetas = limpiar_etiquetas(self.fuente.etiquetas(nombre), claves)
            self.repo.guardar_etiquetas(artista_id, etiquetas)
            ids[normalizar_nombre(nombre)] = artista_id
            if k % 250 == 0:
                log.info("artistas procesados: %d/%d", k, len(nombres))
        return ids

    # ------------------------------------------------------------------ 4
    def poblar_aristas(self, nombres: Sequence[str], ids: dict[str, int]) -> int:
        aristas: dict[tuple[int, int], float] = {}
        for nombre in nombres:
            origen = ids[normalizar_nombre(nombre)]
            for s in self.fuente.similares(nombre, self.config.similares_por_artista):
                destino = ids.get(normalizar_nombre(s.nombre))
                if destino is not None and destino != origen and s.match > 0:
                    par = (min(origen, destino), max(origen, destino))
                    aristas[par] = max(aristas.get(par, 0.0), s.match)
        self.repo.guardar_similares((u, v, m) for (u, v), m in sorted(aristas.items()))
        self.repo.podar_aristas_fuera_del_catalogo()
        return len(aristas)

    # ------------------------------------------------------------------ 5
    def poblar_detalles(self, detalles: FuenteDetalles) -> None:
        with self.repo.conexion() as con:
            filas = con.execute("SELECT id, mbid FROM artists WHERE mbid IS NOT NULL").fetchall()
        for artista_id, mbid in filas:
            pais, anio = detalles.detalles(str(mbid))
            self.repo.actualizar_detalles(int(artista_id), pais, anio)

    # ------------------------------------------------------------------ 6
    def poblar_ontologia(self) -> ResumenIngesta:
        catalogo = self.repo.cargar_catalogo()
        etiquetas = {t for a in catalogo.artistas for t, _ in a.etiquetas}
        generos = self.ontologia.generos_musicales()
        manual = leer_mapeo_manual(self.config.mapeo_manual)
        mapeos = mapear_etiquetas(etiquetas, generos, manual, self.config.umbral_difuso)
        con_ancestros = generos_alcanzables(
            generos, self.ontologia.aristas_subclase(), {m.genero_id for m in mapeos}
        )
        self.repo.guardar_generos(con_ancestros)
        ontologia = Ontologia.construir({g.id: g.padres for g in con_ancestros})
        for rota in ontologia.aristas_rotas:
            log.info("ciclo en P279 roto: %s", rota)
        self.repo.guardar_mapeos(mapeos)
        cob = cobertura(catalogo.artistas, mapeos)
        muestra = muestra_difusos(mapeos, generos)
        escribir_muestra(self.config.reportes / "mapeo_muestra.csv", muestra)
        metodos: dict[str, int] = {}
        for m in mapeos:
            metodos[m.metodo] = metodos.get(m.metodo, 0) + 1
        log.info("cobertura del mapeo de etiquetas: %.1f %%", 100 * cob)
        return ResumenIngesta(
            generos=len(con_ancestros),
            mapeos=len(mapeos),
            cobertura=cob,
            ciclos_rotos=len(ontologia.aristas_rotas),
            metodos=metodos,
        )


def generos_alcanzables(
    generos: Iterable[Genero], aristas: Iterable[tuple[str, str]], mapeados: set[str]
) -> list[Genero]:
    """Géneros mapeados + todos sus ancestros (cierre por P279), con sus padres."""
    padres: dict[str, set[str]] = {}
    for hijo, padre in aristas:
        padres.setdefault(hijo, set()).add(padre)
    incluidos: set[str] = set()
    pila = sorted(mapeados)
    while pila:
        g = pila.pop()
        if g in incluidos:
            continue
        incluidos.add(g)
        pila.extend(sorted(padres.get(g, set()) - incluidos))
    por_id = {g.id: g for g in generos}
    return [
        Genero(
            g.id,
            g.etiqueta_en or g.id,
            g.etiqueta_es,
            g.alias,
            tuple(sorted(p for p in padres.get(g.id, set()) if p in incluidos)),
        )
        for g in (por_id[q] for q in sorted(incluidos) if q in por_id)
    ]


def escribir_muestra(ruta: Path, filas: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    columnas = ["etiqueta", "genero_id", "genero", "confianza", "correcto"]
    with ruta.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)


def ingerir_desde_entorno(ruta_db: Path, objetivo: int = 5000, musicbrainz: bool = True) -> int:
    """Compone los clientes reales a partir de LASTFM_API_KEY y MB_USER_AGENT."""
    clave = os.environ.get("LASTFM_API_KEY", "").strip()
    agente = os.environ.get("MB_USER_AGENT", "").strip()
    if not clave or not agente:
        log.error("Faltan LASTFM_API_KEY o MB_USER_AGENT (ver .env.example). Usa --fixture.")
        return 2
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    repo = RepositorioSQLite(ruta_db)
    repo.crear_esquema()
    ingesta = Ingesta(
        repo=repo,
        fuente=ClienteLastFM(clave, ClienteHTTP(0.25, agente), repo),
        ontologia=ClienteWikidata(ClienteHTTP(1.0, agente, timeout=120), repo),
        detalles=ClienteMusicBrainz(ClienteHTTP(INTERVALO_MB, agente), repo),
        config=ConfigIngesta(objetivo=objetivo, usar_musicbrainz=musicbrainz),
    )
    resumen = ingesta.ejecutar()
    print(
        f"{resumen.artistas} artistas, {resumen.aristas} aristas, {resumen.generos} géneros, "
        f"cobertura del mapeo {100 * resumen.cobertura:.1f} %"
    )
    return 0
