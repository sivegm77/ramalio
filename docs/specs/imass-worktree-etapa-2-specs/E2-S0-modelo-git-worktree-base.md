# E2-S0 — Modelo Git/worktree base

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E2 — Lifecycle fundamental
- **Spec:** E2-S0
- **Nombre:** Modelo Git/worktree base
- **Dependencias:** E1-S0, E1-S1, E1-S2
- **Bloquea a:** E2-S1, E2-S2, E2-S3
- **Estado inicial:** Planificada

---

## 2. Contexto

La Etapa 2 introduce el primer núcleo realmente utilizable de `imass-worktree`.

Antes de implementar `init`, `adopt` y `destroy`, el producto necesita una frontera estable alrededor de Git para consultar repositorio, branches y worktrees sin dispersar comandos Git por todo el código.

Git continúa siendo la autoridad sobre:

- repositorios;
- branches;
- HEAD;
- worktrees;
- estado del checkout;
- referencias.

`imass-worktree` no debe duplicar persistentemente información que Git ya conoce con autoridad.

Esta spec crea las abstracciones mínimas para que el lifecycle pueda operar de forma segura, determinista y testeable.

---

## 3. Objetivo

Implementar la capa base de interacción con Git y el modelo de workspace necesario para que las siguientes specs puedan:

1. inspeccionar el repositorio actual;
2. resolver la branch base configurada;
3. consultar branches locales;
4. consultar worktrees existentes;
5. identificar si un target ya tiene branch o worktree asociado;
6. validar precondiciones antes de mutar Git;
7. representar un workspace administrable sin inventar estado persistente prematuro;
8. encapsular comandos Git en una única frontera técnica.

---

## 4. Alcance

### 4.1 Incluido

- Abstracción de repositorio Git.
- Consulta de branch base.
- Consulta de branches.
- Consulta de worktrees.
- Resolución de HEAD/commit cuando aplique.
- Estado Git básico del checkout/worktree.
- Identificación de worktree path y branch.
- Detección de colisiones previas.
- Modelo inicial de workspace.
- Errores de dominio Git/lifecycle.
- Ejecución segura de comandos Git.
- Tests unitarios e integración sobre repositorios temporales.

### 4.2 Fuera de alcance

- Crear worktrees — E2-S1.
- Adoptar worktrees — E2-S2.
- Destruir worktrees — E2-S3.
- Start/stop — E3.
- Capabilities — E4+.
- Puertos, procesos, tmux, runtime, túneles.
- Persistencia de estado administrativo propia.
- Git fetch automático.
- GitHub/GitLab.
- Merge, rebase, push, PR o publicación.

---

## 5. Principios e invariantes

### INV-01 — Git es autoridad

Toda información sobre branches, worktrees y commits debe derivarse de Git cuando Git pueda responderla.

### INV-02 — No shell disperso

El resto del producto no debe ejecutar comandos Git arbitrarios fuera de la frontera Git.

### INV-03 — Sin mutaciones en E2-S0

Esta spec sólo inspecciona y modela. No crea ni elimina refs o worktrees.

### INV-04 — Sin inferencia ambigua

No se debe “adivinar” qué branch corresponde a un target si el naming configurado no lo determina.

### INV-05 — Paths reales

Los worktrees reportados por Git deben modelarse con paths normalizados/canónicos suficientes para comparaciones confiables.

### INV-06 — Errores estables

Los fallos Git deben traducirse a errores de dominio previsibles.

---

# 6. Requirements

## R1 — Repository abstraction

Debe existir una abstracción equivalente a:

```text
GitRepository
```

responsable de:

- root;
- HEAD;
- branches;
- worktrees;
- estado básico;
- validaciones Git requeridas por lifecycle.

La API puede variar, pero la responsabilidad debe quedar centralizada.

---

## R2 — Detección de repositorio

La capa Git debe reutilizar el root resuelto en E1-S0 y verificar que el contexto corresponde a un repositorio válido.

