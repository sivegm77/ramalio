# AGENTS.md — Guía para agentes en Ramalio

Este archivo orienta a agentes de IA (y personas) que trabajan en este
repositorio. Léelo antes de proponer o aplicar cambios.

## Idioma

- Responde e interactúa **siempre en español**.
- Mantén sin traducir: código fuente, comandos, nombres de archivos, rutas,
  identificadores, clases, métodos, variables, APIs, librerías y mensajes de
  error cuando traducirlos reduzca la precisión.
- Los logs o mensajes originales en inglés pueden conservarse, pero explica su
  significado en español.

## Qué es este proyecto

`ramalio` es una herramienta y estándar operativo para gestionar
workspaces de desarrollo aislados basados en **Git worktrees**, con la relación
determinista `target → branch → worktree`.

**El lifecycle está implementado.** La superficie pública del CLI y los
contratos de resultado/error están congelados y respaldados por el lifecycle
real: `init`, `adopt`, `destroy`, `list`, `status`, `doctor`, `start` y `stop`
operan sobre Git/worktrees y coordinan capabilities e integrations opcionales.
Ya no hay comandos reservados devolviendo `NOT_IMPLEMENTED`; ese código de
salida se conserva en el contrato para superficies futuras aún no implementadas,
no para la familia de comandos actual.

Piezas ya materializadas (ver `CHANGELOG.md`):

- Capabilities opcionales: `processes`, `tmux`, `runtime` (drivers `none` y
  `docker-compose`, con workspace provisioning en `init`/`adopt`), `ports`,
  `tunnel` (zrok), `data` (provider `postgres`) y `bootstrap` (provider
  `composer`). Integrations: kiro/vscode/codex/claude.
- Transacciones y rollback (`LifecycleTransaction`), locks/concurrencia por
  recurso (`LockManager`), boundaries de seguridad symlink-aware
  (`SafePathResolver`) y ejecución controlada (`SafeProcessRunner`).
- Suite de conformidad end-to-end.

Toda operación mutable (`init`, `adopt`, `start`, `stop`, `destroy`) se ejecuta
bajo el lock por target y un contexto transaccional común, valida la
configuración de capabilities antes de mutar y verifica los boundaries de path
antes de crear o destruir un worktree. `init` y `adopt` ejecutan además el
workspace provisioning opcional (`after_init`/`after_adopt`): runtime, data y
bootstrap participan cuando el proyecto los habilita, reutilizando registry,
transacción, locks y `SafeProcessRunner` existentes.

El marco conceptual completo (autoritativo) está en
[`docs/standard-operativo.md`](docs/standard-operativo.md). Ante cualquier duda
de diseño, ese documento manda.

## Arquitectura y frontera de responsabilidades

```text
core genérico + configuración del proyecto cliente + capabilities + integrations
```

Antes de añadir cualquier funcionalidad, clasifícala (ver sección 8 del estándar):

1. ¿Comportamiento universal del lifecycle? → **CORE**
2. ¿Regla particular del repositorio cliente? → **CONFIGURACIÓN DEL PROYECTO**
3. ¿Comportamiento opcional del lifecycle? → **CAPABILITY**
4. ¿Herramienta externa que se abre/usa desde el workspace? → **INTEGRATION**
5. Si no encaja, justifica si realmente pertenece a `ramalio`.

## Invariantes que no se pueden romper

Estas invariantes de seguridad (sección 7 del estándar) son obligatorias:

- **INV-001** No pérdida silenciosa de trabajo local.
- **INV-002** `stop` preserva worktree, branch y cambios locales.
- **INV-003** `destroy` es conservador: ante duda, rechaza antes que destruir.
- **INV-004** `init` no sobrescribe worktrees/directorios/branches existentes.
- **INV-005** Un fallo nunca devuelve semántica de éxito.
- **INV-006** Un fallo parcial queda diagnosticable como inconsistente/degradado.
- **INV-007** El core es agnóstico de stack (no exige PHP, Node, Docker, etc.).
- **INV-008** Los secretos no viven en la configuración compartida versionable.
- **INV-009** Una capability opcional sigue siendo opcional.
- **INV-010** Se prefiere la autoridad externa (Git/recurso real) a duplicar estado.

## Convenciones de código

- **Python `>= 3.11`.** Usa sintaxis moderna: `from __future__ import annotations`,
  uniones con `|`, `dataclass(frozen=True, slots=True)`, `IntEnum`, etc.
- **Docstrings y comentarios de código en inglés**, siguiendo el estilo ya
  presente en `src/ramalio/`. (La interacción con el usuario es en
  español; el código existente documenta en inglés — respeta esa convención.)
- **Separación de responsabilidades del CLI:**
  - Los *handlers* de comandos **no imprimen**. Devuelven un `CommandResult`.
  - El *wrapper* del CLI (`cli.py`) es el único que renderiza a stdout/stderr.
  - `stdout` es para salida primaria/máquina; `stderr` para diagnósticos.
- **Errores esperados** se modelan con la jerarquía de
  `core/errors.py` (`RamalioError` y subclases). Cada uno mapea a un
  `ExitCode` estable. No inventes nuevos códigos sin actualizar el contrato.
- **Versión única de verdad:** `ramalio.__version__` en
  `src/ramalio/__init__.py`. `pyproject.toml` la deriva dinámicamente.
- No introduzcas dependencias nuevas sin justificarlo: `dependencies = []` hoy.

## Superficie pública del CLI (congelada)

Comandos con `TARGET`: `init`, `adopt`, `destroy`, `status`, `start`, `stop`.
Comandos sin `TARGET`: `list`, `doctor`.

No añadas, renombres ni elimines comandos de esta familia sin un cambio
deliberado del estándar. La lista vive en `PUBLIC_COMMANDS` (`cli.py`).

## Códigos de salida (contrato estable)

`0` OK · `2` USAGE_ERROR · `3` CONFIGURATION_ERROR · `4` STATE_ERROR ·
`5` SAFETY_BLOCKED · `6` OPERATION_FAILED · `70` INTERNAL_ERROR ·
`78` NOT_IMPLEMENTED.

## Comandos de desarrollo

```bash
# Entorno (requiere Python >= 3.11)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Pruebas (config en pyproject.toml)
pytest
```

## Flujo de trabajo esperado para un agente

1. Lee `docs/standard-operativo.md` y esta guía antes de cambiar diseño.
2. Clasifica toda necesidad nueva (core / config / capability / integration).
3. Respeta las invariantes de seguridad; ante duda, bloquea en lugar de destruir.
4. Escribe/ajusta pruebas en `tests/unit/` para cualquier cambio de comportamiento.
5. Ejecuta `pytest` y verifica que pasa antes de dar por terminado.
6. No introduzcas efectos secundarios fuera del contrato de cada comando; las
   operaciones mutables deben respetar locks, transacción, boundaries e
   invariantes de seguridad.

## Git

- No hagas commits salvo que se pida explícitamente.
- No hagas push directo a `main` sin permiso.
- Añade archivos concretos al *stage* en lugar de `git add .`.
- Señala cualquier archivo que pueda contener secretos antes de commitear.
