# E3-S3 — `imass-wt doctor`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E3 — Control operativo y reanudación
- **Spec:** E3-S3
- **Nombre:** Diagnóstico del proyecto y entorno
- **Dependencias:** E3-S0, E3-S1, E3-S2
- **Bloquea a:** cierre de E3 / MVP operativo, E4+
- **Estado inicial:** Planificada

---

## 2. Contexto

Una herramienta de lifecycle puede fallar por razones muy distintas:

- no estamos en un repo Git;
- falta el TOML;
- configuración inválida;
- branch base inexistente;
- naming inválido;
- worktree directory inseguro;
- worktrees inconsistentes;
- dependencias externas futuras.

`doctor` debe detectar problemas antes de que el usuario tropiece con ellos durante `init`, `adopt`, `start`, `stop` o `destroy`.

En E3, su cobertura real se limita a los componentes ya implementados. Debe diseñarse para que E4+ agreguen checks de capabilities sin convertirlo en una colección rígida de `if tool == ...`.

---

## 3. Objetivo

Implementar:

```bash
imass-wt doctor
```

para ejecutar una batería read-only de diagnósticos sobre:

1. entorno base;
2. Git;
3. proyecto;
4. configuración;
5. target/naming configuration;
6. estructura de worktrees;
7. consistencia observable;
8. readiness para el lifecycle actualmente soportado.

---

## 4. Alcance

### 4.1 Incluido

- Check de Git disponible.
- Repository root.
- TOML presente.
- Configuración parseable/válida.
- Base branch existente.
- Target example válido.
- Normalización/example coherentes.
- Branch/worktree pattern válido.
- Worktree directory boundary básico.
- Detección de inconsistencias en worktrees actuales.
- Matriz PASS/WARN/FAIL.
- Exit code agregado.
- Arquitectura extensible de checks.

### 4.2 Fuera de alcance

- Reparación automática.
- Instalación de Git.
- Instalación de capabilities.
- tmux/zrok/docker checks concretos antes de que existan.
- Network.
- Git fetch.
- Prune.
- Permisos sudo.
- Diagnóstico del stack interno del proyecto cliente (Laravel, Node, Python, etc.) salvo futuras capabilities configuradas.

---

## 5. Principios e invariantes

### INV-01 — Doctor es read-only

Nunca corrige automáticamente.

### INV-02 — Checks independientes

Un fallo no debe impedir ejecutar checks que todavía puedan producir información útil, salvo dependencia técnica inevitable.

### INV-03 — Resultado estructurado

Cada check produce estado, código y mensaje.

### INV-04 — Extensible

Futuras capabilities registrarán checks sin modificar el core de doctor.

### INV-05 — No asumir stack

E3 no verifica PHP, Composer, Docker o Kiro salvo que futuras specs lo incorporen como capability/integration.

---

# 6. Requirements

## R1 — Ejecución

Comando:

```bash
imass-wt doctor
```

sin target.

---

## R2 — Modelo de check

Cada diagnóstico debe producir conceptualmente:

```text
DoctorCheckResult
├── check_id
├── status
├── summary
├── details?
└── remediation?
```

Estados:

```text
PASS
WARN
FAIL
SKIP
```

---

## R3 — Agregación

Resultado global:

```text
PASS
WARN
FAIL
```

Reglas:

- cualquier FAIL → global FAIL;
- sin FAIL pero con WARN → global WARN;
- todos PASS/SKIP → global PASS.

---

## R4 — Exit codes

Decisión:

```text
PASS → 0
WARN → 0
FAIL → non-zero
```

Warnings informan pero no bloquean operación por sí mismos.

---

## R5 — Check Git executable

Debe verificar que Git está disponible y puede ejecutarse.

```text
GIT_AVAILABLE
```

FAIL si no.

---

## R6 — Check repository

Debe verificar que cwd pertenece a repo Git válido.

```text
GIT_REPOSITORY
```

---

## R7 — Check config present

Verificar:

```text
.imass-worktree.toml
```

en repository root.

---

## R8 — Check config valid

Parseo, tipos, claves y required fields de E1-S0.

---

## R9 — Check base branch

Verificar `project.base_branch` local.

No fetch.

---

## R10 — Check target policy

Verificar:

- regex compilable;
- example válido;
- case policy válida.

---

## R11 — Check normalization

Aplicar pipeline al example y comprobar que termina en target válido.

Si el example ya es canónico, debe permanecer estable.

---

## R12 — Check branch pattern

Expandir con example y validar Git ref result.

---

## R13 — Check worktree pattern

Expandir con example y validar path/boundary básico sin crear nada.

---

## R14 — Check current worktrees

Inspeccionar `list` y detectar:

- detached;
- prunable;
- inconsistent;
- unrecognized.

### Severidades iniciales

- INCONSISTENT → WARN.
- PRUNABLE → WARN.
- DETACHED adicional → WARN.
- UNRECOGNIZED → WARN.

No todos representan corrupción del producto.

---

## R15 — Check main checkout

Debe verificar que el checkout principal sigue siendo un repositorio coherente.

No debe exigir que use base branch.

---

## R16 — Worktree directory availability

Si el directory parent configurado puede evaluarse sin mutar:

- path válido → PASS;
- boundary inválido → FAIL;
- parent no existe pero puede crearse en `init` → PASS/WARN según contrato;
- permisos imposibles de determinar sin escribir → no hacer probe destructivo.

No crear archivos sólo para doctor.

---

## R17 — Lifecycle readiness

Debe producir un resumen equivalente a:

