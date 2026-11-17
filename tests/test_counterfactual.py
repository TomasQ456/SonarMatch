"""Contrafactuales (prueba de fidelidad y presupuesto) y "¿por qué no?" (un caso por motivo)."""

import random
import time

import numpy as np
import pytest

from sonarmatch.domain.counterfactual import (
    Contrafactuales,
    Efecto,
    YaRecomendadoError,
    diagnosticar,
    resumen_efectos,
)
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import EntradaPerfil
from sonarmatch.domain.pipeline import MotorRecomendacion, ResultadoConsulta
from sonarmatch.domain.profile import perfil_sin
from sonarmatch.domain.razonamiento import Pesos

SHOEGAZE = ("Slowdive", "Low", "Codeine", "Red House Painters", "My Bloody Valentine", "Lush")


def _consulta(
    motor: MotorRecomendacion, nombres: tuple[str, ...], parametros: Pesos | None = None
) -> ResultadoConsulta:
    perfil = motor.perfil([EntradaPerfil(n, 1 + i % 5) for i, n in enumerate(nombres)])
    return motor.recomendar(perfil, parametros)


def _casos_aleatorios(indice: IndiceCatalogo, n: int, semilla: int) -> list[tuple[str, ...]]:
    rng = random.Random(semilla)
    conectados = [a.nombre for i, a in enumerate(indice.artistas) if not indice.colgantes[i]]
    return [tuple(rng.sample(conectados, rng.randint(5, 12))) for _ in range(n)]


def test_fidelidad_contrafactual_contra_ejecucion_real(
    motor: MotorRecomendacion, indice: IndiceCatalogo
) -> None:
    """La posición predicha (PPR reutilizado) = la de ejecutar de verdad sin ese artista."""
    rng = random.Random(7)
    comparados = 0
    for nombres in _casos_aleatorios(indice, 12, semilla=2026):
        res = _consulta(motor, nombres)
        cf = Contrafactuales(motor, res, None, None)
        recs = rng.sample(res.recomendaciones, min(3, len(res.recomendaciones)))
        for rec in recs:
            for efecto in cf.efectos(rec.indice):
                i = nombres.index(efecto.artista_usuario)
                perfil = res.perfil.perfil
                real = motor.recomendar(perfil_sin(perfil, i))  # recalcula PPR desde cero
                assert efecto.posicion_sin_artista == real.posicion(rec.indice)
                assert [r.indice for r in real.recomendaciones] == [
                    r.indice for r in cf.ejecuciones()[i].recomendaciones
                ]
                comparados += 1
    assert comparados > 100


def test_contrafactual_reutiliza_ppr_sin_recalcular(
    motor: MotorRecomendacion, monkeypatch: pytest.MonkeyPatch
) -> None:
    res = _consulta(motor, SHOEGAZE)
    llamadas = []
    original = motor.ppr
    monkeypatch.setattr(motor, "ppr", lambda p: llamadas.append(p) or original(p))
    cf = Contrafactuales(motor, res, None, None)
    cf.efectos(res.recomendaciones[0].indice)
    cf.efectos(res.recomendaciones[1].indice)  # reutiliza las ejecuciones cacheadas
    assert llamadas == []
    assert len(cf.ejecuciones()) == len(SHOEGAZE)


def test_efectos_ordenados_y_resumen(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, SHOEGAZE)
    rec = res.recomendaciones[0]
    efectos = Contrafactuales(motor, res, None, None).efectos(rec.indice)
    assert [abs(e.impacto) for e in efectos] == sorted(
        (abs(e.impacto) for e in efectos), reverse=True
    )
    assert all(e.posicion_original == 1 for e in efectos)
    assert efectos[0].artista_usuario in resumen_efectos(rec.nombre, efectos)
    with pytest.raises(ValueError, match="recomendados"):
        Contrafactuales(motor, res, None, None).efectos(indice_no_recomendado(res))


def indice_no_recomendado(res: ResultadoConsulta) -> int:
    recomendados = {r.indice for r in res.recomendaciones}
    return next(i for i in range(10**6) if i not in recomendados and i not in res.extendido)


def test_resumen_textos() -> None:
    assert "no cambiaría" in resumen_efectos("X", [Efecto("A", 3, 3, 0.5)])
    assert "dejaría de ser candidato" in resumen_efectos("X", [Efecto("A", 3, None, None)])
    assert "bajaría del puesto 2 al 15" in resumen_efectos("X", [Efecto("A", 2, 15, 0.1)])
    assert "subiría del puesto 5 al 3" in resumen_efectos("X", [Efecto("A", 5, 3, 0.9)])


