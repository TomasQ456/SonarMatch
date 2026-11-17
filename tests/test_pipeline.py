"""Flujo completo: estrategias, orquestador, explicaciones, traza y casos borde."""

import re

import numpy as np
import pytest
from juguete import catalogo_juguete

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import TERMINOS, Artista, Catalogo, EntradaPerfil
from sonarmatch.domain.pipeline import MotorRecomendacion, ResultadoConsulta
from sonarmatch.domain.razonamiento import OpcionesMotor, Pesos
from sonarmatch.domain.strategies.popularity_strategy import etiquetas_dominantes

SHOEGAZE = ("Slowdive", "Low", "Codeine", "Red House Painters", "My Bloody Valentine", "Lush")
JAZZ = ("Miles Davis", "Weather Report", "Charlie Parker")


def recomendar(
    motor: MotorRecomendacion, nombres: tuple[str, ...], **kw: object
) -> ResultadoConsulta:
    perfil = motor.perfil([EntradaPerfil(n, 1 + i % 5) for i, n in enumerate(nombres)])
    return motor.recomendar(perfil, **kw)


def test_diez_recomendaciones_sin_entrada_ni_duplicados(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, SHOEGAZE)
    nombres = [r.nombre for r in res.recomendaciones]
    assert len(nombres) == 10
    assert len(set(nombres)) == 10
    assert not set(nombres) & set(SHOEGAZE)
    assert all(r.estrategia == "grafo" for r in res.recomendaciones)
    assert res.activaciones == []


def test_aportes_suman_el_puntaje(motor: MotorRecomendacion) -> None:
    for r in recomendar(motor, SHOEGAZE).recomendaciones:
        assert set(r.aportes) == set(TERMINOS)
        assert sum(r.aportes.values()) == pytest.approx(r.puntaje)
        assert 0 <= r.puntaje <= 1


def test_explicaciones_solo_mencionan_artistas_del_usuario(
    motor: MotorRecomendacion, indice: IndiceCatalogo
) -> None:
    for perfil in (SHOEGAZE, (*JAZZ, "Slowdive", "Bon Iver"), ("Slowdive", "Metallica")):
        res = recomendar(motor, perfil)
        for r in res.recomendaciones:
            assert r.explicacion is not None
            assert set(r.explicacion.artistas_origen) <= set(perfil)
            ajenos = {a.nombre for a in indice.artistas} - set(perfil) - {r.nombre}
            texto = r.explicacion.texto + " ".join(r.explicacion.cadena_inferencia)
            for nombre in ajenos:
                assert not re.search(rf"\b{re.escape(nombre)}\b", texto), (nombre, texto)


def test_artistas_origen_son_los_de_mayor_aporte_ppr(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, SHOEGAZE)
    pr = res.perfil
    for r in res.recomendaciones:
        aporte = pr.ppr[r.indice] * np.asarray(pr.perfil.pesos)
        mejores = [SHOEGAZE[j] for j in np.argsort(-aporte, kind="stable")[:2]]
        assert r.explicacion is not None
        assert list(r.explicacion.artistas_origen) == mejores


def test_traza_es_fiel_cada_paso_corresponde_a_un_disparo(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, (*SHOEGAZE, "Mogwai", "Explosions in the Sky"))
    pr = res.perfil
    reales = set(pr.motor.redactar([d for d in pr.motor.disparos if d.conclusiones], pr.contexto))
    pasos = [p for r in res.recomendaciones for p in r.explicacion.cadena_inferencia]
    assert pasos
    assert set(pasos) <= reales


def test_r2_aparece_en_la_explicacion_de_sus_candidatos(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, SHOEGAZE)
    assert res.traza is not None
    r2 = [r for r in res.recomendaciones if "r2" in res.traza.origen[r.indice]]
    assert r2
    for r in r2:
        assert r.explicacion is not None
        assert any(p.startswith("R2") for p in r.explicacion.cadena_inferencia)
        assert "(R2)" in r.explicacion.texto


def test_parametros_de_usuario_quedan_en_la_cadena(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, SHOEGAZE, parametros=Pesos(0.25, 0.25, 0.25, 0.25, 0.7))
    for r in res.recomendaciones:
        assert r.explicacion is not None
        assert "parámetros personalizados" in r.explicacion.cadena_inferencia[-1]


def test_sin_mmr_el_orden_es_el_ranking_previo(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, SHOEGAZE, opciones=OpcionesMotor(usar_mmr=False))
    assert res.traza is not None
    assert res.traza.orden_mmr == res.traza.ranking_previo
    con = recomendar(motor, SHOEGAZE, parametros=Pesos(0.3, 0.35, 0.15, 0.2, 0.0))
    assert con.traza is not None
    assert con.traza.orden_mmr != con.traza.ranking_previo


def test_determinista(motor: MotorRecomendacion) -> None:
    a = [r.nombre for r in recomendar(motor, SHOEGAZE).recomendaciones]
    b = [r.nombre for r in recomendar(motor, SHOEGAZE).recomendaciones]
    assert a == b


# ------------------------------------------------------------------ orquestador
def test_pocos_artistas_en_catalogo_salta_la_principal(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, ("Slowdive", "Low", "Nadie 1", "Nadie 2", "Nadie 3"))
    assert res.traza is None
    assert res.activaciones[0] == ("contenido", "pocos_artistas")
    assert len(res.recomendaciones) == 10
    assert {r.estrategia for r in res.recomendaciones} <= {"contenido", "popularidad"}
    assert "respaldo" in res.recomendaciones[0].explicacion.texto


