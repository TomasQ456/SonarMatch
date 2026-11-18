"""Interfaz de línea de comandos: ingest, evaluate, recommend.

Uso:
  python -m sonarmatch.adapters.inbound.cli ingest [--fixture] [--db data/sonarmatch.db]
  python -m sonarmatch.adapters.inbound.cli recommend "Artista:peso" ... [--db ...]
  python -m sonarmatch.adapters.inbound.cli evaluate [--dataset hetrec|csv] [--ruta ...]
  python -m sonarmatch.adapters.inbound.cli evaluate-social [--ruta ...] [--params ...]
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite, guardar_catalogo
from sonarmatch.bootstrap import crear_servicios
from sonarmatch.config import RUTA_CALIBRADOS
from sonarmatch.evaluation.protocol import evaluar_desde_cli
from sonarmatch.evaluation.social import evaluar_social_desde_cli
from sonarmatch.ingestion.fixture import RUTA_FIXTURE, catalogo_desde_json
from sonarmatch.ingestion.pipeline import ingerir_desde_entorno
from sonarmatch.ports.inbound import EntradaArtista, ErrorEntradaInvalida, SolicitudRecomendacion

DB_POR_DEFECTO = "data/sonarmatch.db"
log = logging.getLogger("sonarmatch")


def cmd_ingest(args: argparse.Namespace) -> int:
    ruta = Path(args.db)
    if args.fixture:
        if ruta.exists():
            ruta.unlink()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        guardar_catalogo(RepositorioSQLite(ruta), catalogo_desde_json(RUTA_FIXTURE))
        print(f"Catálogo de demostración cargado en {ruta}")
        return 0
    return ingerir_desde_entorno(ruta, objetivo=args.objetivo, musicbrainz=not args.sin_musicbrainz)


def _parsear_entrada(texto: str) -> EntradaArtista:
    nombre, _, peso = texto.rpartition(":")
    if not nombre:
        return EntradaArtista(texto, 3.0)
    try:
        return EntradaArtista(nombre, float(peso))
    except ValueError:
        return EntradaArtista(texto, 3.0)


def cmd_recommend(args: argparse.Namespace) -> int:
    try:
        servicios = crear_servicios(args.db)
        solicitud = SolicitudRecomendacion(tuple(_parsear_entrada(a) for a in args.artistas))
        resp = servicios.recomendar.recomendar(solicitud)
    except (FileNotFoundError, ErrorEntradaInvalida) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    if resp.artistas_no_encontrados:
        print("No encontrados:", ", ".join(resp.artistas_no_encontrados))
    for k, r in enumerate(resp.recomendaciones, 1):
        print(f"{k:2d}. {r.nombre}  ({r.puntaje:.3f}, {r.estrategia})")
        print(f"    {r.explicacion}")
        for paso in r.cadena_inferencia:
            print(f"      · {paso}")
    print(f"Latencia: {resp.latencia_ms:.0f} ms")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    ruta = Path(args.ruta or ("data/hetrec2011-lastfm-2k" if args.dataset == "hetrec" else ""))
    return evaluar_desde_cli(
        Path(args.db),
        args.dataset,
        ruta,
        salida=Path(args.salida),
        semilla=args.semilla,
        paso=args.paso,
        guardar=not args.sin_guardar_parametros,
        max_validacion=args.max_validacion,
    )


def cmd_evaluate_social(args: argparse.Namespace) -> int:
    return evaluar_social_desde_cli(
        Path(args.db),
        Path(args.ruta),
        Path(args.params),
        salida=Path(args.salida),
        semilla=args.semilla,
        guardar=not args.sin_guardar_parametros,
    )


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sonarmatch", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)
    db = os.environ.get("SONARMATCH_DB", DB_POR_DEFECTO)

    p_ing = sub.add_parser("ingest", help="pobla la base SQLite")
    p_ing.add_argument("--db", default=db)
    p_ing.add_argument("--fixture", action="store_true", help="carga el catálogo sintético")
    p_ing.add_argument("--objetivo", type=int, default=5000, help="artistas a alcanzar")
    p_ing.add_argument("--sin-musicbrainz", action="store_true", help="omite país y año")
    p_ing.set_defaults(func=cmd_ingest)

    p_rec = sub.add_parser("recommend", help="recomienda desde la terminal")
    p_rec.add_argument("artistas", nargs="+", help='"Artista:peso" (peso 1..5)')
    p_rec.add_argument("--db", default=db)
    p_rec.set_defaults(func=cmd_recommend)

    p_ev = sub.add_parser("evaluate", help="evaluación offline y calibración")
    p_ev.add_argument("--db", default=db)
    p_ev.add_argument("--dataset", choices=["hetrec", "csv"], default="hetrec")
    p_ev.add_argument("--ruta", help="carpeta de HetRec o archivo CSV user_id,artist_name,peso")
    p_ev.add_argument("--salida", default="reports")
    p_ev.add_argument("--semilla", type=int, default=42)
    p_ev.add_argument("--paso", type=float, default=0.1, help="paso del símplex de a, b, c, d")
    p_ev.add_argument(
        "--max-validacion", type=int, help="usa solo N usuarios de validación en el grid"
    )
    p_ev.add_argument(
        "--sin-guardar-parametros", action="store_true", help="no escribe parametros_calibrados"
    )
    p_ev.set_defaults(func=cmd_evaluate)

    p_so = sub.add_parser("evaluate-social", help="evaluación de la dimensión social (HetRec)")
    p_so.add_argument("--db", default=db)
    p_so.add_argument("--ruta", default="data/hetrec2011-lastfm-2k", help="carpeta de HetRec")
    p_so.add_argument(
        "--params", default=str(RUTA_CALIBRADOS), help="parámetros base (se guarda β aquí)"
    )
    p_so.add_argument("--salida", default="reports")
    p_so.add_argument("--semilla", type=int, default=42)
    p_so.add_argument(
        "--sin-guardar-parametros", action="store_true", help="no escribe β en --params"
    )
    p_so.set_defaults(func=cmd_evaluate_social)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = construir_parser().parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
