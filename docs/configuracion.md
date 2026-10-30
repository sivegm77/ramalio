# Configuración de proyecto (E1-S0)

Este documento describe el contrato inicial mediante el cual `ramalio`
descubre un proyecto, localiza su configuración compartida y produce un modelo
de configuración resuelto para el resto del producto.

El marco conceptual completo vive en
[`standard-operativo.md`](standard-operativo.md); aquí se documenta únicamente
lo introducido por la spec **E1-S0**.

## Descubrimiento del proyecto

- El root del repositorio se deriva del contexto de ejecución usando Git como
  autoridad (`git rev-parse --show-toplevel`).
- Funciona invocando desde el root o desde cualquier subdirectorio del mismo
  repositorio; ambos resuelven el mismo proyecto.
- No se depende de rutas absolutas fijas ni de variables globales específicas de
  un repositorio (por ejemplo, **no** se usa `KIRO_PROJECT_ROOT`).
- Si el directorio no pertenece a un repositorio Git, la resolución falla con el
  error estable `NOT_IN_GIT_REPOSITORY`.

## Archivo de configuración compartida

Una vez resuelto el root, se busca exactamente:

```text
<repository-root>/.ramalio.toml
```

No se recorren directorios padre en busca de más archivos. La ausencia del
archivo produce `PROJECT_CONFIG_NOT_FOUND`.

`ramalio` trata el TOML estrictamente como datos: nunca ejecuta comandos,
interpola shell, sigue includes ni evalúa expresiones.

## Estructura soportada

Secciones modeladas en E1 (las semánticas de `target`, `worktree` y `branch` se
validan en specs posteriores):

```toml
[project]
name = "mi-proyecto"      # string no vacío (obligatorio)
base_branch = "main"       # string no vacío (default: "main")

[target]
regex = "^[a-z0-9-]+$"     # opcional en E1
example = "mi-feature"      # opcional en E1
case_sensitive = false      # default: false

[target.normalization]
trim = true
lowercase_slug = true
replace_spaces = "-"
collapse_dashes = true

[worktree]
directory = ".local-wt"    # default: ".local-wt"
pattern = "{target}"        # default: "{target}"

[branch]
pattern = "spec/{target}"  # default: "{target}"

# Secciones extensibles: en E1 sólo se cargan, no se ejecutan.
[capabilities.tmux]
enabled = true

[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
```

### Claves desconocidas (fail-closed)

Dentro de un namespace conocido, cualquier clave desconocida se rechaza con
`PROJECT_CONFIG_INVALID`, evitando typos silenciosos como:

```toml
[worktree]
direcotry = ".local-wt"   # ERROR: "worktree: unknown key(s): direcotry"
```

Los namespaces top-level no pueden inventarse sin un cambio de contrato.

## Workspace provisioning (E10)

Además de las secciones anteriores (comunes a todo proyecto Git-only),
`[capabilities.runtime]`, `[capabilities.bootstrap]` y `[capabilities.data]`
extienden la configuración con **workspace provisioning opcional**: preparar
un runtime, instalar dependencias y aislar datos durante `init`/`adopt`. Un
proyecto que no declare estas secciones no cambia de comportamiento (Git-only
sigue siendo el comportamiento base).

