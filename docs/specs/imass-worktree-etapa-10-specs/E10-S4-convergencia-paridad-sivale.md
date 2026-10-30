# E10-S4 — Convergencia de paridad SiVale

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E10
- **Spec:** E10-S4
- **Nombre:** Convergencia de paridad SiVale
- **Dependencias:** E8-S0, E8-S1, E8-S2, E10-S0, E10-S1, E10-S2, E10-S3
- **Bloquea a:** cierre operacional E8-S1/E8-S2 y reanudación del piloto final

## 2. Contexto

E8 introdujo SiVale como primer cliente real y construyó una matriz de paridad. La auditoría posterior demostró que la matriz sobreestimó `init/adopt/destroy` al no descomponer todo el provisioning que el harness legacy ejecuta.

E10-S0..S3 proporcionan contratos cerrados. Esta spec únicamente configura SiVale y demuestra equivalencia. No puede cambiar namespaces, eventos, provider contracts ni arquitectura definidos en S0..S3; cualquier incumplimiento se corrige en la spec propietaria, no inventando una excepción SiVale.

## 3. Objetivo

Conseguir que SiVale opere el lifecycle soportado mediante `imass-wt` + `.imass-worktree.toml` + capabilities/providers del producto, reproduciendo como mínimo las responsabilidades relevantes del harness legacy y sin lógica SiVale/Laravel dentro del core.

## 4. Fuente de verdad de paridad

- `docs/context/snapshot-scripts.txt` como referencia histórica del lifecycle real;
- E8-S0/E8-S1/E8-S2;
- `docs/examples/sivale-parity-matrix.md` actualizada;
- configuración real soportada de SiVale;
- contratos E10-S0..S3.

No se exige copiar comandos Bash literalmente; se exige conservar el resultado operativo soportado.

## 5. Requirements

### R1 — Init completo
`imass-wt init` con configuración SiVale debe cubrir:
- target/branch/worktree;
- puerto;
- identidad/config runtime;
- data PostgreSQL aislada;
- runtime build/start cuando la policy lo requiera;
- dependency provisioning Composer;
- permission/readiness configurado;
- artifacts requeridos;
- tmux si está habilitado;
- `--open kiro` cuando se solicite.

### R2 — Adopt completo
`adopt` debe preservar trabajo preexistente y completar el provisioning equivalente que falte para dejar el workspace listo.

### R3 — Start/stop
Debe suspender/reanudar recursos soportados sin recrear Git ni repetir bootstrap inicial destructivo innecesario.

### R4 — Destroy completo
Debe comparar guards y cleanup de runtime/data/ports/processes/tmux/tunnel/worktree/branch policy conforme a ownership y configuración.

### R5 — Paralelismo real
Al menos dos targets simultáneos deben demostrar aislamiento de branch/path/port/runtime/data.

### R6 — No scripts lifecycle indispensables
Tras PASS, `worktree-init.sh`, `worktree-adopt.sh`, `worktree-teardown.sh` y `compose-project.sh` no deben conservar una responsabilidad exclusiva necesaria para el lifecycle soportado. Su retiro físico pertenece al proyecto SiVale y sólo procede después de evidencia.

### R7 — No coupling
No se acepta ningún cambio productivo condicionado por `sivale`, `zurich`, `laravel`, `KIRO_PROJECT_ROOT` o `KIRO_DEVELOPER` en el core.

### R8 — Gaps
Todo gap debe clasificarse y sólo bloquea si viola un requirement/AC de esta spec. No se abre arquitectura nueva por mejoras hipotéticas.

### R9 — Evidencia determinista y operacional
La suite/conformance debe cubrir el contrato de forma reproducible y el piloto real debe ejecutarse sobre el entorno SiVale para cerrar la evidencia operacional.

### R10 — Docs post-implementación
Al quedar implementada, Kiro debe actualizar las guías de producto (`capabilities`, `configuracion`, `lifecycle`, ejemplo SiVale, troubleshooting, README/AGENTS/CHANGELOG si aplica) para describir únicamente features realmente soportadas.

## 6. Matriz mínima de paridad

| Operación | Responsabilidad |
|---|---|
| init | branch/worktree |
| init | puerto |
| init | runtime identity/config |
| init | PostgreSQL data provisioning |
| init | runtime build/start |
| init | dependency provisioning |
| init | permission/readiness |
| init | artifacts |
| init | tmux/open |
| adopt | trabajo existente + provisioning |
| start/stop | reactivación/suspensión sin reconstrucción |
| destroy | guards + cleanup de todos los recursos propios |
| paralelismo | aislamiento de dos targets |
| fallo parcial | rollback/diagnóstico sin tocar recursos ajenos |

Cada fila debe tener evidencia y estado `PASS`, `GAP justificado` o `FAIL`; un exit code 0 no basta como evidencia de paridad completa.

## 7. Acceptance Criteria

- AC-01 todas las filas obligatorias de la matriz quedan PASS o GAP explícitamente no requerido por el contrato.
- AC-02 ningún script legacy conserva responsabilidad exclusiva necesaria para el lifecycle soportado antes de marcarlo reemplazado.
- AC-03 `init` deja un workspace realmente listo conforme a la configuración SiVale.
- AC-04 `adopt` conserva trabajo y completa provisioning.
- AC-05 dos workspaces reales no colisionan en recursos soportados.
- AC-06 `destroy` limpia sólo recursos propios y bloquea dirty.
- AC-07 no existe coupling SiVale/Laravel en core.
- AC-08 Git-only/conformance siguen verdes.
- AC-09 piloto real archivado bajo `docs/evidence/`.
- AC-10 E8-S1/E8-S2 tracking puede volver a estado de evidencia operacional cerrada.

## 8. Tasks

1. Actualizar `docs/examples/sivale.imass-worktree.toml` con el contrato E10 implementado.
2. Configurar runtime provisioning, Composer/readiness y PostgreSQL data provisioning.
3. Actualizar tests/conformance de paridad a nivel de responsabilidad.
4. Ejecutar suite completa.
5. Ejecutar conformance.
6. Ejecutar piloto real SiVale con concurrencia y archivar evidencia.
7. Comparar nuevamente cada responsabilidad legacy.
8. Clasificar y reparar sólo gaps contractuales directos.
9. Actualizar docs de producto implementado.
10. Actualizar `implementation-status.json` y sólo entonces declarar `SIVALE_PARITY = PASS`.

## 9. Criterio de salida

E10-S4 termina cuando SiVale puede usar `imass-wt` como mecanismo real del lifecycle soportado sin conocimiento SiVale/Laravel en el core y sin depender de scripts legacy para responsabilidades que ya pertenecen al producto.
