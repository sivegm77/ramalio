# Informe de implementación — Renombrado `imass-worktree` → Ramalio

> **Fecha del informe:** 2026-10-30
> **Estado:** COMPLETADO (ver sección H, que lista las reservas de validación; correcciones en la sección I)

---

## A. Resumen ejecutivo

Se renombró el producto `imass-worktree` a **Ramalio** en código, empaquetado,
CLI, configuración, variables de entorno, estado persistente, pruebas y
documentación operativa. No se implementó retrocompatibilidad.

Verificado en esta ronda en un entorno virtual nuevo, fuera del repositorio:

- El paquete se instala con `pip install -e ".[dev]"` y se importa como `ramalio`.
- El ejecutable `ramalio` responde a `--version`, `--help`, `doctor` y `list`
  con código de salida 0 (con configuración válida).
- La suite completa de pytest da **726 aprobadas, 4 omitidas, 0 fallidas**.

Estado del repositorio verificado al cierre de la última ronda (secciones G e I):

1. Los 40 registros históricos coinciden con `HEAD` en el índice y en el árbol de trabajo.
2. `changes.diff` existe en el árbol de trabajo, no está en staging y está excluido
   localmente con `.git/info/exclude`.
3. `.gitignore` es idéntico a `HEAD`. No forma parte del renombrado.

Este informe corrige afirmaciones de versiones anteriores: el número de pruebas
(no eran "~644"), la conservación de los registros históricos (no se conservaron
en la primera ronda) y el estado de `MM`/`AD` en el índice, que ya no se reproduce.

---

## B. Inventario de modificaciones

| Archivo / ubicación | Cambio | Motivo | Validación |
|---|---|---|---|
| `src/imass_worktree/` → `src/ramalio/` | Renombrado de directorio | Namespace Python | `import ramalio` en venv limpio |
| `pyproject.toml` | `name = "ramalio"`, `scripts.ramalio`, `version.attr = "ramalio.__version__"` | Distribución y entry point | `pip install -e` y `ramalio --version` |
| `src/ramalio/cli.py` | `prog="ramalio"`, mensajes, docstrings, `RamalioError` | Identidad CLI y errores | `ramalio --help` (8 comandos, código 0) |
| `src/ramalio/core/errors.py` | Base `RamalioError`, sin alias `ImassWorktreeError` | Jerarquía de errores | Comprobado: `RamalioError` exportada, `ImassWorktreeError` ausente |
| `src/ramalio/core/__init__.py` | Exportaciones | Contrato del core | Import OK |
| `src/ramalio/core/project.py` | `PROJECT_CONFIG_FILENAME = ".ramalio.toml"` | Descubrimiento de config | `doctor` con `.ramalio.toml` válido: PASS |
| `src/ramalio/config/loader.py` | `RAMALIO_BASE_BRANCH`, `RAMALIO_WORKTREE_DIRECTORY`, `RAMALIO_RUNTIME_BASE_PROJECT_PATTERN` | Overrides de entorno | Comprobado (sección D.4) |
| `src/ramalio/capabilities/tmux/runtime.py` | `OWNER_ENV_KEY = "RAMALIO_TARGET"`, `_DEFAULT_PATTERN = "ramalio-{target}"` | Ownership y default de sesión | Suite tmux |
| `src/ramalio/capabilities/runtime/docker_compose.py` | Fallbacks y default `"ramalio"` | Identidad de fallback Compose | Suite docker compose |
| `src/ramalio/resources/locks.py` | `_state_root()` → `ramalio` | Estado persistente | Comprobado (sección D.4) |
| `src/ramalio/resources/ports.py` | `_state_root()` → `ramalio` | Estado persistente | Comprobado (sección D.4) |
| `src/ramalio/capabilities/processes/runtime.py` | `_state_root()` → `ramalio`; `.imass-logs` → `.ramalio-logs` | Estado y recurso interno | Comprobado (sección D.4) |
| `src/ramalio/capabilities/tunnels/zrok.py` | `_state_root()` → `ramalio` | Estado persistente | Comprobado (sección D.4) |
| `src/ramalio/capabilities/bootstrap/composer.py` | `.imass-writable-probe` → `.ramalio-writable-probe` | Recurso interno | Suite bootstrap |
| `tests/**` | Imports `ramalio`, fixtures `*.ramalio.toml`, expectativas de nombres | Coherencia de pruebas | Suite completa |
| `tests/conformance/test_sivale_migration.py` | `test_migration_guide_present` con aserciones estrictas (H1) | Contrato de documentación | Ver sección I.1 |
| `tests/unit/test_tmux_secret_redaction.py` | `IMASS_WT_TARGET` → `RAMALIO_TARGET` (corrección I.3) | Identificador de ownership | Suite tmux |
| `tests/fixtures/profiles/*.ramalio.toml` | Renombrado de sufijo | Descubrimiento de config | Suite de perfiles |
| `docs/examples/{minimal,second-pilot,sivale}.ramalio.toml` | Renombrado de sufijo; contenido de cliente intacto | Ejemplos de config | Pruebas de ejemplos |
| `README.md`, `AGENTS.md`, `CHANGELOG.md` (entradas vigentes) | Identidad y comandos | Documentación operativa | Revisión manual |
| `docs/installation.md`, `docs/configuracion.md`, `docs/capabilities.md`, `docs/lifecycle.md`, `docs/troubleshooting.md`, `docs/getting-started.md`, `docs/integrations.md`, `docs/adoption-guide.md`, `docs/second-pilot-checklist.md`, `docs/sivale-migration.md`, `docs/plan-macro.md`, `docs/vision-y-alcance.md`, `docs/migration-from-scripts.md`, `docs/versioning-and-compatibility.md`, `docs/estructura-y-plan-specs.md`, `docs/standard-operativo.md`, `docs/workspace-provisioning.md`, `docs/context/README.md` | Identidad, comandos y variables vigentes | Guías operativas | Pruebas de contrato de documentación |
| `scripts/validate-sivale-pilot.sh` | Invocaciones `ramalio`, `.ramalio.toml` | Script de validación | Revisión; no ejecutado (ver G) |