El detalle completo de cada capability (semántica, lifecycle, doctor/status)
vive en [`capabilities.md`](capabilities.md#runtime); aquí se documenta sólo
el contrato de configuración público.

### `[capabilities.runtime]` — provisioning

Claves E6-S2 existentes (`driver`, `compose_file`, `project_pattern`,
`port_env`) más las siguientes, todas opcionales con defaults seguros/
compatibles y **fail-closed en claves desconocidas**:

```toml
[capabilities.runtime]
driver = "docker-compose"
compose_file = "docker-compose.yml"
compose_files = ["docker-compose.override.yml"]  # capas -f adicionales opcionales
project_pattern = "{project}-{target}"
base_project_pattern = "{project}"                # identidad del runtime base (scope 'project')
port_env = "APP_HTTP_PORT"

provision_on_init = false      # ejecuta provision() en after_init
provision_on_adopt = false     # ejecuta provision() en after_adopt
build_on_provision = false     # añade --build sólo durante provisioning
materialize_env_file = ".env"  # copia <repo_root>/<ruta> -> <worktree>/<ruta>
remove_volumes_on_destroy = false  # down -v en destroy (opt-in)
```

Reglas relevantes:

- `compose_files` es una lista ordenada; una entrada ausente en el worktree se
  omite silenciosamente (equivalente al `docker-compose.override.yml` opcional
  de un runtime legacy), pero una entrada presente debe resolver dentro del
  worktree (symlink-aware) o la operación falla cerrada.
- `materialize_env_file` nunca sobrescribe un archivo preexistente con
  contenido distinto (preserva trabajo adoptado); su contenido nunca se
  imprime ni se versiona.
- `base_project_pattern` sólo sustituye `{project}` en el TOML compartido; no
  ofrece un placeholder para un identificador personal del desarrollador (el
  core no debe conocer variables tipo `KIRO_DEVELOPER`). Si el runtime base
  real es developer-scoped, un desarrollador puede sobreescribirlo desde su
  propio entorno (no versionado) exportando
  `RAMALIO_RUNTIME_BASE_PROJECT_PATTERN` (ver "Variables de entorno
  soportadas" más abajo); el override sólo aplica si `[capabilities.runtime]`
  ya está declarado, nunca activa la capability por sí solo.

### `[capabilities.bootstrap]` — dependencias + readiness

```toml
[capabilities.bootstrap]
enabled = true
provider = "composer"          # único provider soportado
on_init = true
on_adopt = true
executor = "host"              # host | runtime
arguments = ["install", "--no-interaction", "--prefer-dist", "--no-progress"]
pass_env = []                   # allowlist de nombres de variables del host
writable_paths = []              # paths relativos al worktree, probados antes de instalar

# sólo cuando executor = "runtime"
runtime_service = "app"
runtime_workdir = "/var/www/html"
runtime_user = "host"           # único alias soportado -> <uid>:<gid> del host

[capabilities.bootstrap.environment]
COMPOSER_HOME = "/tmp/composer"

[[capabilities.bootstrap.artifacts]]
path = "vendor/autoload.php"
kind = "file"                    # file | directory | executable
```

El executable es fijo (`composer`); el TOML sólo controla `arguments`. Cada
`writable_paths` se prueba (create+delete) antes de instalar, con la misma
identidad que ejecutará Composer; el path resuelto debe permanecer dentro del
worktree (symlink-aware). Los artifacts declarados se validan después de
instalar.

### `[capabilities.data]` — PostgreSQL aislado por target

```toml
[capabilities.data]
enabled = true
provider = "postgres"           # único provider soportado
on_init = true
on_adopt = true
runtime_service = "db"
readiness_timeout = 30           # segundos, entero > 0
cleanup_mode = "preserve"        # preserve | runtime
```

No se configura usuario/contraseña/base en el TOML: el provider resuelve
`POSTGRES_USER`/`POSTGRES_DB` dentro de cada servicio y nunca lee
`POSTGRES_PASSWORD`. `cleanup_mode = "runtime"` exige que
`[capabilities.runtime].remove_volumes_on_destroy = true`; de lo contrario la
configuración se rechaza (`PROJECT_CONFIG_INVALID`). No existe `drop database`
automático en ningún modo.

## Defaults del producto

Los defaults son universales, seguros y agnósticos de stack (ver
`config/defaults.py`). No inventan secretos y **no activan** ninguna capability
ni integración por defecto.

## Precedencia

De menor a mayor prioridad:

```text
defaults del producto
        ↓
configuración global/personal del desarrollador
        ↓
.ramalio.toml del proyecto
        ↓
variables de entorno soportadas
        ↓
opciones CLI explícitas
```

Reglas relevantes:

- La configuración personal es opcional; no se exige ningún archivo global.
- La identidad del proyecto (`project.name`) proviene del TOML del proyecto y no
  puede ser redefinida silenciosamente por la configuración personal.
- Los secretos no pertenecen a la configuración compartida versionada.

Variables de entorno soportadas en E1:

| Variable                     | Campo sobreescrito     |
|------------------------------|------------------------|
| `RAMALIO_BASE_BRANCH`       | `project.base_branch`  |
| `RAMALIO_WORKTREE_DIRECTORY`| `worktree.directory`   |
| `RAMALIO_RUNTIME_BASE_PROJECT_PATTERN` | `capabilities.runtime.base_project_pattern` (sólo si `[capabilities.runtime]` ya está declarado; nunca activa la capability por sí sola) |

## Errores diagnósticos

Todos mapean al exit code `3` (`CONFIGURATION_ERROR`) y exponen un identificador
estable en el atributo `code`:

| Identificador                | Situación                                      |
|------------------------------|------------------------------------------------|
| `NOT_IN_GIT_REPOSITORY`      | El contexto no pertenece a un repositorio Git. |
| `PROJECT_CONFIG_NOT_FOUND`   | No existe `.ramalio.toml` en el root.   |
| `PROJECT_CONFIG_PARSE_ERROR` | El TOML es sintácticamente inválido.           |
| `PROJECT_CONFIG_INVALID`     | El TOML viola el contrato estructural.         |

## Modelo resuelto

El resto del producto **no** debe leer `.ramalio.toml` directamente. Debe
consumir `ResolvedProjectConfig` producido por
`ramalio.config.resolve_project_config()`:

```python
from ramalio.config import resolve_project_config

config = resolve_project_config()  # descubre desde el cwd
config.repository_root
config.project.name
config.worktree.directory
```

El modelo es inmutable y determinista: con las mismas fuentes de entrada, la
configuración efectiva es siempre la misma.

## Perfiles de ejemplo

En `tests/fixtures/profiles/` hay tres configuraciones conceptualmente distintas
que se cargan con el mismo core sin requerir tecnologías opcionales:

1. `simple-git` — proyecto simple, sólo Git worktrees.
2. `web-runtime` — proyecto web con capabilities/integrations declaradas.
3. `cli-python` — proyecto CLI/Python sin Docker ni puertos.
