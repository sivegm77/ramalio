# E4-S1 — Lifecycle hooks

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E4 — Capacidades y procesos
- **Spec:** E4-S1
- **Nombre:** Lifecycle hooks para capabilities
- **Dependencias:** E4-S0
- **Bloquea a:** E4-S2, E5, E6
- **Estado inicial:** Planificada

---

## 2. Contexto

E4-S0 define qué es una capability y cómo se registra.

Ahora se necesita conectar las capabilities al lifecycle sin incrustar lógica concreta dentro de:

```text
init
start
stop
destroy
```

La visión del producto ya contempla eventos conceptuales:

```text
before_init
after_init
before_start
after_start
before_stop
after_stop
before_destroy
after_destroy
```

Esta spec formaliza ese contrato.

---

## 3. Objetivo

Implementar un runner de lifecycle hooks que:

1. exponga eventos estables;
2. invoque capabilities habilitadas en orden determinista;
3. defina fail behavior por fase;
4. permita rollback/compensación cuando corresponda;
5. mantenga separada la operación central de Git de las capabilities;
6. produzca resultados observables y testeables.

---

## 4. Alcance

### Incluido

- Enum/contrato de eventos.
- Hook runner.
- Orden determinista.
- Contexto por evento.
- Resultados.
- Error propagation.
- Reglas before/after.
- Integración con init/start/stop/destroy.
- Tests con capabilities fake.
- Compensación básica de acciones de capability realizadas durante una operación.

### Fuera de alcance

- Implementación concreta de processes — E4-S2.
- tmux/runtime/tunnels.
- Distributed transactions.
- Persistencia durable de journal — E7.
- Retry automático genérico.
- Ejecución paralela de hooks.

---

## 5. Principios e invariantes

### INV-01 — Core lifecycle sigue siendo autoridad

Los hooks complementan; no reemplazan las reglas de seguridad de Git.

### INV-02 — Orden determinista

Las capabilities se ejecutan en orden estable.

### INV-03 — Fail closed en before

Un `before_*` fallido bloquea la operación principal correspondiente.

### INV-04 — After no falsifica éxito

Un fallo en `after_*` debe reportarse; no debe esconderse como éxito completo.

### INV-05 — No concurrencia prematura

Los hooks se ejecutan secuencialmente en E4.

### INV-06 — Compensación explícita

Sólo se compensa lo creado/modificado por la operación actual.

---

# 6. Requirements

## R1 — Eventos soportados

Debe existir exactamente este conjunto inicial:

```text
before_init
after_init
before_start
after_start
before_stop
after_stop
before_destroy
after_destroy
```

---

## R2 — Hook API

Una capability debe poder implementar callbacks equivalentes a:

```text
before_init(context)
after_init(context)
before_start(context)
after_start(context)
before_stop(context)
after_stop(context)
before_destroy(context)
after_destroy(context)
```

Se permite una API genérica `handle(event, context)` si mantiene igual semántica.

---

## R3 — Hooks opcionales

Una capability no está obligada a implementar todos los eventos.

Los no soportados son no-op.

---

## R4 — Contexto

Debe incluir como mínimo cuando aplique:

```text
project
target
workspace_identity
workspace_status
operation
```

y datos de resultado de la operación central para `after_*`.

---

## R5 — Before init

Se ejecuta después de preflight suficiente para conocer identidad, pero antes de crear branch/worktree.

Si falla:

- no se muta Git;
- init termina bloqueado.

---

## R6 — After init

Se ejecuta después de que el worktree fundamental exista y haya pasado postcondición Git.

Si una capability falla:

- iniciar compensación de capabilities ya activadas por esta operación cuando sea seguro;
- el lifecycle debe reportar fallo parcial;
- no destruir automáticamente el worktree Git salvo que el contrato de rollback de init determine que toda la operación debe revertirse y pueda hacerlo de forma segura.

### Decisión inicial

En E4, `init` sigue siendo una operación unitaria de workspace. Si `after_init` de una capability habilitada requerida falla, se intenta compensar capabilities y luego revertir el worktree/branch usando el rollback seguro ya existente en E2-S1.

