# Estructura del Proyecto y Plan Inicial de Specs — ramalio

## 1. Propósito

Este documento complementa el Documento de Visión y Alcance y el Plan Macro de `ramalio`.

Define dos elementos:

1. la estructura inicial propuesta para el proyecto Python;
2. la descomposición de specs por etapa.

La cantidad de specs no es contractual. Debe evitar mega-specs y fragmentación artificial.

---

# 2. Estructura propuesta del proyecto

La estructura original de referencia es:

```text
ramalio/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── docs/
│   ├── vision-y-alcance.md
│   ├── plan-macro.md
│   ├── estructura-y-plan-specs.md
│   └── ...
├── src/ramalio/
│   ├── cli.py
│   ├── core/
│   ├── config/
│   ├── git/
│   ├── capabilities/
│   ├── integrations/
│   ├── resources/
│   ├── hooks/
│   └── security/
└── tests/
```

El árbol es orientativo: una carpeta/componente aparece cuando una spec exige esa responsabilidad. La implementación real ya evolucionó respecto del bosquejo inicial; el principio rector permanece.

---

# 3. Responsabilidad de cada área

## `core/`
Conceptos y lifecycle universal. No depende de Laravel, Docker, Kiro, tmux, zrok ni proyecto concreto.

## `config/`
Carga y valida `.ramalio.toml`, defaults, target, naming, capabilities e integrations.

## lifecycle/core services
Implementan `init`, `adopt`, `start`, `stop`, `destroy` independientemente de CLI.

## `git/`
Autoridad de operaciones Git/worktree encapsuladas.

## `capabilities/`
Comportamientos opcionales coordinados por lifecycle: processes, tmux, runtime, ports/tunnel y provisioning E10.

## `integrations/`
Herramientas externas abiertas desde el workspace: Kiro, Codex, Claude, VS Code.

## `resources/`
Recursos compartidos que requieren coordinación, como ports/locks.

## `hooks/`
Puntos de extensión ordenados; E10 añade únicamente `after_adopt` al conjunto necesario para provisioning de adopción.

## `security/`
Boundaries, ejecución segura y redacción; E10 los reutiliza.

---

# 4. Estructura del proyecto cliente

El proyecto cliente **no contiene el motor de `ramalio`**.

```text
proyecto-cliente/
├── .ramalio.toml
├── código/documentación normal del proyecto
└── ...
```

La particularidad reusable del workspace se expresa principalmente mediante `.ramalio.toml`. No se exige copiar scripts de lifecycle de SiVale ni mantener `worktree-init/adopt/cleanup` propios para responsabilidades soportadas por el producto.

Ejemplo conceptual histórico:

```toml
[project]
name = "sivale-zurich"
base_branch = "main"

[target]
regex = "^E[0-9]+-S[0-9]+-[a-z0-9]+(-[a-z0-9]+)*$"
example = "E7-S8-convergencia-schema-tests"
case_sensitive = true

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "spec/{target}"

[ports]
enabled = true
start = 8100
size = 20

[capabilities.tmux]
enabled = true

[capabilities.runtime]
driver = "docker-compose"

[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
```

E10 amplía este contrato únicamente mediante las claves exactas definidas en sus specs; este documento de planificación no afirma que dichas claves estén ya implementadas.

---

# 5. Principios estructurales

## 5.1 El core es genérico
No se crean conceptos centrales `laravel/`, `sivale/`, `kiro/` ni `docker/`. Kiro es integration; Docker Compose es driver runtime.

## 5.2 Configuración por proyecto
Cada proyecto define target, naming, worktree directory, runtime, puertos, bootstrap/provisioning, procesos, capabilities e integrations.

## 5.3 Extensibilidad controlada
Nuevas capabilities se añaden sin romper lifecycle existente y sin implementar tecnologías futuras por anticipación.

## 5.4 Provisioning no reintroduce scripts de lifecycle al cliente
El cliente declara necesidades; capabilities/providers del producto las ejecutan cuando pertenecen al workspace reusable.

---

# 6. Presupuesto de specs actualizado

| Etapa | Tema | Specs |
|---|---|---:|
| E0 | Estándar operativo | 2 |
| E1 | Configuración y targets | 3 |
| E2 | Lifecycle fundamental | 4 |
| E3 | Control operativo | 4 |
| E4 | Capacidades y procesos | 3 |
| E5 | tmux / `--open` / herramientas | 3 |
| E6 | runtime / puertos / zrok | 4 |
| E7 | Robustez y conformidad | 4 |
| E8 | Piloto SiVale | 3 |
| E9 | Adopción iMass + convergencia contractual | 4 |
| E10 | Workspace provisioning | 5 |
| **Total actual** |  | **39** |

---

# 7. E0 — Estándar operativo

### E0-S0 — Modelo operativo de workspace
Target, workspace, relación target→branch→worktree, estados, lifecycle e invariantes.

### E0-S1 — CLI base y contratos de resultado
Superficie `ramalio`, salidas, exit codes y errores comunes.

**Total E0: 2**

---

# 8. E1 — Configuración y targets

### E1-S0 — Descubrimiento y TOML
Git root, `.ramalio.toml`, defaults, errores y modelo.

### E1-S1 — Target validation
Regex, ejemplo, case sensitivity y errores.

### E1-S2 — Target normalization y naming
Trim, slug, branch pattern y worktree pattern.

**Total E1: 3**

---

