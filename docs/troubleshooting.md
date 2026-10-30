# Troubleshooting (E9-S2 R11)

Empieza siempre por:

```bash
ramalio doctor
```

`doctor` es el gate de diagnóstico (R10): reporta PASS/WARN/FAIL por check y
distingue configuración inválida de herramientas externas ausentes.

| Síntoma | Causa probable | Acción |
|---|---|---|
| `NOT_IN_GIT_REPOSITORY` | No estás dentro de un repo Git | Ejecuta desde el repositorio. |
| `PROJECT_CONFIG_NOT_FOUND` | Falta `.ramalio.toml` | Copia `docs/examples/minimal.ramalio.toml` y ajústalo. |
| `PROJECT_CONFIG_PARSE_ERROR` / `PROJECT_CONFIG_INVALID` | TOML mal formado o claves inválidas | Corrige el archivo; `doctor` señala la clave. |
| `TARGET_INVALID` | El target no cumple la convención del proyecto | Usa el formato de `target.example`. |
| `BASE_BRANCH_NOT_FOUND` | La rama base no existe localmente | Crea/trae la rama base (no hay fetch implícito). |
| `BRANCH_ALREADY_EXISTS` (en `init`) | La branch derivada ya existe | Usa `adopt` o `status`. |
| `WORKSPACE_ALREADY_EXISTS` | El workspace ya está creado | Usa `status`/`start`. |
| `ADOPT_BRANCH_NOT_FOUND` | No hay branch que adoptar | Usa `init`. |
| `ADOPT_*` (mismatch/conflict/detached) | Realidad Git incompatible con la identidad | Inspecciona con `status`; resuelve manualmente. |
| `DESTROY_BLOCKED_DIRTY` | Hay trabajo local sin commitear | Revisa/guarda el trabajo antes de destruir. |
| `DESTROY_BRANCH_IN_OTHER_WORKTREE` / `DESTROY_WORKTREE_MISMATCH` | El worktree/branch no corresponde al target | `status` para diagnosticar. |
| `CAPABILITY_UNKNOWN` | El TOML habilita una capability no registrada | Revisa el nombre o actualiza el CLI. |
| `CAPABILITY_CONFIG_INVALID` | Config namespaced de la capability inválida | Corrige la sección `[capabilities.<name>]`. |
| capability FAIL en `doctor` (docker/tmux/kiro/zrok) | Herramienta ausente | Instala la herramienta o deshabilita la capability. |
| `PORT_RANGE_EXHAUSTED` | Sin puertos libres en el rango | Amplía `[ports].size` o libera con `destroy`. |
| `LOCK_TIMEOUT` | Otra operación tiene el recurso del target/pool | Espera a que termine; revisa procesos colgados. |
| `CONFIG_VERSION_UNSUPPORTED` | `[meta].schema_version` mayor que el soportado | Actualiza `ramalio` (ver `versioning-and-compatibility.md`). |
| `RUNTIME_DRIVER_UNKNOWN` | `[capabilities.runtime].driver` no está registrado | Usa `none` o `docker-compose`. |
| `RUNTIME_START_FAILED` (durante `provision`) | Fallo de `docker compose up` en provisioning, o `materialize_env_file`/`compose_files` inválido | Revisa el mensaje: distingue fallo de Compose de un boundary rechazado (symlink/preexistente distinto). |
| `materialize_env_file` rechazado con "already exists with different content" | El worktree ya tiene su propio `.env` distinto del de la raíz (p. ej. tras `adopt`) | Es intencional (E10-S4 R2): revisa manualmente cuál `.env` debe prevalecer; el producto nunca sobrescribe trabajo preexistente en silencio. |
| `materialize_env_file`/`compose_files` rechazado con "escapes the ... boundary" | El destino resuelve (por symlink u otra causa) fuera del worktree/repositorio | No es un falso positivo: revisa el symlink. El boundary check es symlink-aware (E7-S2). |
| `runtime: unknown option(s) for driver 'docker-compose'` | `[capabilities.runtime]` declara una clave no reconocida por el driver | Corrige el nombre; ver el contrato exacto en `configuracion.md#capabilitiesruntime--provisioning`. |
| `CAPABILITY_CONFIG_INVALID` con prefijo `bootstrap:` | Config de `[capabilities.bootstrap]` inválida (provider/executor/paths/artifacts) | Corrige la sección; el mensaje indica el campo exacto. |
| `BOOTSTRAP_READINESS_FAILED` | Falló el writable probe (antes de Composer) o falta un artifact declarado (después) | Revisa permisos del path declarado en `writable_paths`, o que el artifact exista con el `kind` correcto tras instalar. |
| `BOOTSTRAP_PROVIDER_FAILED` | `composer install` falló (host o dentro del runtime) | Revisa el mensaje redactado (sin secretos); el problema es del propio Composer/dependencias, no del contrato. |
| `bootstrap: executor='runtime' requires a runtime driver that implements command execution` | `executor="runtime"` pero el driver de `[capabilities.runtime]` no implementa `RuntimeCommandExecutor` | Usa `driver = "docker-compose"` o cambia a `executor = "host"`. |
| `CAPABILITY_CONFIG_INVALID` con prefijo `data:` | Config de `[capabilities.data]` inválida | Corrige la sección; el mensaje indica el campo exacto. |
| `data: cleanup_mode='runtime' requires the runtime to set remove_volumes_on_destroy=true` | `[capabilities.data].cleanup_mode = "runtime"` sin `[capabilities.runtime].remove_volumes_on_destroy = true` | Añade `remove_volumes_on_destroy = true` al runtime, o usa `cleanup_mode = "preserve"`. |
| `DATA_READINESS_TIMEOUT` | El servicio PostgreSQL no respondió `pg_isready` dentro de `readiness_timeout` | Aumenta `readiness_timeout` o revisa que el servicio realmente arranque. |
| `DATA_PROVISIONING_FAILED` | Fallo resolviendo identidad (`POSTGRES_USER`/`POSTGRES_DB`), `pg_dump` en el source o `psql` restore en el target | El source nunca se muta; revisa el servicio y las credenciales del contenedor (nunca en el TOML). |

