# Getting started con `ramalio`

`ramalio` administra workspaces de desarrollo aislados basados en Git
worktrees, con la relación determinista `target → branch → worktree`. Ofrece una
CLI común (`ramalio`) mientras cada proyecto conserva sus reglas mediante
configuración; el core no conoce ningún stack concreto.

## Qué resuelve

- Un comando común para crear, adoptar, inspeccionar, suspender/reanudar y
  destruir workspaces por unidad de trabajo (`target`).
- Aislamiento por target (branch, worktree y, opcionalmente, puertos/runtime/
  túneles/procesos/tmux) sin acoplar el core a herramientas concretas.

## Instalación

Ver [`installation.md`](installation.md). Resumen:

```bash
pipx install ramalio
ramalio --version
```

## Primer lifecycle (Git-only)

```bash
# 1. Copia la plantilla mínima al raíz del repo
cp docs/examples/minimal.ramalio.toml ./.ramalio.toml
# 2. Ajusta project/target/branch/worktree
# 3. Verifica el entorno
ramalio doctor
# 4. Crea, inspecciona y cierra un workspace
ramalio init my-feature
ramalio status my-feature
ramalio list
ramalio destroy my-feature
```

## Siguientes pasos

- Referencia de configuración: [`configuracion.md`](configuracion.md).
- Lifecycle común: [`lifecycle.md`](lifecycle.md).
- Adopción formal (checklist, gobernanza): [`adoption-guide.md`](adoption-guide.md).
- Capacidades e integraciones opcionales: [`capabilities.md`](capabilities.md),
  [`integrations.md`](integrations.md).
- Problemas comunes: [`troubleshooting.md`](troubleshooting.md).
