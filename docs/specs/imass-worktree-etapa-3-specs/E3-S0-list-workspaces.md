# E3-S0 — `imass-wt list`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E3 — Control operativo y reanudación
- **Spec:** E3-S0
- **Nombre:** Listado de workspaces administrados
- **Dependencias:** E2-S0, E2-S1, E2-S2, E2-S3
- **Bloquea a:** E3-S1 y experiencia operativa posterior
- **Estado inicial:** Planificada

---

## 2. Contexto

Después de E2, `imass-worktree` ya puede crear, adoptar y destruir workspaces basados en Git worktrees.

La siguiente necesidad es operativa:

> ¿Qué workspaces existen en este proyecto y cuál es su condición básica?

`imass-wt list` debe ofrecer una vista rápida y confiable, sin convertir a `imass-worktree` en una base de datos paralela a Git.

Git seguirá siendo autoridad para branches y worktrees. La configuración del proyecto seguirá siendo autoridad para naming y reglas compartidas.

Esta spec introduce la primera vista agregada de los workspaces reconocibles por el producto.

---

## 3. Objetivo

Implementar:

```bash
imass-wt list
```

para:

1. descubrir el proyecto actual;
2. consultar los worktrees reales registrados en Git;
3. identificar cuáles corresponden a la convención de `imass-worktree`;
4. derivar, cuando sea posible y sin ambigüedad, el target asociado;
5. mostrar una vista compacta y estructurada;
6. señalar inconsistencias relevantes sin ocultarlas;
7. evitar dependencia de un registry persistente propio.

---

## 4. Alcance

### 4.1 Incluido

- Enumeración de worktrees Git.
- Reconocimiento de workspaces compatibles con naming configurado.
- Derivación target ↔ branch/worktree cuando sea inequívoca.
- Estado operativo básico.
- Identificación de checkout principal vs worktrees adicionales.
- Señalización de detached, prunable, missing path o mismatch básico.
- Salida humana y estructura interna reusable.
- Tests con múltiples worktrees.

### 4.2 Fuera de alcance

- Estado detallado de un target — E3-S1.
- Start/stop — E3-S2.
- Doctor completo — E3-S3.
- Capabilities — E4+.
- Persistencia administrativa propia.
- Reparación automática de inconsistencias.
- Eliminación de worktrees huérfanos.
- Network Git.
- Listado multi-repositorio global.

---

## 5. Principios e invariantes

### INV-01 — Git es autoridad del inventario

El listado parte de `git worktree list` o equivalente machine-readable.

### INV-02 — No inventar targets

Si un worktree no puede mapearse inequívocamente a un target, se reporta como no reconocido o inconsistente.

### INV-03 — No ocultar anomalías

Un worktree roto, detached o con naming incompatible debe aparecer como tal cuando sea relevante.

### INV-04 — Sin mutaciones

`list` es read-only.

### INV-05 — Sin registry obligatorio

No se requiere un archivo de estado propio para enumerar workspaces.

---

# 6. Requirements

## R1 — Comando sin target

El comando se invoca:

```bash
imass-wt list
```

y opera sobre el proyecto actual.

---

## R2 — Descubrimiento del proyecto

Debe reutilizar E1-S0 para resolver:

- repository root;
- configuración efectiva.

---

## R3 — Enumeración de worktrees

Debe reutilizar E2-S0 para listar los worktrees Git registrados.

No debe ejecutar parsing Git independiente dentro del comando CLI.

---

## R4 — Identificación del checkout principal

El resultado debe distinguir:

```text
main checkout
worktree adicional
```

El checkout principal puede no corresponder a un target administrado y no debe ser presentado como uno artificialmente.

---

## R5 — Reconocimiento por branch naming

Para worktrees adicionales con branch:

1. obtener branch real;
2. evaluar si cumple el patrón de branch configurado;
3. extraer el target únicamente si el mapping es reversible e inequívoco;
4. validar el target mediante E1-S1.

Si no puede derivarse un target:

```text
UNRECOGNIZED
```

como estado/flag observable, no necesariamente como error global.

---

## R6 — Reconocimiento por path

El path derivado puede utilizarse como corroboración de identidad.

No debe utilizarse para sobreescribir silenciosamente una contradicción entre branch y path.

---

## R7 — Mismatch branch/path

Si branch deriva target A y path esperado para target A no coincide con el worktree real:

```text
INCONSISTENT
```

con razón equivalente a:

```text
WORKTREE_PATH_MISMATCH
```

---

## R8 — Detached worktree

Un worktree detached debe mostrarse como:

```text
DETACHED
```

No se le inventa target.

---

## R9 — Prunable / missing

Si Git marca el worktree como prunable o el path no existe:

```text
PRUNABLE
```

o estado equivalente.

`list` no ejecuta prune.

---

## R10 — Estado básico

Cada workspace reconocido debe exponer al menos:

```text
target
branch
path
state
```

Estados iniciales:

```text
READY
DIRTY
DETACHED
PRUNABLE
INCONSISTENT
UNRECOGNIZED
```

