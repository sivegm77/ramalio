# E10-S1 — Runtime provisioning lifecycle

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E10
- **Spec:** E10-S1
- **Nombre:** Runtime provisioning lifecycle
- **Dependencias:** E10-S0, E6-S0, E6-S2, E7-S0, E7-S1, E7-S2, E7-S3
- **Bloquea a:** E10-S3, E10-S4
- **Estado inicial:** Planificada

## 2. Contexto

Runtime ya modela start/stop/status/cleanup y Docker Compose ya es driver opcional. E10 necesita dos extensiones concretas: provisionar durante init/adopt y ofrecer ejecución controlada a providers downstream sin que éstos conozcan Docker Compose.

## 3. Objetivo

Extender **el runtime existente**; no crear otro subsystem.

## 4. Configuración pública exacta

Se conservan las claves E6 existentes y se añaden únicamente las siguientes dentro de `[capabilities.runtime]`:

```toml
[capabilities.runtime]
driver = "docker-compose"
compose_file = "docker-compose.yml"          # existente
project_pattern = "{project}-{target}"       # existente
port_env = "APP_HTTP_PORT"                   # existente/opcional

provision_on_init = false                     # nuevo, bool
provision_on_adopt = false                    # nuevo, bool
build_on_provision = false                    # nuevo, bool
base_project_pattern = "{project}"           # nuevo, string
materialize_env_file = ".env"                # nuevo, string opcional; ausencia = no copiar
remove_volumes_on_destroy = false             # nuevo, bool
```

Reglas:
- defaults nuevos son seguros/compatibles: `false`, `"{project}"`, ausencia de env file;
- unknown keys siguen fail-closed conforme al contrato existente de capability/provider;
- `materialize_env_file` es ruta relativa al repository root y al worktree, sin absolute/`..`/NUL;
- source = `<repository_root>/<materialize_env_file>`; destination = `<worktree>/<materialize_env_file>`;
- si se declara y source no existe, provisioning falla antes de start;
- el contenido nunca se imprime y el copy no lo convierte en config versionada.

## 5. Runtime driver contract exacto

### R1 — `provision`
`RuntimeDriver` MUST añadir:

```text
provision(workspace: RuntimeWorkspace) -> RuntimeResult
```

Semántica: preparar/arrancar el runtime para dejar el workspace utilizable durante provisioning. `start()` conserva la semántica de reanudación normal.

`NoneRuntimeDriver.provision()` es no-op `NOT_APPLICABLE`.

### R2 — Runtime command execution seam
Añadir un protocolo separado, no obligatorio para todos los drivers:

```text
RuntimeCommandExecutor
```

con dos operaciones:

```text
ensure_service(scope, workspace, service) -> RuntimeResult
exec(scope, workspace, request) -> RuntimeExecResult
```

Donde:
- `scope` es exactamente `project` o `workspace`;
- `workspace` es requerido para scope `workspace` y `None` para `project`;
- `project` usa repository root + `base_project_pattern`;
- `workspace` usa worktree + `project_pattern`.

`RuntimeExecRequest` contiene exactamente:
- `service: str` no vacío;
- `argv: tuple[str, ...]` no vacío;
- `env: Mapping[str,str]` explícito, default vacío;
- `user: str | None`;
- `workdir: str | None` (path dentro del runtime, no path host);
- `stdin: bytes | None`.

`RuntimeExecResult` contiene `returncode`, `stdout` bytes y `stderr` bytes. No imprime automáticamente.

Docker Compose implementa `RuntimeCommandExecutor`. `none` no lo implementa. Providers que configuren executor runtime deben fallar config/doctor si el driver no lo soporta.

## 6. Lifecycle exacto

### R3 — AFTER_INIT
Si `provision_on_init=true`, `RuntimeCapability.handle("after_init")` llama `driver.provision(workspace)`.

### R4 — AFTER_ADOPT
Si `provision_on_adopt=true`, `handle("after_adopt")` llama la misma operación.

### R5 — AFTER_START
Permanece `driver.start(workspace)` y no fuerza build.

### R6 — BEFORE_STOP
Permanece `driver.stop(workspace)`.

### R7 — BEFORE_DESTROY
Permanece `driver.cleanup(workspace)`; Docker Compose usa `down -v` **sólo** cuando `remove_volumes_on_destroy=true`, de otro modo conserva `down` sin volúmenes.

## 7. Docker Compose exacto

