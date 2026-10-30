# Migración desde scripts existentes (E9-S2 + modelo E10)

Guía genérica para adoptar `ramalio` en un proyecto que ya posee scripts de worktree.

## 1. Inventariar responsabilidades

Lista cada script/wrapper y qué hace realmente: Git/worktree, bootstrap, runtime, data, dependencias, puertos, procesos, IDE, teardown, build o deploy.

No clasifiques por nombre del script; clasifica por responsabilidad.

## 2. Clasificación

| Categoría | Significado | Destino |
|---|---|---|
| **core** | target/branch/worktree/safety universal | `ramalio` core |
| **configuración cliente** | naming, base branch, policies | `.ramalio.toml` |
| **capability** | comportamiento opcional reusable del workspace | `[capabilities.*]` / recursos |
| **workspace provisioning** | preparación necesaria para que el workspace quede utilizable | capability/provider E10 cuando exista |
| **integration** | abrir editor/agente/herramienta | `[integrations.*]` |
| **proyecto cliente** | lógica de negocio, build de producto, deploy | permanece en proyecto |
| **fuera de alcance** | responsabilidad que no pertenece al workspace | no se absorbe |

### 2.1 Distinción crítica: provisioning vs build/deploy

Ejemplos de **workspace provisioning**:

- instalar dependencias necesarias para desarrollar;
- preparar runtime local necesario para trabajar;
- preparar datos aislados requeridos por el workspace;
- checks de readiness.

Ejemplos de **responsabilidad del proyecto**:

- build de release productivo;
- deploy;
- promociones de ambiente;
- inicialización de negocio.

No marques algo `PROJECT_LOCAL` sólo porque `ramalio` todavía no lo soporte. Primero determina si es una necesidad reusable del workspace.

## 3. El cliente declara, no reimplementa

El objetivo de adopción es que las reglas se declaren en configuración y que las capabilities del producto ejecuten la mecánica reusable. No se considera una solución final trasladar `worktree-init.sh` a otro script con otro nombre.

## 4. Retiro gradual

No elimines un script hasta:

1. demostrar paridad de la responsabilidad;
2. confirmar que no conserva una responsabilidad exclusiva;
3. tener alternativa documentada;
4. comprobar que tests/flujo real no dependen de él.

Durante la transición puede mantenerse como legacy/delegador, sin lógica divergente que administre el mismo recurso de forma contradictoria.

## 5. Definition of adopted

Un proyecto está adoptado cuando puede operar el lifecycle acordado y dejar sus workspaces utilizables sin depender de scripts legacy indispensables para responsabilidades que pertenecen al estándar/capabilities, y sin conocimiento del proyecto embebido en el core.
