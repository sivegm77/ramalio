# E7-S1 — Locks y concurrencia

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E7 — Robustez, recuperación y conformidad
- **Spec:** E7-S1
- **Nombre:** Locks y concurrencia
- **Dependencias:** E7-S0, E6-S1
- **Estado inicial:** Planificada

## 2. Contexto

El producto está diseñado para operar múltiples workspaces simultáneos. Eso implica concurrencia legítima, pero algunas operaciones comparten recursos: mismo target, misma branch, mismo path, pool de puertos, runtime project names, sesiones o túneles.

El locking no debe serializar innecesariamente todos los workspaces de un usuario. Debe proteger únicamente recursos que realmente compiten.

## 3. Objetivo

Implementar un modelo de locks granular y determinista que impida carreras destructivas sin bloquear trabajo paralelo independiente.

## 4. Invariantes

- Lock por recurso, no lock global por usuario.
- Targets distintos pueden operar en paralelo si no comparten recursos.
- Orden de adquisición determinista para evitar deadlocks.
- Locks abandonados deben ser detectables/recuperables de forma segura.
- Los locks no sustituyen postcondition checks.

## 5. Requirements

### R1 — Lock manager
Debe existir una abstracción `LockManager` independiente de capabilities concretas.

### R2 — Lock scopes
Scopes mínimos: `project`, `target`, `branch`, `worktree_path`, `port_pool` y resource-specific key cuando aplique.

### R3 — Target lifecycle lock
Operaciones mutables sobre el mismo target son mutuamente excluyentes.

### R4 — Parallel targets
Dos targets distintos deben poder ejecutar operaciones compatibles simultáneamente.

### R5 — Port allocation lock
La selección/reserva de puertos debe protegerse de carreras mediante lock del pool relevante.

### R6 — Canonical lock key
La key debe derivarse de identidad canónica y paths normalizados, no de strings ambiguos.

### R7 — Deterministic ordering
Si una operación necesita múltiples locks, se adquieren según un orden global definido.

### R8 — Timeout
La espera de lock debe tener timeout configurable/razonable y devolver `LOCK_TIMEOUT`.

### R9 — Owner metadata
Un lock debe registrar metadata suficiente para diagnóstico: pid, target, operation, timestamp y host local cuando aplique.

### R10 — Stale detection
Debe detectarse lock cuyo owner local ya no existe o cuya metadata sea inválida.

### R11 — Safe stale recovery
No retirar un lock sólo por antigüedad. La recuperación requiere evidencia de owner inexistente o mecanismo del backend que libere automáticamente al morir el proceso.

### R12 — Process-scoped release
Locks se liberan en finally/context manager incluso ante excepciones.

### R13 — Cross-process
El mecanismo debe funcionar entre procesos independientes del CLI en la misma máquina.

### R14 — No distributed guarantee
E7-S1 no promete lock distribuido multi-host para el mismo filesystem remoto salvo soporte explícito futuro.

### R15 — Read operations
`list` y `status` no deben tomar locks exclusivos globales. Pueden observar mientras otros targets trabajan.

### R16 — Doctor
`doctor` debe poder reportar locks activos/stale relevantes sin modificarlos automáticamente.

## 6. Diseño

Backend inicial recomendado: locks de filesystem/OS sobre un directorio personal de estado, con keys hash de identidades canónicas. La implementación concreta debe preservar exclusión cross-process y liberación segura.

Orden sugerido:

```text
project-resource
→ target
→ branch
→ worktree_path
→ shared-pool/resource
```

La granularidad exacta puede ajustarse si pruebas demuestran menor contención sin perder seguridad.

## 7. Criterios de aceptación

- AC-01 dos `init` del mismo target no crean duplicados.
- AC-02 targets distintos pueden progresar en paralelo.
- AC-03 dos asignaciones concurrentes no reciben el mismo puerto.
- AC-04 timeout produce error claro sin mutaciones posteriores.
- AC-05 locks se liberan ante excepción.
- AC-06 stale real puede diagnosticarse y recuperarse de forma segura.
- AC-07 `list/status` no quedan bloqueados por un lock global innecesario.

## 8. Casos de prueba mínimos

- Mismo target, dos procesos.
- Targets distintos, dos procesos.
- Mismo branch derivado por config defectuosa.
- Mismo worktree path.
- Port pool concurrente.
- Lock timeout.
- Proceso owner terminado.
- Excepción dentro del critical section.
- Orden de múltiples locks.

## 9. Tasks

1. Definir scopes, keys y metadata.
2. Implementar backend cross-process local.
3. Implementar context manager de adquisición/liberación.
4. Añadir timeout.
5. Añadir stale detection segura.
6. Integrar locks en lifecycle mutable.
7. Integrar port allocation.
8. Añadir diagnóstico a doctor.
9. Crear tests multiprocess.
10. Validar paralelismo real de targets independientes.

## 10. Resultado esperado

El producto permite trabajo paralelo real sin reproducir el antipatrón de un lock global por usuario y sin permitir carreras sobre recursos compartidos.
