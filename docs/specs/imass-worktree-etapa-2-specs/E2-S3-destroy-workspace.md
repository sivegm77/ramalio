# E2-S3 — `imass-wt destroy`

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E2 — Lifecycle fundamental
- **Spec:** E2-S3
- **Nombre:** Destrucción segura de workspace
- **Dependencias:** E2-S0, E2-S1, E2-S2
- **Bloquea a:** cierre de E2, E3
- **Estado inicial:** Planificada

---

## 2. Contexto

`destroy` es la operación más sensible del lifecycle fundamental porque puede retirar:

- un Git worktree;
- opcionalmente una branch asociada.

La visión del producto establece que `destroy` no significa “borrar”, sino cerrar de manera controlada una unidad de trabajo y proteger contra pérdida accidental.

En E2 todavía no existen capabilities. Por tanto, esta spec se concentra únicamente en Git/worktree y branch cleanup seguro.

---

## 3. Objetivo

Implementar:

```bash
imass-wt destroy <target>
```

para:

1. resolver la identidad canónica;
2. observar el estado actual;
3. comprobar que el workspace corresponde al target;
4. detectar trabajo local que impediría destrucción segura;
5. retirar el worktree;
6. eliminar la branch sólo cuando la política y las condiciones de seguridad lo permitan;
7. verificar postcondiciones;
8. no tocar recursos ajenos.

---

## 4. Alcance

### 4.1 Incluido

- Validación target/identity.
- Validación de correspondencia branch/worktree.
- Protección ante cambios locales.
- Retiro de worktree.
- Política inicial de branch cleanup.
- Detección de branch no integrada.
- Postcondition verification.
- Fail-closed.
- Tests de integración.

### 4.2 Fuera de alcance

- Stop de procesos/capabilities — E3/E4.
- tmux/runtime/zrok.
- Remote branch deletion.
- Push.
- PR.
- Merge automático.
- Stash automático.
- Commit automático.
- Recuperación avanzada de interrupciones — E7.
- `--force` destructivo general.

---

## 5. Principios e invariantes

### INV-01 — No pérdida silenciosa

Si existe trabajo local no preservado, `destroy` debe bloquear.

### INV-02 — Identidad exacta

Sólo puede destruir el worktree que corresponde al target/branch/path derivados.

### INV-03 — No cleanup global

No se ejecutan limpiezas indiscriminadas de worktrees o branches.

### INV-04 — Branch conservadora

Eliminar la branch requiere más garantías que retirar el worktree.

### INV-05 — Remotes fuera de alcance

Nunca eliminar branch remota.

### INV-06 — Sin auto-commit/stash

`destroy` no “salva” trabajo alterándolo automáticamente.

### INV-07 — Postcondiciones explícitas

El éxito se reporta sólo después de comprobar qué recursos fueron retirados y cuáles se conservaron.

---

# 6. Requirements

## R1 — Entrada

El target debe resolverse mediante E1.

`destroy` no acepta paths arbitrarios como sustituto del target en E2.

---

## R2 — Workspace inexistente

Si no existe worktree ni branch correspondientes:

```text
WORKSPACE_NOT_FOUND
```

No debe considerarse éxito silencioso.

---

## R3 — Branch sin worktree

Si existe la branch derivada pero no existe worktree:

- `destroy` debe tratarlo como estado parcial;
- puede evaluar branch cleanup únicamente si es seguro;
- no debe fingir que existía un workspace completo.

El resultado debe distinguir el caso.

---

## R4 — Worktree mismatch

Si el path canónico existe como worktree pero usa otra branch:

```text
DESTROY_WORKTREE_MISMATCH
```

No tocar nada.

---

## R5 — Branch en otro worktree

Si la branch está checked out en otro path distinto al canónico:

```text
DESTROY_BRANCH_IN_OTHER_WORKTREE
```

No retirar ese worktree.

---

## R6 — Dirty tracked changes

Si el worktree objetivo tiene cambios tracked no committeados:

```text
DESTROY_BLOCKED_DIRTY
```

No eliminar worktree ni branch.

---

## R7 — Untracked files

