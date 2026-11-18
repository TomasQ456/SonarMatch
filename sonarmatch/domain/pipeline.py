"""Flujo completo de una consulta y su traza.

perfil (+ semillas de amigos) → reglas fase "perfil" → candidatos (top-K PPR + R2/R7)
→ reglas fase "candidatos" (R5) → puntuación con parámetros ajustados → MMR → (respaldos)
→ explicaciones.

Las columnas de PPR se cachean por artista semilla: cada columna se congela al converger y no
depende de las demás del lote, así que una columna cacheada es idéntica a una recalculada.
"""

import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.explanation import Explicador
from sonarmatch.domain.indice import IndiceCatalogo, Vector
from sonarmatch.domain.models import ContextoSocial, EntradaPerfil, PerfilUsuario, Recomendacion
from sonarmatch.domain.orchestrator import Orquestador
from sonarmatch.domain.profile import construir_perfil
from sonarmatch.domain.razonamiento import OpcionesMotor, PerfilRazonado, Pesos, razonar_perfil
from sonarmatch.domain.scoring import Matriz, ppr_columnas
from sonarmatch.domain.social import SemillasSociales, semillas_sociales, vector_de_perfil
from sonarmatch.domain.strategies.content_strategy import EstrategiaContenido
from sonarmatch.domain.strategies.graph_strategy import EstrategiaGrafo, TrazaGrafo
from sonarmatch.domain.strategies.popularity_strategy import EstrategiaPopularidad


@dataclass
class ResultadoConsulta:
    perfil: PerfilRazonado
    recomendaciones: list[Recomendacion]
    extendido: list[int]
    traza: TrazaGrafo | None
    activaciones: list[tuple[str, str]] = field(default_factory=list)

    def posicion(self, indice: int) -> int | None:
        """Posición 1-based en la lista final extendida con el resto del orden de la principal."""
        try:
            return self.extendido.index(indice) + 1
        except ValueError:
            return None

    def reglas_disparadas(self) -> set[str]:
        return {d.regla_id for d in self.perfil.motor.disparos if d.conclusiones}


@dataclass
class MotorRecomendacion:
    indice: IndiceCatalogo
    config: ConfigMotor = field(default_factory=ConfigMotor)

    def __post_init__(self) -> None:
        self.grafo = EstrategiaGrafo(self.indice, self.config)
        self.contenido = EstrategiaContenido(self.indice)
        self.popularidad = EstrategiaPopularidad(self.indice, self.config.n_etiquetas_dominantes)
        self.orquestador = Orquestador(self.grafo, (self.contenido, self.popularidad), self.config)
        self.explicador = Explicador(self.indice, self.config)
        self._columnas: OrderedDict[int, Matriz] = OrderedDict()
        self._lock_columnas = threading.Lock()
        self.columnas_calculadas = 0  # cuántas columnas de PPR se han calculado de verdad
        self._vectores_amigo: OrderedDict[PerfilUsuario, Vector] = OrderedDict()

    def perfil(self, entradas: Sequence[EntradaPerfil]) -> PerfilUsuario:
        return construir_perfil(self.indice, entradas)

    def columnas(self, semillas: Sequence[int]) -> Matriz:
        """Columnas de PPR de ``semillas`` (N × S); solo calcula las que no están en caché."""
        if not semillas:
            return np.zeros((self.indice.n, 0))
        with self._lock_columnas:
            faltan = sorted({s for s in semillas if s not in self._columnas})
            if faltan:
                nuevas = ppr_columnas(
                    self.indice.transicion,
                    self.indice.colgantes,
                    faltan,
                    self.config.ppr_damping,
                    self.config.ppr_tolerancia,
                    self.config.ppr_max_iter,
                )
                self.columnas_calculadas += len(faltan)
                for k, s in enumerate(faltan):
                    self._columnas[s] = nuevas[:, k].copy()
            for s in semillas:
                self._columnas.move_to_end(s)
            salida = np.column_stack([self._columnas[s] for s in semillas])
            while len(self._columnas) > self.config.max_columnas_cache:
                self._columnas.popitem(last=False)
        return salida

    def ppr(self, perfil: PerfilUsuario) -> Matriz:
        return self.columnas(list(perfil.indices))

    def vector_amigo(self, perfil: PerfilUsuario) -> Vector:
        """Σ_j w_fj·PPR_fj de un amigo (cacheado por perfil; columnas del caché de columnas)."""
        with self._lock_columnas:
            if perfil in self._vectores_amigo:
                self._vectores_amigo.move_to_end(perfil)
                return self._vectores_amigo[perfil]
        vector = vector_de_perfil(perfil, self.columnas)
        with self._lock_columnas:
            self._vectores_amigo[perfil] = vector
            while len(self._vectores_amigo) > self.config.max_columnas_cache:
                self._vectores_amigo.popitem(last=False)
        return vector

    def sociales(self, social: ContextoSocial | None) -> SemillasSociales | None:
        return semillas_sociales(social, self.vector_amigo)

    def razonar(
        self,
        perfil: PerfilUsuario,
        parametros: Pesos | None = None,
        opciones: OpcionesMotor | None = None,
        ppr: Matriz | None = None,
        social: ContextoSocial | None = None,
    ) -> PerfilRazonado:
        columnas = self.ppr(perfil) if ppr is None else ppr
        return razonar_perfil(
            self.indice,
            self.config,
            perfil,
            columnas,
            parametros,
            opciones or OpcionesMotor(),
            self.sociales(social),
        )

    def recomendar(
        self,
        perfil: PerfilUsuario,
        parametros: Pesos | None = None,
        opciones: OpcionesMotor | None = None,
        ppr: Matriz | None = None,
        explicar: bool = True,
        social: ContextoSocial | None = None,
    ) -> ResultadoConsulta:
        """Ejecuta el flujo completo. ``ppr`` permite reutilizar columnas ya calculadas.

        ``social`` trae los amigos que comparten gustos y β; None o β = 0 = sin amigos.
        """
        pr = self.razonar(perfil, parametros, opciones, ppr, social)
        n = self.config.n_recomendaciones
        res = self.orquestador.ejecutar(pr, n, pr.entrada)
        motivo = res.activaciones[0][1] if res.activaciones else None
        recs = res.recomendaciones
        if explicar:
            recs = [self._con_explicacion(r, pr, res.traza, motivo) for r in recs]
        return ResultadoConsulta(pr, recs, res.extendido, res.traza, res.activaciones)

    def _con_explicacion(
        self, r: Recomendacion, pr: PerfilRazonado, traza: TrazaGrafo | None, motivo: str | None
    ) -> Recomendacion:
        exp = self.explicador.explicar(r, pr, traza, motivo)
        return Recomendacion(
            indice=r.indice,
            artista_id=r.artista_id,
            nombre=r.nombre,
            puntaje=r.puntaje,
            puntaje_crudo=r.puntaje_crudo,
            oyentes=r.oyentes,
            estrategia=r.estrategia,
            explicacion=exp,
            aportes=r.aportes,
        )
