# E7-S3 — Suite de conformidad

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E7 — Robustez, recuperación y conformidad
- **Spec:** E7-S3
- **Nombre:** Suite integral de conformidad
- **Dependencias:** E7-S0, E7-S1, E7-S2 y funcionalidad E0-E6
- **Estado inicial:** Planificada

## 2. Contexto

La Etapa 0 definió un estándar operativo; E1-E6 lo materializaron; E7 debe poder demostrar sistemáticamente que el producto mantiene ese contrato ante éxito, error, concurrencia e inconsistencias.

La suite de conformidad no debe ser una colección de tests ligados a SiVale. Debe validar comportamiento genérico del producto y permitir fixtures de proyectos cliente diferentes.

## 3. Objetivo

Construir una suite integral que valide el lifecycle y los principales invariantes del estándar de `imass-worktree` de forma reproducible.

## 4. Alcance

Incluye:

- lifecycle `init/adopt/start/stop/destroy`;
- `list/status/doctor`;
- capabilities y hooks;
- procesos;
- tmux/open integrations mediante fakes/adapters cuando corresponda;
- runtimes;
- puertos;
- túneles;
- rollback;
- locks/concurrencia;
- path/security boundaries;
- configuración y compatibilidad básica.

No incluye pruebas funcionales de aplicaciones cliente como Laravel/Node/Python.

## 5. Requirements

### R1 — Conformance harness
Debe existir un harness de pruebas reusable que pueda crear repositorios/proyectos temporales con config propia.

### R2 — Project profiles
Debe soportar al menos tres perfiles:

1. Git-only.
2. Git + processes/capabilities.
3. Runtime + ports + tunnel simulated.

### R3 — Real Git
Las pruebas de Git/worktrees deben usar repositorios reales temporales, no mocks como única evidencia.

### R4 — Fake external adapters
Herramientas externas como tmux/zrok/docker pueden simularse mediante adapters deterministas en la suite base; pruebas reales opcionales quedan separadas.

### R5 — Happy-path lifecycle
Debe cubrir crear → status/list → stop/start → destroy.

### R6 — Adopt lifecycle
Debe cubrir branch/worktree existente, branch-only y dirty worktree compatible.

### R7 — Failure injection
Debe existir mecanismo para inducir fallo después de cada punto crítico del lifecycle.

### R8 — Rollback assertions
Cada fallo inducido debe verificar recursos restantes y ownership.

### R9 — Concurrency
Debe cubrir same-target exclusion y different-target parallelism.

### R10 — Port races
Dos procesos concurrentes no pueden reservar el mismo puerto.

### R11 — Security regressions
Debe cubrir traversal, symlink escape y command argument safety.

### R12 — Orphan detection
Debe crear procesos/resources simulados huérfanos y comprobar diagnóstico.

### R13 — Interrupted operations
Debe simular interrupciones controladas y validar resultado/rollback.

### R14 — Exit contracts
Los códigos de salida públicos definidos desde E0 deben permanecer estables y testeados.

### R15 — Output contracts
stdout/stderr o formatos estructurados deben validarse sin depender de mensajes internos de Git.

### R16 — Configuration compatibility
Debe validar configs válidas de la versión soportada y rechazo claro de versiones/keys incompatibles según contrato vigente.

### R17 — Determinism
Tests deben ser repetibles sin depender de puertos hardcodeados, red externa o estado del equipo del developer.

### R18 — No SiVale coupling
Ningún test base debe requerir naming `E#-S#`, Laravel, Kiro o Docker real.

### R19 — CI suitable
La suite base debe poder ejecutarse en un entorno CI estándar con Git y Python, usando fakes para dependencias opcionales.

### R20 — Optional integration profile
Pruebas reales de tmux/docker/zrok podrán existir como perfiles opt-in separados y no deben volver obligatorias esas herramientas para el core.

## 6. Diseño

Estructura conceptual:

```text
tests/
├── unit/
├── integration/
├── conformance/
│   ├── fixtures/
│   ├── profiles/
│   ├── failure_injection/
│   ├── concurrency/
│   └── security/
└── optional_integration/
```

El harness debe ofrecer helpers para:

- crear repo y commits;
- generar TOML;
- crear branches/worktrees;
- ejecutar CLI;
- inspeccionar filesystem/Git;
- inyectar adapters fake;
- lanzar procesos concurrentes;
- afirmar ausencia de recursos huérfanos.

## 7. Matriz mínima de conformidad

| Área | Escenario mínimo |
|---|---|
| Config | load/invalid/precedence |
| Target | validate/normalize/naming |
| Init | happy/collision/rollback |
| Adopt | existing/branch-only/dirty |
| Destroy | clean/dirty/branch preserve |
| List | multiple/inconsistent |
| Status | ready/dirty/missing |
| Start/Stop | no-op + capability-backed |
| Doctor | pass/warn/fail |
| Hooks | order/failure |
| Processes | start/status/stop/orphan |
| tmux | fake lifecycle |
| Open | fake integration |
| Runtime | none/fake/docker optional |
| Ports | allocate/release/race |
| Tunnel | fake/zrok optional |
| Rollback | failure points |
| Locks | same/different target |
| Security | traversal/symlink/argv |

## 8. Criterios de aceptación

- AC-01 suite base pasa sin Docker/tmux/zrok reales.
- AC-02 lifecycle completo está cubierto end-to-end.
- AC-03 cada punto crítico mutable tiene al menos un failure injection test.
- AC-04 concurrencia same-target y different-target está cubierta.
- AC-05 security regression suite pasa.
- AC-06 los tres project profiles usan el mismo core.
- AC-07 no existe dependencia de SiVale en conformance base.
- AC-08 optional integrations quedan separadas.

## 9. Tasks

1. Diseñar conformance harness y fixtures.
2. Crear project profiles.
3. Crear fake capability/runtime/tunnel/open adapters.
4. Crear CLI runner de tests.
5. Implementar failure injection framework.
6. Implementar lifecycle matrices.
7. Implementar concurrency suite.
8. Implementar security suite.
9. Implementar output/exit contract tests.
10. Separar optional integration tests.
11. Integrar ejecución CI.
12. Documentar cómo una nueva capability añade casos de conformidad.

## 10. Verificación

La Etapa 7 se considera cerrada cuando los principales escenarios de error, concurrencia y seguridad pueden reproducirse automáticamente y el producto responde de forma determinista, segura y diagnosticable.

## 11. Resultado esperado

`imass-worktree` pasa de ser una herramienta funcional a un producto con un estándar verificable y una red de regresión reutilizable antes del piloto real de SiVale.