Archivos untracked también bloquean por defecto.

La razón es que pueden contener trabajo útil no representado en Git.

---

## R8 — Ignored files

Los archivos ignored no deben bloquear automáticamente si Git considera seguro retirar el worktree sin `--force`.

No obstante, `destroy` no debe usar opciones forzadas que borren contenido ignored sin evaluación.

Si Git rechaza la retirada por contenido local, el comando debe bloquear.

---

## R9 — Worktree removal

Cuando el worktree está en estado seguro:

- retirar el worktree mediante Git;
- no usar `rm -rf` como mecanismo primario;
- verificar que dejó de estar registrado.

---

## R10 — Branch cleanup policy

La configuración debe permitir una política inicial equivalente a:

```toml
[branch]
delete_on_destroy = true | false
```

Default seguro:

```text
false
```

La ausencia del campo implica conservar branch.

---

## R11 — Branch delete deshabilitado

Si `delete_on_destroy = false`:

- retirar worktree;
- conservar branch;
- reportar claramente `branch_deleted=false`.

---

## R12 — Branch delete habilitado

Si está habilitado, la branch sólo puede eliminarse cuando:

- ya no está checked out en ningún worktree;
- no contiene trabajo no integrado según la política definida;
- no es la base branch;
- no es una branch protegida por identidad del checkout principal;
- Git permite eliminación segura sin force.

---

## R13 — Integración de branch

Para E2, la condición mínima de seguridad será que Git permita una eliminación no forzada respecto de la branch actualmente considerada segura/base según la estrategia implementada.

No usar:

```text
git branch -D
```

en el flujo normal.

Si no puede eliminarse de forma no forzada:

```text
DESTROY_BRANCH_NOT_SAFE_TO_DELETE
```

El worktree ya retirado puede permanecer retirado y la branch conservarse.

Ese resultado debe reportarse como cierre parcial controlado, no como pérdida de datos.

---

## R14 — Nunca eliminar base branch

Si por configuración defectuosa la branch derivada coincide con `project.base_branch`, bloquear:

```text
DESTROY_PROTECTED_BRANCH
```

---

## R15 — Orden de operación

El orden normal será:

```text
preflight
→ remove worktree
→ verify worktree removal
→ optional branch deletion
→ verify final state
```

No eliminar branch antes de retirar el worktree.

---

## R16 — Fallo al retirar worktree

Si Git no puede retirar el worktree:

- no intentar branch deletion;
- devolver error;
- preservar diagnóstico.

---

## R17 — Fallo al borrar branch

Si el worktree ya fue retirado y branch cleanup falla por seguridad:

- conservar branch;
- no intentar force;
- devolver resultado que indique worktree retirado y branch conservada.

---

## R18 — Resultado

Debe incluir como mínimo:

```text
target
worktree_removed
branch_deleted
branch_preserved_reason
```

cuando aplique.

---

## R19 — Idempotencia controlada

Una segunda llamada después de un destroy completo debe responder `WORKSPACE_NOT_FOUND`.

No debe afectar otras branches/worktrees.

---

## R20 — Sin efectos remotos

No fetch, push ni delete remoto.

---

# 7. Diseño

## 7.1 Servicio

```text
DestroyWorkspaceService
```

Flujo:

```text
resolve identity
      ↓
observe state
      ↓
validate exact ownership
      ↓
check dirty/untracked
      ↓
remove worktree
      ↓
verify removal
      ↓
branch policy?
   no ───────────────→ preserve
   sí
      ↓
safe non-force delete?
   no ───────────────→ preserve + reason
   sí ───────────────→ delete
      ↓
final verification
```

---

## 7.2 Diferencia entre error y cierre parcial

Caso:

```text
worktree removed
branch unsafe to delete
```

no debe provocar force cleanup.

El resultado puede ser no-cero o una categoría específica según E0-S1, pero debe expresar inequívocamente que el trabajo no fue perdido y que la branch quedó preservada.

---

## 7.3 Dirty detection

Debe reutilizar E2-S0.

La capa de destroy no debe parsear Git status independientemente.

---

## 7.4 Worktree removal