---

## R7 — Before start

Fallo bloquea reactivación.

---

## R8 — After start

Fallo en capability produce start incompleto y debe activar compensación de las capabilities arrancadas por esa ejecución en orden inverso.

---

## R9 — Before stop

Fallo bloquea stop si la capability declara que detenerla es obligatorio para preservar consistencia.

En E4, todo hook failure se considera bloqueante salvo contrato futuro explícito.

---

## R10 — After stop

Fallo debe reportarse como stop incompleto.

No re-arrancar automáticamente capabilities ya detenidas salvo compensación explícitamente implementada y segura.

---

## R11 — Before destroy

Debe ejecutarse antes de eliminar el Git worktree.

Si falla, destroy se bloquea.

Esto permite que capabilities retiren/validen recursos antes de perder el workspace.

---

## R12 — After destroy

Se ejecuta después del retiro Git fundamental.

Sólo debe usarse para cleanup que no requiera que el worktree siga presente.

---

## R13 — Orden normal

Capabilities habilitadas se ejecutan en orden del registry.

---

## R14 — Orden de compensación

La compensación se ejecuta en orden inverso al de acciones exitosas.

---

## R15 — Hook result

Cada ejecución debe producir:

```text
HookResult
├── capability
├── event
├── success
├── changed
├── summary
└── compensation?
```

---

## R16 — Exception boundary

Excepciones internas deben traducirse a:

```text
CAPABILITY_HOOK_FAILED
```

con capability/event.

---

## R17 — Integración status

Después de una operación fallida, `status` debe poder observar el estado real de capabilities; no persistir un éxito ficticio.

---

## R18 — No hook desde CLI

El CLI no invoca capabilities directamente.

La capa lifecycle coordina runner + operación central.

---

## R19 — Tests de orden

Debe demostrarse:

```text
A before
B before
core
A after
B after
```

según el evento y diseño elegido, y compensación inversa cuando aplique.

---

# 7. Diseño

## 7.1 Estructura conceptual

```text
hooks/
├── events.py
└── runner.py
```

---

## 7.2 Lifecycle orchestration

Ejemplo init:

```text
preflight
↓
before_init hooks
↓
Git init
↓
after_init hooks
↓
success
```

---

## 7.3 Journal de hooks

En memoria:

```text
HookJournal
- capability
- event
- changed
- compensation available
```

E7 podrá endurecer recuperación durable.

---

## 7.4 Compensación

El contrato de capability puede exponer compensación específica o utilizar el lifecycle inverso cuando sea inequívoco.

No se debe inventar rollback genérico mediante shell.

---

# 8. Criterios de aceptación

## AC-01

Fake capability recibe before/after init.

## AC-02

Before failure bloquea core mutation.

## AC-03

After init failure provoca rollback controlado.

## AC-04

Start compensation ocurre en orden inverso.

## AC-05

Before destroy failure conserva worktree.

## AC-06

Orden de hooks es determinista.

## AC-07

Excepción de capability se traduce a error estable.

## AC-08

CLI no contiene lógica específica de capabilities.

---

# 9. Tasks

## T1 — Definir lifecycle events
Conjunto inicial.

## T2 — Definir hook result/context
Modelos.

## T3 — Implementar hook runner
Orden y optional hooks.

## T4 — Implementar error boundary
Excepciones → dominio.

## T5 — Implementar journal en memoria
Acciones exitosas.

## T6 — Implementar compensación inversa
Cuando aplique.

## T7 — Integrar init
Before/after.

## T8 — Integrar start/stop
Before/after.

## T9 — Integrar destroy
Before/after.

## T10 — Crear fake capabilities de prueba
Orden/fallos/compensación.

## T11 — Tests integración
Lifecycle real + hooks.

---

# 10. Verificación

La spec está completa cuando una capability simulada puede participar en todo el lifecycle sin modificar la lógica concreta de Git de cada comando.

---

# 11. Resultado esperado

Después de E4-S1, el lifecycle fundamental queda abierto a extensión mediante contratos estables y secuenciales, con fallos y compensaciones explícitos.