`READY` y `DIRTY` sólo se aplican cuando la identidad es reconocida.

---

## R11 — Dirty

Para workspaces reconocidos, el listado puede consultar estado Git básico y distinguir:

```text
READY
DIRTY
```

No necesita detallar archivos; eso pertenece a `status`.

---

## R12 — Orden estable

Los resultados deben presentarse en orden determinista.

Decisión inicial:

```text
target ascendente
```

y luego entries no reconocidos por path.

---

## R13 — Sin workspaces adicionales

Si sólo existe el checkout principal:

- exit code exitoso;
- salida clara de que no hay workspaces administrados/reconocidos.

---

## R14 — Salida humana

La salida debe ser compacta y útil para terminal.

Ejemplo conceptual:

```text
TARGET                         STATE   BRANCH                         PATH
FEATURE-123-login              READY   spec/FEATURE-123-login         .local-wt/FEATURE-123-login
BUG-482-stripe-webhook         DIRTY   spec/BUG-482-stripe-webhook    .local-wt/BUG-482-stripe-webhook
```

El formato exacto debe respetar E0-S1.

---

## R15 — Resultado estructurado

La lógica debe producir una colección estructurada antes de renderizar CLI.

---

## R16 — Cero mutaciones

No se permiten:

- prune;
- remove;
- branch delete;
- filesystem cleanup;
- fetch/push.

---

# 7. Diseño

## 7.1 Servicio

```text
ListWorkspacesService
```

Flujo:

```text
resolve project
      ↓
list Git worktrees
      ↓
ignore/classify main checkout
      ↓
for each additional worktree
      ↓
derive/validate identity
      ↓
corroborate branch + path
      ↓
observe basic status
      ↓
sort
      ↓
return structured list
```

---

## 7.2 Modelo de resultado

Conceptualmente:

```text
WorkspaceListItem
├── target?
├── branch?
├── path
├── state
├── recognized
└── reason?
```

---

## 7.3 Reversibilidad del naming

La spec no exige que todos los patterns futuros sean arbitrariamente reversibles.

Para E3, el patrón soportado desde E1-S2 basado en `{target}` debe poder mapear:

```text
spec/{target}
→ target
```

sin heurísticas.

---

## 7.4 Inconsistencias

Una contradicción no bloquea todo el listado.

Se representa por item y el comando sigue mostrando los demás workspaces.

---

# 8. Criterios de aceptación

## AC-01

Lista varios worktrees reconocidos.

## AC-02

No presenta el checkout principal como target ficticio.

## AC-03

Deriva targets desde naming reversible.

## AC-04

Dirty se diferencia de ready.

## AC-05

Detached aparece sin target inventado.

## AC-06

Mismatch branch/path aparece como inconsistente.

## AC-07

Prunable aparece sin ser reparado.

## AC-08

Sin workspaces adicionales produce éxito.

## AC-09

El orden es estable.

## AC-10

No ejecuta ninguna mutación.

---

# 9. Casos de prueba mínimos

### CT-01 — Sin worktrees adicionales
Lista vacía administrada.

### CT-02 — Un workspace ready
Reconocimiento correcto.

### CT-03 — Dos targets
Orden ascendente.

### CT-04 — Dirty
Estado DIRTY.

### CT-05 — Detached
Sin target.

### CT-06 — Branch pattern no reconocida
UNRECOGNIZED.

### CT-07 — Path mismatch
INCONSISTENT.

### CT-08 — Prunable
Estado visible.

### CT-09 — Main checkout en branch parecida
No convertirlo en workspace administrado.

### CT-10 — Read-only
Verificar ausencia de mutations.

---

# 10. Tasks

## T1 — Definir modelo de item/listado
Estados y razones.

## T2 — Implementar reverse mapping del branch pattern soportado
Sin heurísticas.

## T3 — Crear `ListWorkspacesService`
Orquestación.

## T4 — Integrar worktree observation E2-S0
Git como autoridad.

## T5 — Integrar dirty básico
READY/DIRTY.

## T6 — Implementar clasificación de anomalías
Detached/prunable/inconsistent/unrecognized.

## T7 — Implementar orden estable
Targets y paths.

## T8 — Conectar CLI
Render compacto.

## T9 — Tests unitarios
Mapping y clasificación.

## T10 — Tests integración
Múltiples worktrees reales.

---

# 11. Verificación

La spec está completa cuando:

- `list` responde qué workspaces reconocibles existen;
- anomalías no quedan ocultas;
- no necesita registry propio;
- no inventa targets;
- no realiza mutaciones;
- la salida es determinista.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R4 | 7.1 | T3-T4 | AC-01,02 |
| R5-R9 | 7.3-7.4 | T2, T6 | AC-03,05..07 |
| R10-R15 | 7.2 | T1, T5, T7-T8 | AC-04,08,09 |
| R16 | 7.1 | T10 | AC-10 |

---

# 13. Resultado esperado

Después de E3-S0, el desarrollador puede entrar al proyecto y responder rápidamente:

```text
¿Qué workspaces existen aquí?
```

sin inspeccionar manualmente `git worktree list`, branches y paths.
