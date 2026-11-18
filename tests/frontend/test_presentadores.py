"""Pruebas unitarias para las funciones de presentación (ui/presentadores.py)."""

from sonarmatch.adapters.inbound.ui.presentadores import (
    construir_solicitud,
    etiqueta_aporte,
    filas_tabla_contrafactual,
    filtrar_catalogo_por_que_no,
    formatear_efecto_contrafactual,
    formatear_estado_amigo,
    formatear_latencia,
    formatear_oyentes,
    formatear_resumen_estrategias,
    preparar_datos_comparativa_aportes,
    preparar_datos_grafica_aportes,
    resolver_parametros,
    son_parametros_iguales,
    texto_contador_artistas,
    texto_insignia,
    texto_motivo_no,
    validar_cantidad_artistas,
)
from sonarmatch.ports.inbound import (
    AmigoDTO,
    EfectoContrafactual,
    EntradaArtista,
    ParametrosMotor,
    SolicitudRecomendacion,
)


def test_formatear_oyentes() -> None:
    assert formatear_oyentes(-10) == "-10"
    assert formatear_oyentes(0) == "0"
    assert formatear_oyentes(500) == "500"
    assert formatear_oyentes(1_000) == "1 mil"
    assert formatear_oyentes(12_300) == "12,3 mil"
    assert formatear_oyentes(412_000) == "412 mil"
    assert formatear_oyentes(1_000_000) == "1 M"
    assert formatear_oyentes(2_100_000) == "2,1 M"
    assert formatear_oyentes(5_600_000) == "5,6 M"


def test_etiqueta_aporte() -> None:
    assert etiqueta_aporte("s_tags") == "Etiquetas"
    assert etiqueta_aporte("s_grafo") == "Conexiones"
    assert etiqueta_aporte("s_social") == "Amigos"
    assert etiqueta_aporte("p_nov") == "Novedad"
    assert etiqueta_aporte("s_onto") == "Afinidad de género"
    assert etiqueta_aporte("desconocido") == "desconocido"


def test_preparar_datos_grafica_aportes() -> None:
    aportes = {
        "s_tags": 0.2,
        "s_grafo": 0.25,
        "s_social": 0.1,
        "p_nov": 0.15,
        "s_onto": 0.22,
    }
    datos = preparar_datos_grafica_aportes(aportes)
    assert len(datos) == 5
    assert datos[0] == {"componente": "Etiquetas", "valor": 0.2}
    assert datos[1] == {"componente": "Conexiones", "valor": 0.25}
    assert datos[2] == {"componente": "Amigos", "valor": 0.1}
    assert datos[3] == {"componente": "Novedad", "valor": 0.15}
    assert datos[4] == {"componente": "Afinidad de género", "valor": 0.22}

    datos_vacios = preparar_datos_grafica_aportes({})
    assert len(datos_vacios) == 5
    assert all(d["valor"] == 0.0 for d in datos_vacios)


def test_preparar_datos_comparativa_aportes() -> None:
    candidato = {"s_tags": 0.1, "s_grafo": 0.2, "s_social": 0.0, "p_nov": 0.05, "s_onto": 0.06}
    decimo = {"s_tags": 0.15, "s_grafo": 0.2, "s_social": 0.05, "p_nov": 0.1, "s_onto": 0.08}
    datos = preparar_datos_comparativa_aportes(candidato, "Deftones", decimo, "The Cure")
    assert len(datos) == 10
    artistas = {d["artista"] for d in datos}
    assert artistas == {"10.°: The Cure", "Consultado: Deftones"}
    componentes = {d["componente"] for d in datos}
    assert "Amigos" in componentes


def test_texto_insignia() -> None:
    assert texto_insignia("grafo") == "Principal"
    assert texto_insignia("contenido") == "Respaldo"
    assert texto_insignia("popularidad") == "Respaldo"
    assert texto_insignia("desconocida") == "Respaldo"


def test_validar_cantidad_artistas() -> None:
    assert not validar_cantidad_artistas(0)
    assert not validar_cantidad_artistas(4)
    assert validar_cantidad_artistas(5)
    assert validar_cantidad_artistas(12)
    assert validar_cantidad_artistas(20)
    assert not validar_cantidad_artistas(21)


def test_texto_contador_artistas() -> None:
    assert texto_contador_artistas(3) == "3 de 5–20"
    assert texto_contador_artistas(5) == "5 de 5–20"
    assert texto_contador_artistas(20) == "20 de 5–20"


def test_construir_solicitud() -> None:
    lista = [("Slowdive", 4.5), ("Low", 3.0)]
    solicitud_lista = construir_solicitud(lista)
    assert isinstance(solicitud_lista, SolicitudRecomendacion)
    assert len(solicitud_lista.artistas) == 2
    assert solicitud_lista.artistas[0] == EntradaArtista(nombre="Slowdive", peso=4.5)
    assert solicitud_lista.parametros is None
    assert solicitud_lista.apodo is None

    dicc = {"Slowdive": 5.0, "Low": 2.5}
    param = ParametrosMotor(a=0.2, b=0.3, c=0.2, d=0.3, lambda_mmr=0.6)
    solicitud_dict = construir_solicitud(dicc, param, apodo="  demo  ")
    assert len(solicitud_dict.artistas) == 2
    assert solicitud_dict.parametros == param
    assert solicitud_dict.apodo == "demo"

    solicitud_vacia = construir_solicitud(dicc, param, apodo="   ")
    assert solicitud_vacia.apodo is None


