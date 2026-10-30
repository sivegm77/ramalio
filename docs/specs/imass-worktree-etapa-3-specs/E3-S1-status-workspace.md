# E3-S1 — `imass-wt status <target>`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E3 — Control operativo y reanudación
- **Spec:** E3-S1
- **Nombre:** Estado detallado de un workspace
- **Dependencias:** E3-S0
- **Bloquea a:** E3-S2, E3-S3 y capabilities posteriores
- **Estado inicial:** Planificada

---

## 2. Contexto

`list` ofrece una vista rápida, pero no explica en detalle qué ocurre con un target concreto.

`status` debe convertirse en la herramienta principal para responder:

- ¿existe?
- ¿qué branch usa?
- ¿dónde está?
- ¿está limpio o dirty?
- ¿hay inconsistencias?
- ¿está listo para operar?
- ¿podría destruirse con seguridad desde la perspectiva Git?

En E3 todavía no existe el sistema formal de capabilities de E4. Por tanto, esta spec define un contrato extensible que pueda incorporar estados adicionales más adelante sin rediseñar el comando.

---

## 3. Objetivo

Implementar:

```bash
imass-wt status <target>
```

para producir un diagnóstico detallado, read-only y estructurado del workspace correspondiente.

---

## 4. Alcance

### 4.1 Incluido

- Resolución de target.
- Identidad esperada.
- Branch real.
- Worktree real.
- HEAD.
- Clean/dirty/untracked.
- Detached.
- Mismatch.
- Branch missing.
- Worktree missing.
- Estado conceptual del workspace.
- Evaluación básica de seguridad para destroy.
- Resultado extensible.

### 4.2 Fuera de alcance

- Reparar inconsistencias.
- Start/stop — E3-S2.
- Capabilities — E4.
- Runtime/puertos/tmux.
- Network.
- Historial completo de commits.
- Comparación con remote.
- Determinar si PR fue mergeado externamente.

---

## 5. Principios e invariantes

### INV-01 — Read-only

`status` nunca muta Git/filesystem.

### INV-02 — Esperado vs observado

Debe distinguir:

```text
expected identity
observed reality
```

### INV-03 — No ocultar parciales

Branch-only, path-only o mismatch deben aparecer explícitamente.

### INV-04 — Extensible

El resultado debe permitir agregar capabilities más adelante.

### INV-05 — Git local solamente

No depende de remotes.

---

# 6. Requirements

## R1 — Entrada target

El target se normaliza/valida y produce identidad derivada.

---

## R2 — Identidad esperada

Debe mostrar al menos:

```text
target
expected_branch
expected_worktree_path
```

---

## R3 — Observación real

Debe consultar:

```text
branch_exists
branch_checked_out_where
worktree_registered
worktree_branch
worktree_head
worktree_path_exists
```

---

## R4 — Git status detallado

Para worktree existente y compatible:

```text
clean
tracked_changes
untracked_changes
detached
```

No es necesario listar cada diff completo.

Puede incluir contadores o flags.

---

## R5 — Estados conceptuales iniciales

Debe producir uno de:

```text
READY
DIRTY
BRANCH_ONLY
MISSING
INCONSISTENT
DETACHED
PRUNABLE
```

### Semántica

`READY`
: branch/worktree compatibles y clean.

`DIRTY`
: compatibles con cambios locales.

`BRANCH_ONLY`
: branch existe, worktree no.

`MISSING`
: no existe branch ni worktree esperados.

`INCONSISTENT`
: realidad contradice identidad.

`DETACHED`
: path esperado en detached HEAD.

`PRUNABLE`
: Git marca worktree como prunable/missing.

---

## R6 — Razones

Estados no normales deben incluir razones estructuradas.

Ejemplos:

```text
BRANCH_NOT_FOUND
WORKTREE_NOT_FOUND
WORKTREE_PATH_MISMATCH
WORKTREE_BRANCH_MISMATCH
BRANCH_IN_OTHER_WORKTREE
WORKTREE_DETACHED
WORKTREE_PRUNABLE
```

---

## R7 — Destroy readiness

Debe evaluar de forma informativa:

```text
destroy_safe: true | false
destroy_blockers: [...]
```

Esta evaluación reutiliza reglas de E2-S3.

No ejecuta destroy.

---

## R8 — Init/adopt guidance

El resultado puede indicar acción conceptual sugerida:

```text
suggested_action:
  init | adopt | none | inspect
```

Reglas:

- MISSING → init.
- BRANCH_ONLY compatible → adopt.
- READY/DIRTY → none.
- INCONSISTENT/DETACHED/PRUNABLE → inspect.

No ejecutar automáticamente la acción.

---

## R9 — Worktree dirty

Dirty no es inconsistencia.

Debe conservar identidad reconocida y mostrar blockers de destroy.

---

