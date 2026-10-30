# E7-S0 — Transacciones y rollback del lifecycle

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E7 — Robustez, recuperación y conformidad
- **Spec:** E7-S0
- **Nombre:** Transacciones y rollback del lifecycle
- **Dependencias:** E2, E3, E4, E5, E6
- **Estado inicial:** Planificada

## 2. Contexto

Hasta E6 el producto ya dispone de lifecycle, capabilities, integraciones, runtimes, puertos y túneles. E7 debe convertir ese conjunto funcional en una herramienta confiable frente a fallos parciales, interrupciones y estados divergentes.

Esta spec formaliza el comportamiento transaccional de `init`, `adopt`, `start`, `stop` y `destroy`, sin pretender convertir Git o el sistema operativo en una transacción ACID. El objetivo es registrar intención, ownership de mutaciones y compensaciones seguras.

## 3. Objetivo

Diseñar e implementar un mecanismo común de transacciones de lifecycle que permita:

1. registrar pasos ejecutados y recursos creados/modificados;
2. asociar ownership inequívoco a cada mutación;
3. ejecutar compensaciones en orden inverso cuando falle una operación;
4. distinguir rollback completo, parcial e imposible;
5. conservar evidencia suficiente para diagnóstico y recuperación posterior;
6. impedir que un rollback retire recursos preexistentes o ajenos.

## 4. Alcance

Incluye lifecycle core, capabilities, runtime, puertos, túneles y procesos administrados cuando hayan participado en la operación. Incluye fallos inducidos, interrupciones controladas y postcondiciones.

Fuera de alcance: distribución multi-host, transacciones remotas fuertes, rollback de commits de usuario, rollback de push/PR, recuperación automática de datos que Git ya considera perdidos.

## 5. Invariantes

- **INV-01 Ownership primero:** ninguna compensación destruye un recurso sin evidencia de que fue creado por la operación actual.
- **INV-02 Compensación inversa:** los pasos se compensan en orden inverso al de mutación.
- **INV-03 Fail-closed:** si la seguridad del rollback no puede demostrarse, se conserva el recurso y se reporta estado parcial.
- **INV-04 Causa original preservada:** el error de rollback no debe ocultar el fallo inicial.
- **INV-05 Postcondiciones verificadas:** éxito y rollback deben verificarse contra realidad observable.
- **INV-06 Idempotencia de compensaciones:** repetir una compensación segura no debe causar daño.

## 6. Requirements

### R1 — Transaction context
Cada operación mutable debe ejecutar dentro de un contexto común equivalente a `LifecycleTransaction`.

### R2 — Step journal
El contexto debe registrar por paso: `step_id`, resource type, identity, action, ownership, completed, compensation y resultado.

### R3 — Resource ownership
Cada capability/driver que cree recursos debe devolver identidad suficiente para determinar si el recurso es propio de la operación.

### R4 — Compensations
Cada mutación reversible debe declarar una compensación explícita o justificar que no existe una segura.

### R5 — Reverse rollback
Ante fallo, las compensaciones completadas deben ejecutarse en orden LIFO.

### R6 — Rollback outcomes
El resultado debe distinguir `ROLLBACK_COMPLETE`, `ROLLBACK_PARTIAL` y `ROLLBACK_NOT_SAFE`.

### R7 — Error composition
El resultado final debe preservar `primary_error` y `rollback_errors[]`.

### R8 — Postcondition verification
Después de cada mutación crítica y de cada compensación debe comprobarse el estado observable cuando sea posible.

### R9 — Init integration
`init` debe cubrir branch, worktree, puertos, runtime, processes, tunnels y capabilities activadas.

### R10 — Adopt integration
`adopt` sólo puede compensar recursos que él mismo haya creado; nunca branch/worktree preexistentes fuera de su ownership.

### R11 — Start integration
Un start parcial debe detener en rollback únicamente recursos arrancados por ese start.

### R12 — Stop integration
Si stop falla a mitad, el sistema debe reportar qué recursos quedaron activos/detenidos; no reactivar automáticamente salvo compensación explícita y segura.

### R13 — Destroy integration
Destroy debe mantener política conservadora: una eliminación irreversible ya ejecutada no se “recrea” artificialmente si no hay contrato seguro.

### R14 — Interrupt handling
La transacción debe responder de forma controlada a cancelación/KeyboardInterrupt y ejecutar compensaciones seguras.

### R15 — No global cleanup
Nunca usar cleanup global como rollback.

### R16 — Diagnostic result
CLI/status/doctor deben poder mostrar que una operación terminó con rollback parcial.

## 7. Diseño

Componentes conceptuales:

```text
LifecycleTransaction
├── begin()
├── record_step()
├── mark_completed()
├── rollback()
└── finish()

TransactionStep
├── id
├── resource_identity
├── ownership
├── action
├── compensation
└── state
```

El journal puede ser inicialmente de memoria si la operación sigue viva, pero su diseño debe permitir persistencia durable en una evolución posterior sin romper contratos.

## 8. Criterios de aceptación

- AC-01 fallo después de crear branch revierte sólo la branch propia.
- AC-02 fallo después de arrancar runtime/proceso detiene sólo recursos arrancados por esa operación.
- AC-03 rollback parcial conserva causa original y errores secundarios.
- AC-04 recursos preexistentes nunca se eliminan por compensación.
- AC-05 interrupción controlada dispara rollback seguro.
- AC-06 repetición de compensación es segura.
- AC-07 `status`/resultado puede expresar operación parcialmente compensada.

## 9. Casos de prueba mínimos

- Fallo tras branch.
- Fallo tras worktree.
- Fallo tras reserva de puerto.
- Fallo tras runtime start.
- Fallo tras process start.
- Fallo tras tunnel start.
- Adopt con branch preexistente.
- Start parcial.
- Stop parcial.
- Destroy con branch no borrable.
- KeyboardInterrupt inducido.
- Compensation failure.

## 10. Tasks

1. Definir modelos de transacción, steps y outcomes.
2. Adaptar lifecycle services a transaction context.
3. Extender capability/runtime/process/tunnel contracts con ownership y compensation metadata.
4. Implementar rollback LIFO.
5. Implementar composición de errores.
6. Integrar postcondition verification.
7. Integrar interrupciones controladas.
8. Exponer resultado parcial a CLI/status/doctor.
9. Crear failure injection helpers.
10. Crear suite de integración de rollback.

## 11. Verificación

La spec se considera completa cuando todos los lifecycle mutables usan el mecanismo común, los fallos inducidos son reproducibles y no existe cleanup destructivo basado en heurísticas.

## 12. Resultado esperado

`imass-worktree` deja de depender de rollbacks ad hoc por comando y obtiene un contrato común de compensación segura y diagnosticable.
