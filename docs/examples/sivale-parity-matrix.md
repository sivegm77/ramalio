# Matriz de paridad SiVale — lifecycle legado vs. `imass-wt` (E8-S1 / E10)

Compara las responsabilidades del lifecycle legacy de SiVale (`docs/context/snapshot-scripts.txt`) con el producto actual y con el destino planificado en E10.

## 1. Regla de evidencia

Un comando que retorna `0` **no demuestra por sí solo paridad de toda la operación**. Cada responsabilidad relevante debe tener evidencia independiente.

Se distinguen:

- **CI/componente:** prueba determinista sin depender del entorno real;
- **PILOTO:** evidencia sobre el entorno SiVale real;
- **GAP E10:** responsabilidad requerida que el producto actual todavía no cubre completamente.

Hasta que E10-S4 cierre los GAPs y exista piloto real, E8-S1 no debe presentarse como paridad operacional completa.

## 2. Invariantes que ya permanecen vigentes

1. target identifica inequívocamente workspace;
2. branch/path/puertos/runtime no deben colisionar entre targets soportados;
3. fallo parcial no destruye recursos preexistentes;
4. `destroy` protege trabajo útil;
5. `stop` preserva identidad y trabajo;
6. `start` no recrea Git;
7. capabilities opcionales pertenecen al target correcto;
8. no se resuelven gaps mediante acoplamiento SiVale en core.

## 3. Matriz descompuesta por responsabilidad

| Operación | Responsabilidad legacy | Producto actual | Evidencia actual | Estado previo a E10 |
|---|---|---|---|---|
| init | validar target/naming | config + target normalizer | `tests/conformance/test_sivale_profile.py::test_ac02_sivale_target_normalizes` | PASS |
| init | crear branch/worktree | core `init` | `tests/conformance/test_sivale_parity.py::test_init_new` | PASS |
| init | bloquear duplicado | safety/core | `tests/conformance/test_sivale_parity.py::test_init_duplicate_blocked` | PASS |
| init | reservar puerto aislado | ports capability | `tests/conformance/test_sivale_parity.py::test_two_parallel_workspaces_isolated` + `test_destroy_clean_releases_resources` | PASS |
| init | identidad runtime por target | runtime driver | `tests/unit/test_docker_compose_driver.py` + `scripts/validate-sivale-pilot.sh` | PASS componente; piloto pendiente |
| init | materializar config runtime local | runtime `materialize_env_file` + `compose_files` opcional (E10-S1 §12) | `tests/unit/test_e10_s1_runtime_provisioning.py::test_ac07_env_file_copied_when_declared` + `tests/unit/test_docker_compose_driver.py` (H5.B) | PASS componente |
| init | preparar DB aislada desde base | data/postgres provisioning (E10-S3) | `tests/conformance/test_sivale_parity.py::test_e10_init_drives_full_provisioning` + `tests/unit/test_e10_s3_data_postgres.py` | PASS componente; piloto pendiente |
| init | build del runtime desde worktree actual | runtime `provision` + `build_on_provision` (E10-S1) | `tests/unit/test_e10_s1_runtime_provisioning.py::test_ac06_provision_with_build_uses_up_build` | PASS componente |
| init | arrancar runtime como parte del workspace listo | runtime `provision` en `after_init`/`after_adopt` (E10-S1) | `tests/conformance/test_sivale_parity.py::test_e10_init_drives_full_provisioning` | PASS componente; piloto pendiente |
| init | instalar Composer dependencies | bootstrap/composer (E10-S2) | `tests/conformance/test_sivale_parity.py::test_e10_init_drives_full_provisioning` + `tests/unit/test_e10_s2_bootstrap.py::test_ac03_host_uses_exact_argv_and_cwd` | PASS componente; piloto pendiente |
| init | normalizar/verificar permisos efectivos | bootstrap writable probe (E10-S2) | `tests/unit/test_e10_s2_bootstrap.py::test_ac05_writable_probe_host` + `test_ac04_runtime_uses_executor_not_docker` | PASS componente |
| init | verificar artifacts requeridos | bootstrap artifact readiness (E10-S2) | `tests/unit/test_e10_s2_bootstrap.py::test_ac06_artifacts_validated` + `test_ac06_executable_artifact` | PASS componente |
| init | tmux | capability tmux | `tests/unit/test_tmux_capability.py` + piloto real | PASS componente; piloto pendiente |
| init | abrir Kiro opcional | integration | `tests/unit/test_integration_adapters.py` + piloto real | PASS componente; piloto pendiente |
| adopt | preservar/adoptar Git compatible/dirty | core `adopt` | `tests/conformance/test_sivale_parity.py::test_adopt_branch_only` + `tests/unit/test_adopt.py::test_ct02_existing_compatible_dirty_reports_dirty` | PASS |
| adopt | completar provisioning del workspace | `after_adopt` + runtime/data/bootstrap (E10-S0..S3) | `tests/conformance/test_sivale_parity.py::test_e10_adopt_completes_provisioning` | PASS componente; piloto pendiente |
| status | observar Git/capabilities existentes | `status` | `tests/unit/test_status.py` | PASS para capacidades actuales |
| stop/start | preservar Git y suspender/reactivar resources | lifecycle/capabilities | `tests/conformance/test_sivale_parity.py::test_start_stop_preserve_identity` + piloto real | PASS base; piloto real pendiente |
| destroy | dirty guard | core safety | `tests/conformance/test_sivale_parity.py::test_destroy_dirty_blocked` | PASS |
| destroy | retirar worktree/branch según policy | core | `tests/conformance/test_sivale_parity.py::test_destroy_clean_releases_resources` | PASS |
| destroy | liberar puerto | ports | `tests/conformance/test_sivale_parity.py::test_destroy_clean_releases_resources` | PASS |
| destroy | cleanup runtime | runtime cleanup (`down`/`down -v` con `remove_volumes_on_destroy`, E10-S1) | `tests/unit/test_e10_s1_runtime_provisioning.py::test_ac10_remove_volumes_opt_in` | PASS componente; piloto pendiente |
| destroy | cleanup data aislada propia | data `cleanup_mode="runtime"` delega el `down -v` target-scoped al runtime (E10-S3) | `tests/unit/test_e10_s3_data_postgres.py::test_ac10_cleanup_runtime_ok_with_remove_volumes` | PASS componente; piloto pendiente |
| paralelismo | dos workspaces Git/ports | locks + ports | `tests/conformance/test_sivale_parity.py::test_two_parallel_workspaces_isolated` + `tests/conformance/test_conformance_robustness.py::test_port_race_no_duplicate` | PASS determinista |
| paralelismo | runtime/data reales concurrentes | requiere entorno real + E10 | piloto no ejecutado | PENDIENTE (evidencia operacional) |
| fallo parcial | rollback genérico | LifecycleTransaction | `tests/conformance/test_sivale_parity.py::test_partial_failure_rolls_back` + `tests/unit/test_hook_transaction_journal.py` | PASS genérico; E10 integra recursos nuevos (bootstrap/data NOT_SAFE diagnosable) |

