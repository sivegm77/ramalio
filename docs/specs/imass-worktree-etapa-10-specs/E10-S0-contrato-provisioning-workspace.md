# E10-S0 — Contrato de provisioning del workspace

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E10 — Convergencia de workspace provisioning
- **Spec:** E10-S0
- **Nombre:** Contrato de provisioning del workspace
- **Dependencias:** E9-S3, E7-S0, E7-S1, E7-S2, E7-S3
- **Bloquea a:** E10-S1, E10-S2, E10-S3
- **Estado inicial:** Planificada

## 2. Contexto

E8 demostró que una identidad Git válida no garantiza que un workspace complejo esté listo. La solución no es un framework adapter ni scripts del cliente: provisioning será participación de capabilities en el lifecycle existente.

## 3. Objetivo

Extender el lifecycle existente con el mínimo contrato necesario para que capabilities opcionales puedan provisionar un workspace después de `init` y `adopt`, reutilizando registry, hooks, transaction journal, locks, safety y observabilidad actuales.

## 4. Alcance

Incluye:
- semántica de provisioning;
- `init` mediante `after_init` existente;
- **un único evento nuevo `after_adopt`**;
- integración de ambos escenarios exitosos de adopt con HookRunner/LifecycleTransaction;
- ordering por registry;
- rollback/ownership existente;
- doctor/status vía capability contract existente;
- no-regression Git-only.

Fuera:
- tecnología concreta;
- nuevo CLI;
- before_adopt;
- workflow engine/DAG;
- segundo registry/transaction/lock/runner;
- persistencia nueva de estado READY.

## 5. Requirements

### R1 — Opcional
Sin capabilities E10 habilitadas, todos los proyectos conservan comportamiento observable previo.

### R2 — Init usa `after_init`
No se crea un evento nuevo para init. Las capabilities de provisioning participan en `LifecycleEvent.AFTER_INIT` después de que el worktree Git existe y antes de que `init` devuelva éxito.

### R3 — Nuevo `after_adopt`
`LifecycleEvent` MUST añadir exactamente `AFTER_ADOPT = "after_adopt"`. No se añade `BEFORE_ADOPT` en E10.

### R4 — Adopt existing-worktree
Después de validar un worktree compatible, `AdoptWorkspaceService` MUST abrir una `LifecycleTransaction`, ejecutar `AFTER_ADOPT` mediante `HookRunner` y devolver éxito sólo si los hooks terminan. Como Git no fue mutado por esa llamada, la transacción sólo registra mutaciones de capabilities.

### R5 — Adopt created-worktree
Cuando adopt crea el worktree para una branch preexistente, el worktree creado y los hooks `AFTER_ADOPT` MUST formar parte de la misma `LifecycleTransaction`; rollback retira sólo el worktree creado por esa llamada y compensa únicamente capabilities propias.

### R6 — Ordering
Setup events (`AFTER_INIT`, `AFTER_ADOPT`, `AFTER_START`) ejecutan capabilities en registry order. Teardown mantiene reverse registry order existente. No se introduce scheduler.

### R7 — Ownership/idempotencia
Cada capability es responsable de observar si su recurso ya existía y reportar `changed` correctamente; rollback jamás elimina recursos preexistentes sólo porque la capability los observó.

### R8 — Failure semantics
Una excepción/hook failure de provisioning mantiene el exit/error mapping existente (`CapabilityHookFailedError`/errores de dominio); no se crea un exit code E10.

### R9 — Doctor/status
No se crea un subsistema de readiness. Doctor usa `doctor_checks`; status usa `CapabilityStatus`. `init/adopt` sólo reportan éxito cuando los hooks requeridos terminan satisfactoriamente.

### R10 — Start/stop
E10-S0 no modifica `start/stop`; downstream capabilities deciden si reaccionan a esos eventos. Bootstrap/data inicial no se repite automáticamente por start.

### R11 — Integrations
Las integrations opcionales se abren sólo después del éxito del servicio lifecycle. Provisioning debe completar antes de `--open` en init.

### R12 — Seguridad
Toda ejecución nueva downstream debe respetar E7-S2/E9-S3: argv estructurado, environment controlado, no implicit shell tokenization y sin secretos en diagnostics.

### R13 — No coupling
No se acepta lógica central por `sivale`, `zurich`, `laravel`, `project.name`, `KIRO_PROJECT_ROOT` o `KIRO_DEVELOPER`.

### R14 — No scripts lifecycle del cliente
E10 no define un “run arbitrary project hook script” como mecanismo de provisioning.

### R15 — No regresión
Suite completa y conformance permanecen verdes.

## 6. Diseño normativo

### 6.1 Evento

```text
LifecycleEvent.AFTER_ADOPT = "after_adopt"
```

`is_after` lo reconoce por prefijo. `is_teardown` permanece falso.

### 6.2 Flujo init

```text
lock target
→ transaction existente
→ BEFORE_INIT
→ crear branch/worktree
→ AFTER_INIT (provisioning incluido por registry)
→ commit transaction
→ resultado init
→ integration opcional en capa existente
```

### 6.3 Flujo adopt existing

```text
lock target
→ validar compatible
→ transaction sin mutación Git
→ AFTER_ADOPT
→ commit
→ AdoptOutcome(existing-worktree)
```

### 6.4 Flujo adopt branch-only

```text
lock target
→ transaction
→ crear worktree para branch existente
→ registrar worktree como owned step
→ AFTER_ADOPT
→ postcondition
→ commit
→ AdoptOutcome(created-worktree)
```

### 6.5 Registro E10
Las capabilities concretas de E10 se incorporarán en specs posteriores. El orden relativo final requerido será `ports → runtime → data → bootstrap → tunnel`; E10-S0 sólo congela que setup usa registry order y teardown su reversa.

## 7. Acceptance Criteria
- AC-01 Git-only no cambia.
- AC-02 fake capability recibe AFTER_INIT.
- AC-03 fake capability recibe AFTER_ADOPT en ambos modos de adopt.
- AC-04 failure de AFTER_ADOPT en created-worktree revierte worktree creado y mutaciones propias.
- AC-05 failure de AFTER_ADOPT en existing-worktree preserva Git preexistente.
- AC-06 preexisting capability resource no se compensa.
- AC-07 doctor/status no requieren nueva persistencia.
- AC-08 sólo se añade AFTER_ADOPT; no BEFORE_ADOPT ni CLI nuevo.
- AC-09 no aparecen framework/project conditionals.
- AC-10 suite completa + conformance PASS.

## 8. Tasks
1. Añadir `AFTER_ADOPT` al enum existente y tests de clasificación del evento.
2. Cablear `AdoptWorkspaceService` a `HookRunner`/`LifecycleTransaction` exactamente para los dos escenarios exitosos.
3. Preservar rollback del worktree sólo en branch-only.
4. Añadir fake capability tests de changed/compensation/preexisting ownership.
5. Añadir regression Git-only para init/adopt.
6. Verificar que init sigue usando AFTER_INIT sin otro evento.
7. Ejecutar suite completa + conformance.

## 9. Criterio de salida
Existe provisioning genérico sobre hooks existentes para init/adopt, sin tecnología concreta, sin estado paralelo y sin decisiones arquitectónicas pendientes para las specs downstream.