```text
ready_for_init: true|false
ready_for_existing_workspace_operations: true|false
```

derivado de checks, no persistido.

---

## R18 — Orden de checks

La salida debe usar orden estable por categoría:

```text
Environment
Project
Configuration
Git
Worktrees
Extensions
```

`Extensions` puede estar vacío en E3.

---

## R19 — Remediation

Los checks pueden ofrecer instrucciones breves.

Ejemplos:

```text
Config missing → create .imass-worktree.toml
Base branch missing → ensure configured base branch exists locally
Prunable worktree → inspect Git worktree state
```

No ejecutar la remediation.

---

## R20 — Future checks

Debe existir un mecanismo interno para registrar checks adicionales.

No es necesario implementar el capability registry de E4, pero doctor no debe ser un único bloque monolítico.

---

## R21 — No network/mutations

No fetch, install, prune, mkdir, touch, chmod, delete.

---

# 7. Diseño

## 7.1 Servicio

```text
DoctorService
```

con checks pequeños:

```text
DoctorCheck
└── run(context) -> DoctorCheckResult
```

No es obligatorio usar inheritance; puede usarse protocolo/callables.

---

## 7.2 Contexto compartido

Para evitar repetir subprocess innecesariamente:

```text
DoctorContext
├── cwd
├── git availability
├── repository?
├── config?
└── cached observations
```

Los checks dependientes pueden devolver SKIP si falta una precondición.

---

## 7.3 Ejemplo de dependencia

Si Git no existe:

```text
GIT_AVAILABLE = FAIL
GIT_REPOSITORY = SKIP
BASE_BRANCH = SKIP
WORKTREES = SKIP
```

pero checks puramente sintácticos de un config accesible sólo se ejecutan si su descubrimiento no depende de Git según el contrato existente.

Dado E1-S0, config discovery depende del repository root, por lo que normalmente será SKIP.

---

## 7.4 Extensiones

E4 podrá registrar checks como:

```text
tmux available
process command valid
runtime available
```

sin modificar la semántica global.

---

# 8. Criterios de aceptación

## AC-01

Proyecto sano produce PASS.

## AC-02

Git ausente produce FAIL y skips dependientes.

## AC-03

Config ausente produce FAIL.

## AC-04

Config inválida produce FAIL.

## AC-05

Base branch missing produce FAIL.

## AC-06

Target example inválido produce FAIL.

## AC-07

Pattern inválido produce FAIL.

## AC-08

Worktree inconsistente produce WARN sin reparación.

## AC-09

Warnings no producen exit code de error.

## AC-10

Doctor no realiza network ni mutaciones.

---

# 9. Casos de prueba mínimos

### CT-01 — Healthy project
Global PASS.

### CT-02 — Git missing
FAIL/SKIP matrix.

### CT-03 — Not a repo
FAIL.

### CT-04 — Missing TOML
FAIL.

### CT-05 — Invalid TOML
FAIL.

### CT-06 — Base branch missing
FAIL.

### CT-07 — Bad target regex/example
FAIL.

### CT-08 — Bad branch pattern
FAIL.

### CT-09 — Unsafe worktree pattern
FAIL.

### CT-10 — Inconsistent current worktree
WARN.

### CT-11 — Prunable
WARN.

### CT-12 — Read-only proof
Filesystem/Git unchanged.

---

# 10. Tasks

## T1 — Definir `DoctorCheckResult`
PASS/WARN/FAIL/SKIP.

## T2 — Definir agregación global
Status y exit codes.

## T3 — Crear `DoctorContext`
Cache de observaciones.

## T4 — Implementar checks Environment/Git
Git executable/repo.

## T5 — Implementar checks Config
Presence/parse/validation.

## T6 — Implementar checks target/naming
Regex/example/normalization/patterns.

## T7 — Implementar check base branch
Local only.

## T8 — Implementar checks worktrees
Reusar list/status logic.

## T9 — Implementar lifecycle readiness summary
Derivado.

## T10 — Crear mecanismo extensible de registro de checks
Sin capabilities concretas.

## T11 — Conectar CLI
Secciones y summaries.

## T12 — Tests unitarios
Checks/agregación.

## T13 — Tests integración
Repositorios sanos/rotos temporales.

## T14 — Test read-only
No mutations/network.

---

# 11. Verificación

E3-S3 está completa cuando:

- un proyecto sano puede demostrar readiness;
- errores comunes se detectan antes del lifecycle;
- warnings quedan separados de failures;
- los checks son extensibles;
- no se corrige ni muta nada;
- no se asume un stack específico.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R4 | 7.1 | T1-T2, T11 | AC-01,09 |
| R5-R9 | 7.2-7.3 | T3-T7 | AC-02..05 |
| R10-R16 | 7.1-7.3 | T6-T8 | AC-06..08 |
| R17-R20 | 7.4 | T9-T10 | AC-01 |
| R21 | 7.2 | T14 | AC-10 |

---

# 13. Resultado esperado

Después de E3-S3, `doctor` puede responder:

```text
¿Está este proyecto y esta máquina en condiciones de usar
el lifecycle actualmente soportado por imass-worktree?
```

con evidencia separada por check, sin reparar automáticamente ni asumir tecnologías específicas.

---

# 14. Cierre de Etapa 3

Con E3-S0, E3-S1, E3-S2 y E3-S3, el producto dispone del MVP operativo previsto:

```text
init
adopt
destroy
list
status
doctor
start
stop
```

El siguiente paso, E4, puede incorporar capabilities y procesos sobre un lifecycle ya visible y estable.
