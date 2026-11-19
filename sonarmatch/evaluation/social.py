"""Evaluación de la dimensión social sobre HetRec 2011 (``user_friends.dat``).

Hipótesis: los gustos de los amigos ayudan a acotar los del usuario. Se mide sin forzar el
resultado. Si no mejora, el reporte lo dice.

Protocolo:
1. Subconjunto social: usuarios evaluables (≥ 8 artistas emparejados) con al menos un amigo
   en HetRec. Mismo esquema 70 % validación / 30 % prueba y misma semilla que el protocolo base.
2. Por usuario se ocultan los mismos artistas que en el protocolo base (``ocultar``). Sus
   semillas propias son solo las visibles, así que los ocultos nunca entran como semillas
   propias.
3. Amigos: todos se consideran con consentimiento. Su perfil se construye igual que el del
   usuario, con sus artistas emparejados y escalados a 1..5, los 20 de mayor peso. A los amigos
   no se les quita nada, porque su información es legítima, aunque contenga artistas ocultos del
   usuario: eso es precisamente lo que la hipótesis pone a prueba.
4. β se calibra en validación sobre ``BETAS`` (gana el mayor P@10; desempate R@10 y luego el
   que va primero, con β = 0 primero). El resto de los hiperparámetros sale de la configuración
   base (los calibrados si existen).
5. En prueba: β = 0 (sistema actual), β calibrado y β calibrado sin R7. Se reportan P@10,
   R@10, novedad e ILS, también por cantidad de amigos activos (1–2, 3–5, más de 5). La
   diferencia de P@10 se acompaña de un intervalo bootstrap pareado del 95 %.

Indicadores para la discusión: homofilia (fracción de los artistas ocultos de un usuario que
aparecen en el perfil de algún amigo) y dispersión del grafo social (amigos activos por usuario).
"""

import csv
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from sonarmatch.adapters.outbound.sqlite_repository import RepositorioSQLite
from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import ContextoSocial, EntradaPerfil, PerfilAmigo
from sonarmatch.domain.pipeline import MotorRecomendacion
from sonarmatch.domain.razonamiento import OpcionesMotor
from sonarmatch.evaluation import metrics
from sonarmatch.evaluation.datasets import (
    PerfilEvaluacion,
    emparejar,
    leer_amigos_hetrec,
    leer_hetrec,
)
from sonarmatch.evaluation.protocol import (
    MAXIMO_ENTRADA,
    MUESTRA_MINIMA,
    Caso,
    dividir_usuarios,
    media,
    ocultar,
)

log = logging.getLogger(__name__)

BETAS = (0.0, 0.1, 0.25, 0.5, 0.75)
GRUPOS = (("1–2", 1, 2), ("3–5", 3, 5), ("más de 5", 6, 10**9))
SIN_R7 = OpcionesMotor(sin_reglas=frozenset({"R7"}))
REMUESTREOS = 2000
UMBRAL_HOMOFILIA = 0.25  # por debajo, los amigos casi no escuchan lo que el usuario oculta
K = 10


@dataclass
class CasoSocial(Caso):
    amigos: tuple[PerfilAmigo, ...] = ()
    homofilia: float = 0.0  # fracción de ocultos presentes en algún amigo

    def social(self, beta: float) -> ContextoSocial:
        return ContextoSocial(self.amigos, beta)


@dataclass
class FilaSocial:
    sistema: str
    grupo: str
    usuarios: int
    p10: float
    r10: float
    novedad: float
    ils: float


@dataclass
class ResultadoSocial:
    dataset: str
    usuarios_validacion: int
    usuarios_prueba: int
    beta: float
    p10_por_beta: dict[float, float]
    filas: list[FilaSocial]
    diferencia_p10: float  # β calibrado − β = 0, en prueba
    ic_diferencia: tuple[float, float]
    homofilia: float
    amigos_activos_mediana: float
    sin_amigos_activos: int
    config: ConfigMotor = field(default_factory=ConfigMotor)


# ---------------------------------------------------------------- preparación
def perfiles_de_amigos(
    filas: Sequence[tuple[str, str, float]], por_nombre: Mapping[str, int]
) -> dict[str, PerfilEvaluacion]:
    """Perfil (1..5) de cada usuario con al menos un artista emparejado, para usarlo de amigo."""
    return {p.usuario: p for p in emparejar(filas, por_nombre, minimo=1, escalar=True)}