Código de error:

```text
GIT_REPOSITORY_INVALID
```

---

## R3 — Branch base configurada

Debe poder comprobarse que:

```text
project.base_branch
```

existe como referencia local utilizable para crear un nuevo workspace.

En E2 no se hará `fetch` implícito.

Si la branch base requerida no existe localmente:

```text
BASE_BRANCH_NOT_FOUND
```

---

## R4 — Consulta de branches

La capa debe poder responder:

- si una branch existe;
- qué commit referencia;
- si una branch está actualmente checked out en algún worktree cuando Git lo permita determinar.

---

## R5 — Consulta de worktrees

Debe parsearse la salida machine-readable de Git y modelar al menos:

```text
path
head
branch | detached
bare
prunable
locked
```

cuando esos datos estén disponibles.

No se debe parsear salida pensada para humanos si Git ofrece formato estable para scripts.

---

## R6 — Workspace identity

A partir de E1-S2 debe poder representarse:

```text
ResolvedWorkspaceIdentity
├── target
├── branch_name
└── worktree_path
```

Esta identidad es derivada, no persistida.

---

## R7 — Workspace observation

Debe existir una representación observable equivalente a:

```text
ObservedWorkspace
├── identity
├── branch_exists
├── worktree_exists
├── worktree_branch
├── worktree_head
└── git_status
```

No todos los campos tienen que existir físicamente como dataclass; el contrato semántico sí.

---

## R8 — Estado Git básico

La capa debe poder determinar, para un checkout/worktree:

```text
clean
dirty
untracked
detached
```

como mínimo suficiente para las decisiones de seguridad de E2.

No se requiere todavía un modelo exhaustivo de `status` para UI; eso pertenece a E3.

---

## R9 — Colisión de branch

Si la branch derivada para un target ya existe, la capa debe poder distinguir ese hecho sin decidir todavía si es adoptable.

Código conceptual:

```text
BRANCH_ALREADY_EXISTS
```

---

## R10 — Colisión de worktree path

Si el path derivado ya existe o ya está registrado como worktree, debe poder distinguirse.

Códigos conceptuales:

```text
WORKTREE_PATH_ALREADY_EXISTS
WORKTREE_ALREADY_REGISTERED
```

---

## R11 — Branch usada por otro worktree

Debe poder detectarse cuando la branch objetivo ya está checked out en otro worktree.

Código:

```text
BRANCH_ALREADY_CHECKED_OUT
```

---

## R12 — Ejecución segura

Los comandos Git deben:

- ejecutarse sin concatenación shell insegura;
- recibir argumentos como lista/argv;
- ejecutar con cwd explícito;
- capturar exit code, stdout y stderr;
- aplicar timeout razonable si el runner del proyecto lo soporta.

---

## R13 — Resultado tipado

La frontera Git no debe obligar al resto del producto a interpretar stdout crudo.

Debe devolver estructuras de dominio o resultados estructurados.

---

## R14 — No network side effects

E2-S0 no debe:

- hacer fetch;
- pull;
- push;
- contactar remotes.

---

## R15 — Repositorios temporales de prueba

La suite debe crear repositorios Git reales temporales para validar:

- branch base;
- múltiples worktrees;
- branch checked out;
- dirty state;
- detached HEAD cuando aplique.

---

# 7. Diseño

## 7.1 Estructura conceptual

```text
src/imass_worktree/
├── core/
│   └── worktree.py
└── git/
    ├── repository.py
    ├── branches.py
    └── worktrees.py
```

No es obligatorio crear exactamente esos archivos si la implementación encuentra una división más simple.

---

## 7.2 Operaciones mínimas

```text
GitRepository
├── get_root()
├── resolve_ref(name)
├── branch_exists(name)
├── list_worktrees()
├── get_worktree_by_path(path)
├── get_worktree_by_branch(branch)
└── get_status(path)
```

---

## 7.3 Parsing de worktrees

