# E3-S2 — `imass-wt stop` / `imass-wt start`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E3 — Control operativo y reanudación
- **Spec:** E3-S2
- **Nombre:** Suspensión y reanudación de workspace
- **Dependencias:** E3-S1
- **Bloquea a:** E4 — Capacidades y procesos
- **Estado inicial:** Planificada

---

## 2. Contexto

La visión del producto define un lifecycle más amplio que crear y destruir:

```text
init
↓
trabajo
↓
stop / start
↓
destroy
```

Sin embargo, en E3 todavía no existe el sistema de capabilities que posteriormente administrará tmux, procesos, runtimes, puertos o túneles.

Esta spec debe introducir correctamente el contrato de `start` y `stop` sin inventar recursos que aún no existen.

Por tanto, E3-S2 formaliza el concepto de workspace operativo `started/stopped` y establece una interfaz extensible. En el core Git-only de E3, detener un workspace no elimina branch, worktree ni trabajo local.

---

## 3. Objetivo

Implementar los contratos:

```bash
imass-wt stop <target>
imass-wt start <target>
```

de manera que:

1. el workspace Git permanezca intacto;
2. el producto tenga una semántica clara de suspensión/reanudación;
3. las operaciones sean idempotentes;
4. se prepare una frontera para que E4 conecte resources/capabilities;
5. no se cree persistencia innecesaria sólo para simular recursos inexistentes.

---

## 4. Alcance

### 4.1 Incluido

- Contrato de start.
- Contrato de stop.
- Precondiciones de identidad.
- Semántica Git-only.
- Idempotencia.
- Resultado estructurado.
- Hooks internos/preparación de extensión, sin capability framework completo.
- Integración con `status`.
- Tests.

### 4.2 Fuera de alcance

- tmux.
- processes.
- Docker Compose.
- zrok.
- puertos.
- capability registry — E4-S0.
- lifecycle hooks formalizados — E4-S1.
- persistencia durable de process state.
- matar procesos genéricos.
- desmontar worktree.
- modificar branch.
- stash/commit/reset.

---

## 5. Decisión central de E3

En un proyecto **Git-only** sin capabilities activas:

```text
stop
```

no tiene recursos operativos que apagar.

Por tanto debe ser una operación válida e idempotente que:

- verifica que el workspace existe y es coherente;
- conserva worktree/branch/trabajo;
- devuelve que no había recursos suspendibles.

De forma equivalente:

```text
start
```

verifica que el workspace sigue disponible y devuelve que no había recursos que reactivar.

No se creará una bandera persistente artificial `stopped=true` sólo para aparentar estado.

Cuando E4 introduzca capabilities, el estado operativo se derivará del estado real de esas capabilities.

---

## 6. Principios e invariantes

### INV-01 — Stop no destruye

No elimina worktree ni branch.

### INV-02 — Start no recrea Git

No crea worktree si falta; debe diagnosticar.

### INV-03 — Estado derivado de realidad

No persistir un booleano artificial si no existe recurso real que representar.

### INV-04 — Idempotencia

Start/stop repetidos son seguros.

### INV-05 — Preparación para E4

La API debe permitir agregar acciones de capabilities sin cambiar comandos públicos.

---

# 7. Requirements

## R1 — Target válido

Ambos comandos reutilizan E1 y E3-S1.

---

## R2 — Workspace requerido

`start` y `stop` requieren un workspace reconocido con identidad compatible.

Estados aceptables inicialmente:

```text
READY
DIRTY
```

Dirty no bloquea start/stop.

---

## R3 — Missing

Si el workspace está MISSING:

```text
WORKSPACE_NOT_FOUND
```

---

## R4 — Branch-only

Si está BRANCH_ONLY:

- `start` no recrea automáticamente el worktree;
- `stop` no tiene un workspace completo que detener.

Debe devolver:

```text
WORKSPACE_NOT_ACTIVE
```

o diagnóstico equivalente con sugerencia `adopt`.

---

## R5 — Inconsistent/detached/prunable

Ambos comandos deben bloquear y sugerir inspección.

No intentan reparar.

---

## R6 — `stop` Git-only

Sin resources/capabilities suspendibles:

```text
result = success
resources_stopped = 0
workspace_preserved = true
```

---

## R7 — `start` Git-only

Sin resources/capabilities:

```text
result = success
resources_started = 0
workspace_preserved = true
```

---

## R8 — No persistencia artificial

No escribir:

```text
stopped=true
```

en un state file únicamente para distinguir llamadas.

---

## R9 — Idempotencia stop

Dos `stop` consecutivos sobre un workspace Git-only producen resultados equivalentes y no mutan Git.