## 4. Clasificación de gaps

### GAP-P1 — Workspace provisioning

**Clasificación:** `CAPABILITY_GAP` — **CERRADO en E10-S0**.

El contrato genérico de provisioning existe: `after_init` (ya existía) y el nuevo
`after_adopt` ejecutan capabilities bajo la `LifecycleTransaction` común, sin
scripts específicos del proyecto.

### GAP-P2 — Runtime durante provisioning

**Clasificación:** `CAPABILITY_GAP` sobre runtime existente — **CERRADO en E10-S1**.

El runtime gana `provision()` y el protocolo `RuntimeCommandExecutor`; no se creó
otro runtime subsystem.

### GAP-P3 — Dependencies/readiness

**Clasificación:** `CAPABILITY_GAP` — **CERRADO en E10-S2**.

Capability `bootstrap` con provider `composer` (executor host/runtime), writable
probe y artifact readiness. Composer es el primer caso real, no universal.

### GAP-P4 — PostgreSQL data provisioning

**Clasificación:** `CAPABILITY_GAP` con provider tecnológico — **CERRADO en E10-S3**.

Capability `data` con provider `postgres` sobre el runtime execution contract.
PostgreSQL no entra al core.

### GAP-P5 — Evidencia real

**Clasificación:** `PENDING_OPERATIONAL_EVIDENCE`.

La paridad de responsabilidad está demostrada de forma **determinista** (suite +
conformance). El piloto real con runtime/puertos/tmux/Kiro y concurrencia
efectiva sobre el entorno SiVale sigue pendiente de ejecutarse en ese entorno y
archivarse bajo `docs/evidence/` (ver `docs/evidence/sivale-e10-pilot.md`).

## 5. Divergencias intencionales que no son blocker

- El lifecycle base no necesita preservar exactamente la variable personal `KIRO_DEVELOPER`; la identidad debe derivarse del contrato genérico.
- Operaciones de red Git no exigidas por el producto base no se incorporan sólo por imitar el Bash legacy.
- No se exige copiar la implementación de `pg_dump/psql` literalmente; se exige el resultado funcional seguro definido por E10-S3.
- La resolución del `RuntimeCommandExecutor` por parte de `data`/`bootstrap` usa el registry global de drivers (`register_driver`), no la instancia concreta: en producción docker-compose está registrado globalmente, así que los providers resuelven el mismo executor que el runtime activo.

## 5bis. Identidad del runtime base developer-scoped (H5.C / F2) — cerrado a nivel de contrato

El harness legacy deriva el runtime base compartido con una identidad developer-scoped (`zurich-$KIRO_DEVELOPER`, resuelta desde configuración personal, nunca desde el core). `base_project_pattern` (E10-S1 R9) sólo sustituye `{project}` en el TOML compartido; no ofrece, ni debe ofrecer, un placeholder `{developer}` en el core (violaría INV-007/INV-008).