## Provisioning (runtime/bootstrap/data) — prerequisitos

Antes de habilitar provisioning, `ramalio doctor` valida sin mutar nada:

- `DOCKER_AVAILABLE` / `DOCKER_COMPOSE_AVAILABLE` / `DOCKER_COMPOSE_FILE` — el
  driver `docker-compose` y el archivo configurado deben existir para que
  `runtime.provision`, `data` y `bootstrap(executor="runtime")` funcionen.
- `BOOTSTRAP_PROVIDER` / `BOOTSTRAP_RUNTIME_EXEC` / `BOOTSTRAP_COMPOSER` — según
  `executor`, valida que `composer` esté en el `PATH` (host) o que el runtime
  soporte ejecución de comandos (runtime).
- `DATA_PROVIDER` / `DATA_RUNTIME_EXEC` / `DATA_CLEANUP_RUNTIME` — valida el
  provider, el soporte de ejecución del runtime y, si `cleanup_mode="runtime"`,
  que el runtime esté configurado para retirar volúmenes.

Ninguno de estos checks instala, arranca ni destruye nada: son de sólo lectura.

## Categorías de soporte (R18)

Al reportar un problema, clasifícalo:

- **Bug del core:** comportamiento del producto que viola un contrato/invariante
  documentado, reproducible en un proyecto genérico.
- **Configuración inválida del proyecto:** el `.ramalio.toml` o los
  valores del proyecto son incorrectos (lo que `doctor` marca como config FAIL).
- **Dependencia externa ausente:** una capability/integration habilitada requiere
  una herramienta no instalada.
- **Feature request:** una necesidad nueva; sigue el proceso de propuesta en
  [`adoption-guide.md`](adoption-guide.md#proponer-una-extensión).
