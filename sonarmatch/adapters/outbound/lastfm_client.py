"""Cliente de la API de Last.fm (JSON).

Formato verificado en la documentación oficial (artist.getSimilar: ``match`` entre 0 y 1;
artist.getTopTags). Peculiaridades del JSON de Last.fm que se manejan aquí:
- los atributos XML aparecen como ``@attr``; los números llegan como cadenas;
- una lista con un solo elemento puede llegar como objeto en vez de arreglo;
- los errores llegan como ``{"error": código, "message": ...}``: 6 (no encontrado) se trata
  como resultado vacío; 8, 11, 16 y 29 (límite de tasa) se reintentan; el resto es fatal.
La clave de API nunca forma parte de la clave de caché ni de los registros.
"""

from dataclasses import dataclass

from sonarmatch.adapters.outbound.http_base import (
    Cache,
    ClienteHTTP,
    FuenteError,
    ReintentableError,
    con_cache,
)
from sonarmatch.ports.outbound import ArtistaFuente, SimilarFuente

URL = "https://ws.audioscrobbler.com/2.0/"
NO_ENCONTRADO = 6
REINTENTABLES = {8, 11, 16, 29}


def _lista(x: object) -> list[dict[str, object]]:
    if isinstance(x, dict):
        return [x]
    if isinstance(x, list):
        return [e for e in x if isinstance(e, dict)]
    return []


def _entero(x: object) -> int | None:
    try:
        return int(str(x))
    except (TypeError, ValueError):
        return None


def _dict(x: object, *claves: str) -> dict[str, object]:
    for k in claves:
        x = x.get(k, {}) if isinstance(x, dict) else {}
    return x if isinstance(x, dict) else {}


def _validar(datos: object) -> None:
    if isinstance(datos, dict) and "error" in datos:
        codigo = _entero(datos["error"])
        if codigo in REINTENTABLES:
            raise ReintentableError(f"Last.fm {codigo}: {datos.get('message')}")
        if codigo != NO_ENCONTRADO:
            raise FuenteError(f"Last.fm {codigo}: {datos.get('message')}")


def _artista(d: dict[str, object]) -> ArtistaFuente:
    return ArtistaFuente(
        nombre=str(d.get("name", "")),
        mbid=str(d["mbid"]) if d.get("mbid") else None,
        oyentes=_entero(d.get("listeners")),
        playcount=_entero(d.get("playcount")),
    )


@dataclass
class ClienteLastFM:
    api_key: str
    http: ClienteHTTP
    cache: Cache | None = None

    def _llamar(self, metodo: str, **params: str | int) -> dict[str, object]:
        clave = "lastfm:" + metodo + ":" + "&".join(f"{k}={params[k]}" for k in sorted(params))

        def obtener() -> object:
            todos: dict[str, str | int] = {
                "method": metodo,
                "format": "json",
                "api_key": self.api_key,
                **params,
            }
            return self.http.get_json(URL, todos, _validar)

        datos = con_cache(self.cache, clave, obtener)
        if not isinstance(datos, dict) or "error" in datos:
            return {}
        return datos

    def top_artistas(self, pagina: int, limite: int) -> list[ArtistaFuente]:
        d = self._llamar("chart.getTopArtists", page=pagina, limit=limite)
        return [_artista(a) for a in _lista(_dict(d, "artists").get("artist"))]

    def top_artistas_etiqueta(self, etiqueta: str, pagina: int, limite: int) -> list[ArtistaFuente]:
        d = self._llamar("tag.getTopArtists", tag=etiqueta, page=pagina, limit=limite)
        return [_artista(a) for a in _lista(_dict(d, "topartists").get("artist"))]

    def similares(self, nombre: str, limite: int) -> list[SimilarFuente]:
        d = self._llamar("artist.getSimilar", artist=nombre, limit=limite, autocorrect=1)
        salida = []
        for a in _lista(_dict(d, "similarartists").get("artist")):
            try:
                match = float(str(a.get("match", "0")))
            except ValueError:
                continue
            salida.append(
                SimilarFuente(
                    str(a.get("name", "")),
                    min(1.0, max(0.0, match)),
                    str(a["mbid"]) if a.get("mbid") else None,
                )
            )
        return salida

    def etiquetas(self, nombre: str) -> list[tuple[str, int]]:
        d = self._llamar("artist.getTopTags", artist=nombre, autocorrect=1)
        return [
            (str(t.get("name", "")), _entero(t.get("count")) or 0)
            for t in _lista(_dict(d, "toptags").get("tag"))
        ]

    def info(self, nombre: str) -> ArtistaFuente | None:
        d = _dict(self._llamar("artist.getInfo", artist=nombre, autocorrect=1), "artist")
        if not d:
            return None
        stats = _dict(d, "stats")
        return ArtistaFuente(
            nombre=str(d.get("name", nombre)),
            mbid=str(d["mbid"]) if d.get("mbid") else None,
            oyentes=_entero(stats.get("listeners")),
            playcount=_entero(stats.get("playcount")),
        )
