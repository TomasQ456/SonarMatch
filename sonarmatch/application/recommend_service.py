"""Servicio de aplicación: implementa los puertos de entrada sobre el motor del dominio.

Traduce DTOs del contrato a objetos del dominio y viceversa. Cachea por solicitud el
resultado de la consulta y sus contrafactuales (LRU pequeño, seguro entre hilos), de modo que
el contrafactual y el "¿por qué no?" reutilizan la misma traza y las mismas columnas de PPR.
"""

import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from sonarmatch.application.perfiles import ServicioPerfiles
from sonarmatch.application.validation import validar_solicitud
from sonarmatch.domain.counterfactual import (
    Contrafactuales,
    YaRecomendadoError,
    diagnosticar,
    resumen_efectos,
)
from sonarmatch.domain.models import ContextoSocial, EntradaPerfil, PerfilAmigo, Recomendacion
from sonarmatch.domain.pipeline import MotorRecomendacion, ResultadoConsulta
from sonarmatch.domain.razonamiento import Pesos
from sonarmatch.ports.inbound import (
    ContrafactualDTO,
    EfectoContrafactual,
    ErrorEntradaInvalida,
    ErrorPerfil,
    Estrategia,
    ParametrosMotor,
    PorQueNoDTO,
    RecomendacionDTO,
    RespuestaRecomendacion,
    SolicitudRecomendacion,
)
from sonarmatch.ports.outbound import RepositorioEvaluaciones

TAMANO_CACHE = 32


def a_pesos(p: ParametrosMotor | None) -> Pesos | None:
    return None if p is None else Pesos(p.a, p.b, p.c, p.d, p.lambda_mmr)


def a_dto(r: Recomendacion) -> RecomendacionDTO:
    exp = r.explicacion
    return RecomendacionDTO(
        artista_id=r.artista_id,
        nombre=r.nombre,
        puntaje=min(1.0, max(0.0, r.puntaje)),
        aportes=dict(r.aportes),
        explicacion=exp.texto if exp else "",
        artistas_origen=exp.artistas_origen if exp else (),
        etiquetas_clave=exp.etiquetas_clave if exp else (),
        estrategia=r.estrategia,
        oyentes=r.oyentes,
        cadena_inferencia=exp.cadena_inferencia if exp else (),
        amigos_origen=exp.amigos_origen if exp else (),
    )


