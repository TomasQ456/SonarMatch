"""Hiperparámetros del motor con sus valores por defecto (un único lugar para todos).

Los valores calibrados en validación se guardan en reports/parametros_calibrados.json y se
cargan con ``ConfigMotor.desde_json``; si el archivo no existe se usan estos valores.
"""

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class ConfigMotor:
    # --- Combinación lineal (a + b + c + d = 1) ---
    a: float = 0.30  # peso de S_tags
    b: float = 0.35  # peso de S_grafo
    c: float = 0.15  # peso de P_nov
    d: float = 0.20  # peso de S_onto
    lambda_mmr: float = 0.70  # MMR: 1 = solo puntaje, 0 = solo diversidad

    # --- Personalized PageRank ---
    ppr_damping: float = 0.85
    ppr_tolerancia: float = 1e-6
    ppr_max_iter: int = 100
    top_k_ppr: int = 200  # candidatos por PPR

    # --- Resultado ---
    n_recomendaciones: int = 10

    # --- Estrategias de respaldo ---
    min_artistas_en_catalogo: int = 3  # por debajo se salta la estrategia principal
    tau: float = 0.05  # umbral del puntaje crudo del décimo resultado

    # --- Reglas (umbrales de la tabla R1-R6) ---
    theta1_r1: float = 0.10  # peso mínimo de cada subgénero para R1
    min_subgeneros_r1: int = 2
    min_profundidad_r1: int = 2  # R1 no aplica a géneros de profundidad < 2
    m_r2: int = 20  # artistas por subgénero explorado en R2
    pertenencia_genero_r2: float = 0.20  # fracción mínima del género H en el artista para R2
    percentil_nicho_r3: float = 25.0
    percentil_mainstream_r4: float = 75.0
    ajuste_c_r3: float = 0.10
    ajuste_c_r4: float = -0.10
    theta5_r5: float = 0.20  # sim Wu-Palmer mínima para no descartar
    theta6_r6: float = 0.30  # sim Wu-Palmer media bajo la cual el perfil es ecléctico
    generos_principales_r6: int = 5
    ajuste_lambda_r6: float = -0.10
    max_iteraciones_reglas: int = 50

    # --- Dimensión social ---
    beta: float = 0.25  # s = (1 − β)·s_propio + β·s_amigos (β = 0 si no hay amigos que compartan)
    theta7_r7: float = 0.15  # peso mínimo de un género en el perfil de un amigo para R7
    min_amigos_r7: int = 2  # amigos que comparten gustos y escuchan el género
    n_amigos_origen: int = 2  # amigos que nombra la explicación

    # --- Explicaciones ---
    umbral_poco_conocido: float = 0.45  # P_nov crudo por encima del cual se dice "poco conocido"
    n_artistas_origen: int = 2
    n_etiquetas_clave: int = 3
    n_etiquetas_dominantes: int = 3  # respaldo de popularidad: etiquetas del perfil que usa

    # --- Mapeo de etiquetas ---
    umbral_difuso: float = 90.0

    def a_json(self, ruta: Path) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def desde_json(cls, ruta: Path) -> "ConfigMotor":
        """Carga solo las claves conocidas; sin archivo devuelve los valores por defecto."""
        if not ruta.exists():
            return cls()
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        conocidas = {f.name for f in fields(cls)}
        return replace(cls(), **{k: v for k, v in datos.items() if k in conocidas})


RUTA_CALIBRADOS = Path("reports/parametros_calibrados.json")