def preparar_casos_sociales(
    motor: MotorRecomendacion,
    usuarios: Sequence[PerfilEvaluacion],
    amistades: Mapping[str, frozenset[str]],
    como_amigo: Mapping[str, PerfilEvaluacion],
    semilla: int,
) -> list[CasoSocial]:
    casos = []
    for p in usuarios:
        visibles, ocultos = ocultar(p, semilla)
        entrada = tuple(EntradaPerfil(motor.indice.nombre(i), w) for i, w in visibles)
        perfil = motor.perfil(entrada)
        amigos = []
        de_amigos: set[int] = set()
        for apodo in sorted(amistades.get(p.usuario, frozenset())):
            datos = como_amigo.get(apodo)
            if datos is None:
                continue
            top = sorted(datos.artistas, key=lambda x: (-x[1], x[0]))[:MAXIMO_ENTRADA]
            entradas = [EntradaPerfil(motor.indice.nombre(i), w) for i, w in top]
            amigos.append(PerfilAmigo(apodo, motor.perfil(entradas)))
            de_amigos.update(i for i, _ in top)
        casos.append(
            CasoSocial(
                p.usuario,
                entrada,
                ocultos,
                perfil,
                motor.ppr(perfil),
                tuple(amigos),
                len(ocultos & de_amigos) / len(ocultos) if ocultos else 0.0,
            )
        )
    return casos


# ---------------------------------------------------------------- medición
def recomendar_casos(
    motor: MotorRecomendacion,
    casos: Sequence[CasoSocial],
    beta: float,
    opciones: OpcionesMotor | None = None,
) -> list[list[int]]:
    listas = []
    for c in casos:
        res = motor.recomendar(
            c.perfil, None, opciones, ppr=c.ppr, explicar=False, social=c.social(beta)
        )
        listas.append([r.indice for r in res.recomendaciones])
    return listas


def fila(
    sistema: str,
    grupo: str,
    casos: Sequence[CasoSocial],
    listas: Sequence[list[int]],
    indice: IndiceCatalogo,
) -> FilaSocial:
    pct = metrics.percentiles_popularidad(indice.oyentes)
    return FilaSocial(
        sistema,
        grupo,
        len(casos),
        media(
            [
                metrics.precision_en_k(lst, c.ocultos, K)
                for c, lst in zip(casos, listas, strict=True)
            ]
        ),
        media(
            [metrics.recall_en_k(lst, c.ocultos, K) for c, lst in zip(casos, listas, strict=True)]
        ),
        media([metrics.novedad(lst, pct) for lst in listas]),
        media([metrics.ils(lst, indice.tfidf) for lst in listas]),
    )


def p10_por_caso(casos: Sequence[CasoSocial], listas: Sequence[list[int]]) -> np.ndarray:
    return np.array(
        [metrics.precision_en_k(lst, c.ocultos, K) for c, lst in zip(casos, listas, strict=True)]
    )


def bootstrap_pareado(
    diferencias: np.ndarray, semilla: int, remuestreos: int = REMUESTREOS
) -> tuple[float, float]:
    """IC del 95 % de la media de las diferencias por usuario (bootstrap percentil)."""
    if diferencias.size == 0:
        return 0.0, 0.0
    rng = np.random.default_rng(semilla)
    medias = rng.choice(diferencias, size=(remuestreos, diferencias.size)).mean(axis=1)
    return float(np.percentile(medias, 2.5)), float(np.percentile(medias, 97.5))


def calibrar_beta(
    motor: MotorRecomendacion, casos: Sequence[CasoSocial]
) -> tuple[float, dict[float, float]]:
    puntajes: dict[float, float] = {}
    mejor, clave = BETAS[0], (-1.0, -1.0)
    for beta in BETAS:
        f = fila("", "", casos, recomendar_casos(motor, casos, beta), motor.indice)
        puntajes[beta] = f.p10
        if (f.p10, f.r10) > clave:
            mejor, clave = beta, (f.p10, f.r10)
    return mejor, puntajes


