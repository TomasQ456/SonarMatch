"""Cliente de MusicBrainz: país y año de inicio por MBID.

Formato verificado (GET /ws/2/artist/<mbid>?fmt=json → ``country`` y ``life-span.begin``).
MusicBrainz exige un User-Agent descriptivo y como máximo 1 solicitud por segundo.
"""

from dataclasses import dataclass

from sonarmatch.adapters.outbound.http_base import Cache, ClienteHTTP, FuenteError, con_cache

URL = "https://musicbrainz.org/ws/2/artist/"
INTERVALO_MB = 1.0


@dataclass
class ClienteMusicBrainz:
    http: ClienteHTTP
    cache: Cache | None = None

    def detalles(self, mbid: str) -> tuple[str | None, int | None]:
        def obtener() -> object:
            try:
                return self.http.get_json(URL + mbid, {"fmt": "json"})
            except FuenteError:
                return {}  # MBID desconocido (404) u otro error definitivo: sin detalles

        datos = con_cache(self.cache, f"mb:artist:{mbid}", obtener)
        if not isinstance(datos, dict):
            return None, None
        pais = datos.get("country")
        vida = datos.get("life-span")
        inicio = vida.get("begin") if isinstance(vida, dict) else None
        anio = int(str(inicio)[:4]) if inicio and str(inicio)[:4].isdigit() else None
        return (str(pais) if pais else None), anio
