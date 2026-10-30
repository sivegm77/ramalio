# Segundo piloto — matriz de conformidad (E9-S0)

Valida que un proyecto **materialmente distinto** a SiVale adopta
`imass-worktree` sólo por configuración, sin tocar el core.

Perfil: `pylib-tools` (ver `docs/examples/second-pilot.imass-worktree.toml`).

> **Alcance de esta evidencia.** `pylib-tools` es un **fixture sintético**
> construido dentro del test (`tests/conformance/test_second_pilot.py`): `git
> init` + commit semilla + este TOML. Demuestra que el **core soporta un perfil
> materialmente distinto** a SiVale, lo cual es una prueba válida de
> desacoplamiento/genericidad. **No** demuestra que un **segundo proyecto real
> de iMass** haya adoptado `imass-worktree` y lo opere cotidianamente, que es lo
> que E9-S0 exige (§2, R2, R12). Ese cierre operacional se realiza siguiendo
> `docs/second-pilot-checklist.md` sobre un repo real y archivando la evidencia
> en `docs/evidence/`. Este fixture se conserva como perfil permanente de
> conformance, no como sustituto de esa evidencia.

## Justificación del perfil (R1, §5)

Difiere de SiVale en (≥3 requerido):

- **Sin runtime containerizado** (no Docker Compose).
- **Lenguaje/uso distinto**: librería/CLI Python, no aplicación web.
- **Sin Kiro obligatorio**, **sin tmux**, **sin puertos exclusivos**, **sin zrok**.
- **Convención de target distinta**: `issue-<n>-<slug>` vs. `E<n>-S<n>-<slug>`.
- **Branch naming distinto**: `wt/{target}` vs. `spec/{target}`.
- **Normalización distinta**: `preserve_prefix_segments = 0` vs. `2`.

No es un clon operativo de SiVale.

## Inventario operativo (R2)

| Aspecto | Valor |
|---|---|
| Unidad de trabajo | issue-<numero>-<slug> |
| Branch base | main |
| Naming de branch | `wt/<target>` |
| Worktrees | `.worktrees/<target>` |
| Bootstrap | ninguno (Git-only) |
| Procesos | ninguno |
| Runtime | ninguno |
| Puertos | ninguno |
| Herramientas dev | editor libre; sin integración obligatoria |
| Teardown | `destroy` con `delete_on_destroy = true` |
| Riesgos | pérdida de trabajo local → cubierto por guards de destroy |

## Matriz (§8.2)

| Área | Evidencia esperada | Test | Resultado |
|---|---|---|---|
| Config | TOML válido y suficiente | `test_ac02_config_loads` | PASS |
| Target | validación/normalización de convención distinta | `test_ac01_different_target` | PASS |
| Git | branch/worktree deterministas (`wt/`, `.worktrees/`) | `test_ac01_different_target` | PASS |
| Lifecycle | init/adopt/destroy | `test_full_lifecycle`, `test_ac05_adopt` | PASS |
| Operación | list/status/start/stop | `test_full_lifecycle` | PASS |
| Diagnóstico | doctor PASS Git-only | `test_ac03_doctor_healthy` | PASS |
| Extensibilidad | capabilities sólo si aplican (aquí ninguna) | `test_ac02_config_loads` | PASS |
| Seguridad | destroy bloquea trabajo dirty | `test_ac08_destroy_blocks_dirty` | PASS |
| Concurrencia | 2 workspaces aislados | `test_parallel_isolated` | PASS |
| Core | sin reglas específicas del proyecto | `test_ac07_no_sivale_conditionals_in_core` (E8-S0) + config-only | PASS |

## Clasificación de gaps (R8)

Ningún gap encontrado. La adopción fue 100% por configuración:

- Convención de target distinta → **CONFIG_GAP resuelto** (regex/normalization).
- Branch naming distinto → **CONFIG_GAP resuelto** (`branch.pattern`).
- Ausencia de runtime/puertos/tmux/kiro → **no aplica** (capabilities opcionales
  deshabilitadas; el lifecycle Git-only funciona, AC-09).

No se introdujo ninguna condición `if project == ...` en el core (AC-10/INV-01).

## Regresión SiVale (R11/AC-12)

La suite completa (incluida la conformidad de SiVale de E8) se ejecuta verde tras
este piloto; no hubo cambios de core, por lo que no hay riesgo de regresión.

## Resultado (R12/AC-11)

**PASS a nivel de genericidad (conformance sintético):** el core soporta el
perfil `pylib-tools` — materialmente distinto a SiVale — 100% por
configuración, sin scripts fuera del contrato y sin conocimiento del proyecto
embebido en el core (AC-10/INV-01). Esto prueba que `imass-worktree` no quedó
acoplado al primer piloto.

**PENDIENTE a nivel de piloto real (E9-S0 §2/R2/R12):** falta adoptar un
**segundo proyecto real** de iMass, inventariar su lifecycle real, operarlo con
`imass-wt` y archivar la evidencia. El fixture sintético no sustituye ese paso.
Procedimiento y checklist: `docs/second-pilot-checklist.md`.