---

## R10 — Idempotencia start

Dos `start` consecutivos sobre un workspace Git-only producen resultados equivalentes.

---

## R11 — Preparación de operación

La capa lifecycle debe definir un contrato conceptual donde futuras capabilities puedan participar:

```text
start workspace resources
stop workspace resources
```

sin implementar todavía registry/hooks E4.

---

## R12 — Integración con status

En E3, `status` sigue reportando Git state.

Puede incluir:

```text
operational_resources: none
```

No debe reportar STARTED/STOPPED ficticio.

---

## R13 — Resultado

Start:

```text
target
workspace_path
resources_started
no_op
```

Stop:

```text
target
workspace_path
resources_stopped
no_op
```

---

## R14 — No mutaciones Git

No checkout, branch changes, remove, prune, reset.

---

## R15 — No process discovery genérico

E3 no busca PIDs, puertos ni sesiones por heurísticas.

---

# 8. Diseño

## 8.1 Servicios

```text
StartWorkspaceService
StopWorkspaceService
```

Ambos consumen `WorkspaceStatus`.

---

## 8.2 Flujo stop

```text
resolve status
      ↓
validate operationally addressable
      ↓
obtain configured operational handlers
      ↓
E3: none
      ↓
return successful no-op
```

---

## 8.3 Flujo start

Mismo patrón:

```text
resolve status
      ↓
validate workspace
      ↓
obtain operational handlers
      ↓
E3: none
      ↓
return successful no-op
```

---

## 8.4 Punto de extensión

No crear todavía `capabilities/registry.py` si E4 no lo requiere aún.

Sí debe evitarse diseñar start/stop de forma que E4 obligue a reescribir su interfaz pública.

---

## 8.5 Status

La ausencia de resources es un hecho observable:

```text
resources = []
```

no un estado persistente.

---

# 9. Criterios de aceptación

## AC-01

Stop sobre READY Git-only es éxito no-op.

## AC-02

Stop sobre DIRTY es éxito y preserva cambios.

## AC-03

Start sobre READY Git-only es éxito no-op.

## AC-04

Missing falla.

## AC-05

Branch-only no se recrea.

## AC-06

Inconsistent bloquea.

## AC-07

Dos stop son idempotentes.

## AC-08

Dos start son idempotentes.

## AC-09

No existe state file artificial de started/stopped.

## AC-10

No hay Git/process mutations.

---

# 10. Casos de prueba mínimos

### CT-01 — stop READY
No-op.

### CT-02 — stop DIRTY
No tocar cambios.

### CT-03 — start READY
No-op.

### CT-04 — missing
Fail.

### CT-05 — branch-only
Sugerir adopt.

### CT-06 — inconsistent
Fail closed.

### CT-07 — repeated stop
Equivalente.

### CT-08 — repeated start
Equivalente.

### CT-09 — no state artifact
Filesystem unchanged.

### CT-10 — no process heuristics
No ejecución de herramientas externas ajenas a Git/status.

---

# 11. Tasks

## T1 — Definir resultados start/stop
Estructurados.

## T2 — Crear `StartWorkspaceService`
Consumir status.

## T3 — Crear `StopWorkspaceService`
Consumir status.

## T4 — Implementar precondition matrix
READY/DIRTY/MISSING/etc.

## T5 — Implementar no-op Git-only
Sin state artificial.

## T6 — Preparar interfaz interna para handlers futuros
Sin capability framework adelantado.

## T7 — Integrar status
Resources vacíos.

## T8 — Conectar CLI
Start/stop.

## T9 — Tests unitarios
Matriz e idempotencia.

## T10 — Tests integración
Preservación real de worktree/branch/dirty state.

---

# 12. Verificación

E3-S2 está completa cuando:

- start/stop ya forman parte del CLI;
- su semántica Git-only es correcta y no inventa estado;
- dirty work se conserva;
- E4 puede extenderlos sin cambiar la interfaz pública;
- no hay process/resource heuristics prematuras.

---

# 13. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R5 | 8.1-8.3 | T2-T4 | AC-01..06 |
| R6-R10 | 8.2-8.5 | T5, T7 | AC-01..09 |
| R11-R13 | 8.4 | T1, T6, T8 | AC-01,03 |
| R14-R15 | 8.5 | T9-T10 | AC-10 |

---

# 14. Resultado esperado

Después de E3-S2, el lifecycle público ya queda expresado como:

```text
init
start
stop
destroy
```

aunque en un proyecto Git-only start/stop sean no-op válidos.

Esto evita acoplar el core a recursos que todavía no existen y deja preparado el punto correcto para E4.