Los registros históricos no se modificaron. Ver sección F y la corrección I.2.

---

## C. Decisiones aplicadas

### C.1. Identidad definitiva

| Elemento | Identidad |
|---|---|
| Producto | Ramalio |
| Distribución y paquete Python | `ramalio` |
| Ejecutable | `ramalio` |
| Archivo de config | `.ramalio.toml` |
| Variables de entorno | `RAMALIO_*` |
| Estado persistente | `~/.local/state/ramalio/` (o `$XDG_STATE_HOME/ramalio/`) |
| Marcador tmux | `RAMALIO_TARGET` |
| Error base | `RamalioError` |

### C.2. Política de compatibilidad (verificada contra el código)

No hay retrocompatibilidad. Comprobado en el venv aislado:

- **Ejecutable anterior:** `imass-wt` no existe en el entorno instalado. No hay
  alias ni entry point anterior en `pyproject.toml`.
- **Config anterior:** con un `.imass-worktree.toml` como único archivo, `ramalio doctor`
  reporta `FAIL CONFIG_PRESENT: .ramalio.toml not found` y sale con código 6.
  El archivo antiguo no se descubre.
- **Variables anteriores:** con `IMASS_WT_BASE_BRANCH=legacy-branch` y un
  `.ramalio.toml` que define `base_branch = "main"`, la configuración resuelve
  `main`. La variable antigua se ignora. Con `RAMALIO_BASE_BRANCH=release`, la
  configuración resuelve `release`.
- **Estado anterior:** las cuatro implementaciones de `_state_root()` apuntan a
  `<XDG_STATE_HOME o ~/.local/state>/ramalio`. No hay código que lea ni migre
  `imass-worktree`. Búsqueda en `src/`: cero coincidencias de `imass` en minúsculas o mayúsculas.
- **Símbolos anteriores:** `RamalioError` está exportada y `ImassWorktreeError` no existe
  en `ramalio.core.errors`.

Por tanto, el estado previo no se lee, no se migra y no hay compatibilidad hacia atrás.

---

## D. Pruebas ejecutadas

Entorno: venv nuevo en `/tmp/ramalio-verify-venv` (Python 3.11.13), creado fuera del
repositorio. Estado persistente aislado con `XDG_STATE_HOME=/tmp/ramalio-verify-state`.
Logs en `/tmp`, fuera del repositorio.

### D.1. Instalación y entry point

