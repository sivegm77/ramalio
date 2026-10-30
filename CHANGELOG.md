# Changelog

Todas las versiones siguen [SemVer](https://semver.org/lang/es/). Las notas
describen cambios de comportamiento y de compatibilidad de configuración
(E9-S1 R16).

## [Unreleased]

### Added
- Versionado explícito de schema de configuración vía `[meta].schema_version`
  con verificación fail-closed (`CONFIG_VERSION_UNSUPPORTED`) (E9-S1).
- Checks `CLI_VERSION` y `CONFIG_SCHEMA` en `ramalio doctor` (E9-S1).
- Guía de instalación/distribución/uninstall (`docs/installation.md`) (E9-S1).
- `integrations.<name>.pass_env`: allowlist explícita de nombres de variables
  del host que se agregan al environment controlado de la integration (E9-S3).
- `LifecycleEvent.AFTER_ADOPT` (`after_adopt`): único evento nuevo del contrato
  de workspace provisioning. `adopt` ahora ejecuta los hooks `after_adopt` bajo
  la `LifecycleTransaction` común en sus dos modos exitosos (existing-worktree
  registra sólo mutaciones de capabilities; created-worktree incluye además el
  worktree creado), reutilizando registry/HookRunner/locks/ownership
  existentes. `init` sigue usando `after_init`. Sin tecnología concreta, sin CLI
  nuevo y sin `before_adopt` (E10-S0).
- Runtime provisioning: el driver de runtime gana la operación `provision()`
  (arranca el runtime durante `init`/`adopt`) y un protocolo opcional
  `RuntimeCommandExecutor` (`ensure_service`/`exec`) para providers downstream
  que necesiten ejecutar argv dentro de un runtime, sin conocer Docker Compose.
  `[capabilities.runtime]` acepta seis claves nuevas opcionales con defaults
  seguros: `provision_on_init`, `provision_on_adopt`, `build_on_provision`,
  `base_project_pattern` (`"{project}"`), `materialize_env_file` (ruta relativa,
  ausencia = no copiar) y `remove_volumes_on_destroy`. Docker Compose implementa
  `provision` (materializa el env file declarado, `up -d`, `--build` opt-in),
  el executor (identidad de proyecto para scope `project`/`workspace`, `exec -T`
  con argv estructurado) y `down -v` sólo cuando se opta explícitamente por
  `remove_volumes_on_destroy`. El driver `none` sigue siendo no-op (E10-S1).
- Capability `bootstrap`: nueva capability opcional de dependency provisioning
  + readiness bajo `[capabilities.bootstrap]`, con provider único `composer`
  (registry explícito de providers, sin discovery dinámico). Ejecuta Composer en
  el host (`SafeProcessRunner`, argv `("composer", *arguments)`, cwd=worktree,
  env controlado + `environment` + allowlist `pass_env`) o dentro de un runtime
  vía el `RuntimeCommandExecutor` de E10-S1 (`runtime_user="host"` →
  `<uid>:<gid>`), previa sonda writable con la misma identidad y con validación
  de artifacts `file`/`directory`/`executable`. Participa en `after_init`/
  `after_adopt` según `on_init`/`on_adopt`; no toca `start`/`stop` ni borra
  dependencias en `destroy`. Un fallo de Composer que pudo mutar se registra como
  no compensable (rollback no fingido) y queda diagnosticable. El executable
  `composer` es fijo; el TOML sólo controla `arguments`. Sin `framework` ni
  branching por proyecto (E10-S2).
- Capability `data`: nueva capability opcional de data provisioning PostgreSQL
  aislado bajo `[capabilities.data]`, con provider único `postgres` (registry
  explícito). Copia la base PostgreSQL del proyecto (runtime scope `project`,
  `base_project_pattern`) hacia una base aislada del target (runtime scope
  `workspace`) sobre el `RuntimeCommandExecutor` de E10-S1, sin conocer Docker
  Compose. Resuelve identidad con `printenv POSTGRES_USER`/`POSTGRES_DB` dentro
  de cada scope (nunca lee/imprime `POSTGRES_PASSWORD`), espera readiness con
  `pg_isready` hasta `readiness_timeout`, toma snapshot con
  `pg_dump --clean --if-exists --no-owner --no-privileges` (el dump nunca se
  imprime) y restaura con `psql -v ON_ERROR_STOP=1` por stdin. `cleanup_mode`
  `preserve` (default) o `runtime`; `runtime` exige un runtime docker-compose con
  `remove_volumes_on_destroy=true` (si no, `PROJECT_CONFIG_INVALID`) y delega el
  cleanup al runtime — no existe `drop database` automático. Nunca aplica DDL
  destructivo sobre el source. Participa en `after_init`/`after_adopt` según
  flags. Registrada después de runtime y antes de bootstrap. Sin username/
  password/database en el TOML (E10-S3).
- Convergencia de paridad SiVale (E10-S4): `docs/examples/sivale.ramalio.toml`
  configura el lifecycle completo de SiVale usando exclusivamente los contratos
  E10 (runtime provisioning con `build_on_provision`/`materialize_env_file`/
  `remove_volumes_on_destroy`, data PostgreSQL con `cleanup_mode="runtime"` y
  bootstrap Composer con `executor="runtime"`), sin conocimiento de SiVale/
  Laravel en el core. La matriz `docs/examples/sivale-parity-matrix.md` cierra
  los GAP-P1..P4 a nivel de contrato + evidencia determinista y mapea el
  reemplazo de los scripts legacy; la evidencia operacional real queda
  registrada como pendiente en `docs/evidence/sivale-e10-pilot.md`. Nuevas
  pruebas de paridad a nivel de responsabilidad en
  `tests/conformance/test_sivale_parity.py`.

### Changed
- `integrations.<name>.command` es ahora **argv estructurado** (lista de
  strings), p. ej. `command = ["kiro-cli", "--v3"]`. Un string de shell ya no
  es el formato canónico y se rechaza como configuración inválida; se eliminó
  toda tokenización implícita (`split()`) del camino de ejecución (E9-S3).

### Removed
- `integrations.<name>.inherit_env` deja de formar parte del contrato público:
  una configuración que lo declare se rechaza como clave no soportada. El
  environment controlado por defecto y `pass_env` cubren la necesidad legítima
  de herencia explícita (E9-S3).

### Compatibility
- Configuraciones sin `[meta]` siguen siendo válidas: se asume el schema
  soportado por el CLI. Schema soportado actual: `1`.
- La convergencia de E9-S3 no incrementa el schema de configuración: antes de
  E9-S3 ninguna release oficial distribuyó el contrato divergente (string
  `command` / `inherit_env`) —evidencia histórica registrada en la spec E9-S3
  §14—, por lo que se corrige directamente al contrato canónico sin migración
  (E9-S3 R12, decisión §7.4 opción 1). El schema soportado se mantiene en `1`;
  una release futura del contrato ya correcto es legítima y no altera esta
  decisión.

## [0.1.0]

- Superficie pública del CLI y lifecycle completo: `init`, `adopt`, `destroy`,
  `list`, `status`, `doctor`, `start`, `stop`.
- Capabilities opcionales: processes, tmux, runtime (none/docker-compose),
  ports, tunnel (zrok). Integrations: kiro/vscode/codex/claude.
- Transacciones y rollback, locks/concurrencia, boundaries de seguridad y suite
  de conformidad.
