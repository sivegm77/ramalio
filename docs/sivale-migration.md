# Migración operativa de SiVale a `ramalio` (E8-S2 / convergencia E10)

## 1. Estado actual

E10-S0..S4 están implementadas y mergeadas, e incluyen la ronda de remediación
post-auditoría (hallazgos H1..H7: seguridad del writable probe/artifacts,
boundary de `materialize_env_file`, fail-closed de `[capabilities.runtime]`,
paridad exacta de la configuración runtime real de SiVale y soporte de
`docker-compose.override.yml`).

Este documento distingue explícitamente dos niveles de paridad (ver
`docs/examples/sivale-parity-matrix.md` §6):

- **`DETERMINISTIC_PARITY = PASS`** — cada responsabilidad del lifecycle
  legacy tiene una capability/provider equivalente en el producto, demostrado
  por suite + conformance reproducible en CI (sin depender de Docker/
  PostgreSQL/tmux/Kiro reales).
- **`SIVALE_PARITY = PENDING_OPERATIONAL_EVIDENCE`** — la migración **no debe
  considerarse operacionalmente cerrada** hasta ejecutar el piloto real sobre
  el entorno SiVale (dos targets concurrentes, runtime/datos/dependencias
  reales, `destroy` real) y archivar la evidencia en
  `docs/evidence/sivale-e10-pilot.md`.

El core continúa agnóstico: SiVale se expresa mediante configuración +
capabilities/providers opcionales (`runtime`, `data`, `bootstrap`), nunca
mediante condiciones SiVale/Laravel en el core
(`tests/conformance/test_sivale_profile.py::test_ac07_no_sivale_conditionals_in_core`).

## 2. Flujo objetivo

La interfaz canónica permanece:

```bash
ramalio init <target>
ramalio adopt <target>
ramalio status <target>
ramalio stop <target>
ramalio start <target>
ramalio destroy <target>
ramalio list
```

Y opcionalmente:

```bash
ramalio init <target> --open kiro
```

Con la configuración de `docs/examples/sivale.ramalio.toml`, `init` y
`adopt` ya disparan runtime provisioning (build + start del compose del
target), data provisioning PostgreSQL (snapshot del runtime base + restore
aislado por target) y bootstrap Composer + readiness — demostrado
deterministamente en `tests/conformance/test_sivale_parity.py`. Lo que falta
demostrar es que esas mismas responsabilidades funcionan igual sobre el
entorno SiVale real (§5).

## 3. Clasificación temporal de wrappers legacy

| Script legado | Responsabilidad real | Estado actual | Condición para `REPLACED` |
|---|---|---|---|
| `worktree-init.sh` | Git + puerto + runtime + DB + build + permisos + dependencies/readiness | **DETERMINISTIC_PARITY: PASS** — cubierto por core + `ports` + `runtime.provision` + `data` + `bootstrap` | `SIVALE_PARITY = PASS` (piloto real ejecutado) |
| `worktree-adopt.sh` | adopción Git + provisioning equivalente | **DETERMINISTIC_PARITY: PASS** — `after_adopt` dispara el mismo provisioning que `after_init` | `SIVALE_PARITY = PASS` (piloto real ejecutado) |
| `worktree-teardown.sh` | guards + cleanup de runtime/data/puerto/worktree | **DETERMINISTIC_PARITY: PASS** — `destroy` + `runtime.cleanup` (`down -v` opt-in) + `data.cleanup_mode="runtime"` (delegado) + `ports` release | `SIVALE_PARITY = PASS` (piloto real ejecutado) |
| `compose-project.sh` | ejecución Compose con identidad/env aislados | **DETERMINISTIC_PARITY: PASS** — runtime `project_pattern`/`base_project_pattern`, `materialize_env_file`, `compose_files` (override opcional) | `SIVALE_PARITY = PASS` (piloto real ejecutado) |
| `developer.env` | preferencias personales | **CONSERVADO/PERSONAL** | no se versiona como secreto/config compartida; la identidad developer-scoped del runtime base se resuelve vía `RAMALIO_RUNTIME_BASE_PROJECT_PATTERN` (entorno personal, ver `docs/examples/sivale-parity-matrix.md` §5bis) |

Ningún script conserva ya una responsabilidad **exclusiva** a nivel de
contrato (ver el mapa detallado en `docs/examples/sivale-parity-matrix.md`
§7): cada responsabilidad tiene una capability/provider equivalente en el
producto. Lo que impide su retiro físico hoy es exclusivamente la falta de
evidencia operacional real (§5), no una brecha de contrato.

## 4. Regla de retiro

Un script sólo puede retirarse cuando simultáneamente:

1. su responsabilidad esté clasificada;
2. exista alternativa implementada/documentada (✅ cumplido para las cuatro
   filas de §3);
3. la matriz de paridad tenga evidencia suficiente — **determinista** (✅
   cumplido) **y operacional real** (❌ pendiente, §5);
4. ningún flujo/test real dependa de la responsabilidad legacy;
5. exista rollback operativo razonable durante la transición.

No se elimina un script sólo porque `ramalio init` o `destroy` retornen
éxito, ni sólo porque la evidencia determinista esté en verde: el punto 3
exige ambos niveles.

## 5. Qué falta para `SIVALE_PARITY = PASS`

Únicamente el piloto operacional real sobre el entorno SiVale:

- `ramalio init` real con runtime construido/arrancado, base PostgreSQL
  restaurada desde la base compartida, Composer instalado y artifacts
  verificados, tmux y `--open kiro`;
- `ramalio adopt` real preservando trabajo y completando el provisioning que
  falte;
- dos targets simultáneos con aislamiento real de
  branch/path/port/runtime/data (identidades Compose y bases de datos
  distintas y verificables, no sólo puertos distintos);
- `ramalio destroy` real retirando volúmenes del target sin afectar otros
  targets ni el runtime base compartido.

El procedimiento y las verificaciones exactas que el script de piloto debe
capturar están en `docs/evidence/sivale-e10-pilot.md` §4.

## 6. Qué NO debe ocurrir

- `framework = "laravel"` controlando el core;
- `if project == "sivale"`;
- copiar los scripts legacy dentro del producto como solución;
- exigir al proyecto cliente nuevos scripts de worktree;
- hacer Docker/PostgreSQL/Composer obligatorios para otros proyectos;
- declarar `SIVALE_PARITY = PASS` sin el piloto real ejecutado.

## 7. Evidencia

La evidencia determinista (Git, safety, locks, ports, runtime/data/bootstrap
provisioning, tmux/integrations) es completa y está en verde
(`DETERMINISTIC_PARITY = PASS`). Ver `docs/examples/sivale-parity-matrix.md` y
`docs/evidence/sivale-e10-pilot.md`.

## 8. Estado de migración

```text
Git/worktree core                  PASS
capabilities existentes            PASS
provisioning completo SiVale       DETERMINISTIC_PARITY: PASS
piloto real final                  PENDIENTE (SIVALE_PARITY: PENDING_OPERATIONAL_EVIDENCE)
retiro definitivo harness legacy   BLOQUEADO hasta SIVALE_PARITY = PASS
```
