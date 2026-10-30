# Catálogo de capabilities soportadas (E9-S2 R14)

Las capabilities son comportamientos **opcionales** del lifecycle. Ninguna está
habilitada por defecto: un proyecto sólo las activa cuando las necesita. El core
conoce el contrato, nunca la implementación concreta.

Cada capability se habilita en `[capabilities.<name>]` (o `[ports]` para
puertos) y participa en el lifecycle mediante hooks (`after_init`,
`after_adopt`, `after_start`, `before_stop`, `before_destroy`), aportando
también `status` y checks de `doctor`.

## processes

- **Propósito:** ejecutar procesos por workspace (workers, watchers, dev servers).
- **Lifecycle:** arranca en `after_init`/`after_start` según flags; detiene en
  `before_stop`/`before_destroy`.
- **Dependencias:** el ejecutable declarado en cada `command` (argv).
- **Configuración:** `[capabilities.processes]` + `[[capabilities.processes.items]]`
  con `name`, `command` (argv), `cwd`, `environment`, flags `start_on_*`/`stop_on_*`,
  `stop_timeout`.
- **doctor/status:** disponibilidad del ejecutable; estado ACTIVE/STOPPED/STALE
  con protección contra PID reuse.
- **cleanup:** detiene procesos propios y limpia su metadata (nunca borra logs
  por defecto).

## tmux

- **Propósito:** sesión persistente por target.
- **Lifecycle:** crea en `after_init`/asegura en `after_start`; stop/destroy según
  `stop_policy`/`destroy_policy` (`keep`|`kill`).
- **Dependencias:** `tmux`.
- **Configuración:** `session_pattern` (`{target}`), `create_on_init`,
  `attach_on_init`, `stop_policy`, `destroy_policy`.
- **doctor/status:** disponibilidad de tmux; ACTIVE/STOPPED; ownership por marcador
  de sesión (no reutiliza/mata sesiones ajenas).

## runtime

- **Propósito:** runtime opcional por target. Drivers: `none` (default), `docker-compose`.
- **Lifecycle:** `after_init`/`after_adopt` `provision` (opt-in), `after_start`
  start, `before_stop` stop, `before_destroy` cleanup.
- **Dependencias:** ninguna (`none`) / `docker` + `docker compose`.
- **Configuración:** `[capabilities.runtime].driver` y, para docker-compose,
  `compose_file`, `compose_files` (lista opcional de capas `-f` adicionales,
  añadidas sólo cuando el archivo existe en el worktree; equivalente al
  `docker-compose.override.yml` opcional del harness legacy), `project_pattern`,
  `port_env`. Provisioning (E10-S1, opt-in):
  `provision_on_init`, `provision_on_adopt`, `build_on_provision`,
  `base_project_pattern` (identidad del runtime base compartido; sobreescribible
  desde el entorno personal del desarrollador vía
  `RAMALIO_RUNTIME_BASE_PROJECT_PATTERN`),
  `materialize_env_file` (copia un `.env` de la raíz al worktree antes de
  Compose; su contenido nunca se imprime) y `remove_volumes_on_destroy`
  (`down -v` opt-in).
- **Ejecución en runtime:** docker-compose implementa el protocolo
  `RuntimeCommandExecutor` (scopes `project`/`workspace`) que usan `data` y
  `bootstrap`; `none` no lo implementa.
- **doctor/status:** disponibilidad del driver; RUNNING/STOPPED/…; project name
  único por target; cleanup conservador (no borra volúmenes salvo opt-in).

## data

- **Propósito:** data provisioning aislado por target. Provider: `postgres`.
- **Lifecycle:** `after_init`/`after_adopt` según `on_init`/`on_adopt`.
- **Dependencias:** un runtime que implemente ejecución de comandos
  (docker-compose); nunca conoce Docker directamente.
- **Configuración:** `[capabilities.data]` con `enabled`, `provider`,
  `on_init`, `on_adopt`, `runtime_service`, `readiness_timeout`, `cleanup_mode`
  (`preserve` | `runtime`). `cleanup_mode="runtime"` exige un runtime
  docker-compose con `remove_volumes_on_destroy=true`. No hay usuario/contraseña
  /base en el TOML: el provider resuelve `POSTGRES_USER`/`POSTGRES_DB` dentro del
  servicio y nunca lee `POSTGRES_PASSWORD`.
- **Semántica:** copia la base del runtime base (scope `project`) hacia la base
  del target (scope `workspace`) con `pg_dump ... --clean --if-exists --no-owner
  --no-privileges` (nunca impreso) + `psql -v ON_ERROR_STOP=1` por stdin. Nunca
  aplica DDL destructivo sobre el source; no existe `drop database` automático.
- **doctor/status:** provider, soporte de ejecución en runtime y precondición de
  cleanup validados sin dump/restore; ACTIVE/READY/DEGRADED por `pg_isready`.

## bootstrap

- **Propósito:** provisioning de dependencias + readiness. Provider: `composer`.
- **Lifecycle:** `after_init`/`after_adopt` según `on_init`/`on_adopt`; no toca
  `start`/`stop`; no borra dependencias en `destroy`.
- **Dependencias:** `composer` en el host (`executor="host"`) o un runtime con
  ejecución de comandos (`executor="runtime"`).
- **Configuración:** `[capabilities.bootstrap]` con `enabled`, `provider`,
  `on_init`, `on_adopt`, `executor` (`host` | `runtime`), `arguments` (el
  executable `composer` es fijo; sólo se controlan los argumentos), `pass_env`
  (allowlist de nombres), `writable_paths`, `[capabilities.bootstrap.environment]`
  y `[[capabilities.bootstrap.artifacts]]` (`file`/`directory`/`executable`).
  Con `executor="runtime"`: `runtime_service`, `runtime_workdir`, `runtime_user`
  (`host` → `<uid>:<gid>`).
- **Semántica:** sonda writable con la misma identidad/executor → Composer →
  verificación de artifacts. Un fallo de Composer que pudo mutar queda
  diagnosticable (rollback no fingido).
- **doctor/status:** provider, disponibilidad de Composer o soporte de ejecución
  en runtime; READY/DEGRADED según artifacts, sin instalar.

## ports

- **Propósito:** reserva de puerto determinista por target.
- **Lifecycle:** reserva en `after_init`; libera en `before_destroy`.
- **Dependencias:** ninguna.
- **Configuración:** `[ports]` con `enabled`, `start`, `size`.
- **doctor/status:** rango configurado; puerto reservado observable; sin
  colisiones; detección de puerto ocupado externamente.

## tunnel

- **Propósito:** exposición temporal de un endpoint local. Providers: `zrok`.
- **Lifecycle:** `after_start` abre; `before_stop`/`before_destroy` cierra/limpia.
- **Dependencias:** el provider (p.ej. `zrok`); requiere un endpoint local
  (normalmente el puerto reservado por `ports`).
- **Configuración:** `[capabilities.tunnel]` con `enabled`, `provider`.
- **doctor/status:** disponibilidad del provider; ACTIVE con `public_url`;
  tokens nunca se leen ni se registran.

## Proponer una nueva capability

Ver el proceso de gobernanza en [`adoption-guide.md`](adoption-guide.md#proponer-una-extensión).