### R8 — provision
`DockerComposeDriver.provision()`:
1. si `materialize_env_file` está configurado, copia source→destination antes de ejecutar Compose;
2. observa pre-state con el mismo criterio fail-closed existente;
3. ejecuta `docker compose ... up -d`;
4. añade `--build` únicamente si `build_on_provision=true`;
5. reporta `changed` con la misma semántica de ownership ya usada por start.

### R9 — project identity
- workspace scope: sanitized `project_pattern` con `{project}`/`{target}`;
- project scope: sanitized `base_project_pattern` con `{project}`;
- no `KIRO_DEVELOPER` ni nombres SiVale.

### R10 — ensure_service
Docker Compose ejecuta `up -d <service>` en el scope solicitado, siempre con project identity explícita.

### R11 — exec
Docker Compose ejecuta `exec -T`, añade `--user`, `--workdir` y `-e KEY=VALUE` sólo cuando estén presentes, y después `service + argv`; host execution sigue pasando por `SafeProcessRunner` con `shell=False`.

### R12 — env/port
La inyección `port_env` existente sigue siendo explícita. `materialize_env_file` no recibe sustituciones ni secretos desde TOML.

## 8. Ordering

Default registry E10 debe mantener las capabilities existentes y ubicar downstream de esta forma relativa:

```text
ports → runtime → data → bootstrap → tunnel
```

E10-S1 sólo garantiza runtime antes de data/bootstrap; S2/S3 registran sus capabilities en los lugares indicados.

## 9. Acceptance Criteria
- AC-01 configs previas cargan con defaults E10 y mismo comportamiento.
- AC-02 `none` sigue no-op.
- AC-03 `provision_on_init` dispara provision sólo en init.
- AC-04 `provision_on_adopt` dispara provision sólo en adopt.
- AC-05 normal start no usa `--build` por `build_on_provision`.
- AC-06 Docker provision con build usa `up -d --build` desde el worktree actual.
- AC-07 env file se copia únicamente cuando se declara y nunca se imprime.
- AC-08 project/workspace scopes derivan identidades distintas y deterministas.
- AC-09 command exec preserva argv y no shell-tokeniza.
- AC-10 remove volumes es opt-in y target-scoped.
- AC-11 rollback no detiene runtime preexistente.
- AC-12 no se añaden drivers nuevos.
- AC-13 suite + conformance PASS.

## 10. Tasks
1. Añadir las seis opciones nuevas con defaults/validación exactos.
2. Extender RuntimeDriver con `provision` y actualizar none/docker drivers.
3. Añadir `RuntimeCommandExecutor`, request/result y scope exactos.
4. Implementar project/workspace execution en Docker Compose.
5. Cablear AFTER_INIT/AFTER_ADOPT según flags.
6. Implementar materialize env, build policy y remove-volumes policy.
7. Cubrir idempotencia/partial mutation/rollback con contratos E7 existentes.
8. Añadir regresiones de configs previas, none, start sin build y no-secret diagnostics.
9. Ejecutar suite + conformance.

## 12. Enmienda post-auditoría — Compose override opcional (H5.B)

La auditoría integral E10 (post-implementación) encontró que el harness legacy de SiVale compone el runtime con un archivo base (`docker-compose.yml`) y, **sólo si existe**, un `docker-compose.override.yml` adicional (`-f docker-compose.yml -f docker-compose.override.yml`). El contrato original de esta spec congeló un único `compose_file`, lo que no permite representar esa composición sin forzar al proyecto cliente a fusionar manualmente sus archivos Compose.

Esta sección enmienda el §4/§7 con el mínimo cambio compatible necesario, sin abrir una mega-feature de composición:

### R13 — `compose_files` opcional (lista ordenada adicional)

Se añade una clave opcional, ortogonal a `compose_file`:

```toml
[capabilities.runtime]
compose_file = "docker-compose.yml"                 # existente, obligatorio-por-default
compose_files = ["docker-compose.override.yml"]      # nuevo, opcional, lista de strings
```

Reglas:
- `compose_files` es una lista ordenada de rutas relativas al worktree, adicionales a `compose_file` (que sigue siendo el primer `-f`);
- cada entrada se valida con las mismas reglas de `materialize_env_file` (relativa, sin absolute/`..`/NUL) y con el boundary symlink-aware (E7-S2);
- **una entrada que no exista en el worktree se omite silenciosamente** (mismo comportamiento que el harness legacy: el override es opcional, no se falla por su ausencia); una entrada que exista pero escape del boundary sí falla-cerrado;
- el comando Compose resultante es `-f <compose_file> -f <compose_files[0]> -f <compose_files[1]> ...` en orden declarado, para todas las operaciones (`up`, `down`, `stop`, `ps`, `exec`, etc.), no sólo `provision`;
- default es lista vacía (comportamiento idéntico al actual, AC-01 preservado);
- `compose_files` se añade a la allowlist fail-closed de opciones del driver (H4).

