# Modelo de workspace provisioning — ramalio

## 1. Propósito

Define el modelo arquitectónico previo a E10 para cerrar la brecha detectada al comparar el lifecycle real de SiVale con el producto actual. No es código ni documentación de feature ya implementada; es autoridad de diseño para las specs E10.

Evita dos errores:
1. introducir SiVale/Laravel en el core;
2. devolver al proyecto cliente scripts propios de lifecycle.

## 2. Problema observado

El producto materializa identidad Git y coordina ports/runtime/processes/tmux/tunnel/integrations, pero el lifecycle legacy de SiVale prepara además configuración local, base aislada, runtime construido/arrancado, dependencias y readiness.

```text
branch + worktree válidos ≠ siempre workspace listo
```

## 3. Workspace listo

### Git-only
`target → branch → worktree` válido = READY.

### Con provisioning
Identidad Git válida + capabilities de provisioning satisfechas + readiness = READY.

No se crea un segundo estado persistente; `status` deriva estado de Git/capabilities.

## 4. Frontera de responsabilidades

| Responsabilidad | Dueño |
|---|---|
| target/branch/worktree | core existente |
| locks/transaction/safety/boundaries | core existente |
| selección/naming | configuración |
| ports/processes/tmux/tunnel | capabilities existentes |
| IDE/IA | integrations |
| runtime | runtime existente ampliado por E10-S1 |
| bootstrap/dependencies/readiness | capability `bootstrap` E10-S2 |
| data aislada | capability `data` E10-S3 |
| deploy/build de release/negocio | proyecto cliente |

## 5. Decisiones arquitectónicas cerradas

### 5.1 No existe una nueva “provisioning engine”
Provisioning significa **capabilities existentes/nuevas respondiendo a hooks del lifecycle**. Se reutilizan `CapabilityRegistry`, `HookRunner`, `LifecycleTransaction`, locks y `SafeProcessRunner`.

### 5.2 Único evento nuevo
`init` ya dispone de `after_init`. Para `adopt`, E10-S0 añade exactamente:

```text
after_adopt
```

No se añade `before_adopt` porque la necesidad demostrada es provisionar después de que la identidad Git compatible exista/materialice.

### 5.3 Adopt
Tanto `existing-worktree` como `created-worktree` ejecutan `after_adopt` antes de devolver éxito. El primer modo journaliza sólo mutaciones de capabilities; el segundo incluye además el worktree creado dentro de la transacción existente.

### 5.4 Ordering
Se usa registry order en setup y reverse order en teardown. Con E10, el orden relativo requerido es:

```text
... → ports → runtime → data → bootstrap → tunnel → ...
```

No se introduce DAG runtime. Data depende de runtime; bootstrap corre después de data.

### 5.5 Runtime execution contract
E10-S1 extiende el runtime existente con `provision(workspace)` y un protocolo opcional `RuntimeCommandExecutor` para providers que necesiten ejecutar argv dentro de un runtime. Sólo Docker Compose implementa ese protocolo en E10.

### 5.6 Configuración exacta
Los namespaces nuevos son únicamente:

```text
[capabilities.bootstrap]   # E10-S2
[capabilities.data]        # E10-S3
```

Runtime se amplía dentro de `[capabilities.runtime]`; no se agrega `framework` ni `workspace preset`.

## 6. Lifecycle objetivo

### init
validar → crear Git → `after_init` en registry order → readiness implícita por éxito de capabilities → integration opcional → éxito.

### adopt
validar/materializar Git → `after_adopt` en registry order → éxito.

### start
reactiva recursos. No repite bootstrap/data provisioning inicial.

### stop
suspende recursos sin destruir Git.

### destroy
teardown en reverse registry order y después retiro Git conforme a contratos existentes.

## 7. Idempotencia
- cada capability observa estado antes de mutar;
- rollback sólo compensa recursos creados/cambiados por la operación;
- start no equivale a init;
- adopt completa faltantes sin duplicar recursos propios válidos;
- readiness puede reevaluarse sin mutación.

## 8. Seguridad
- structured argv;
- `shell=False` en host;
- runtime command requests también son argv estructurado;
- cwd/path boundaries validados;
- environment controlado;
- `pass_env` sólo allowlist;
- secretos fuera del TOML y diagnostics;
- si un provider usa un shell dentro de un contenedor para una sonda fija, el script es constante del producto, nunca texto arbitrario proveniente del TOML.

## 9. Clasificación SiVale

| Legacy | Destino E10 |
|---|---|
| branch/worktree | core |
| port | ports |
| compose identity | runtime |
| copiar `.env` local | runtime `materialize_env_file` |
| `up -d --build` | runtime `provision()` |
| base/target DB + dump/restore | data/postgres |
| Composer | bootstrap/composer |
| writable probe | bootstrap readiness |
| artifacts vendor/bin | bootstrap readiness |
| `down -v` target | runtime `remove_volumes_on_destroy` opt-in |
| tmux/Kiro | existentes |

## 10. Fuera de alcance
- framework detection;
- scripts arbitrarios como workflow engine;
- nuevos runtimes;
- package managers distintos de Composer;
- DB engines distintos de PostgreSQL;
- CI/CD/deploy/business bootstrap;
- nuevo CLI;
- otro lock/transaction/runner.

## 11. DAG E10

```text
E10-S0
  ├──→ E10-S1 ───→ E10-S3 ─┐
  └──→ E10-S2 ──────────────┼→ E10-S4
                             ┘
```

S1 y S2 pueden implementarse en paralelo. S3 requiere S1 por el runtime execution contract.