def test_presupuesto_contrafactual_perfil_de_20(
    motor: MotorRecomendacion, indice: IndiceCatalogo
) -> None:
    conectados = [a.nombre for i, a in enumerate(indice.artistas) if not indice.colgantes[i]]
    res = _consulta(motor, tuple(conectados[:20]))
    inicio = time.perf_counter()
    Contrafactuales(motor, res, None, None).efectos(res.recomendaciones[0].indice)
    assert time.perf_counter() - inicio < 1.5


# --------------------------------------------------------------------- ¿por qué no?
def test_por_que_no_ya_en_entrada(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, SHOEGAZE)
    d = diagnosticar(motor, res, SHOEGAZE, "  slowdive")
    assert d.motivo == "ya_en_entrada"
    assert d.posicion_previa_mmr is None


def test_por_que_no_no_en_catalogo(motor: MotorRecomendacion) -> None:
    d = diagnosticar(motor, _consulta(motor, SHOEGAZE), SHOEGAZE, "Artista Inventado")
    assert d.motivo == "no_en_catalogo"
    assert d.aportes == {}


def test_por_que_no_no_conectado(motor: MotorRecomendacion) -> None:
    d = diagnosticar(motor, _consulta(motor, SHOEGAZE), SHOEGAZE, "miles davis")
    assert d.motivo == "no_conectado"
    assert d.nombre == "Miles Davis"
    assert d.aportes == {}


def test_por_que_no_descartado_por_regla(motor: MotorRecomendacion, indice: IndiceCatalogo) -> None:
    res = _consulta(motor, SHOEGAZE)
    assert res.traza is not None
    i = min(res.traza.descartes)
    d = diagnosticar(motor, res, SHOEGAZE, indice.nombre(i))
    assert d.motivo == "descartado_por_regla"
    assert d.cadena_regla
    assert d.cadena_regla[-1].startswith("R5")
    assert indice.nombre(i) in d.cadena_regla[-1]


def test_por_que_no_puntaje_insuficiente(motor: MotorRecomendacion, indice: IndiceCatalogo) -> None:
    res = _consulta(motor, SHOEGAZE)
    assert res.traza is not None
    i = res.traza.ranking_previo[-1]
    d = diagnosticar(motor, res, SHOEGAZE, indice.nombre(i))
    assert d.motivo == "puntaje_insuficiente"
    assert d.posicion_previa_mmr == len(res.traza.ranking_previo)
    decimo = res.traza.puntajes[res.traza.ranking_previo[9]]
    assert d.diferencia_con_decimo == pytest.approx(decimo - res.traza.puntajes[i])
    assert d.diferencia_con_decimo > 0
    assert sum(d.aportes.values()) == pytest.approx(res.traza.puntajes[i])


def test_por_que_no_desplazado_por_diversidad(
    motor: MotorRecomendacion, indice: IndiceCatalogo
) -> None:
    res = _consulta(motor, SHOEGAZE, Pesos(0.3, 0.35, 0.15, 0.2, lambda_mmr=0.2))
    assert res.traza is not None
    finales = {r.indice for r in res.recomendaciones}
    desplazados = [i for i in res.traza.ranking_previo[:10] if i not in finales]
    assert desplazados
    d = diagnosticar(motor, res, SHOEGAZE, indice.nombre(desplazados[0]))
    assert d.motivo == "desplazado_por_diversidad"
    assert d.similar_a in {r.nombre for r in res.recomendaciones}
    assert d.posicion_previa_mmr is not None
    assert d.posicion_previa_mmr <= 10
    # similar_a es, entre los recomendados, el de mayor coseno con el desplazado
    t = indice.tfidf
    sims = {
        r.nombre: float((t[r.indice] @ t[desplazados[0]].T).toarray()[0, 0])
        for r in res.recomendaciones
    }
    assert sims[d.similar_a] == pytest.approx(max(sims.values()))


def test_por_que_no_de_un_recomendado_es_error(motor: MotorRecomendacion) -> None:
    res = _consulta(motor, SHOEGAZE)
    with pytest.raises(YaRecomendadoError, match="puesto 1"):
        diagnosticar(motor, res, SHOEGAZE, res.recomendaciones[0].nombre)


def test_por_que_no_sin_estrategia_principal(motor: MotorRecomendacion) -> None:
    nombres = ("Slowdive", "Low", "Nadie 1", "Nadie 2", "Nadie 3")
    res = _consulta(motor, nombres)
    assert res.traza is None
    no_recomendado = next(
        a.nombre
        for a in motor.indice.artistas
        if a.nombre not in {r.nombre for r in res.recomendaciones} and a.nombre not in nombres
    )
    assert diagnosticar(motor, res, nombres, no_recomendado).motivo == "no_conectado"
    assert np.isfinite(res.perfil.ppr).all()