Una auditoría posterior (F2) encontró que la solución documentada anteriormente ("resolverlo en configuración personal") no tenía un mecanismo real conectado al contrato: la interfaz `PersonalConfigSource` no tiene implementación activa en el CLI de producción, y sin un override de entorno específico el TOML compartido siempre ganaba sobre cualquier intento de personalización.

Se cerró con la variable de entorno `IMASS_WT_RUNTIME_BASE_PROJECT_PATTERN` (E10-S1 §13 R14), que reutiliza el mecanismo genérico ya existente de `_ENV_OVERRIDES` (mismo patrón que `IMASS_WT_BASE_BRANCH`): un desarrollador exporta esa variable en su propio entorno (no versionado) y `capabilities.runtime.base_project_pattern` la honra con precedencia mayor que el TOML compartido, **sólo si `[capabilities.runtime]` ya estaba declarado** (nunca activa la capability por sí sola, INV-009). El core sigue sin conocer `KIRO_DEVELOPER`, `zurich` ni `sivale`.

Con esto, `data`/E10-S3 (que restaura desde el runtime base en `RuntimeScope.PROJECT`) resuelve la identidad Compose real que el desarrollador usa, en vez de siempre `{project}`. Evidencia determinista: `tests/unit/test_config_loader.py` (casos `test_f2_*`), incluyendo un test end-to-end contra la config real de SiVale.

Lo que sigue pendiente, exclusivamente para el piloto operacional real (no bloqueante a nivel de contrato): confirmar en el entorno SiVale real que, con `IMASS_WT_RUNTIME_BASE_PROJECT_PATTERN` configurado en el shell del desarrollador, el `pg_dump` de `data` efectivamente apunta al mismo Compose project que el desarrollador usa día a día, y no a uno distinto.

## 6. Criterio de cierre

Esta matriz distingue explícitamente dos niveles de evidencia, y sólo el primero está cerrado hoy:

- **`DETERMINISTIC_PARITY`** — paridad de contrato demostrada por suite + conformance reproducible en CI, sin depender del entorno real. Requiere:
  1. E10-S0..S3 implementadas y mergeadas;
  2. cada responsabilidad obligatoria de la matriz tiene evidencia determinista
     (componente/conformance) referenciada;
  3. suite completa + conformance en verde;
  4. ningún script legacy conserva una responsabilidad exclusiva necesaria: cada
     responsabilidad de `compose-project.sh`, `worktree-adopt.sh`,
     `worktree-init.sh` y `worktree-teardown.sh` está cubierta por core +
     capabilities (ver §7);
  5. no existe acoplamiento SiVale/Laravel en el core
     (`tests/conformance/test_sivale_profile.py::test_ac07_no_sivale_conditionals_in_core`).

  **`DETERMINISTIC_PARITY = PASS`** — los 5 puntos anteriores están cumplidos.

- **`SIVALE_PARITY`** — paridad operacional real, exigida explícitamente por E10-S4 R5/R9/AC-05/AC-09 y por la Task 10 de la spec ("sólo entonces declarar SIVALE_PARITY = PASS"): requiere el piloto real sobre el entorno SiVale (dos targets concurrentes, runtime real, DB origen/target reales, Composer/readiness reales, tmux/Kiro reales, destroy real) archivado en `docs/evidence/sivale-e10-pilot.md`. Mientras ese piloto no se ejecute, **`SIVALE_PARITY` NO puede declararse `PASS`**: el estado correcto es `PENDING_OPERATIONAL_EVIDENCE`.

El retiro físico de los scripts legacy pertenece al proyecto SiVale y sólo procede después de que `SIVALE_PARITY = PASS` (piloto real), nunca a partir de `DETERMINISTIC_PARITY` únicamente.

**Estado actual:** `DETERMINISTIC_PARITY = PASS`; `SIVALE_PARITY = PENDING_OPERATIONAL_EVIDENCE` (piloto real no ejecutado en este entorno; ver `docs/evidence/sivale-e10-pilot.md`).

## 7. Mapa de reemplazo de scripts legacy

| Script legacy | Responsabilidad exclusiva previa | Cubierto por |
|---|---|---|
| `compose-project.sh` | identidad Compose + `.env` autoritativo | runtime driver docker-compose (`project_pattern`/`base_project_pattern`, `materialize_env_file`) |
| `worktree-init.sh` | branch/worktree + puerto + runtime + deps + readiness | core `init` + ports + runtime `provision` + bootstrap + data |
| `worktree-adopt.sh` | adopción + provisioning equivalente + `pg_dump/psql` | core `adopt` + `after_adopt` + data postgres (`pg_dump`/`psql`) + bootstrap |
| `worktree-teardown.sh` | guards + cleanup runtime/data/puerto/worktree | core `destroy` + runtime `cleanup` (`down -v` opt-in) + data `cleanup_mode="runtime"` + ports release |

Ninguna de esas responsabilidades requiere ya un script del cliente: todas
pertenecen al producto (core + capabilities). El retiro físico de los scripts
es una tarea del repositorio SiVale posterior al piloto real.
