"""Cliente SPARQL de Wikidata: géneros musicales y su jerarquía.

QID y propiedades verificados con una consulta de prueba: Q188451 = "music genre",
P31 = "instance of", P279 = "subclass of".

Decisión: la consulta de ancestros con ruta P279* tardó ~27 s para 2 QID, así que se
descargan en una sola consulta las aristas P279 directas entre géneros (≈8.000, ~2,5 s) y el
cierre de ancestros se calcula localmente. A la base solo pasan los géneros alcanzables desde
etiquetas mapeadas y sus ancestros. Se pierden los caminos que pasan por clases que no son
géneros (p. ej. "popular music" si no fuese instancia de género).

Formato verificado: algunos géneros ya no tienen etiqueta en inglés sino solo la etiqueta por
defecto ``mul`` (p. ej. Q3071, "punk rock"); se usa ``mul`` cuando falta ``en`` y sus alias
también se incluyen.
"""

import hashlib
from dataclasses import dataclass

from sonarmatch.adapters.outbound.http_base import Cache, ClienteHTTP, con_cache
from sonarmatch.domain.models import Genero

URL = "https://query.wikidata.org/sparql"
PREFIJO = "http://www.wikidata.org/entity/"
GENERO_MUSICAL = "Q188451"

CONSULTA_GENEROS = f"""
SELECT ?g ?en ?es ?mul (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases) WHERE {{
  ?g wdt:P31 wd:{GENERO_MUSICAL} .
  OPTIONAL {{ ?g rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?g rdfs:label ?es FILTER(LANG(?es) = "es") }}
  OPTIONAL {{ ?g rdfs:label ?mul FILTER(LANG(?mul) = "mul") }}
  OPTIONAL {{ ?g skos:altLabel ?alias FILTER(LANG(?alias) IN ("en", "es", "mul")) }}
}} GROUP BY ?g ?en ?es ?mul
"""

CONSULTA_ARISTAS = f"""
SELECT ?hijo ?padre WHERE {{
  ?hijo wdt:P31 wd:{GENERO_MUSICAL} .
  ?hijo wdt:P279 ?padre .
  ?padre wdt:P31 wd:{GENERO_MUSICAL} .
}}
"""


def _filas(datos: object) -> list[dict[str, str]]:
    if not isinstance(datos, dict):
        return []
    resultados = datos.get("results")
    filas = resultados.get("bindings", []) if isinstance(resultados, dict) else []
    salida = []
    for f in filas if isinstance(filas, list) else []:
        if isinstance(f, dict):
            salida.append({k: str(v.get("value", "")) for k, v in f.items() if isinstance(v, dict)})
    return salida


def _qid(uri: str) -> str:
    return uri.removeprefix(PREFIJO)


@dataclass
class ClienteWikidata:
    http: ClienteHTTP
    cache: Cache | None = None

    def _consultar(self, nombre: str, consulta: str) -> list[dict[str, str]]:
        """La clave de caché incluye un hash de la consulta: si la consulta cambia, se rehace."""
        datos = con_cache(
            self.cache,
            f"wikidata:{nombre}:{hashlib.sha256(consulta.encode()).hexdigest()[:16]}",
            lambda: self.http.get_json(
                URL, {"query": consulta}, cabeceras={"Accept": "application/sparql-results+json"}
            ),
        )
        return _filas(datos)

    def generos_musicales(self) -> list[Genero]:
        """Todos los géneros con etiquetas en/es y alias (sin padres)."""
        por_qid: dict[str, Genero] = {}
        for f in self._consultar("generos", CONSULTA_GENEROS):
            qid = _qid(f.get("g", ""))
            if not qid or qid in por_qid:
                continue
            alias = tuple(sorted({a for a in f.get("aliases", "").split("|") if a}))
            en = f.get("en") or f.get("mul", "")
            por_qid[qid] = Genero(qid, en, f.get("es", ""), alias)
        return [por_qid[q] for q in sorted(por_qid)]

    def aristas_subclase(self) -> list[tuple[str, str]]:
        """Aristas (hijo, padre) de P279 entre géneros musicales."""
        return sorted(
            {
                (_qid(f["hijo"]), _qid(f["padre"]))
                for f in self._consultar("aristas_p279", CONSULTA_ARISTAS)
                if "hijo" in f and "padre" in f
            }
        )
