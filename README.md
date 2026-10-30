# Ramalio

Herramienta y estándar operativo para gestionar workspaces de desarrollo aislados
basados en **Git worktrees**, con un lifecycle reproducible y configuración por
proyecto. El objetivo es que cada unidad de trabajo (un *target*) tenga una
relación determinista `target → branch → worktree`, sin que la herramienta se
convierta en una segunda fuente de verdad frente a Git.

> El lifecycle está implementado. La superficie pública del CLI y los contratos
> de resultado/error están congelados y respaldados por operaciones reales sobre
> Git/worktrees, con capabilities e integrations opcionales (ver `CHANGELOG.md`).
> Los comandos ya **no** devuelven `NOT_IMPLEMENTED`.

## Principios rectores

La arquitectura se organiza como:

```text
core genérico
+ configuración del proyecto cliente
+ capabilities opcionales
+ integrations opcionales
```

- **Git es autoridad sobre Git.** No se duplica información derivable de Git
  (commits, branches, worktrees).
- **El proyecto cliente es autoridad sobre sus reglas** (naming de targets,
  ubicación, bootstrap, capabilities e integrations).
- **Core agnóstico.** El core no requiere ningún stack concreto (Laravel, PHP,
  Node, Docker, tmux, etc.). Que la herramienta esté escrita en Python no
  convierte a Python en requisito del proyecto cliente.

El detalle completo del marco conceptual (glosario, modelo de autoridad,
estados, lifecycle e invariantes de seguridad) vive en
[`docs/standard-operativo.md`](docs/standard-operativo.md).

## Requisitos

- Python `>= 3.11`

## Instalación (desarrollo)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Esto expone el ejecutable de consola `ramalio`. Para incluir además las
herramientas de desarrollo (pruebas), instala el extra `dev`:

```bash
pip install -e ".[dev]"
```

## Uso

La superficie pública del CLI está congelada. Los comandos son:

| Comando   | Requiere TARGET | Descripción                                          |
| --------- | --------------- | ---------------------------------------------------- |
| `init`    | sí              | Crear un workspace administrado.                     |
| `adopt`   | sí              | Adoptar trabajo existente como workspace administrado.|
| `destroy` | sí              | Retirar de forma segura un workspace administrado.   |
| `status`  | sí              | Mostrar el estado de un workspace.                   |
| `start`   | sí              | Reactivar recursos de un workspace existente.        |
| `stop`    | sí              | Detener recursos sin destruir el workspace.          |
| `list`    | no              | Listar workspaces administrados.                     |
| `doctor`  | no              | Diagnosticar proyecto y entorno.                     |

```bash
ramalio --version
ramalio --help
ramalio doctor          # diagnostica readiness del proyecto/entorno
ramalio init TASK-1     # crea branch + worktree para el target
```

Los comandos ejecutan el lifecycle real y producen efectos sobre Git/worktrees
según su contrato; las operaciones mutables corren bajo lock por target y un
contexto transaccional común.

## Contrato de códigos de salida

Los códigos de salida son estables y forman parte del contrato público
(`ramalio.core.result.ExitCode`):

| Código | Nombre                | Significado                                        |
| ------ | --------------------- | -------------------------------------------------- |
| 0      | `OK`                  | Éxito.                                             |
| 2      | `USAGE_ERROR`         | Sintaxis o argumentos de CLI inválidos.            |
| 3      | `CONFIGURATION_ERROR` | Configuración ausente o inválida.                  |
| 4      | `STATE_ERROR`         | El estado/identidad del workspace no permite la operación. |
| 5      | `SAFETY_BLOCKED`      | Una invariante de seguridad bloquea la operación.  |
| 6      | `OPERATION_FAILED`    | Fallo esperado de operación o dependencia.         |
| 70     | `INTERNAL_ERROR`      | Error interno inesperado (sin traceback por defecto). |
| 78     | `NOT_IMPLEMENTED`     | Reservado para superficies futuras aún no implementadas. |

## Estructura del proyecto

```text
src/ramalio/
├── __init__.py         # __version__ (fuente única de versión)
├── cli.py              # superficie pública del CLI, parser, dispatch y render
└── core/
    ├── errors.py       # jerarquía de errores esperados → exit codes
    └── result.py       # CommandResult y ExitCode
tests/unit/             # pruebas de CLI, result y errors
docs/
└── standard-operativo.md   # estándar operativo (marco conceptual)
```

## Desarrollo y pruebas

```bash
pytest
```

La configuración de pytest está en `pyproject.toml` (`testpaths = ["tests"]`).

## Licencia

Sin licencia declarada por el momento.