def test_texto_motivo_no() -> None:
    motivos = [
        "ya_en_entrada",
        "no_en_catalogo",
        "no_conectado",
        "no_conectado_ni_por_amigos",
        "descartado_por_regla",
        "puntaje_insuficiente",
        "desplazado_por_diversidad",
    ]
    for m in motivos:
        texto = texto_motivo_no(m)
        assert isinstance(texto, str)
        assert len(texto) > 10
        assert not texto.startswith("Motivo:")

    assert "otro_motivo" in texto_motivo_no("otro_motivo")


def test_filas_tabla_contrafactual() -> None:
    efectos = (
        EfectoContrafactual(
            artista_usuario="Beach House",
            posicion_original=1,
            posicion_sin_artista=None,
            puntaje_sin_artista=None,
        ),
        EfectoContrafactual(
            artista_usuario="Cocteau Twins",
            posicion_original=1,
            posicion_sin_artista=3,
            puntaje_sin_artista=0.8123,
        ),
        EfectoContrafactual(
            artista_usuario="todos tus amigos",
            posicion_original=1,
            posicion_sin_artista=4,
            puntaje_sin_artista=0.7000,
            tipo="amigos",
        ),
        EfectoContrafactual(
            artista_usuario="ana_m",
            posicion_original=1,
            posicion_sin_artista=2,
            puntaje_sin_artista=0.8000,
            tipo="amigo",
        ),
    )
    assert formatear_efecto_contrafactual(efectos[0]) == "Sin Beach House"
    assert formatear_efecto_contrafactual(efectos[2]) == "Sin tus amigos"
    assert formatear_efecto_contrafactual(efectos[3]) == "Sin el amigo ana_m"

    filas = filas_tabla_contrafactual(efectos)
    assert len(filas) == 4
    assert filas[0]["Qué se quita"] == "Sin Beach House"
    assert filas[0]["Posición original"] == "#1"
    assert filas[0]["Posición sin artista"] == "fuera de la lista"
    assert filas[0]["Cambio"] == "#1 → fuera de la lista"
    assert filas[0]["Puntaje sin artista"] == "—"

    assert filas[1]["Qué se quita"] == "Sin Cocteau Twins"
    assert filas[1]["Posición sin artista"] == "#3"
    assert filas[1]["Cambio"] == "#1 → #3"
    assert filas[1]["Puntaje sin artista"] == "0.8123"

    assert filas[2]["Qué se quita"] == "Sin tus amigos"
    assert filas[3]["Qué se quita"] == "Sin el amigo ana_m"


def test_son_parametros_iguales_y_resolver() -> None:
    p1 = ParametrosMotor(a=0.3, b=0.35, c=0.15, d=0.2, lambda_mmr=0.7)
    p2 = ParametrosMotor(a=0.3, b=0.35, c=0.15, d=0.2, lambda_mmr=0.7)
    p3 = ParametrosMotor(a=0.3, b=0.35, c=0.15, d=0.25, lambda_mmr=0.7)
    p4 = ParametrosMotor(a=0.3, b=0.35, c=0.15, d=0.2, lambda_mmr=0.7, beta=0.0)
    assert son_parametros_iguales(p1, p2)
    assert not son_parametros_iguales(p1, p3)
    assert not son_parametros_iguales(p1, p4)
    assert resolver_parametros(p1, p2) is None
    assert resolver_parametros(p3, p1) == p3
    assert resolver_parametros(p4, p1) == p4


def test_filtrar_catalogo_por_que_no() -> None:
    catalogo = ["Beach House", "Wild Nothing", "Slowdive", "The Cure"]
    recomendados = ["wild nothing", "THE CURE"]
    filtrado = filtrar_catalogo_por_que_no(catalogo, recomendados)
    assert filtrado == ["Beach House", "Slowdive"]


def test_formatear_latencia_y_resumen_estrategias() -> None:
    assert formatear_latencia(123.456) == "123.5 ms"
    assert formatear_resumen_estrategias({}) == "Sin estrategias registradas"
    assert formatear_resumen_estrategias({"grafo": 0}) == "Sin estrategias registradas"
    resumen = formatear_resumen_estrategias({"grafo": 6, "contenido": 2, "popularidad": 2})
    assert "Grafo (Principal): 6" in resumen
    assert "Contenido (Respaldo): 2" in resumen
    assert "Popularidad (Respaldo): 2" in resumen


def test_formatear_estado_amigo() -> None:
    amigo_activo = AmigoDTO(apodo="ana_m", comparte_gustos=True)
    amigo_privado = AmigoDTO(apodo="luis_priv", comparte_gustos=False)

    txt_activo = formatear_estado_amigo(amigo_activo)
    txt_privado = formatear_estado_amigo(amigo_privado)

    assert "ana_m" in txt_activo
    assert "Comparte sus gustos" in txt_activo
    assert "luis_priv" in txt_privado
    assert "No comparte sus gustos" in txt_privado
    assert "no influye en tus recomendaciones" in txt_privado