```bash
python3 -m venv /tmp/ramalio-verify-venv
/tmp/ramalio-verify-venv/bin/python -m pip install -e ".[dev]"   # exit 0
/tmp/ramalio-verify-venv/bin/python -c "import ramalio; print(ramalio.__version__)"
# 0.1.0 (desde src/ramalio/__init__.py)
/tmp/ramalio-verify-venv/bin/ramalio --version    # "ramalio 0.1.0", exit 0
/tmp/ramalio-verify-venv/bin/ramalio --help       # exit 0; lista init, adopt, destroy, list, status, doctor, start, stop
ls /tmp/ramalio-verify-venv/bin/imass-wt          # no existe
```

Limitación: la instalación editable crea `src/ramalio.egg-info/` dentro del
repositorio. Es un artefacto ignorado por `.gitignore` (`*.egg-info/`).

### D.2. Diagnóstico y lectura con el ejecutable instalado

| Escenario (repo temporal fuera del proyecto) | Comando | Resultado |
|---|---|---|
| Sin config | `ramalio doctor` | `FAIL CONFIG_PRESENT`, exit 6 |
| Config válida `.ramalio.toml` | `ramalio doctor` | `Global: PASS`, exit 0 |
| Config válida | `ramalio list` | "No managed workspaces found.", exit 0 |

No se ejecutaron `init`, `adopt`, `start`, `stop` ni `destroy` con el ejecutable
instalado, porque mutan Git y recursos. Los ocho comandos y sus contratos están
cubiertos por las pruebas de conformidad y lifecycle de la suite, que se ejecutaron
dentro del venv con el estado aislado.

### D.3. Suite completa de pytest

```bash
XDG_STATE_HOME=/tmp/ramalio-verify-state \
  /tmp/ramalio-verify-venv/bin/python -m pytest -p no:cacheprovider -rs
```

Resultado de la última ejecución, repetida después de las correcciones de documentación
de la sección I.5: **726 passed, 4 skipped, 0 failed, exit 0** (110.73 s). El resultado
coincide con la ejecución anterior (108.88 s). Las 4 omitidas son
`tests/unit/test_cli.py:83, 91, 100, 109`, parametrizadas con listas `RESERVED_*` vacías
porque todos los comandos ya están implementados. Esa lógica viene del código original,
no del renombrado.

Recolección comparada con el commit `HEAD` original (exportado a `/tmp`):
**730 pruebas en `HEAD` y 730 en el árbol renombrado.** No se eliminó ninguna prueba.

### D.4. Comprobaciones de identidad y de estado

Medidas directamente con el código instalado:

- `PROJECT_CONFIG_FILENAME == ".ramalio.toml"`.
- `_state_root()` de locks, ports, processes y zrok devuelve `/tmp/ramalio-verify-state/ramalio`.
- `OWNER_ENV_KEY == "RAMALIO_TARGET"`, `_DEFAULT_PATTERN == "ramalio-{target}"`.
- `sanitize_project_name("--__--") == "ramalio"`.
- `PUBLIC_COMMANDS == ('init','adopt','destroy','list','status','doctor','start','stop')`.

---

## E. Verificación de invariantes

La arquitectura, los contratos de comandos, los códigos de salida, `CommandResult`
y la lógica de locks, transacciones, boundaries y ejecución segura no se modificaron.
Solo cambiaron identificadores de identidad. La evidencia de conservación es la
suite de pruebas (726 aprobadas), incluidas las pruebas de seguridad, transacciones,
locks y conformidad. Esas pruebas se ejecutaron tal como están, salvo los cambios
nominales documentados en la sección B.

| Invariante | Evidencia |
|---|---|
| INV-001 a INV-006 (lifecycle y seguridad) | Suites `test_destroy`, `test_init`, `test_adopt`, `test_startstop`, `test_transactions`, `test_hook_transaction_journal`, `test_conformance_robustness` |
| INV-007 (core agnóstico) | `test_ac07_no_sivale_conditionals_in_core` y suite de conformidad SiVale/segundo piloto |
| INV-008 (secretos fuera de config compartida) | `test_tmux_secret_redaction`, `test_integration_env_policy` |
| INV-009 (capabilities opcionales) | `test_capabilities`, pruebas de runtime y del override condicional `RAMALIO_RUNTIME_BASE_PROJECT_PATTERN` |
| INV-010 (Git como autoridad) | `test_git_*`, `test_workspace_observer` |

---

## F. Referencias históricas conservadas

Se conservan sin modificar (idénticas a `HEAD` en el árbol de trabajo):

