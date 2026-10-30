# E2-S1 — `imass-wt init`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E2 — Lifecycle fundamental
- **Spec:** E2-S1
- **Nombre:** Crear workspace administrado
- **Dependencias:** E2-S0
- **Bloquea a:** E3 y piloto posterior
- **Estado inicial:** Planificada

---

## 2. Contexto

`init` es la operación principal para crear una nueva unidad de trabajo.

Debe convertir:

```text
target
+
configuración del proyecto
```

en:

```text
branch
+
Git worktree
```

sin depender todavía de tmux, Docker, Kiro, procesos, puertos o capabilities.

La operación debe ser segura, determinista, repetible y capaz de revertir fallos parciales básicos.

---

## 3. Objetivo

Implementar:

```bash
imass-wt init <target>
```

para:

1. descubrir el proyecto;
2. normalizar y validar el target;
3. derivar branch y worktree path;
4. validar precondiciones Git;
5. crear branch desde la base configurada;
6. crear el worktree;
7. verificar el resultado;
8. devolver una salida estructurada;
9. hacer rollback si una mutación intermedia falla.

---

## 4. Alcance

### 4.1 Incluido

- Pipeline E1 completo.
- Preflight.
- Creación de branch.
- Creación de worktree.
- Verificación postcondición.
- Rollback básico.
- Idempotencia definida.
- Mensajes/exit codes.
- Tests end-to-end sobre repos Git temporales.

### 4.2 Fuera de alcance

- Bootstrap del proyecto.
- Composer/npm/pip.
- Docker.
- tmux.
- Kiro/VS Code/Codex/Claude.
- Puertos.
- Processes.
- Start/stop.
- Remote fetch.
- Push/PR.
- Registro persistente propio.

---

## 5. Principios e invariantes

### INV-01 — Target determinista

El target canónico determina branch y worktree path según E1-S2.

### INV-02 — No overwrite

`init` nunca sobrescribe una branch o worktree preexistente de forma silenciosa.

### INV-03 — Base explícita

La nueva branch nace de `project.base_branch`.

### INV-04 — Atomicidad práctica

Si la operación crea recursos y después falla, debe intentar retirar sólo lo que ella misma creó.

### INV-05 — Ownership del rollback

Rollback no puede eliminar recursos preexistentes.

### INV-06 — Sin capabilities

E2-S1 crea sólo la unidad Git/worktree fundamental.

### INV-07 — Resultado verificable

`init` sólo reporta éxito después de comprobar que branch y worktree existen y corresponden.

---

# 6. Requirements

## R1 — Entrada target

El comando requiere un target completo.

La entrada pasa por:

```text
normalize
→ validate
→ Target
→ derive identity
```

No se acepta inferencia desde branch actual o historial.

---

## R2 — Preflight de proyecto

Antes de mutar debe validarse:

- repository válido;
- config válida;
- base branch existente;
- target válido;
- branch derivada válida;
- worktree path válido.

---

## R3 — Branch preexistente

Si la branch derivada ya existe, `init` debe fallar:

```text
INIT_BRANCH_EXISTS
```

Debe orientar al usuario a `adopt` cuando corresponda, sin adoptarla automáticamente.

---

## R4 — Worktree preexistente

Si el path derivado:

- existe en filesystem;
- está registrado en Git;
- pertenece a otro worktree;

`init` debe fallar sin borrar nada.

Errores distinguibles:

```text
INIT_WORKTREE_PATH_EXISTS
INIT_WORKTREE_ALREADY_REGISTERED
```

---

## R5 — Base branch checked out

Que la base branch esté checked out en el checkout principal no bloquea por sí mismo la creación de una nueva branch derivada.

La operación debe crear una branch nueva desde la ref base.

---

## R6 — Creación de branch

La branch debe crearse a partir del commit resuelto de:

```text
project.base_branch
```

No debe depender del HEAD actual del shell si HEAD difiere de la base configurada.

---

## R7 — Creación de worktree

El worktree debe asociarse exactamente a la branch recién creada.

El path debe ser el derivado por E1-S2.

---

## R8 — No cambio del checkout invocador

`init` no debe cambiar la branch ni HEAD del checkout desde el cual se ejecutó.

---

## R9 — Postcondiciones

Antes de devolver éxito se debe verificar:

- branch existe;
- worktree está registrado;
- worktree path coincide;
- worktree usa la branch esperada;
- HEAD del worktree corresponde al commit esperado inicialmente o a un estado Git coherente tras la creación.

---

## R10 — Resultado

Un éxito debe exponer al menos:

```text
target
branch
worktree_path
base_branch
```

La representación CLI final debe respetar E0-S1.

---

## R11 — Rollback si falla después de crear branch

Si la branch fue creada por esta ejecución y el worktree no llega a crearse:

1. intentar retirar cualquier worktree parcial creado por esta ejecución;
2. eliminar la branch creada por esta ejecución si sigue siendo seguro;
3. reportar el fallo original;
4. reportar además si rollback quedó incompleto.

---

## R12 — Rollback si falla verificación post-creación

Si Git reporta una postcondición incoherente, la operación debe intentar volver al estado anterior usando ownership explícito de recursos creados.

---

## R13 — No borrar branch preexistente

Si por una condición inesperada se descubre que la branch no fue creada por esta ejecución, rollback no puede eliminarla.

---

## R14 — Idempotencia

