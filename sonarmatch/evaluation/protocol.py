"""Protocolo de evaluación offline.

1. Usuarios → 70 % validación / 30 % prueba (semilla fija).
2. Por usuario se oculta el 20 % de sus artistas emparejados (mínimo 2); se recomienda con el
   resto (como mucho los 20 de mayor peso, el límite de la interfaz) y se mide sobre los ocultos.
3. Grid search de a, b, c, d (símplex con paso configurable y los cuatro pesos > 0, para que
   cada ablación quite un término que de verdad estaba activo), λ y τ solo en validación,
   optimizando P@10 (desempate: R@10; ante empate total gana la configuración evaluada antes,
   y la de config.py va primero).
4. En prueba: línea base de popularidad, sistema calibrado y ablaciones.

Decisiones:
- Los hiperparámetros del grid se fijan en ``ConfigMotor`` (como los calibrados), no como
  parámetros del usuario, porque los ajustes de las reglas solo se aplican sin parámetros
  explícitos; así se calibra el sistema tal como funciona en la app.
- La línea base de popularidad recomienda los 10 artistas con más oyentes que no están en la
  entrada (sin mirar etiquetas), que es la referencia habitual de "lo más popular".
- Las columnas de PPR no dependen de los parámetros del grid: se calculan una vez por caso.
- Latencia: tiempo de ``recomendar`` completo (PPR + reglas + explicaciones) por consulta;
  contrafactual: tiempo de calcular los efectos de la primera recomendación desde cero.
"""

import csv
import itertools
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.config import RUTA_CALIBRADOS, ConfigMotor
from sonarmatch.domain.counterfactual import Contrafactuales
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import TERMINOS, EntradaPerfil, PerfilUsuario
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.domain.razonamiento import OpcionesMotor
from sonarmatch.domain.scoring import Matriz
from sonarmatch.evaluation import metrics
from sonarmatch.evaluation.datasets import PerfilEvaluacion, cargar_perfiles

log = logging.getLogger(__name__)

FRACCION_VALIDACION = 0.7
FRACCION_OCULTA = 0.2
MINIMO_OCULTOS = 2
MAXIMO_ENTRADA = 20
K = 10
MUESTRA_MINIMA = 30  # por debajo, el reporte advierte que no es concluyente
REGLAS = ("R1", "R2", "R3", "R4", "R5", "R6")
RESPALDOS = ("contenido", "popularidad")
LAMBDAS = (0.5, 0.7, 0.9)
TAUS = (0.0, 0.05, 0.1)

ABLACIONES: dict[str, OpcionesMotor] = {
    "sin S_tags": OpcionesMotor(terminos=frozenset(TERMINOS) - {"s_tags"}),
    "sin S_grafo": OpcionesMotor(terminos=frozenset(TERMINOS) - {"s_grafo"}),
    "sin P_nov": OpcionesMotor(terminos=frozenset(TERMINOS) - {"p_nov"}),
    "sin S_onto": OpcionesMotor(terminos=frozenset(TERMINOS) - {"s_onto"}),
    "sin reglas": OpcionesMotor(usar_reglas=False),
    "sin MMR": OpcionesMotor(usar_mmr=False),
    "sin respaldo": OpcionesMotor(usar_respaldo=False),
}


@dataclass
class Caso:
    usuario: str
    entrada: tuple[EntradaPerfil, ...]
    ocultos: frozenset[int]
    perfil: PerfilUsuario
    ppr: Matriz


@dataclass
class Metricas:
    sistema: str
    usuarios: int
    p10: float
    r10: float
    novedad: float
    ils: float
    cobertura: float
    respaldo: dict[str, float] = field(default_factory=dict)
    reglas: dict[str, float] = field(default_factory=dict)
    latencia_p50_ms: float | None = None
    latencia_p95_ms: float | None = None
    contrafactual_p95_ms: float | None = None


@dataclass
class ResultadoEvaluacion:
    dataset: str
    usuarios_validacion: int
    usuarios_prueba: int
    config: ConfigMotor
    configuraciones_probadas: int
    p10_validacion: float
    cobertura_mapeo: float
    filas: list[Metricas]


# ---------------------------------------------------------------- preparación
def dividir_usuarios(
    perfiles: Sequence[PerfilEvaluacion], semilla: int
) -> tuple[list[PerfilEvaluacion], list[PerfilEvaluacion]]:
    rng = np.random.default_rng(semilla)
    orden = rng.permutation(len(perfiles))
    corte = round(FRACCION_VALIDACION * len(perfiles))
    return [perfiles[i] for i in orden[:corte]], [perfiles[i] for i in orden[corte:]]