- `docs/specs/**` (37 especificaciones de las etapas 1 a 10). Sus nombres de carpeta y
  de archivo documentan su origen.
- `docs/evidence/sivale-e10-pilot.md`: evidencia de ejecución con el nombre anterior.
- `docs/examples/sivale-parity-matrix.md` y `docs/examples/second-pilot-conformance.md`:
  registros de cierre de las etapas E10-S4 y E9-S0. Describen la variable y el CLI
  vigentes en su momento. Sus enlaces a `*.imass-worktree.toml` apuntan a nombres
  que ya no existen; se dejan así porque son parte del registro.
- `docs/specs/implementation-status.json`: metadatos de PRs, commits y ramas.
- Entradas históricas de `CHANGELOG.md`. Solo se actualizaron la ruta del ejemplo SiVale
  y el comando de la entrada E9-S1 (`ramalio doctor`), que describen la identidad vigente.
- `imass-worktree.pdf`: binario sin cambios.
- Nombre de la organización **iMass** (por ejemplo, "segundo proyecto real de iMass").
  Es la organización del cliente, no el producto. Se conserva.

---

## G. Problemas encontrados y limitaciones

1. **Barrido global inicial (resuelto).** La primera versión de este informe afirmaba que
   los registros estaban intactos, y era falso: un `sed` global sobre `docs/` alteró 40
   registros históricos. Se restauraron desde `HEAD`. Estado verificado: los 40 archivos
   coinciden con `HEAD` en el índice y en el árbol de trabajo (H3, sección I.2).
2. **Restos operativos `IMASS_WT_*` (resuelto).** Quedaban en `docs/configuracion.md`,
   `docs/capabilities.md`, `docs/sivale-migration.md` y
   `tests/unit/test_tmux_secret_redaction.py`. La búsqueda previa usaba `imass` en
   minúsculas y no vio las variables en mayúsculas (sección I.3).
3. **`changes.diff` (resuelto).** El archivo existe en el árbol de trabajo y no está en
   staging. Su contenido no se modificó en esta ronda (SHA-256 idéntico antes y después de
   intervenir el `.gitignore`). Está excluido localmente con `/changes.diff` en
   `.git/info/exclude`. Durante la sesión el archivo se regeneró fuera de los comandos de
   esta tarea (835 008 bytes a las 12:42; 329 609 bytes a las 13:06). La versión que estuvo
   en el índice sigue recuperable como blob `ee86bdd539fb21e54c6b57a9014c0bc322d736d0`
   (426 532 bytes).
4. **`RENAME-IMPACT-RAMALIO.md`** ya no existe en el repositorio. Se creó al inicio del
   análisis. No lo referencia este informe y no se recreó.
5. **Script de validación no ejecutado.** `scripts/validate-sivale-pilot.sh` solo se revisó
   estáticamente. Muta worktrees, contenedores y volúmenes, y el encargo prohibía ejecutarlo.
6. **Validación no ejecutada:** pilotos reales (Docker Compose, tmux, zrok, Kiro) y
   ejecución de `init`/`destroy` con el ejecutable instalado sobre un repo real.
7. **Estado de staging (resuelto).** `docs/installation.md` y `docs/vision-y-alcance.md`
   tenían las correcciones de la sección I.5 sin preparar. En la verificación de la ronda
   H9/H10 ya no había cambios sin preparar: esas correcciones están en el índice. Esa
   ronda modifica solo este informe, que queda pendiente de `git add` por parte del
   responsable.

---

## H. Dictamen final

**COMPLETADO.**

