"""Explicaciones: descomposición del puntaje en aportes de artistas y etiquetas + cadena de reglas.

- Artistas de origen: los del usuario con mayor w_i · PPR_i(c) (exacto por la linealidad del
  PPR). En las estrategias de respaldo, los de mayor w_i · cos(tfidf_i, tfidf_c).
- Etiquetas clave: mayor producto término a término perfil ⊙ tfidf(c).
- Cadena de inferencia: los disparos de reglas que influyeron (ajustes globales R3/R4/R6,
  procedencia por R2 con sus R1, y las afinidades R1 que pesan en S_onto del candidato).
"""

from dataclasses import dataclass

import numpy as np

from sonarmatch.config import ConfigMotor
from sonarmatch.domain.indice import IndiceCatalogo
from sonarmatch.domain.models import Explicacion, Recomendacion
from sonarmatch.domain.razonamiento import PerfilRazonado
from sonarmatch.domain.rules.engine import Disparo, Hecho
from sonarmatch.domain.strategies.graph_strategy import TrazaGrafo
from sonarmatch.domain.strategies.popularity_strategy import etiquetas_dominantes
from sonarmatch.domain.textos import lista_natural

MOTIVOS_RESPALDO = {
    "pocos_artistas": "pocos de tus artistas están en el catálogo",
    "menos_de_n": "la estrategia principal no encontró suficientes artistas conectados",
    "bajo_tau": "la confianza de la estrategia principal era baja",
}
NOTA_PARAMETROS = (
    "Usaste parámetros personalizados: se respetaron tal cual y no se aplicaron los ajustes "
    "de las reglas R3, R4 y R6."
)
FRASES_AJUSTE = {
    "R3": "Como tu perfil es de nicho, se dio más peso a la novedad (R3).",
    "R4": "Como tu perfil es mainstream, se dio menos peso a la novedad (R4).",
    "R6": "Como tu perfil es ecléctico, se priorizó la diversidad (R6).",
}
UMBRAL_APORTE_GRAFO = 0.0