def ocultar(
    perfil: PerfilEvaluacion, semilla: int
) -> tuple[list[tuple[int, float]], frozenset[int]]:
    """Devuelve (entrada visible, ocultos). La semilla depende del usuario, no del split."""
    rng = np.random.default_rng([semilla, *perfil.usuario.encode()])
    n = len(perfil.artistas)
    k = max(MINIMO_OCULTOS, round(FRACCION_OCULTA * n))
    ocultos_pos = set(rng.choice(n, size=k, replace=False).tolist())
    visibles = [a for j, a in enumerate(perfil.artistas) if j not in ocultos_pos]
    visibles = sorted(visibles, key=lambda x: (-x[1], x[0]))[:MAXIMO_ENTRADA]
    return visibles, frozenset(perfil.artistas[j][0] for j in ocultos_pos)


def preparar_casos(
    motor: MotorRecomendacion, perfiles: Sequence[PerfilEvaluacion], semilla: int
) -> list[Caso]:
    casos = []
    for p in perfiles:
        visibles, ocultos = ocultar(p, semilla)
        entrada = tuple(EntradaPerfil(motor.indice.nombre(i), w) for i, w in visibles)
        perfil = motor.perfil(entrada)
        casos.append(Caso(p.usuario, entrada, ocultos, perfil, motor.ppr(perfil)))
    return casos


# ---------------------------------------------------------------- medición
def media(xs: Sequence[float]) -> float:
    return float(np.mean(xs)) if xs else 0.0


@dataclass
class _Acumulador:
    listas: list[list[int]] = field(default_factory=list)
    p10: list[float] = field(default_factory=list)
    r10: list[float] = field(default_factory=list)
    respaldo: Counter[str] = field(default_factory=Counter)
    reglas: Counter[str] = field(default_factory=Counter)
    latencias: list[float] = field(default_factory=list)
    contrafactuales: list[float] = field(default_factory=list)

    def agregar(self, recs: list[int], ocultos: frozenset[int]) -> None:
        self.listas.append(recs)
        self.p10.append(metrics.precision_en_k(recs, ocultos, K))
        self.r10.append(metrics.recall_en_k(recs, ocultos, K))

    def metricas(self, sistema: str, indice: IndiceCatalogo, pct: np.ndarray) -> Metricas:
        n = len(self.listas)

        def pct_de(c: Counter[str], claves: Sequence[str]) -> dict[str, float]:
            return {k: c[k] / n if n else 0.0 for k in claves}

        return Metricas(
            sistema=sistema,
            usuarios=n,
            p10=media(self.p10),
            r10=media(self.r10),
            novedad=media([metrics.novedad(lst, pct) for lst in self.listas]),
            ils=media([metrics.ils(lst, indice.tfidf) for lst in self.listas]),
            cobertura=metrics.cobertura_catalogo(self.listas, indice.n),
            respaldo=pct_de(self.respaldo, RESPALDOS),
            reglas=pct_de(self.reglas, REGLAS),
            latencia_p50_ms=metrics.percentil(self.latencias, 50) if self.latencias else None,
            latencia_p95_ms=metrics.percentil(self.latencias, 95) if self.latencias else None,
            contrafactual_p95_ms=(
                metrics.percentil(self.contrafactuales, 95) if self.contrafactuales else None
            ),
        )


def evaluar(
    motor: MotorRecomendacion,
    casos: Sequence[Caso],
    sistema: str = "sistema completo",
    opciones: OpcionesMotor | None = None,
    medir_tiempos: bool = False,
) -> Metricas:
    acc = _Acumulador()
    for caso in casos:
        if medir_tiempos:
            inicio = time.perf_counter()
            res = motor.recomendar(motor.perfil(caso.entrada), None, opciones)
            acc.latencias.append((time.perf_counter() - inicio) * 1000)
        else:
            res = motor.recomendar(caso.perfil, None, opciones, ppr=caso.ppr, explicar=False)
        recs = [r.indice for r in res.recomendaciones]
        acc.agregar(recs, caso.ocultos)
        acc.respaldo.update({e for e, _ in res.activaciones})
        acc.reglas.update(res.reglas_disparadas())
        if medir_tiempos and recs:
            inicio = time.perf_counter()
            Contrafactuales(motor, res, None, opciones).efectos(recs[0])
            acc.contrafactuales.append((time.perf_counter() - inicio) * 1000)
    return acc.metricas(
        sistema, motor.indice, metrics.percentiles_popularidad(motor.indice.oyentes)
    )


def evaluar_popularidad(indice: IndiceCatalogo, casos: Sequence[Caso]) -> Metricas:
    orden = sorted(range(indice.n), key=lambda i: (-indice.oyentes[i], i))
    acc = _Acumulador()
    for caso in casos:
        entrada = set(caso.perfil.indices)
        acc.agregar([i for i in orden if i not in entrada][:K], caso.ocultos)
    return acc.metricas(
        "línea base: popularidad", indice, metrics.percentiles_popularidad(indice.oyentes)
    )


