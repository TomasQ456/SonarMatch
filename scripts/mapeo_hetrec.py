"""Mapeo de etiquetas reales de Last.fm (HetRec 2011) a géneros de Wikidata.

Sirve para revisar el mapeo sin API key de Last.fm: las etiquetas salen de ``tags.dat`` y
``user_taggedartists.dat`` de HetRec (formato verificado: TSV con CRLF; ``tags.dat`` está en
ISO-8859-1), ponderadas por número de usos, y se limpian y mapean con el mismo código que la
ingesta. Escribe ``reports/mapeo_muestra.csv`` (muestra de mapeos difusos para revisión manual)
y ``reports/mapeo_resumen.md``.

Uso: python scripts/mapeo_hetrec.py [--hetrec data/hetrec2011-lastfm-2k] [--min-usos 5]
"""

import argparse
import csv
import os
from collections import Counter
from pathlib import Path

from sonarmatch.adapters.outbound.http_base import ClienteHTTP
from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.adapters.outbound.wikidata_client import ClienteWikidata
from sonarmatch.domain.textos import normalizar_nombre
from sonarmatch.ingestion.genre_mapping import leer_mapeo_manual, mapear_etiquetas, muestra_difusos
from sonarmatch.ingestion.limpieza import es_musical, normalizar_etiqueta
from sonarmatch.ingestion.pipeline import escribir_muestra

AGENTE_GENERICO = "SonarMatch/0.1 (prototipo academico)"


def usos_por_etiqueta(directorio: Path) -> Counter[str]:
    with (directorio / "tags.dat").open(encoding="latin-1", newline="") as f:
        nombres = {
            fila["tagID"]: fila["tagValue"]
            for fila in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        }
    with (directorio / "artists.dat").open(encoding="utf-8", newline="") as f:
        artistas = frozenset(
            normalizar_nombre(fila["name"])
            for fila in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        )
    usos: Counter[str] = Counter()
    with (directorio / "user_taggedartists.dat").open(encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            etiqueta = normalizar_etiqueta(nombres.get(fila["tagID"], ""))
            if es_musical(etiqueta, artistas):
                usos[etiqueta] += 1
    return usos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hetrec", default="data/hetrec2011-lastfm-2k")
    parser.add_argument("--min-usos", type=int, default=5)
    parser.add_argument("--cache", default="data/cache_wikidata.db")
    parser.add_argument("--reportes", default="reports")
    args = parser.parse_args()

    usos = usos_por_etiqueta(Path(args.hetrec))
    etiquetas = {t for t, n in usos.items() if n >= args.min_usos}
    repo = RepositorioSQLite(args.cache)
    repo.crear_esquema()
    agente = os.environ.get("MB_USER_AGENT", "").strip() or AGENTE_GENERICO
    wikidata = ClienteWikidata(ClienteHTTP(1.0, agente, timeout=120), repo)
    generos = wikidata.generos_musicales()
    manual = leer_mapeo_manual(Path("data/mapeo_manual.csv"))
    mapeos = mapear_etiquetas(etiquetas, generos, manual, 90.0)

    mapeadas = {m.etiqueta for m in mapeos}
    total = sum(usos[t] for t in etiquetas)
    cubierto = sum(usos[t] for t in mapeadas)
    metodos = Counter(m.metodo for m in mapeos)
    reportes = Path(args.reportes)
    escribir_muestra(reportes / "mapeo_muestra.csv", muestra_difusos(mapeos, generos))
    sin_mapear = sorted(etiquetas - mapeadas, key=lambda t: (-usos[t], t))[:30]
    lineas = [
        "# Mapeo de etiquetas a géneros de Wikidata (etiquetas reales de HetRec 2011)",
        "",
        f"- Géneros de Wikidata (instancias de Q188451): {len(generos)}",
        f"- Etiquetas musicales con al menos {args.min_usos} usos: {len(etiquetas)}",
        f"- Etiquetas mapeadas: {len(mapeadas)} "
        f"({', '.join(f'{k}: {v}' for k, v in sorted(metodos.items()))})",
        f"- Cobertura ponderada por usos: {100 * cubierto / total:.1f} %",
        "- Muestra de mapeos difusos para revisión manual: `reports/mapeo_muestra.csv` "
        "(columna `correcto` por llenar).",
        f"- Mapeos manuales y bloqueos aplicados: {len(manual)} (`data/mapeo_manual.csv`); "
        "la revisión de la muestra anterior está en `reports/mapeo_muestra_revisada.csv`.",
        "",
        "## Etiquetas más usadas sin mapear",
        "",
        "| Etiqueta | Usos |",
        "|---|---:|",
        *(f"| {t} | {usos[t]} |" for t in sin_mapear),
        "",
    ]
    (reportes / "mapeo_resumen.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n".join(lineas[:8]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