## R10 — Branch-only

Si branch existe y no está checked out:

```text
state = BRANCH_ONLY
suggested_action = adopt
```

---

## R11 — Branch en otro path

Si branch está checked out fuera del path canónico:

```text
state = INCONSISTENT
reason = BRANCH_IN_OTHER_WORKTREE
```

---

## R12 — Salida estructurada

El servicio debe devolver un objeto equivalente a:

```text
WorkspaceStatus
├── identity
├── state
├── observed
├── git
├── destroy_safety
└── suggested_action
```

---

## R13 — Salida humana

Debe ser legible sin obligar al usuario a interpretar datos crudos.

Ejemplo conceptual:

```text
Target: FEATURE-123-login
State: DIRTY
Branch: spec/FEATURE-123-login
Worktree: /repo/.local-wt/FEATURE-123-login
Git: 2 tracked changes, 1 untracked
Destroy safe: no
Suggested action: none
```

---

## R14 — Future capabilities slot

El modelo debe reservar una sección conceptual:

```text
capabilities: []
```

o equivalente, inicialmente vacía en E3.

No implementar capabilities aquí.

---

## R15 — Workspace inexistente

`status` sobre target inexistente debe producir un resultado diagnóstico `MISSING`, no necesariamente un error operacional.

La CLI debe poder distinguir consulta exitosa de estado ausente.

---

## R16 — Sin mutaciones/network

No prune, fetch, pull, checkout, reset, clean ni remove.

---

# 7. Diseño

## 7.1 Servicio

```text
GetWorkspaceStatusService
```

Flujo:

```text
resolve identity
      ↓
observe branch/worktree
      ↓
classify state
      ↓
observe git status when applicable
      ↓
evaluate destroy safety
      ↓
derive suggested action
      ↓
return WorkspaceStatus
```

---

## 7.2 Reutilización

Debe reutilizar lógica de:

- E2-S0 observation;
- E2-S3 destroy preconditions;
- E3-S0 recognition cuando sea aplicable.

No duplicar reglas.

---

## 7.3 Clasificador

La clasificación debe ser determinista y testeable por tabla de estados.

---

## 7.4 Extensibilidad

E4 podrá añadir:

```text
capabilities:
- name
- state
- details
```

sin cambiar el núcleo de identidad/Git.

---

# 8. Criterios de aceptación

## AC-01

Workspace clean compatible → READY.

## AC-02

Compatible dirty → DIRTY.

## AC-03

Branch-only → BRANCH_ONLY + adopt.

## AC-04

Nada existe → MISSING + init.

## AC-05

Branch en otro path → INCONSISTENT.

## AC-06

Detached → DETACHED.

## AC-07

Prunable → PRUNABLE.

## AC-08

Dirty bloquea `destroy_safe`.

## AC-09

Resultado incluye expected vs observed.

## AC-10

No realiza mutaciones/network.

---

# 9. Casos de prueba mínimos

### CT-01 — READY
Clean.

### CT-02 — DIRTY tracked
Destroy false.

### CT-03 — Untracked
DIRTY.

### CT-04 — BRANCH_ONLY
Adopt.

### CT-05 — MISSING
Init.

### CT-06 — Wrong path
Inconsistent.

### CT-07 — Wrong branch
Inconsistent.

### CT-08 — Detached
Detached.

### CT-09 — Prunable
Prunable.

### CT-10 — Read-only
Sin mutations.

---

# 10. Tasks

## T1 — Definir `WorkspaceStatus`
Modelo estructurado.

## T2 — Implementar state classifier
Tabla determinista.

## T3 — Integrar observación E2-S0
Expected/observed.

## T4 — Integrar Git status
Flags/contadores.

## T5 — Reutilizar destroy safety
Blockers informativos.

## T6 — Implementar suggested action
Init/adopt/none/inspect.

## T7 — Reservar capability status collection
Vacía en E3.

## T8 — Conectar CLI
Salida detallada.

## T9 — Tests unitarios de clasificación
Todas las combinaciones.

## T10 — Tests integración
Worktrees reales.

---

# 11. Verificación

E3-S1 está completa cuando `status` puede explicar con claridad el estado Git/local de cualquier target sin modificarlo y sin depender de capabilities futuras.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R4 | 7.1 | T1, T3-T4 | AC-01,02,09 |
| R5-R6 | 7.3 | T2 | AC-01..07 |
| R7-R11 | 7.2 | T5-T6 | AC-03..08 |
| R12-R15 | 7.4 | T1, T7-T8 | AC-09 |
| R16 | 7.1 | T10 | AC-10 |

---

# 13. Resultado esperado

Después de E3-S1, el desarrollador puede preguntar:

```bash
imass-wt status FEATURE-123-login
```

y obtener una explicación completa del estado local del workspace y de cualquier inconsistencia relevante.