def test_grafo_desconectado_completa_con_respaldo_sin_duplicar(motor: MotorRecomendacion) -> None:
    # El componente del jazz solo tiene 3 artistas, todos en la entrada: no hay candidatos.
    # Nadie fuera del jazz comparte sus etiquetas: contenido tampoco alcanza y sigue popularidad.
    res = recomendar(motor, JAZZ)
    assert res.activaciones == [("contenido", "menos_de_n"), ("popularidad", "menos_de_n")]
    nombres = [r.nombre for r in res.recomendaciones]
    assert len(nombres) == len(set(nombres)) == 10
    assert not set(nombres) & set(JAZZ)
    # Con un artista puente, la principal aporta algo y el resto se completa sin duplicar.
    mixto = recomendar(motor, (*JAZZ, "Nick Drake"))
    estrategias = [r.estrategia for r in mixto.recomendaciones]
    assert estrategias[0] == "grafo"
    assert len({r.nombre for r in mixto.recomendaciones}) == 10
    # el orden respeta la cadena: primero las de nivel superior
    rango = {"grafo": 0, "contenido": 1, "popularidad": 2}
    assert [rango[e] for e in estrategias] == sorted(rango[e] for e in estrategias)
    assert mixto.activaciones[0][0] == "contenido"


def test_umbral_tau_activa_respaldo(indice: IndiceCatalogo) -> None:
    motor = MotorRecomendacion(indice, ConfigMotor(tau=0.3))
    res = recomendar(motor, SHOEGAZE)
    assert ("contenido", "bajo_tau") in res.activaciones
    for r in res.recomendaciones:
        if r.estrategia == "grafo":
            assert r.puntaje_crudo >= 0.3
    assert len({r.nombre for r in res.recomendaciones}) == 10
    assert motor.orquestador.estadisticas["motivo_bajo_tau"] == 1
    assert motor.orquestador.estadisticas["activa_contenido"] == 1


def test_sin_respaldo_devuelve_lo_que_haya(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, JAZZ, opciones=OpcionesMotor(usar_respaldo=False))
    assert res.recomendaciones == []
    assert res.activaciones == []


def test_popularidad_ordena_por_oyentes_en_etiquetas_dominantes(motor: MotorRecomendacion) -> None:
    perfil = motor.perfil([EntradaPerfil(n, 3) for n in ("Metallica", "Slayer")])
    pr = motor.razonar(perfil)
    recs = motor.popularidad.recomendar(pr, 10, pr.entrada)
    # Etiquetas dominantes: thrash metal, heavy metal, metal → solo Megadeth fuera de la entrada.
    assert recs[0].nombre == "Megadeth"
    resto = [r.oyentes for r in recs[1:]]
    assert resto == sorted(resto, reverse=True)  # se completa con los más populares
    assert len(recs) == 10


def test_n_etiquetas_dominantes_sale_de_config(indice: IndiceCatalogo) -> None:
    """Hallazgo B-06: el número de etiquetas dominantes es un hiperparámetro de ConfigMotor."""
    entrada = [EntradaPerfil(n, 3) for n in ("Metallica", "Slayer")]
    for k in (1, 3):
        motor = MotorRecomendacion(indice, ConfigMotor(n_etiquetas_dominantes=k))
        pr = motor.razonar(motor.perfil(entrada))
        assert len(etiquetas_dominantes(indice, pr, motor.config.n_etiquetas_dominantes)) == k
        assert motor.popularidad.n_etiquetas == k


# ------------------------------------------------------------------ casos borde
def test_catalogo_vacio() -> None:
    motor = MotorRecomendacion(IndiceCatalogo.construir(Catalogo((), ())), ConfigMotor())
    res = recomendar(motor, ("A", "B", "C", "D", "E"))
    assert res.recomendaciones == []
    assert res.perfil.perfil.no_encontrados == ("A", "B", "C", "D", "E")


def test_todos_los_artistas_desconocidos_usa_popularidad_global(motor: MotorRecomendacion) -> None:
    res = recomendar(motor, ("X1", "X2", "X3", "X4", "X5"))
    assert [r.estrategia for r in res.recomendaciones] == ["popularidad"] * 10
    oyentes = [r.oyentes for r in res.recomendaciones]
    assert oyentes == sorted(oyentes, reverse=True)


def test_catalogo_sin_etiquetas_ni_aristas() -> None:
    artistas = tuple(Artista(i, f"A{i}", 100 * i, ()) for i in range(1, 15))
    motor = MotorRecomendacion(IndiceCatalogo.construir(Catalogo(artistas, ())), ConfigMotor())
    res = recomendar(motor, ("A1", "A2", "A3", "A4", "A5"))
    assert len(res.recomendaciones) == 9  # 14 − 5 de entrada
    assert all(r.estrategia == "popularidad" for r in res.recomendaciones)


def test_empates_se_resuelven_de_forma_determinista() -> None:
    # Estrella simétrica: todos los vecinos de 1 empatan en PPR, etiquetas y novedad.
    cat = catalogo_juguete(aristas=tuple((1, j, 0.5) for j in range(2, 17)))
    artistas = tuple(Artista(a.id, a.nombre, 1000, (("x", 100.0),)) for a in cat.artistas)
    motor = MotorRecomendacion(
        IndiceCatalogo.construir(Catalogo(artistas, cat.similares)), ConfigMotor()
    )
    perfil = motor.perfil([EntradaPerfil("Dream A", 3)])
    res = motor.recomendar(perfil, opciones=OpcionesMotor(usar_respaldo=False))
    assert [r.artista_id for r in res.recomendaciones] == list(range(2, 12))
