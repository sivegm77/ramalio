# Evidencia — paridad SiVale E10 (E10-S4)

Este documento archiva la evidencia de la convergencia de paridad SiVale de la
etapa E10 y deja explícito qué evidencia es determinista (reproducible en CI) y
qué evidencia operacional real sigue pendiente.

Se distinguen explícitamente dos niveles (ver `docs/examples/sivale-parity-matrix.md` §6):

- **`DETERMINISTIC_PARITY`** — paridad de contrato demostrada por suite + conformance, sin depender del entorno real.
- **`SIVALE_PARITY`** — paridad operacional real, exigida por E10-S4 R5/R9/AC-05/AC-09/Task 10, que sólo puede declararse `PASS` después de ejecutar el piloto real.

**Estado en este documento:** `DETERMINISTIC_PARITY = PASS`; `SIVALE_PARITY = PENDING_OPERATIONAL_EVIDENCE`. Ninguna sección de este documento debe leerse como que la paridad operacional está cerrada.

## 1. Alcance

E10-S4 configura SiVale como proyecto cliente usando exclusivamente los
contratos E10-S0..S3 (workspace provisioning, runtime provisioning, bootstrap
Composer, data PostgreSQL) y demuestra equivalencia con el lifecycle legacy
descrito en `docs/context/snapshot-scripts.txt`, sin introducir conocimiento de
SiVale/Laravel en el core.

La configuración real vive en `docs/examples/sivale.imass-worktree.toml`.

## 2. Evidencia determinista (reproducible, PASS)

Ejecutada por la suite completa del repositorio (`pytest`), sin depender de un
entorno real con Docker/PostgreSQL/tmux/Kiro:

- **Configuración válida contra el registry de producción**:
  `tests/conformance/test_sivale_parity.py::test_e10_config_is_accepted_by_default_registry`
  — la config E10 de SiVale (runtime + data + bootstrap + tmux) valida contra el
  `default_registry()` real, incluyendo la precondición de
  `data.cleanup_mode="runtime"` (runtime docker-compose con
  `remove_volumes_on_destroy=true`).
- **Init dispara todo el provisioning**:
  `tests/conformance/test_sivale_parity.py::test_e10_init_drives_full_provisioning`
  — `init` ejecuta runtime `provision`, data provisioning (ensure_service en
  scope project y workspace, `pg_dump` en source, `psql` restore en target vía
  el `RuntimeCommandExecutor`) y bootstrap Composer.
- **Adopt completa el provisioning equivalente**:
  `tests/conformance/test_sivale_parity.py::test_e10_adopt_completes_provisioning`.
- **Invariantes de lifecycle** (init/adopt/start/stop/destroy, dirty guard,
  aislamiento de dos targets, rollback de fallo parcial): resto de
  `tests/conformance/test_sivale_parity.py`.
- **Contratos de capability por componente**:
  `tests/unit/test_e10_s1_runtime_provisioning.py`,
  `tests/unit/test_e10_s2_bootstrap.py`,
  `tests/unit/test_e10_s3_data_postgres.py`.
- **No coupling SiVale/Laravel en el core**:
  `tests/conformance/test_sivale_profile.py::test_ac07_no_sivale_conditionals_in_core`.

## 3. Mapa de reemplazo de scripts legacy

Ver `docs/examples/sivale-parity-matrix.md` §7. Cada responsabilidad exclusiva
de `compose-project.sh`, `worktree-init.sh`, `worktree-adopt.sh` y
`worktree-teardown.sh` está cubierta por core + capabilities del producto. El
retiro físico de esos scripts pertenece al repositorio SiVale y sólo procede
tras el piloto operacional real (§4).

## 4. Evidencia operacional real — PENDIENTE

Lo siguiente NO puede reproducirse en CI y requiere el entorno SiVale real
(Docker Compose, PostgreSQL, tmux, Kiro y concurrencia efectiva). Queda como
evidencia operacional pendiente (GAP-P5, `PENDING_OPERATIONAL_EVIDENCE`):

- `imass-wt init` real de un target SiVale con runtime construido/arrancado,
  base PostgreSQL restaurada desde la base compartida, dependencias Composer
  instaladas y artifacts verificados, tmux y `--open kiro`.
- `imass-wt adopt` real preservando trabajo y completando el provisioning que
  falte.
- Dos targets simultáneos demostrando aislamiento real de
  branch/path/port/runtime/data.
- `imass-wt destroy` real limpiando runtime (`down -v`), data y puerto.

Procedimiento sugerido de captura: ejecutar `scripts/validate-sivale-pilot.sh`
en el entorno SiVale y archivar aquí la salida (fechada), incluyendo los
identificadores de proyecto Compose por target y la verificación de que ningún
recurso se comparte entre targets.

El script de piloto debe capturar específicamente las garantías nuevas de E10
(no basta con que `imass-wt init` termine con exit code 0):

- que el runtime del target realmente construyó/arrancó (`docker compose ps`
  del proyecto derivado, no sólo el código de salida de `imass-wt`);
- que la base PostgreSQL del target contiene realmente los datos restaurados
  desde la base compartida (consulta de verificación, no sólo `pg_isready`);
- que Composer instaló dependencias reales y los artifacts declarados existen
  con los permisos esperados;
- que dos targets concurrentes usan identidades de proyecto Compose y bases de
  datos distintas y verificables (no sólo puertos distintos);
- que `destroy` retiró efectivamente los volúmenes del target
  (`remove_volumes_on_destroy=true`) y no afectó el runtime/datos de otro
  target ni del runtime base compartido.

## 5. Sección post-auditoría — hallazgos H1..H7 remediados

Una auditoría integral de la etapa E10 (posterior al merge inicial de S0..S4)
encontró 7 hallazgos reales, ninguno relacionado con este documento en sí, pero
relevante para la evidencia que aquí se archiva:

- H1..H4: vulnerabilidades de seguridad y un contrato no fail-closed,
  corregidos con regresiones en `tests/unit/test_e10_s2_bootstrap.py` y
  `tests/unit/test_e10_s1_runtime_provisioning.py`.
- H5: la configuración de ejemplo SiVale tenía tres divergencias respecto al
  runtime legacy real (`port_env` incorrecto, falta de soporte de
  `docker-compose.override.yml`, y una limitación no documentada sobre la
  identidad del runtime base developer-scoped). Las primeras dos están
  corregidas en el contrato (`compose_files`, E10-S1 §12); la tercera queda
  documentada como limitación conocida (E10-S1 §13) — es precisamente la razón
  por la que el piloto real (§4 de este documento) sigue siendo obligatorio
  antes de declarar `SIVALE_PARITY = PASS`.
- H6: este mismo documento y el tracker declaraban `SIVALE_PARITY = PASS`
  usando una redacción ambigua ("PASS (contract + deterministic evidence)").
  Se corrigió a la nomenclatura de dos niveles explícita de la cabecera de este
  documento.
- H7: se completó la documentación de producto pendiente
  (`docs/configuracion.md`, `docs/troubleshooting.md`,
  `docs/sivale-migration.md`).

Ninguno de estos hallazgos cambia el estado de este documento: `SIVALE_PARITY`
seguía y sigue siendo `PENDING_OPERATIONAL_EVIDENCE` antes y después de la
remediación; lo que cambió es que la evidencia determinista subyacente ahora es
más precisa y la declaración de estado ya no es ambigua.

**Estado:** pendiente de ejecución en el entorno real. Hasta entonces,
`SIVALE_PARITY = PENDING_OPERATIONAL_EVIDENCE`; `DETERMINISTIC_PARITY = PASS`.
