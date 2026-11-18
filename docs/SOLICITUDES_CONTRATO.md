# Solicitudes de cambio al contrato

Formato: `## <fecha> — <título>` con quién lo pide, qué y por qué. El responsable del backend añade debajo la
**Decisión** (aceptada / rechazada) y su justificación.



## 2026-11-17 — Dimensión social

Pedido por el equipo: agregar perfiles, amigos y su aporte a las recomendaciones.

**Decisión: aceptada, como cambio aditivo.** Campos nuevos con valor por defecto (`apodo`, `beta`,
`amigos_origen`, `tipo` del efecto contrafactual), la clave `s_social` en `aportes`, el motivo
`no_conectado_ni_por_amigos`, el puerto `GestionarPerfiles` (con valor por defecto en
`Servicios`) y `ErrorPerfil` como subclase de `ErrorEntradaInvalida`. Ningún código existente
cambia de comportamiento sin apodo o con β = 0. Detalle en `docs/CONTRATO.md`.