| Criterio | Estado | Evidencia |
|---|---|---|
| AC-01 Distribución `ramalio` | Cumplido | `pyproject.toml`, `pip install -e` |
| AC-02 Paquete importable `ramalio` | Cumplido | Import en venv |
| AC-03 Único entry point `ramalio` | Cumplido | `ramalio --version` exit 0; `imass-wt` no existe |
| AC-04 Config `.ramalio.toml` | Cumplido | D.2, C.2 |
| AC-05 Variables `RAMALIO_*` | Cumplido | D.4, C.2 |
| AC-06 Estado en `ramalio` | Cumplido | D.4 |
| AC-07 `RamalioError` | Cumplido | C.2 |
| AC-08 Ocho comandos | Cumplido | `--help` lista los ocho; ejecución mutable cubierta por la suite (D.2, D.3). Reserva: sin ejecución mutable con el ejecutable instalado |
| AC-09 Capabilities e integrations | Cumplido | Suite completa (D.3). Reserva: sin piloto real (G.6) |
| AC-10 Invariantes de seguridad | Cumplido | E |
| AC-11 Pruebas pasan | Cumplido | 726 passed, 0 failed, repetido tras la última edición (D.3) |
| AC-12 Instalación y ejecución verificadas | Cumplido | D.1, D.2 |
| AC-13 Documentación operativa | Cumplido | B, I.5 |
| AC-14 Sin referencias operativas involuntarias | Cumplido | Búsqueda final sensible a mayúsculas (I.6) |
| AC-15 Sin cambios funcionales fuera del renombrado | Cumplido | Revisión de diff (B, I.6) |
| AC-16 Identidades de clientes y registros históricos intactos | Cumplido | 40 registros iguales a `HEAD` en índice y árbol (G.1) |
| AC-17 Sin commits ni push | Cumplido | `HEAD` sigue en `7bcd217` |
| AC-18 Sin pérdida de trabajo preexistente | Cumplido | Al iniciar, el único archivo sin seguimiento era el informe de impacto creado por esta sesión. Blob anterior de `changes.diff` recuperable; `changes.diff` actual sin modificar por esta tarea (G.3). Reserva: su regeneración ocurrió fuera de estos comandos y no se puede atribuir |

**Reservas de validación (se mantienen y no invalidan los criterios comprobados):**

- No se ejecutaron pilotos reales (Docker Compose, tmux, zrok, Kiro) ni el script
  `scripts/validate-sivale-pilot.sh` (G.5, G.6).
- No se ejecutaron comandos mutables (`init`, `adopt`, `start`, `stop`, `destroy`) con el
  ejecutable instalado sobre un repositorio real. Su comportamiento está cubierto por la
  suite (D.2, D.3).
- `changes.diff` se regeneró fuera de estos comandos y no se puede atribuir (G.3). Volvió a
  regenerarse a las 13:39 (337 086 bytes). Es un diff generado: no existía al iniciar la
  implementación, y la versión que estuvo en el índice sigue recuperable como blob
  `ee86bdd539fb21e54c6b57a9014c0bc322d736d0`.

**Por qué las reservas no invalidan los criterios.** Cada criterio AC-01 a AC-18 se apoya
en evidencia ejecutada o medida y registrada en este informe. Las reservas describen
validaciones adicionales que ningún criterio exige: el criterio AC-12 pide instalación y
ejecución verificadas (D.1, D.2), y AC-08 y AC-09 piden conservar contratos y
comportamiento, que prueba la suite completa (D.3). El código no cambió desde la última
ejecución de pytest (726 aprobadas, 4 omitidas, 0 fallidas).

---

## I. Corrección de hallazgos (auditoría)

### I.1. H1 — `test_migration_guide_present`: RESUELTO

- Se restauraron las aserciones estrictas:
  `assert "ramalio init" in text` y `assert "ramalio destroy" in text`.
- El comentario ahora dice que la guía debe documentar el CLI canónico `ramalio`, y que
  aceptar el nombre anterior ocultaría una regresión.
- Evidencia: `test_migration_guide_present` pasa (1 passed). El módulo
  `tests/conformance/test_sivale_migration.py` pasa completo (4 passed). El diff contra
  `HEAD` solo sustituye identificadores por los nuevos. No se debilitó ninguna aserción
  ni se eliminó ninguna prueba.
- Otros escenarios de conformidad no se modificaron.

### I.2. H2 y H3 — Informe y registros históricos: RESUELTO

- **Sección C.2:** reescrita y verificada contra el código.
- **Instalación:** verificada en venv aislado con el entry point `ramalio` (D.1, D.2).
  Lo que no se ejecutó está declarado en G.5 y G.6.
- **Pytest:** resultado real registrado (D.3). Las cifras "~644" y "61 files" de versiones
  anteriores no provenían de una ejecución y se retiraron.
- **Coherencia del dictamen:** secciones C.2, D, F, G y H reescritas.
- **Registros históricos (H3):** 40 archivos bajo `docs/specs/`, `docs/evidence/`,
  `docs/examples/second-pilot-conformance.md` y `docs/examples/sivale-parity-matrix.md`
  se restauraron desde `HEAD`. Antes de restaurar comprobé que los cambios eran solo
  sustituciones de nombre y que ninguna prueba los lee. **Estado verificado al cierre:**
  los 40 archivos coinciden con `HEAD` en el índice y en el árbol de trabajo.
  No existe ningún archivo en estado `MM` por este motivo.