# ---------------------------------------------------------------- grid search
def simplex(paso: float) -> Iterator[tuple[float, float, float, float]]:
    """Combinaciones (a, b, c, d) > 0 con a + b + c + d = 1 en múltiplos de ``paso``."""
    m = round(1 / paso)
    for a, b, c in itertools.product(range(1, m + 1), repeat=3):
        d = m - a - b - c
        if d > 0:
            yield a / m, b / m, c / m, d / m


def grilla(base: ConfigMotor, paso: float) -> Iterator[ConfigMotor]:
    yield base
    for (a, b, c, d), lam, tau in itertools.product(simplex(paso), LAMBDAS, TAUS):
        yield replace(base, a=a, b=b, c=c, d=d, lambda_mmr=lam, tau=tau)


def buscar_parametros(
    indice: IndiceCatalogo,
    base: ConfigMotor,
    casos: Sequence[Caso],
    paso: float = 0.1,
    progreso: Callable[[int], None] | None = None,
) -> tuple[ConfigMotor, float, int]:
    mejor, clave_mejor, probadas = base, (-1.0, -1.0), 0
    for cfg in grilla(base, paso):
        m = evaluar(MotorRecomendacion(indice, cfg), casos)
        probadas += 1
        if (m.p10, m.r10) > clave_mejor:
            mejor, clave_mejor = cfg, (m.p10, m.r10)
        if progreso is not None:
            progreso(probadas)
    return mejor, clave_mejor[0], probadas


# ---------------------------------------------------------------- orquestación
def cobertura_mapeo(indice: IndiceCatalogo) -> float:
    total = cubierto = 0.0
    for a in indice.artistas:
        for t, w in a.etiquetas:
            total += w
            cubierto += w if t in indice.mapeo else 0.0
    return cubierto / total if total else 0.0


def ejecutar_protocolo(
    indice: IndiceCatalogo,
    perfiles: Sequence[PerfilEvaluacion],
    base: ConfigMotor,
    dataset: str,
    semilla: int = 42,
    paso: float = 0.1,
    max_validacion: int | None = None,
) -> ResultadoEvaluacion:
    if len(perfiles) < 2:  # noqa: PLR2004 — hacen falta usuarios en validación y en prueba
        raise ValueError(
            f"Solo {len(perfiles)} usuario(s) emparejado(s) con el catálogo: no se puede evaluar."
        )
    val, prueba = dividir_usuarios(perfiles, semilla)
    motor_base = MotorRecomendacion(indice, base)
    casos_val = preparar_casos(motor_base, val, semilla)
    casos_prueba = preparar_casos(motor_base, prueba, semilla)
    log.info("validación: %d usuarios; prueba: %d", len(val), len(prueba))
    mejor, p10_val, probadas = buscar_parametros(
        indice,
        base,
        casos_val[:max_validacion],
        paso,
        lambda k: log.info("grid: %d configuraciones", k) if k % 50 == 0 else None,
    )
    motor = MotorRecomendacion(indice, mejor)
    filas = [
        evaluar_popularidad(indice, casos_prueba),
        evaluar(motor, casos_prueba, "sistema completo", medir_tiempos=True),
    ]
    filas += [evaluar(motor, casos_prueba, nombre, op) for nombre, op in ABLACIONES.items()]
    return ResultadoEvaluacion(
        dataset, len(val), len(prueba), mejor, probadas, p10_val, cobertura_mapeo(indice), filas
    )


# ---------------------------------------------------------------- reportes
COLUMNAS = [
    "sistema", "usuarios", "p10", "r10", "novedad", "ils", "cobertura",
    *(f"respaldo_{r}" for r in RESPALDOS), *(f"regla_{r}" for r in REGLAS),
    "latencia_p50_ms", "latencia_p95_ms", "contrafactual_p95_ms",
]  # fmt: skip


def _fila(m: Metricas) -> dict[str, object]:
    fila: dict[str, object] = {
        "sistema": m.sistema,
        "usuarios": m.usuarios,
        "p10": round(m.p10, 4),
        "r10": round(m.r10, 4),
        "novedad": round(m.novedad, 4),
        "ils": round(m.ils, 4),
        "cobertura": round(m.cobertura, 4),
    }
    fila.update({f"respaldo_{k}": round(v, 4) for k, v in m.respaldo.items()})
    fila.update({f"regla_{k}": round(v, 4) for k, v in m.reglas.items()})
    for k in ("latencia_p50_ms", "latencia_p95_ms", "contrafactual_p95_ms"):
        v = getattr(m, k)
        fila[k] = "" if v is None else round(v, 1)
    return fila