@dataclass
class Explicador:
    indice: IndiceCatalogo
    config: ConfigMotor

    def artistas_origen(self, rec: Recomendacion, pr: PerfilRazonado) -> tuple[str, ...]:
        w = np.asarray(pr.perfil.pesos)
        if not pr.perfil.indices:
            return ()
        if rec.estrategia == "grafo":
            aporte = pr.ppr[rec.indice, :] * w
        else:
            filas = self.indice.tfidf[list(pr.perfil.indices)]
            aporte = np.asarray(filas @ self.indice.tfidf[rec.indice].T.toarray()).ravel() * w
        orden = [int(j) for j in np.lexsort((np.arange(len(aporte)), -aporte)) if aporte[j] > 0]
        return tuple(
            self.indice.nombre(pr.perfil.indices[j]) for j in orden[: self.config.n_artistas_origen]
        )

    def etiquetas_clave(self, rec: Recomendacion, pr: PerfilRazonado) -> tuple[str, ...]:
        if self.indice.tfidf.shape[1] == 0:
            return ()
        fila = self.indice.tfidf[rec.indice].toarray().ravel()
        prod = fila * pr.vector
        orden = [int(j) for j in np.lexsort((np.arange(len(prod)), -prod)) if prod[j] > 0]
        return tuple(self.indice.vocabulario[j] for j in orden[: self.config.n_etiquetas_clave])

    def disparos(
        self, rec: Recomendacion, pr: PerfilRazonado, traza: TrazaGrafo | None
    ) -> list[Disparo]:
        if rec.estrategia != "grafo":
            return []
        hechos: list[Hecho] = list(pr.base.todos("ajuste"))
        if traza is not None and "r2" in traza.origen.get(rec.indice, set()):
            r2 = pr.candidatos_r2().get(rec.indice)
            if r2 is not None:
                hechos.append(r2)
        if pr.pesos.d > 0:
            propios = set(self.indice.generos_de(rec.indice))
            onto = self.indice.ontologia
            hechos += [
                h for h in pr.base.todos("afinidad") if propios & onto.descendientes(str(h.args[0]))
            ]
        return pr.motor.cadena(hechos)

    def explicar(
        self,
        rec: Recomendacion,
        pr: PerfilRazonado,
        traza: TrazaGrafo | None,
        motivo_respaldo: str | None = None,
    ) -> Explicacion:
        origen = self.artistas_origen(rec, pr)
        etiquetas = self.etiquetas_clave(rec, pr)
        disparos = self.disparos(rec, pr, traza)
        cadena = list(pr.motor.redactar(disparos, pr.contexto))
        if pr.pesos_usuario and rec.estrategia == "grafo":
            cadena.append(NOTA_PARAMETROS)
        if rec.estrategia == "grafo":
            texto = self._texto_grafo(rec, pr, origen, etiquetas, disparos)
        else:
            texto = self._texto_respaldo(rec, pr, origen, etiquetas, motivo_respaldo)
        return Explicacion(
            aportes=dict(rec.aportes),
            artistas_origen=origen,
            etiquetas_clave=etiquetas,
            estrategia=rec.estrategia,
            cadena_inferencia=tuple(cadena),
            texto=texto,
        )

    def _texto_grafo(
        self,
        rec: Recomendacion,
        pr: PerfilRazonado,
        origen: tuple[str, ...],
        etiquetas: tuple[str, ...],
        disparos: list[Disparo],
    ) -> str:
        partes: list[str] = []
        aporte_grafo = rec.aportes.get("s_grafo", 0.0)
        if origen and aporte_grafo > UMBRAL_APORTE_GRAFO and rec.puntaje > 0:
            pct = round(100 * aporte_grafo / rec.puntaje)
            partes.append(f"está muy conectado con {lista_natural(origen)} ({pct} % del puntaje)")
        if etiquetas:
            partes.append(f"comparte las etiquetas {lista_natural(etiquetas)}")
        if not partes:
            partes.append("su combinación de etiquetas, conexiones y géneros se acerca a tu perfil")
        frases = ["Recomendado porque " + " y ".join(partes) + "."]
        frases += self._narrativa_r2(disparos)
        if self.indice.p_nov[rec.indice] >= self.config.umbral_poco_conocido:
            frases.append("Es un artista poco conocido.")
        if not pr.pesos_usuario:
            ids = {d.regla_id for d in disparos}
            frases += [FRASES_AJUSTE[r] for r in ("R3", "R4", "R6") if r in ids]
        return " ".join(frases)

    def _narrativa_r2(self, disparos: list[Disparo]) -> list[str]:
        r2 = [d for d in disparos if d.regla_id == "R2"]
        if not r2:
            return []
        onto = self.indice.ontologia
        padre = str(r2[-1].coincidencia.ligaduras[0])
        hijo = onto.nombre(str(r2[-1].coincidencia.ligaduras[1]))
        r1 = [
            d for d in disparos if d.regla_id == "R1" and str(d.coincidencia.ligaduras[0]) == padre
        ]
        if r1:
            hijos = [onto.nombre(str(p.args[0])) for p in r1[-1].coincidencia.premisas]
            return [
                f"Escuchas {lista_natural(hijos)}, que son subgéneros de {onto.nombre(padre)} "
                f"(R1), así que exploré {hijo} (R2), y este artista es de {hijo}."
            ]
        return [f"Exploré {hijo} (R2), y este artista es de {hijo}."]

    def _texto_respaldo(
        self,
        rec: Recomendacion,
        pr: PerfilRazonado,
        origen: tuple[str, ...],
        etiquetas: tuple[str, ...],
        motivo: str | None,
    ) -> str:
        porque = MOTIVOS_RESPALDO.get(motivo or "", "la estrategia principal no bastó")
        if rec.estrategia == "contenido":
            base = "Recomendado por similitud de etiquetas con tu perfil"
            if etiquetas:
                base += f" (comparte {lista_natural(etiquetas)})"
        else:
            dominantes = etiquetas_dominantes(self.indice, pr)
            base = "Es de los artistas más escuchados"
            if dominantes:
                base += f" con las etiquetas {lista_natural(dominantes)}"
        frases = [f"{base}. Estrategia de respaldo «{rec.estrategia}», porque {porque}."]
        if origen:
            frases.append(f"Se parece a {lista_natural(origen)}.")
        return " ".join(frases)