def ejecutar_social(
    indice: IndiceCatalogo,
    usuarios: Sequence[PerfilEvaluacion],
    amistades: Mapping[str, frozenset[str]],
    como_amigo: Mapping[str, PerfilEvaluacion],
    base: ConfigMotor,
    dataset: str,
    semilla: int = 42,
) -> ResultadoSocial:
    con_amigos = [p for p in usuarios if amistades.get(p.usuario)]
    if len(con_amigos) < 2:  # noqa: PLR2004 — hacen falta usuarios en validación y en prueba
        raise ValueError(f"Solo {len(con_amigos)} usuario(s) con amigos: no se puede evaluar.")
    val, prueba = dividir_usuarios(con_amigos, semilla)
    motor = MotorRecomendacion(indice, base)
    casos_val = preparar_casos_sociales(motor, val, amistades, como_amigo, semilla)
    casos = preparar_casos_sociales(motor, prueba, amistades, como_amigo, semilla)
    beta, por_beta = calibrar_beta(motor, casos_val)
    log.info("β calibrado en validación: %.2f (%s)", beta, por_beta)
    sistemas = {
        "actual (β = 0)": recomendar_casos(motor, casos, 0.0),
        f"con amigos (β = {beta:.2f})": recomendar_casos(motor, casos, beta),
        f"con amigos sin R7 (β = {beta:.2f})": recomendar_casos(motor, casos, beta, SIN_R7),
    }
    activos = [sum(1 for a in c.amigos if a.perfil.indices) for c in casos]
    filas = [fila(s, "todos", casos, listas, indice) for s, listas in sistemas.items()]
    for nombre, lo, hi in GRUPOS:
        sel = [k for k, n in enumerate(activos) if lo <= n <= hi]
        for s, listas in sistemas.items():
            filas.append(fila(s, nombre, [casos[k] for k in sel], [listas[k] for k in sel], indice))
    actual, social = (p10_por_caso(casos, lst) for lst in list(sistemas.values())[:2])
    diferencias = social - actual
    return ResultadoSocial(
        dataset=dataset,
        usuarios_validacion=len(val),
        usuarios_prueba=len(prueba),
        beta=beta,
        p10_por_beta=por_beta,
        filas=filas,
        diferencia_p10=float(diferencias.mean()) if diferencias.size else 0.0,
        ic_diferencia=bootstrap_pareado(diferencias, semilla),
        homofilia=media([c.homofilia for c in casos]),
        amigos_activos_mediana=float(np.median(activos)) if activos else 0.0,
        sin_amigos_activos=sum(1 for n in activos if n == 0),
        config=replace(base, beta=beta),
    )


# ---------------------------------------------------------------- reportes
def conclusion(res: ResultadoSocial) -> str:
    lo, hi = res.ic_diferencia
    d = res.diferencia_p10
    if res.beta == 0:
        return (
            "**No mejora.** La calibración en validación eligió β = 0: ningún peso de los amigos "
            "superó al sistema actual."
        )
    if mejora(res):
        return (
            f"**Mejora.** Con β = {res.beta:.2f}, P@10 sube {d:+.3f} en prueba "
            f"(IC 95 % de la diferencia pareada: [{lo:+.3f}, {hi:+.3f}], que no incluye 0)."
        )
    if hi < 0:
        return (
            f"**Empeora.** Con β = {res.beta:.2f}, P@10 cambia {d:+.3f} en prueba "
            f"(IC 95 %: [{lo:+.3f}, {hi:+.3f}])."
        )
    return (
        f"**No hay mejora demostrable.** Con β = {res.beta:.2f}, P@10 cambia {d:+.3f} en prueba, "
        f"pero el IC 95 % de la diferencia pareada ([{lo:+.3f}, {hi:+.3f}]) incluye 0."
    )


def mejora(res: ResultadoSocial) -> bool:
    return res.beta > 0 and res.ic_diferencia[0] > 0


def discusion(res: ResultadoSocial) -> list[str]:
    """Interpretación de homofilia y dispersión, con o sin mejora (la especificación lo pide)."""
    h = 100 * res.homofilia
    lineas = [
        "- **Homofilia frente a influencia.** HetRec es observacional: si los amigos ayudan, no "
        "se puede saber si es porque se parecen (homofilia) o porque se influyen (influencia). "
        "El sistema solo aprovecha la correlación, y para recomendar eso basta.",
    ]
    if mejora(res):
        lineas.append(
            f"- El {h:.1f} % de los artistas ocultos está en el perfil de algún amigo: los amigos "
            "aportan artistas que el grafo de similitud no alcanzaba desde el perfil propio."
        )
    elif res.homofilia < UMBRAL_HOMOFILIA:
        lineas.append(
            f"- Solo el {h:.1f} % de los artistas ocultos está en el perfil de algún amigo: los "
            "amigos escuchan sobre todo otras cosas, y sus semillas diluyen el perfil propio "
            "en vez de acotarlo."
        )
    else:
        lineas.append(
            f"- El {h:.1f} % de los artistas ocultos sí está en el perfil de algún amigo, pero no "
            "mejora: el grafo de similitud ya llega a esos artistas desde el perfil propio, así "
            "que la señal de los amigos resulta redundante."
        )
    dispersion = (
        f"- **Dispersión del grafo social.** Mediana de {res.amigos_activos_mediana:.0f} amigos "
        "activos (con artistas en el catálogo) por usuario de prueba"
    )
    if res.sin_amigos_activos:
        dispersion += (
            f"; {res.sin_amigos_activos} no tienen ninguno, y para ellos β no cambia nada, lo que "
            "acerca la diferencia media a 0."
        )
    else:
        dispersion += "; todos tienen al menos uno, así que β actúa sobre cada usuario."
    lineas.append(dispersion)
    return lineas