Debe preferirse:

```bash
git worktree list --porcelain
```

o una interfaz machine-readable equivalente.

La capa debe convertir esa salida a objetos estructurados.

---

## 7.4 Estado del checkout

Debe preferirse una salida estable para scripts, por ejemplo:

```bash
git status --porcelain...
```

sin depender de mensajes localizados para humanos.

---

## 7.5 Modelo de errores

Ejemplos:

```text
GitError
├── GitRepositoryInvalid
├── BaseBranchNotFound
├── BranchAlreadyExists
├── BranchAlreadyCheckedOut
├── WorktreePathAlreadyExists
└── WorktreeAlreadyRegistered
```

Los nombres exactos pueden adaptarse al estilo Python adoptado.

---

## 7.6 Frontera con lifecycle

E2-S0 no decide:

- si crear;
- si adoptar;
- si destruir.

Sólo responde con hechos observados y validaciones primitivas.

---

# 8. Criterios de aceptación

## AC-01

La capa identifica correctamente el root Git.

## AC-02

Puede resolver la branch base configurada y detectar si falta.

## AC-03

Puede listar worktrees y asociar branch/path correctamente.

## AC-04

Detecta branch ya usada por otro worktree.

## AC-05

Detecta path ya registrado.

## AC-06

Detecta estado dirty.

## AC-07

No ejecuta ninguna mutación Git.

## AC-08

No ejecuta operaciones de red.

## AC-09

El resto del código no necesita parsear stdout Git crudo.

## AC-10

Los tests funcionan con repositorios reales temporales.

---

# 9. Casos de prueba mínimos

### CT-01 — Repo con main
Resolver base branch.

### CT-02 — Base inexistente
`BASE_BRANCH_NOT_FOUND`.

### CT-03 — Branch existe
Consulta positiva.

### CT-04 — Worktree adicional
Listado correcto.

### CT-05 — Branch checked out
Detección correcta.

### CT-06 — Dirty tracked file
Estado dirty.

### CT-07 — Untracked
Estado untracked.

### CT-08 — Detached
Observación correcta.

### CT-09 — Path registrado
Detección correcta.

### CT-10 — Sin network
Test/spy que demuestre ausencia de fetch/push.

---

# 10. Tasks

## T1 — Definir modelos Git/worktree
Refs, worktree info, status y errores.

## T2 — Implementar runner Git seguro
argv, cwd, captura y traducción de errores.

## T3 — Implementar repository abstraction
Root y refs.

## T4 — Implementar branch queries
Existencia, commit y checkout association.

## T5 — Implementar worktree parser
Salida porcelain.

## T6 — Implementar status básico
Clean/dirty/untracked/detached.

## T7 — Integrar `ResolvedWorkspaceIdentity`
Desde E1-S2.

## T8 — Implementar observación de workspace
Sin mutaciones.

## T9 — Crear fixtures/repos Git temporales
Branches y worktrees reales.

## T10 — Tests de integración
Todos los casos mínimos.

---

# 11. Verificación

La spec está completa cuando:

- ningún comando de lifecycle futuro necesita parsear Git por su cuenta;
- branch/worktree/status pueden consultarse de forma determinista;
- no hay mutaciones ni network side effects;
- los errores de precondición están cubiertos;
- la suite usa repositorios Git reales para integración.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R5 | 7.1-7.4 | T1-T5 | AC-01..05 |
| R6-R8 | 7.6 | T6-T8 | AC-03,06 |
| R9-R11 | 7.5 | T4-T8 | AC-04,05 |
| R12-R14 | 7.2 | T2 | AC-07..09 |
| R15 | 7.3-7.4 | T9-T10 | AC-10 |

---

# 13. Resultado esperado

Después de E2-S0, el producto tendrá una frontera Git suficientemente estable para que `init`, `adopt` y `destroy` puedan concentrarse en reglas de lifecycle y seguridad, no en detalles de subprocess o parsing.