def escribir_reportes(res: ResultadoEvaluacion, directorio: Path) -> tuple[Path, Path]:
    directorio.mkdir(parents=True, exist_ok=True)
    ruta_csv, ruta_md = directorio / "resultados.csv", directorio / "resultados.md"
    with ruta_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(_fila(m) for m in res.filas)
    ruta_md.write_text(markdown(res), encoding="utf-8")
    return ruta_csv, ruta_md


def _pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def markdown(res: ResultadoEvaluacion) -> str:
    c = res.config
    completo = next(m for m in res.filas if m.sistema == "sistema completo")
    lineas = [
        "# Resultados de la evaluación offline",
        "",
        f"- Dataset: {res.dataset}",
        f"- Usuarios: {res.usuarios_validacion} en validación, {res.usuarios_prueba} en prueba "
        f"(20 % de artistas ocultos por usuario, mínimo {MINIMO_OCULTOS}).",
        f"- Grid search en validación: {res.configuraciones_probadas} configuraciones; "
        f"mejor P@10 en validación = {res.p10_validacion:.3f}.",
        f"- Parámetros elegidos: a = {c.a:.2f}, b = {c.b:.2f}, c = {c.c:.2f}, d = {c.d:.2f}, "
        f"λ = {c.lambda_mmr:.2f}, τ = {c.tau:.2f}.",
        f"- Cobertura del mapeo de etiquetas (por peso): {_pct(res.cobertura_mapeo)}.",
    ]
    if res.usuarios_prueba < MUESTRA_MINIMA:
        lineas.append(
            f"- **Atención:** solo {res.usuarios_prueba} usuarios de prueba; las diferencias "
            "entre sistemas no son concluyentes."
        )
    lineas += [
        "",
        "## Comparación en prueba",
        "",
        "| Sistema | P@10 | R@10 | Novedad ↓ | ILS | Cobertura |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lineas += [
        f"| {m.sistema} | {m.p10:.3f} | {m.r10:.3f} | {m.novedad:.3f} | {m.ils:.3f} | "
        f"{_pct(m.cobertura)} |"
        for m in res.filas
    ]
    lineas += [
        "",
        "Novedad: percentil medio de oyentes de lo recomendado (menor = más nicho). "
        "ILS: coseno TF-IDF medio entre pares de la lista. Cobertura: fracción del catálogo "
        "recomendada al menos una vez.",
        "",
        "## Sistema completo: respaldos, reglas y latencia",
        "",
        "| Indicador | Valor |",
        "|---|---:|",
    ]
    lineas += [f"| Activación del respaldo {k} | {_pct(v)} |" for k, v in completo.respaldo.items()]
    lineas += [
        f"| Consultas en que se dispara {k} | {_pct(v)} |" for k, v in completo.reglas.items()
    ]
    lineas += [
        f"| Latencia p50 de la recomendación | {completo.latencia_p50_ms or 0:.0f} ms |",
        f"| Latencia p95 de la recomendación | {completo.latencia_p95_ms or 0:.0f} ms |",
        f"| Latencia p95 del contrafactual | {completo.contrafactual_p95_ms or 0:.0f} ms |",
        "",
    ]
    return "\n".join(lineas)


def guardar_parametros(config: ConfigMotor, ruta: Path = RUTA_CALIBRADOS) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    config.a_json(ruta)


def evaluar_desde_cli(
    db: Path,
    dataset: str,
    ruta: Path,
    salida: Path = Path("reports"),
    semilla: int = 42,
    paso: float = 0.1,
    guardar: bool = True,
    max_validacion: int | None = None,
) -> int:
    """Carga el catálogo de SQLite y los perfiles, ejecuta el protocolo y escribe reportes."""
    if not db.exists():
        log.error("No existe la base %s; ejecuta primero la ingesta.", db)
        return 2
    if not ruta.exists():
        log.error("No existe el dataset %s (ver data/README.md).", ruta)
        return 2
    indice = IndiceCatalogo.construir(RepositorioSQLite(db).cargar_catalogo())
    perfiles = cargar_perfiles(dataset, ruta, indice.por_nombre)
    log.info("%d usuarios con al menos 8 artistas emparejados", len(perfiles))
    descripcion = f"{dataset} ({ruta}) sobre {db} ({indice.n} artistas)"
    base = ConfigMotor()  # siempre desde config.py: reproducible aunque ya haya calibrados
    try:
        res = ejecutar_protocolo(indice, perfiles, base, descripcion, semilla, paso, max_validacion)
    except ValueError as error:
        log.error("%s", error)
        return 2
    ruta_csv, ruta_md = escribir_reportes(res, salida)
    if guardar:
        guardar_parametros(res.config, salida / RUTA_CALIBRADOS.name)
    print(f"Reportes en {ruta_csv} y {ruta_md}")
    print(markdown(res))
    return 0
