# E10-S2 — Bootstrap Composer y readiness del workspace

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E10
- **Spec:** E10-S2
- **Nombre:** Bootstrap Composer y readiness
- **Dependencias:** E10-S0, E9-S3, E7-S2
- **Bloquea a:** E10-S4
- **Estado inicial:** Planificada

## 2. Contexto

SiVale considera listo el workspace sólo después de dependencias y readiness. La solución se modela como una capability `bootstrap` con provider explícito, no como Laravel support ni como arbitrary project script hooks.

## 3. Configuración pública exacta

Namespace nuevo:

```toml
[capabilities.bootstrap]
enabled = true
provider = "composer"               # único provider E10-S2
on_init = true
on_adopt = true
executor = "host"                   # host | runtime
arguments = ["install", "--no-interaction", "--prefer-dist", "--no-progress"]
pass_env = []
writable_paths = []                  # paths relativos al worktree

# sólo cuando executor = "runtime"
runtime_service = "app"
runtime_workdir = "/var/www/html"
runtime_user = "host"               # único valor especial soportado en E10

[capabilities.bootstrap.environment]
COMPOSER_HOME = "/tmp/composer"     # valores explícitos no secretos

[[capabilities.bootstrap.artifacts]]
path = "vendor/autoload.php"
kind = "file"                        # file | directory | executable
```

Defaults:
- `enabled=false` por ausencia de sección;
- provider requerido cuando enabled;
- `on_init=true`, `on_adopt=true`;
- executor=`host`;
- arguments default exactamente al array Composer mostrado;
- pass_env/environment/writable_paths/artifacts vacíos;
- runtime_* prohibidos/ignorados fail-closed cuando executor=host; requeridos según campo cuando executor=runtime.

Validación:
- provider sólo `composer`;
- executor sólo `host|runtime`;
- arrays de argv/nombres/paths con strings no vacíos;
- paths host relativos, sin absolute/`..`/NUL y dentro del worktree;
- artifact kind enum exacto;
- `pass_env` usa las reglas E9-S3 (nombres, no `KEY=value`);
- environment es mapping str→str y por política no contiene secretos versionados.

## 4. Arquitectura exacta

### R1 — Capability/provider
Añadir `BootstrapCapability` al registry **después de `data` y antes de `tunnel`**. Internamente usa registry explícito de providers; E10-S2 registra sólo `composer`. No plugin discovery dinámico.

### R2 — Composer provider
El executable es fijo `composer`. El TOML sólo controla `arguments`; no puede sustituir el executable por un comando arbitrario.

### R3 — Host executor
Usa `SafeProcessRunner` con:
- argv `("composer", *arguments)`;
- cwd = worktree root;
- base environment controlado + `environment` + valores existentes de `pass_env`;
- `shell=False`.

### R4 — Runtime executor
Requiere que la runtime capability resuelva un driver que implemente `RuntimeCommandExecutor` de E10-S1. Ejecuta el mismo argv dentro de `runtime_service`, con `runtime_workdir`, env explícito y user:
- `runtime_user="host"` se resuelve a `<host uid>:<host gid>`;
- no se admiten otros aliases en E10.

Si runtime no soporta execution, configuración/doctor falla antes de bootstrap.

### R5 — Writable probe
Antes de Composer, cada `writable_paths` debe probar create+delete con la **misma identidad/executor** que ejecutará Composer.

- host: operación filesystem directa y segura sobre path resuelto;
- runtime: ejecución mediante `RuntimeCommandExecutor` de una sonda fija del producto; ningún shell/script proviene del TOML.

Un fallo se clasifica como readiness/bootstrap failure, no como Composer failure.

### R6 — Composer execution
Composer corre sólo después de writable probe exitoso. No se ejecuta si el provider/executor/prerequisitos fallan.

### R7 — Artifact readiness
Después de Composer se validan todos los artifacts en el filesystem del worktree:
- file: archivo regular;
- directory: directorio;
- executable: archivo regular y executable por host.

Falta de artifact bloquea éxito.

### R8 — Idempotencia
El provider NO omite Composer basándose sólo en artifacts existentes: ejecutar Composer `install` es la operación idempotente soportada. Readiness sí puede reevaluarse sin mutación. No se inventa cache/state propio.

### R9 — Lifecycle
- `after_init` si `on_init=true`;
- `after_adopt` si `on_adopt=true`;
- no participa en `after_start` ni `before_stop`;
- no borra `vendor` en destroy: el worktree cleanup existente retira esos archivos junto al workspace.

### R10 — Doctor/status
Doctor valida provider, executor, runtime exec support (si aplica) y estructura de config sin instalar. Status:
- disabled si no configurado;
- READY si config válida pero no hay target;
- para target, READY si artifacts/readiness declarados se satisfacen; DEGRADED si no.

## 5. Caso SiVale que S4 debe poder declarar

```toml
[capabilities.bootstrap]
enabled = true
provider = "composer"
executor = "runtime"
runtime_service = "app"
runtime_workdir = "/var/www/html"
runtime_user = "host"
arguments = ["install", "--no-interaction", "--prefer-dist", "--no-progress"]
writable_paths = ["storage", "bootstrap/cache"]

[capabilities.bootstrap.environment]
COMPOSER_HOME = "/tmp/composer"

[[capabilities.bootstrap.artifacts]]
path = "vendor/autoload.php"
kind = "file"

[[capabilities.bootstrap.artifacts]]
path = "vendor/bin/pest"
kind = "executable"

[[capabilities.bootstrap.artifacts]]
path = "vendor/bin/pint"
kind = "executable"

[[capabilities.bootstrap.artifacts]]
path = "vendor/bin/deptrac"
kind = "executable"
```

No hay `framework="laravel"` ni paths Laravel en product defaults; los paths sólo existen en la configuración del cliente.

## 6. Failure/secret semantics
- valores de environment/pass_env nunca se imprimen completos;
- provider errors incluyen provider/check, no environment;
- failure en bootstrap durante init/adopt hace fallar la operación y deja el rollback al transaction contract E10-S0;
- la capability no intenta borrar dependencias preexistentes durante rollback porque no puede demostrar ownership archivo por archivo; si Composer mutó antes de fallar, el error debe quedar diagnosticable y la transacción no debe fingir rollback completo.

## 7. Acceptance Criteria
- AC-01 proyecto sin bootstrap no cambia.
- AC-02 config exacta valida/rechaza unknown/invalid fields según reglas.
- AC-03 Composer host usa argv exacto y safe env.
- AC-04 Composer runtime usa RuntimeCommandExecutor, no docker directamente.
- AC-05 writable probe usa misma identity del executor.
- AC-06 artifacts file/directory/executable se validan.
- AC-07 adopt ejecuta bootstrap cuando enabled.
- AC-08 secrets no aparecen en stdout/stderr/doctor/errors.
- AC-09 no arbitrary executable/provider ni framework branching.
- AC-10 status/doctor son no-destructivos.
- AC-11 suite + conformance PASS.

## 8. Tasks
1. Añadir config parser/validation exactos de `capabilities.bootstrap`.
2. Implementar BootstrapCapability + registry explícito con Composer únicamente.
3. Implementar executors host/runtime usando contratos existentes/E10-S1.
4. Implementar writable probe fijo, Composer y artifact readiness.
5. Integrar AFTER_INIT/AFTER_ADOPT y status/doctor.
6. Cubrir error/secret/idempotence/no-regression.
7. Ejecutar suite + conformance.

## 9. Criterio de salida
Kiro puede implementar Composer/readiness directamente desde este contrato sin decidir namespace, provider model, executor, ordering ni lifecycle.
