# E10-S3 — Data provisioning PostgreSQL

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E10
- **Spec:** E10-S3
- **Nombre:** Data provisioning PostgreSQL
- **Dependencias:** E10-S0, E10-S1, E7-S0, E7-S1, E7-S2
- **Bloquea a:** E10-S4
- **Estado inicial:** Planificada

## 2. Contexto

SiVale necesita copiar la base PostgreSQL del checkout/proyecto base hacia una base aislada del runtime del target. E10-S3 implementa únicamente ese caso real sobre el runtime execution contract de S1.

## 3. Configuración pública exacta

Namespace nuevo:

```toml
[capabilities.data]
enabled = true
provider = "postgres"          # único provider E10-S3
on_init = true
on_adopt = true
runtime_service = "db"
readiness_timeout = 30         # segundos, entero > 0
cleanup_mode = "runtime"      # preserve | runtime
```

Defaults:
- ausencia = disabled;
- provider requerido cuando enabled;
- on_init/on_adopt=true;
- runtime_service=`db`;
- readiness_timeout=30;
- cleanup_mode=`preserve` por seguridad en configuración genérica.

Si `cleanup_mode="runtime"`, la config MUST exigir runtime Docker Compose con `remove_volumes_on_destroy=true`; de otro modo `PROJECT_CONFIG_INVALID`. No existe `drop database` automático en E10-S3.

No se configuran username/password/database en TOML. El provider obtiene `POSTGRES_USER` y `POSTGRES_DB` dentro de cada service scope y nunca lee/imprime `POSTGRES_PASSWORD`.

## 4. Arquitectura exacta

### R1 — Capability/provider
Añadir `DataCapability` al default registry **después de runtime y antes de bootstrap**. Provider registry explícito con único provider `postgres`.

### R2 — Runtime requirement
Postgres provider requiere que el runtime activo implemente `RuntimeCommandExecutor`. No conoce `docker compose` ni importa el driver concreto.

### R3 — Scopes fijos
- source = runtime scope `project` (`workspace=None`, repository root, base_project_pattern);
- target = runtime scope `workspace` (target worktree/project_pattern).

Estos scopes no son configurables en E10-S3; responden al caso soportado y evitan ampliar superficie.

### R4 — Ensure services
Durante provisioning:
1. `ensure_service(project, None, runtime_service)`;
2. `ensure_service(workspace, target_workspace, runtime_service)`.

### R5 — Resolve identity inside service
En cada scope el provider ejecuta argv estructurado:

```text
printenv POSTGRES_USER
printenv POSTGRES_DB
```

Los resultados deben ser no vacíos. No se obtiene password.

### R6 — Readiness
Target se prueba con:

```text
pg_isready -U <target_user> -d <target_db>
```

hasta `readiness_timeout`, con intervalo acotado. Source también debe responder antes del dump.

### R7 — Snapshot
Source scope ejecuta exactamente la semántica:

```text
pg_dump -U <source_user> -d <source_db> --clean --if-exists --no-owner --no-privileges
```

El dump no se imprime. Puede mantenerse en memoria o temp file de modo 0600; si se usa temp file se elimina en success/failure.

### R8 — Restore
Target scope ejecuta:

```text
psql -v ON_ERROR_STOP=1 -U <target_user> -d <target_db>
```

recibiendo dump por `stdin` del RuntimeExecRequest. Return code no cero falla provisioning.

### R9 — Source safety
No se ejecuta DDL destructivo directamente sobre source. `pg_dump --clean` sólo emite instrucciones al dump; la aplicación de esas instrucciones ocurre exclusivamente en target.

### R10 — Idempotencia
Cada `init/adopt` habilitado puede volver a restaurar el snapshot sobre el target propio. Esa es la semántica determinista de convergencia; no se introduce fingerprint/caching de DB.

### R11 — Cleanup
- `preserve`: DataCapability no destruye data en destroy.
- `runtime`: DataCapability declara cleanup delegado y `RuntimeCapability` ejecuta posteriormente `down -v` target-scoped por reverse registry order (`bootstrap → data → runtime`). DataCapability no ejecuta `dropdb`.

### R12 — Rollback
Si target runtime/data fue creado por la operación, las capacidades que lo poseen se compensan conforme transaction journal. El provider PostgreSQL nunca toca source durante rollback. Si un restore parcial queda en un runtime preexistente que la operación no posee, se reporta rollback incompleto/degradado en vez de destruirlo.

### R13 — Doctor/status
Doctor valida provider, runtime exec support y config sin dump/restore. Status de target:
- DISABLED si no config;
- READY si provider/config válida sin target;
- ACTIVE/READY si target service responde a pg_isready;
- DEGRADED si no.

## 5. Caso SiVale para E10-S4

```toml
[capabilities.data]
enabled = true
provider = "postgres"
on_init = true
on_adopt = true
runtime_service = "db"
readiness_timeout = 30
cleanup_mode = "runtime"
```

Y runtime SiVale deberá declarar `remove_volumes_on_destroy=true`.

## 6. Acceptance Criteria
- AC-01 proyecto sin data no cambia.
- AC-02 config exacta valida y unknown/invalid fields fail-closed.
- AC-03 source/project y target/workspace usan identities distintas.
- AC-04 dos targets no comparten target runtime/data.
- AC-05 source no recibe restore/drop.
- AC-06 pg_dump argv y psql argv son exactos y shell-free a nivel host/runtime request.
- AC-07 dump no se imprime ni persiste insecure.
- AC-08 adopt converge target propio.
- AC-09 cleanup preserve/runtime respeta policy exacta.
- AC-10 runtime cleanup requerido para mode runtime se valida antes de mutar.
- AC-11 secrets no aparecen.
- AC-12 sólo provider postgres.
- AC-13 suite + conformance PASS.

## 7. Tasks
1. Añadir config exacta de `capabilities.data`.
2. Implementar DataCapability después de runtime y antes de bootstrap.
3. Implementar provider registry explícito + Postgres provider.
4. Implementar ensure/readiness/identity/dump/restore vía RuntimeCommandExecutor.
5. Implementar cleanup mode contract sin dropdb.
6. Cubrir source safety, dos targets, rollback y redaction.
7. Ejecutar suite + conformance.

## 8. Criterio de salida
Kiro no necesita decidir namespace, source/target model, snapshot/restore semantics, cleanup ni runtime integration; sólo implementar este contrato.
