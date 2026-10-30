# E2-S2 — `imass-wt adopt`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E2 — Lifecycle fundamental
- **Spec:** E2-S2
- **Nombre:** Adoptar trabajo existente
- **Dependencias:** E2-S0, E2-S1
- **Bloquea a:** E3 y piloto posterior
- **Estado inicial:** Planificada

---

## 2. Contexto

No todo trabajo comenzará con `imass-wt init`.

Puede existir:

- una branch ya creada;
- un worktree ya existente;
- trabajo local que debe incorporarse al lifecycle administrado.

`adopt` permite incorporar esa unidad al modelo de `imass-worktree` sin recrearla y sin destruir trabajo útil.

La adopción debe ser conservadora: sólo puede tener éxito cuando la realidad Git es compatible de forma inequívoca con la identidad derivada del target y la configuración del proyecto.

---

## 3. Objetivo

Implementar:

```bash
imass-wt adopt <target>
```

para:

1. resolver target e identidad;
2. inspeccionar branch y worktree existentes;
3. validar que corresponden de forma inequívoca al target;
4. aceptar escenarios soportados;
5. rechazar conflictos sin mutar trabajo;
6. completar únicamente mutaciones mínimas cuando el contrato de adopción lo permita;
7. devolver una identidad administrable por comandos posteriores.

---

## 4. Alcance

### 4.1 Incluido

- Adopción de branch + worktree ya existentes.
- Adopción de branch existente sin worktree mediante creación del worktree canónico.
- Validación de branch/path.
- Protección de trabajo dirty.
- Detección de worktree incompatible.
- Resultado estructurado.
- Rollback de cualquier recurso nuevo creado por `adopt`.
- Tests de integración.

### 4.2 Fuera de alcance

- Renombrar branches.
- Mover worktrees existentes.
- Reescribir history.
- Hacer merge/rebase.
- Inferir target desde nombres incompatibles.
- Adoptar arbitrariamente un worktree fuera del path configurado si no coincide con la identidad derivada.
- Capabilities.
- Start/stop.
- Persistencia administrativa propia.

---

## 5. Principios e invariantes

### INV-01 — Adopción no significa reparación automática

Si branch/path no coinciden con la identidad esperada, `adopt` falla.

### INV-02 — No pérdida de trabajo

Un worktree dirty nunca se limpia, resetea o elimina para conseguir adopción.

### INV-03 — Identidad canónica

El target y naming configurados siguen siendo autoridad para la identidad esperada.

### INV-04 — Mutación mínima

Si la branch existe pero falta el worktree, `adopt` puede crear sólo el worktree necesario.

### INV-05 — Ownership de rollback

Si `adopt` crea un worktree y luego falla, sólo ese worktree nuevo puede retirarse.

### INV-06 — Sin renames

E2 no renombra branch/path para forzar compatibilidad.

---

# 6. Requirements

## R1 — Entrada

El target pasa por E1 completo y produce:

```text
target
branch_name
worktree_path
```

---

## R2 — Escenario A: branch + worktree compatibles

Si:

- branch derivada existe;
- existe worktree registrado en path derivado;
- ese worktree usa la branch derivada;

`adopt` debe tener éxito sin mutaciones Git.

---

## R3 — Escenario B: branch existe, worktree falta

Si:

- branch derivada existe;
- no está checked out en otro worktree;
- path derivado está libre;

`adopt` puede crear el worktree en el path canónico usando la branch existente.

No crea una nueva branch.

---

## R4 — Branch inexistente

Si no existe la branch derivada, `adopt` debe fallar:

```text
ADOPT_BRANCH_NOT_FOUND
```

Debe orientar a `init`.

---

## R5 — Branch usada en otro worktree

Si la branch está checked out en un path distinto al canónico:

```text
ADOPT_BRANCH_IN_OTHER_WORKTREE
```

No se mueve ni elimina.

---

## R6 — Path ocupado no registrado

Si el path canónico existe en filesystem pero no es el worktree esperado:

```text
ADOPT_WORKTREE_PATH_CONFLICT
```

No borrar ni modificar ese path.

---

## R7 — Worktree con branch distinta

Si el path canónico está registrado pero usa otra branch:

```text
ADOPT_WORKTREE_BRANCH_MISMATCH
```

---

## R8 — Detached worktree

Un worktree en el path canónico con detached HEAD no se considera compatible con una identidad que exige branch derivada.

Debe fallar:

```text
ADOPT_WORKTREE_DETACHED
```

---

## R9 — Dirty compatible

Si el worktree existente correcto está dirty, la adopción puede tener éxito.

`adopt` no exige clean state porque su función es incorporar trabajo en progreso.

El resultado debe indicar que el workspace contiene cambios locales.

---

## R10 — Worktree nuevo desde branch dirty imposible

Si sólo existe branch sin worktree, el concepto de dirty no aplica a esa branch fuera de un checkout.