Usar Git como autoridad y mecanismo primario.

Sólo pueden existir operaciones filesystem auxiliares cuando Git ya haya confirmado que el recurso es propio y seguro, y deberán justificarse explícitamente.

---

## 7.5 Branch policy

La eliminación de branch es secundaria al cierre del worktree.

Default:

```text
preserve branch
```

Esto prioriza seguridad.

---

## 7.6 Códigos mínimos

```text
WORKSPACE_NOT_FOUND
DESTROY_WORKTREE_MISMATCH
DESTROY_BRANCH_IN_OTHER_WORKTREE
DESTROY_BLOCKED_DIRTY
DESTROY_WORKTREE_REMOVE_FAILED
DESTROY_BRANCH_NOT_SAFE_TO_DELETE
DESTROY_PROTECTED_BRANCH
DESTROY_POSTCONDITION_FAILED
```

---

# 8. Criterios de aceptación

## AC-01

Worktree limpio se retira correctamente.

## AC-02

Dirty tracked bloquea antes de mutar.

## AC-03

Untracked bloquea antes de mutar.

## AC-04

Mismatch de branch/path no toca recursos.

## AC-05

Default conserva branch.

## AC-06

`delete_on_destroy=true` elimina sólo branch segura mediante delete no forzado.

## AC-07

Branch no segura se conserva.

## AC-08

Nunca se elimina base branch.

## AC-09

Fallo de worktree removal impide branch cleanup.

## AC-10

No hay efectos remotos.

---

# 9. Casos de prueba mínimos

### CT-01 — Clean, preserve branch
Default.

### CT-02 — Clean, safe branch delete
Policy true.

### CT-03 — Dirty tracked
Bloqueo.

### CT-04 — Untracked
Bloqueo.

### CT-05 — Path mismatch
Bloqueo.

### CT-06 — Branch in other worktree
Bloqueo.

### CT-07 — Branch not merged / delete unsafe
Retirar worktree, conservar branch.

### CT-08 — Base branch collision
Bloqueo.

### CT-09 — Git worktree remove failure
No branch delete.

### CT-10 — Segundo destroy
`WORKSPACE_NOT_FOUND`.

### CT-11 — Sin remote effects
No fetch/push/delete remote.

---

# 10. Tasks

## T1 — Extender branch config
`delete_on_destroy` con default false.

## T2 — Crear servicio destroy
Orquestación.

## T3 — Implementar ownership/exact identity checks
Path + branch.

## T4 — Integrar dirty/untracked preflight
Reusar E2-S0.

## T5 — Implementar worktree removal seguro
Git primario.

## T6 — Implementar branch cleanup policy
No-force.

## T7 — Implementar protected branch guard
Base branch.

## T8 — Implementar resultados parciales
Branch preservada con razón.

## T9 — Implementar postcondition verification
Registro Git y refs.

## T10 — Conectar CLI
Salida consistente.

## T11 — Tests unitarios
Policies y decisiones.

## T12 — Tests integración
Repos/worktrees reales y fallos inducidos.

---

# 11. Verificación

E2-S3 está completa cuando:

- `destroy` bloquea ante trabajo local;
- jamás usa force deletion como flujo normal;
- branch cleanup es opt-in y conservador;
- mismatch no destruye nada;
- Git es mecanismo primario de retiro;
- no hay operaciones remotas;
- postcondiciones están cubiertas.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R5 | 7.1 | T2-T3 | AC-04 |
| R6-R9 | 7.3-7.4 | T4-T5 | AC-01..03 |
| R10-R14 | 7.5 | T1, T6-T8 | AC-05..08 |
| R15-R19 | 7.1-7.2 | T5, T8-T9 | AC-09 |
| R20 | 7.4 | T12 | AC-10 |

---

# 13. Resultado esperado

Después de E2-S3 queda cerrado el ciclo fundamental:

```text
init
  ↓
trabajar
  ↓
destroy
```

más:

```text
trabajo existente
  ↓
adopt
  ↓
continuar
  ↓
destroy
```

Con esto E2 entrega el primer núcleo utilizable de `imass-worktree`, todavía sin capabilities opcionales.