No se introduce resolución dinámica de archivos, glob ni merge de contenido: es exactamente la misma composición de capas nativa de `docker compose -f -f` que el harness legacy ya usa, expresada como configuración explícita del proyecto cliente.

### AC-14 (nuevo)
`compose_files` declarado y presente añade capas `-f` en orden; declarado y ausente se omite sin fallar; ausencia total de `compose_files` es idéntica al comportamiento pre-enmienda.

### Justificación de la decisión mínima

Se descarta cualquier mecanismo de discovery automático (`docker-compose.override.yml` implícito sin declarar) porque violaría el principio de configuración explícita del producto. Se descarta soportar `include`/merge de Compose en el core: eso ya lo resuelve Compose nativamente vía `-f` múltiple, que es exactamente lo que esta enmienda expone.

## 13. Enmienda post-auditoría — identidad del runtime base (H5.C / F2)

El harness legacy deriva la identidad Compose del runtime base como `zurich-$KIRO_DEVELOPER`, donde `KIRO_DEVELOPER` es una variable de configuración personal del desarrollador (INV-008, fuera de la configuración compartida). El core **no debe** conocer `KIRO_DEVELOPER` (INV-007/R13 de esta spec).

`base_project_pattern` (R9) sólo sustituye `{project}` en el TOML compartido — **no** ofrece, ni debe ofrecer, un placeholder `{developer}` que obligaría al core a resolver una identidad personal (violaría INV-007/INV-008). Esto sigue siendo así deliberadamente.

### R14 — override de entorno para `base_project_pattern` (F2)

Una auditoría posterior (F2) encontró que la limitación documentada en la versión anterior de esta sección no tenía, en el código, un mecanismo real y funcional para que un desarrollador resolviera esa identidad sin depender del TOML compartido: la "configuración personal" (`PersonalConfigSource`) es sólo una interfaz sin implementación activa en el CLI de producción, y el pipeline de precedencia (`personal < TOML del proyecto < entorno < CLI`) hacía que, sin un override de entorno específico, el TOML compartido siempre ganara.

Se cierra con el mecanismo genérico **ya existente** para overrides de entorno (`config/loader.py::_ENV_OVERRIDES`, el mismo patrón que ya usa `IMASS_WT_BASE_BRANCH`), añadiendo:

```text
IMASS_WT_RUNTIME_BASE_PROJECT_PATTERN
```

Reglas:
- si está presente en el entorno del proceso, sobreescribe `capabilities.runtime.base_project_pattern` con precedencia mayor que el TOML del proyecto y que la configuración personal (mismo nivel que los demás overrides de entorno soportados);
- **sólo se aplica si `[capabilities.runtime]` ya fue declarado** por una fuente de menor prioridad (TOML del proyecto o configuración personal); nunca crea la sección `runtime` desde cero, para que la sola presencia de la variable en el shell de un desarrollador no active la capability por sí misma (INV-009);
- no sustituye ni afecta ninguna otra clave de `[capabilities.runtime]` (driver, compose_file, project_pattern, etc.);
- el core sigue sin conocer `KIRO_DEVELOPER`, `zurich`, `sivale` ni ningún nombre de proyecto/desarrollador concreto: sólo honra una variable de entorno con nombre genérico del producto, exactamente igual que `IMASS_WT_BASE_BRANCH`;
- el valor vive en el entorno personal del desarrollador (shell profile, `direnv`, etc.), nunca en `.imass-worktree.toml` ni en ningún archivo versionado.

Con esto, un proyecto cuyo runtime base sea developer-scoped (como el harness legacy de SiVale) puede resolver correctamente `RuntimeScope.PROJECT` (usado por `data`/E10-S3 para el `pg_dump` del source) sin coupling en el core: el desarrollador exporta `IMASS_WT_RUNTIME_BASE_PROJECT_PATTERN=zurich-<su-identificador>` en su propio entorno, y `base_project_name()` resuelve esa identidad real en lugar del valor compartido `{project}`.

Esta enmienda cierra el hallazgo F2 a nivel de contrato/determinista (existe el mecanismo, está probado). Queda pendiente, como antes, que el piloto operacional real de E10-S4 confirme que, con ese override configurado en el entorno del desarrollador real, `pg_dump`/`data` efectivamente apuntan al Compose project correcto en el entorno SiVale real.
