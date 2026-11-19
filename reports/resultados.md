# Resultados de la evaluación offline

- Dataset: hetrec (data/hetrec2011-lastfm-2k) sobre data/sonarmatch.db (5000 artistas)
- Usuarios: 1286 en validación, 551 en prueba (20 % de artistas ocultos por usuario, mínimo 2).
- Grid search en validación: 37 configuraciones; mejor P@10 en validación = 0.089.
- Parámetros elegidos: a = 0.30, b = 0.35, c = 0.15, d = 0.20, λ = 0.70, τ = 0.05.
- Cobertura del mapeo de etiquetas (por peso): 86.4 %.

## Comparación en prueba

| Sistema | P@10 | R@10 | Novedad ↓ | ILS | Cobertura |
|---|---:|---:|---:|---:|---:|
| línea base: popularidad | 0.045 | 0.059 | 0.999 | 0.140 | 0.3 % |
| sistema completo | 0.084 | 0.125 | 0.689 | 0.395 | 28.6 % |
| sin S_tags | 0.076 | 0.114 | 0.657 | 0.258 | 27.6 % |
| sin S_grafo | 0.033 | 0.053 | 0.553 | 0.439 | 30.5 % |
| sin P_nov | 0.092 | 0.139 | 0.724 | 0.426 | 27.8 % |
| sin S_onto | 0.086 | 0.128 | 0.685 | 0.451 | 28.0 % |
| sin reglas | 0.074 | 0.113 | 0.627 | 0.387 | 28.7 % |
| sin MMR | 0.090 | 0.134 | 0.699 | 0.683 | 26.8 % |
| sin respaldo | 0.084 | 0.125 | 0.689 | 0.395 | 28.6 % |

Novedad: percentil medio de oyentes de lo recomendado (menor = más nicho). ILS: coseno TF-IDF medio entre pares de la lista. Cobertura: fracción del catálogo recomendada al menos una vez.

## Sistema completo: respaldos, reglas y latencia

| Indicador | Valor |
|---|---:|
| Activación del respaldo contenido | 0.0 % |
| Activación del respaldo popularidad | 0.0 % |
| Consultas en que se dispara R1 | 8.2 % |
| Consultas en que se dispara R2 | 8.2 % |
| Consultas en que se dispara R3 | 0.0 % |
| Consultas en que se dispara R4 | 89.8 % |
| Consultas en que se dispara R5 | 0.0 % |
| Consultas en que se dispara R6 | 17.6 % |
| Latencia p50 de la recomendación | 42 ms |
| Latencia p95 de la recomendación | 78 ms |
| Latencia p95 del contrafactual | 612 ms |