### I.3. Restos operativos encontrados en la verificación: RESUELTO

- `docs/configuracion.md`, `docs/capabilities.md`, `docs/sivale-migration.md`:
  `IMASS_WT_*` → `RAMALIO_*` (la guía de migración documenta la variable vigente).
- `tests/unit/test_tmux_secret_redaction.py`: `IMASS_WT_TARGET` → `RAMALIO_TARGET`
  (identificador de ownership; la aserción prueba el mismo comportamiento).
- Búsqueda posterior: no quedan `IMASS_WT_*` fuera de este informe (que los describe) y de
  los registros conservados (`sivale-parity-matrix.md`, `sivale-e10-pilot.md`, specs).

### I.4. H4 y H5 — `changes.diff` y `.gitignore`: RESUELTO

- **H5:** la regla `*.diff` era la única diferencia de `.gitignore` frente a `HEAD`
  (verificado con `git diff HEAD`). Se restauró `.gitignore` a `HEAD` en índice y árbol
  de trabajo. Estado final: `.gitignore` sin diferencias con `HEAD`.
- **H4:** `changes.diff` existe en el árbol de trabajo, no está en staging y no se
  modificó: SHA-256 `75383a74...985cf2` idéntico antes y después. Se excluye localmente
  con `/changes.diff` en `.git/info/exclude`. Esa exclusión no forma parte del repositorio.

### I.5. H6, H7 y H8 — Documentación: RESUELTO

- **H6:** se conservan las dos modificaciones de `CHANGELOG.md` por decisión del
  responsable. Apuntan a artefactos vigentes: `ramalio doctor` y
  `docs/examples/sivale.ramalio.toml`.
- **H7:** `docs/vision-y-alcance.md` ya no limita el producto a iMass ni a "la empresa".
  Diez reemplazos puntuales: el producto se describe como herramienta para equipos de
  desarrollo genéricos. Se conservaron los ejemplos de agnosticismo (SiVale, Laravel,
  Docker, Kiro, etc.), porque ilustran independencia de stack. No cambia alcance,
  funcionalidades ni decisiones arquitectónicas. El título de la sección 7.3 cambió y
  ningún archivo ni prueba enlaza a esa ancla (verificado con búsqueda).
- **H8:** `sólamente` → `solamente` en las dos apariciones de `docs/installation.md`
  (líneas 4 y 114). Antes de este cambio la palabra no existía en `HEAD`.

### I.6. Validación final de la ronda

Resultados medidos al cierre:

- `git diff --cached --check`: sin problemas (exit 0).
- Preparados: 162 archivos, todos clasificados (72 `src/ramalio`, 63 `tests`,
  `pyproject.toml`, 1 script, 3 ejemplos TOML, 3 raíz, 17 guías `docs/*.md`,
  1 `docs/context`, 1 informe). Ninguna ruta sin clasificar.
- Registros históricos en el índice frente a `HEAD`: 0.
- `.gitignore` y `changes.diff`: ni modificados ni en staging.
- Sin preparar (árbol frente a índice): solo `docs/installation.md` (2 líneas),
  `docs/vision-y-alcance.md` (10 líneas) y este informe.
- `HEAD` sin cambios: `7bcd217`. No hubo commits ni push.
- Búsqueda sensible a mayúsculas de `imass_worktree`, `imass-worktree`, `imass-wt`,
  `IMASS_WT`, `ImassWorktreeError`, `.imass-worktree.toml` y `.imass-`, fuera de los
  registros conservados: una sola coincidencia, el comentario de
  `tests/conformance/test_sivale_migration.py:174`, que cita `imass-wt` para explicar
  por qué la aserción es estricta. Es intencional.
- Menciones a la organización **iMass** que quedan fuera de los registros: nombres de
  etapa en `docs/plan-macro.md` y `docs/estructura-y-plan-specs.md`, el contexto del
  segundo piloto y `docs/installation.md:94` ("canal interno autorizado de iMass").
  No se modificaron: el alcance autorizado cubría solo `vision-y-alcance.md`.

### I.7. Cambios fuera de alcance

Ninguno fuera del renombrado. Las correcciones de I.2 y I.3 pertenecen al renombrado y
se justifican aquí.

---

**Fin del informe.**