def markdown_social(res: ResultadoSocial) -> str:
    lineas = [
        "# Evaluación de la dimensión social",
        "",
        f"- Dataset: {res.dataset}",
        f"- Usuarios con al menos un amigo: {res.usuarios_validacion} en validación, "
        f"{res.usuarios_prueba} en prueba (mismo split 70/30 y semilla que el protocolo base). "
        "Todos los amigos se consideran con consentimiento.",
        "- β calibrado en validación: "
        + ", ".join(f"β = {b:.2f} → P@10 {p:.3f}" for b, p in res.p10_por_beta.items())
        + f". Elegido: **β = {res.beta:.2f}**.",
        f"- Amigos activos (con artistas en el catálogo) por usuario de prueba: mediana "
        f"{res.amigos_activos_mediana:.0f}; {res.sin_amigos_activos} usuarios sin ninguno.",
        f"- Homofilia: en promedio, el {100 * res.homofilia:.1f} % de los artistas ocultos de un "
        "usuario aparece en el perfil de algún amigo.",
    ]
    if res.usuarios_prueba < MUESTRA_MINIMA:
        lineas.append(
            f"- **Atención:** solo {res.usuarios_prueba} usuarios de prueba; no es concluyente."
        )
    lineas += ["", "## Conclusión", "", conclusion(res), "", "## Discusión", "", *discusion(res)]
    lineas += ["", "## Resultados en prueba", ""]
    lineas += [
        "| Amigos activos | Sistema | Usuarios | P@10 | R@10 | Novedad ↓ | ILS |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    lineas += [
        f"| {f.grupo} | {f.sistema} | {f.usuarios} | {f.p10:.3f} | {f.r10:.3f} | "
        f"{f.novedad:.3f} | {f.ils:.3f} |"
        for f in res.filas
    ]
    lineas.append("")
    return "\n".join(lineas)


def escribir_reportes_sociales(res: ResultadoSocial, directorio: Path) -> tuple[Path, Path]:
    directorio.mkdir(parents=True, exist_ok=True)
    ruta_csv = directorio / "resultados_social.csv"
    ruta_md = directorio / "resultados_social.md"
    with ruta_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["grupo", "sistema", "usuarios", "p10", "r10", "novedad", "ils"])
        for x in res.filas:
            w.writerow(
                [
                    x.grupo,
                    x.sistema,
                    x.usuarios,
                    *(round(v, 4) for v in (x.p10, x.r10, x.novedad, x.ils)),
                ]
            )
    ruta_md.write_text(markdown_social(res), encoding="utf-8")
    return ruta_csv, ruta_md


def evaluar_social_desde_cli(
    db: Path,
    ruta: Path,
    params: Path,
    salida: Path = Path("reports"),
    semilla: int = 42,
    guardar: bool = True,
) -> int:
    """Carga catálogo, perfiles y amistades de HetRec, ejecuta el protocolo social y reporta."""
    if not db.exists():
        log.error("No existe la base %s; ejecuta primero la ingesta.", db)
        return 2
    if not (ruta / "user_friends.dat").exists():
        log.error("No existe %s/user_friends.dat (ver data/README.md).", ruta)
        return 2
    indice = IndiceCatalogo.construir(RepositorioSQLite(db).cargar_catalogo())
    filas = leer_hetrec(ruta)
    usuarios = emparejar(filas, indice.por_nombre, escalar=True)
    base = ConfigMotor.desde_json(params)
    descripcion = f"hetrec ({ruta}) sobre {db} ({indice.n} artistas), parámetros de {params}"
    try:
        res = ejecutar_social(
            indice,
            usuarios,
            leer_amigos_hetrec(ruta),
            perfiles_de_amigos(filas, indice.por_nombre),
            base,
            descripcion,
            semilla,
        )
    except ValueError as error:
        log.error("%s", error)
        return 2
    ruta_csv, ruta_md = escribir_reportes_sociales(res, salida)
    if guardar:
        res.config.a_json(params)
    print(f"Reportes en {ruta_csv} y {ruta_md}")
    print(markdown_social(res))
    return 0