Una segunda llamada idéntica después de un `init` exitoso no debe crear un segundo workspace ni modificar el existente.

Debe fallar de forma controlada con un diagnóstico equivalente a:

```text
WORKSPACE_ALREADY_EXISTS
```

---

## R15 — Interrupción

E2-S1 debe estructurar la operación de forma que E7 pueda fortalecer recuperación posterior.

En E2 se exige al menos que las mutaciones se registren en memoria durante la ejecución para saber qué es propiedad del rollback actual.

---

## R16 — Salida limpia

El éxito no debe mezclar output de Git sin procesar con la salida pública del CLI.

Git stderr puede conservarse como causa diagnóstica interna.

---

## R17 — Sin side effects externos

No se permiten:

- fetch;
- push;
- PR;
- runtime;
- procesos;
- herramientas de desarrollo.

---

# 7. Diseño

## 7.1 Orquestación

```text
InitWorkspaceService
```

Flujo:

```text
resolve project
      ↓
normalize + validate target
      ↓
derive identity
      ↓
observe current Git state
      ↓
preflight
      ↓
create branch
      ↓
create worktree
      ↓
verify postconditions
      ↓
return success
```

---

## 7.2 Mutation journal en memoria

Durante la ejecución:

```text
MutationJournal
├── branch_created: bool
├── worktree_created: bool
├── branch_name
└── worktree_path
```

Su objetivo en E2 es limitar rollback a recursos creados por esta misma operación.

No es persistencia durable; E7 podrá evolucionarlo.

---

## 7.3 Estrategia Git

La implementación puede:

- crear branch como parte de `git worktree add -b`;
- o crear branch y worktree en pasos separados.

La elección debe favorecer rollback claro y comportamiento testeable.

El contrato externo no depende de la variante.

---

## 7.4 Códigos de error

Como mínimo:

```text
INIT_BRANCH_EXISTS
INIT_WORKTREE_PATH_EXISTS
INIT_WORKTREE_ALREADY_REGISTERED
WORKSPACE_ALREADY_EXISTS
INIT_GIT_OPERATION_FAILED
INIT_POSTCONDITION_FAILED
INIT_ROLLBACK_INCOMPLETE
```

Los errores de E1/E2-S0 se preservan cuando corresponda.

---

## 7.5 Seguridad de rollback

Rollback debe usar:

- identidad derivada;
- journal de mutaciones;
- observación actual de Git;

antes de retirar nada.

Nunca ejecutar “cleanup global”.

---

# 8. Criterios de aceptación

## AC-01

`init` crea branch y worktree correctos desde base configurada.

## AC-02

El checkout invocador permanece en su branch original.

## AC-03

Branch existente bloquea sin mutaciones.

## AC-04

Path existente bloquea sin mutaciones.

## AC-05

Segundo `init` no duplica recursos.

## AC-06

Fallo inducido tras crear branch ejecuta rollback de branch propia.

## AC-07

Rollback no elimina una branch preexistente.

## AC-08

El éxito incluye target, branch y path.

## AC-09

No hay fetch/push ni capabilities.

## AC-10

La postcondición se verifica antes de retornar éxito.

---

# 9. Casos de prueba mínimos

### CT-01 — Happy path
Main → branch → worktree.

### CT-02 — HEAD invocador distinto a base
La nueva branch sigue naciendo desde base.

### CT-03 — Branch ya existe
Fail closed.

### CT-04 — Path ya existe
Fail closed.

### CT-05 — Worktree registrado
Fail closed.

### CT-06 — Segundo init
No duplicación.

### CT-07 — Fallo create worktree
Rollback branch.

### CT-08 — Fallo postcondition
Rollback seguro.

### CT-09 — Branch preexistente
Nunca borrada.

### CT-10 — Sin network
No fetch/push.

---

# 10. Tasks

## T1 — Crear servicio de init
Orquestación fuera de CLI.

## T2 — Integrar pipeline E1
Config + target + naming.

## T3 — Implementar preflight
Colisiones y base.

## T4 — Implementar creación Git
Branch/worktree.

## T5 — Implementar mutation journal en memoria
Ownership de rollback.

## T6 — Implementar postcondition verification
Branch/path/asociación.

## T7 — Implementar rollback
Sólo recursos propios.

## T8 — Definir errores/resultados
Contratos de init.

## T9 — Conectar comando CLI
Sin lógica profunda.

## T10 — Tests unitarios
Preflight y rollback.

## T11 — Tests integración/end-to-end
Repos temporales reales.

---

# 11. Verificación

E2-S1 está completa cuando:

- `init` funciona sobre un proyecto sin capabilities;
- es seguro ante branch/path preexistentes;
- rollback está cubierto con fallos inducidos;
- no altera el checkout invocador;
- no usa network;
- el segundo `init` no produce duplicados.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R5 | 7.1 | T1-T3 | AC-01..05 |
| R6-R10 | 7.1, 7.3 | T4, T6, T8 | AC-01,02,08,10 |
| R11-R15 | 7.2, 7.5 | T5-T7 | AC-06,07 |
| R16-R17 | 7.4 | T8-T9 | AC-08,09 |

---

# 13. Resultado esperado

Después de E2-S1 debe existir el primer flujo usable:

```text
imass-wt init <target>
        ↓
branch aislada
+
worktree aislado
```

sin capacidades opcionales y con protección básica frente a fallos parciales.