# 9. E2 — Lifecycle fundamental

### E2-S0 — Modelo Git/worktree base
Repository abstraction, branches, worktrees, seguridad y base branch.

### E2-S1 — `init`
Crear target/branch/worktree con validaciones, resultado y rollback básico.

### E2-S2 — `adopt`
Incorporar trabajo existente al modelo administrado.

### E2-S3 — `destroy`
Protección de trabajo, retiro worktree, branch cleanup seguro y failure behavior.

**Total E2: 4**

---

# 10. E3 — Control operativo

### E3-S0 — `list`
### E3-S1 — `status`
### E3-S2 — `stop/start`
### E3-S3 — `doctor`

**Total E3: 4**

---

# 11. E4 — Capacidades y procesos

### E4-S0 — Capability contract y registry
### E4-S1 — Lifecycle hooks
Eventos base init/start/stop/destroy.
### E4-S2 — Procesos administrados

**Total E4: 3**

---

# 12. E5 — tmux, `--open` e integrations

### E5-S0 — tmux
### E5-S1 — Integration contract y `--open`
### E5-S2 — Kiro/VS Code/Codex/Claude

**Total E5: 3**

---

# 13. E6 — Runtime, puertos y túneles

### E6-S0 — Runtime capability contract
### E6-S1 — Puertos
### E6-S2 — Docker Compose driver
### E6-S3 — Tunnel/zrok

**Total E6: 4**

---

# 14. E7 — Robustez y conformidad

### E7-S0 — Transacciones/rollback
### E7-S1 — Locks/concurrencia
### E7-S2 — Seguridad/path boundaries/ejecución segura
### E7-S3 — Suite de conformidad

**Total E7: 4**

---

# 15. E8 — Piloto SiVale

### E8-S0 — Configuración SiVale
Crear la configuración cliente con target, naming, puertos, runtime y capabilities requeridas.

### E8-S1 — Paridad con lifecycle existente
Comparar `init`, `adopt`, `destroy` y las responsabilidades reales del harness. La auditoría post-E8 detectó que provisioning no estaba completamente cubierto; no se modifica el requirement original, se cierra mediante E10.

### E8-S2 — Migración operativa
Sólo retirar el mecanismo anterior cuando no conserve responsabilidad exclusiva.

**Total E8: 3**

---

# 16. E9 — Adopción iMass

### E9-S0 — Segundo proyecto piloto
Proyecto real diferente a SiVale para detectar coupling oculto.

### E9-S1 — Instalación y distribución empresarial
Instalación, upgrades, versionado, distribución y configuración personal.

### E9-S2 — Estándar de adopción
Onboarding, plantilla, checklist, documentación y gobernanza.

### E9-S3 — Convergencia contractual post-auditoría
Convergencia del contrato de integrations (`command` argv, `pass_env`, retiro de `inherit_env`) y decisión de schema.

**Total E9: 4**

---

# 17. E10 — Convergencia de workspace provisioning

Objetivo: cerrar exclusivamente la brecha de preparación del workspace detectada al auditar E8, manteniendo el producto agnóstico.

### E10-S0 — Contrato de provisioning del workspace
- reutiliza `after_init`;
- añade exactamente `after_adopt`;
- integra adopt al HookRunner/LifecycleTransaction;
- no crea un segundo plugin system ni estado persistido.

### E10-S1 — Runtime provisioning lifecycle
- amplía runtime existente;
- opciones exactas de provisioning;
- `RuntimeDriver.provision`;
- protocolo opcional de ejecución runtime requerido por downstream;
- Docker Compose es el único driver concreto en scope.

### E10-S2 — Bootstrap Composer y readiness
- capability `bootstrap`;
- provider inicial `composer`;
- executor host/runtime;
- artifacts y writable paths declarativos;
- sin scripts shell del cliente como motor general.

### E10-S3 — Data provisioning PostgreSQL
- capability `data`;
- provider `postgres`;
- source project scope → target workspace scope mediante runtime execution;
- cleanup delegado al runtime target-scoped cuando se configura así.

### E10-S4 — Convergencia de paridad SiVale
Configura el cliente y demuestra paridad real sin añadir nueva arquitectura salvo un incumplimiento directo de E10.

**DAG normativo:**

```text
E10-S0
  ├──→ E10-S1 ───→ E10-S3 ─┐
  └──→ E10-S2 ──────────────┼→ E10-S4
                             ┘
```

**Total E10: 5**

---

# 18. Resumen de roadmap

```text
E0 → E1 → E2 → E3 → E4
              ├→ E5 ─┐
              └→ E6 ─┴→ E7 → E8 → E9 → E10
```

E10 no invalida el historial. E8-S1/E8-S2 permanecen mergeadas pero su cierre operacional espera E10-S4.

---

# 19. Regla de granularidad

Una spec representa una capacidad verificable. Evitar mega-specs y specs microscópicas. El número puede ajustarse si una responsabilidad se demuestra separable o una dependencia real obliga a reordenar.

---

# 20. Criterio de evolución

La estructura es dirección, no obligación de crear carpetas prematuramente. Cada componente aparece cuando una spec lo requiere.

La separación fundamental se mantiene:

```text
core genérico
+ configuración del proyecto cliente
+ capabilities/providers opcionales
+ integrations opcionales
```

E10 debe reutilizar los mecanismos existentes y no crear otra plataforma de workflow, locks, transacciones o process execution.