El nuevo worktree se crea desde el commit actual de la branch sin alterar otros checkouts.

---

## R11 — Postcondición

Después de una adopción exitosa debe poder comprobarse:

- branch existe;
- worktree path canónico está registrado;
- branch asociada es la esperada;
- target/identity permanecen deterministas.

---

## R12 — Resultado

Éxito debe incluir al menos:

```text
target
branch
worktree_path
adoption_mode
git_dirty
```

`adoption_mode`:

```text
existing-worktree
created-worktree
```

---

## R13 — Rollback

Si `adopt` crea el worktree y una verificación posterior falla:

- retirar sólo el worktree creado por esta ejecución;
- no eliminar la branch existente;
- reportar rollback incompleto si no puede limpiarse.

---

## R14 — Idempotencia

Ejecutar `adopt` varias veces sobre branch/worktree compatibles debe devolver éxito equivalente sin duplicar recursos.

---

## R15 — Sin branch cleanup

`adopt` nunca elimina branches, ni siquiera durante rollback.

---

## R16 — Sin network

No fetch/push.

---

# 7. Diseño

## 7.1 Servicio

```text
AdoptWorkspaceService
```

Flujo:

```text
resolve identity
      ↓
observe branch/worktree reality
      ↓
classify scenario
   ├─ compatible existing
   ├─ branch-only adoptable
   └─ conflict
      ↓
minimal mutation if needed
      ↓
verify
      ↓
return adoption result
```

---

## 7.2 Clasificación explícita

La implementación debe separar claramente:

```text
EXISTING_COMPATIBLE
BRANCH_ONLY
BRANCH_MISSING
BRANCH_OTHER_WORKTREE
PATH_CONFLICT
BRANCH_MISMATCH
DETACHED
```

Los nombres internos pueden variar.

---

## 7.3 Mutation journal

Sólo necesita rastrear, para E2-S2:

```text
worktree_created_by_adopt
```

La branch es preexistente y nunca pertenece al rollback de adopt.

---

## 7.4 Dirty state

Dirty no es error en escenario compatible.

Debe reportarse como observación.

---

# 8. Criterios de aceptación

## AC-01

Branch+worktree compatibles se adoptan sin mutaciones.

## AC-02

Branch existente sin worktree crea sólo el worktree.

## AC-03

Branch inexistente falla y no crea nada.

## AC-04

Branch en otro worktree falla.

## AC-05

Path conflict falla sin borrar archivos.

## AC-06

Branch mismatch falla.

## AC-07

Detached falla.

## AC-08

Worktree compatible dirty puede adoptarse.

## AC-09

Segundo adopt es idempotente.

## AC-10

Rollback nunca elimina la branch.

---

# 9. Casos de prueba mínimos

### CT-01 — Existing compatible clean
Éxito sin mutation.

### CT-02 — Existing compatible dirty
Éxito con `git_dirty=true`.

### CT-03 — Branch only
Crear worktree.

### CT-04 — Branch missing
Fail.

### CT-05 — Branch other path
Fail.

### CT-06 — Path occupied ordinary directory
Fail.

### CT-07 — Path uses other branch
Fail.

### CT-08 — Detached
Fail.

### CT-09 — Postcondition failure after worktree creation
Rollback worktree, conservar branch.

### CT-10 — Repeated adopt
Sin duplicación.

---

# 10. Tasks

## T1 — Crear servicio adopt
Orquestación.

## T2 — Implementar clasificación de escenarios
Sobre observación E2-S0.

## T3 — Implementar compatibilidad exacta
Branch/path.

## T4 — Implementar branch-only adoption
Crear worktree.

## T5 — Implementar dirty observation
Sin bloquear.

## T6 — Implementar errores adopt
Contratos estables.

## T7 — Implementar rollback mínimo
Sólo worktree propio.

## T8 — Implementar postcondition verification
Compatibilidad final.

## T9 — Conectar CLI
Salida de adoption mode.

## T10 — Tests unitarios
Clasificación.

## T11 — Tests integración
Repos/worktrees reales.

---

# 11. Verificación

La spec está completa cuando:

- puede incorporarse trabajo existente sin recrearlo;
- dirty worktree compatible se conserva;
- branch/path incompatibles fallan conservadoramente;
- branch-only puede completar el worktree;
- ningún rollback elimina branch preexistente;
- no hay network side effects.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R3 | 7.1-7.2 | T1-T4 | AC-01,02 |
| R4-R8 | 7.2 | T2, T6 | AC-03..07 |
| R9-R12 | 7.4 | T5, T8-T9 | AC-08 |
| R13-R16 | 7.3 | T7 | AC-09,10 |

---

# 13. Resultado esperado

Después de E2-S2, el producto podrá incorporar trabajo preexistente al mismo modelo operativo sin exigir que todo workspace haya nacido con `imass-wt init`.