@dataclass
class _Entrada:
    resultado: ResultadoConsulta
    contrafactuales: Contrafactuales
    latencia_ms: float
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class ServicioRecomendacion:
    motor: MotorRecomendacion
    evaluaciones: RepositorioEvaluaciones
    perfiles: ServicioPerfiles | None = None
    _cache: OrderedDict[tuple[object, ...], _Entrada] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # --------------------------------------------------------- RecomendarArtistas
    def recomendar(self, solicitud: SolicitudRecomendacion) -> RespuestaRecomendacion:
        entrada = self._consultar(solicitud)
        recs = tuple(a_dto(r) for r in entrada.resultado.recomendaciones)
        return RespuestaRecomendacion(
            recomendaciones=recs,
            artistas_no_encontrados=entrada.resultado.perfil.perfil.no_encontrados,
            estrategias_usadas=dict(Counter(r.estrategia for r in recs)),
            latencia_ms=entrada.latencia_ms,
        )

    def contexto_social(self, solicitud: SolicitudRecomendacion) -> ContextoSocial | None:
        """Amigos que comparten gustos (el consentimiento se aplica aquí) y β de la solicitud."""
        if solicitud.apodo is None:
            return None
        if self.perfiles is None:
            raise ErrorPerfil("La gestión de perfiles no está disponible en esta instalación.")
        amigos = self.perfiles.amigos_que_comparten(solicitud.apodo)
        p = solicitud.parametros
        beta = p.beta if p is not None else self.motor.config.beta
        return ContextoSocial(
            tuple(PerfilAmigo(a.apodo, self.motor.perfil(a.artistas)) for a in amigos), beta
        )

    def _consultar(self, solicitud: SolicitudRecomendacion) -> _Entrada:
        validar_solicitud(solicitud)
        social = self.contexto_social(solicitud)
        # La clave incluye el contexto social: si un amigo cambia su perfil o su consentimiento,
        # la consulta se recalcula.
        clave = (solicitud.artistas, solicitud.parametros, social)
        with self._lock:
            if clave in self._cache:
                self._cache.move_to_end(clave)
                return self._cache[clave]
        inicio = time.perf_counter()
        perfil = self.motor.perfil([EntradaPerfil(e.nombre, e.peso) for e in solicitud.artistas])
        pesos = a_pesos(solicitud.parametros)
        resultado = self.motor.recomendar(perfil, pesos, social=social)
        latencia = (time.perf_counter() - inicio) * 1000
        contrafactuales = Contrafactuales(self.motor, resultado, pesos, None, social)
        entrada = _Entrada(resultado, contrafactuales, latencia)
        with self._lock:
            self._cache[clave] = entrada
            while len(self._cache) > TAMANO_CACHE:
                self._cache.popitem(last=False)
        return entrada

    # --------------------------------------------------------- ConsultarCatalogo
    def nombres_artistas(self) -> list[str]:
        return sorted((a.nombre for a in self.motor.indice.artistas), key=str.casefold)

    def parametros_por_defecto(self) -> ParametrosMotor:
        c = self.motor.config
        return ParametrosMotor(a=c.a, b=c.b, c=c.c, d=c.d, lambda_mmr=c.lambda_mmr, beta=c.beta)

    # --------------------------------------------------------- ExplicarRecomendacion
    def contrafactual(self, solicitud: SolicitudRecomendacion, artista_id: int) -> ContrafactualDTO:
        entrada = self._consultar(solicitud)
        indice = self.motor.indice.por_id.get(artista_id)
        recomendados = {r.indice for r in entrada.resultado.recomendaciones}
        if indice is None or indice not in recomendados:
            raise ErrorEntradaInvalida(
                f"El artista {artista_id} no está entre las recomendaciones de esta consulta."
            )
        with entrada.lock:  # las re-ejecuciones se calculan una sola vez por solicitud
            efectos = entrada.contrafactuales.efectos(indice)
        nombre = self.motor.indice.nombre(indice)
        return ContrafactualDTO(
            artista_id=artista_id,
            nombre=nombre,
            efectos=tuple(
                EfectoContrafactual(
                    e.artista_usuario,
                    e.posicion_original,
                    e.posicion_sin_artista,
                    e.puntaje_sin_artista,
                    e.tipo,
                )
                for e in efectos
            ),
            resumen=resumen_efectos(nombre, efectos),
        )

    def por_que_no(self, solicitud: SolicitudRecomendacion, nombre_artista: str) -> PorQueNoDTO:
        entrada = self._consultar(solicitud)
        try:
            d = diagnosticar(
                self.motor,
                entrada.resultado,
                [e.nombre for e in solicitud.artistas],
                nombre_artista,
            )
        except YaRecomendadoError as error:
            raise ErrorEntradaInvalida(str(error)) from error
        return PorQueNoDTO(
            nombre=d.nombre,
            motivo=d.motivo,
            posicion_previa_mmr=d.posicion_previa_mmr,
            aportes=d.aportes,
            diferencia_con_decimo=d.diferencia_con_decimo,
            cadena_regla=d.cadena_regla,
            similar_a=d.similar_a,
            explicacion=d.explicacion,
        )

    # --------------------------------------------------------- RegistrarFeedback
    def registrar(
        self, sesion_id: str, artista_id: int, valoracion: Literal[-1, 1], estrategia: Estrategia
    ) -> None:
        if valoracion not in (-1, 1):
            raise ErrorEntradaInvalida("La valoración debe ser 1 o -1.")
        self.evaluaciones.registrar_feedback(sesion_id, artista_id, valoracion, estrategia)
