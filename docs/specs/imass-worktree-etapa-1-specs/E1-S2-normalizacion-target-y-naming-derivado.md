# E1-S2 — Normalización de target y naming derivado

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E1 — Configuración y targets
- **Spec:** E1-S2
- **Nombre:** Normalización de target y naming derivado
- **Dependencias:** E1-S0, E1-S1
- **Bloquea a:** E2 — Lifecycle fundamental
- **Estado inicial:** Planificada

---

## 2. Contexto

Los proyectos pueden definir targets canónicos estrictos, pero el usuario puede introducir variantes razonables.

Ejemplo conceptual:

```text
E7-S8-Convergencia Schema Tests
```

podría normalizarse, si el proyecto así lo declara, a:

```text
E7-S8-convergencia-schema-tests
```

La normalización debe ser configurable y conservadora.

Esta spec también define cómo, a partir del target canónico validado, se derivan nombres como:

- branch;
- directorio del worktree.

La derivación debe ser determinista y pertenecer a la configuración del proyecto, no al core de manera específica.

---

## 3. Objetivo

Implementar un pipeline configurable que:

1. reciba una entrada raw;
2. aplique transformaciones autorizadas en orden determinista;
3. rechace transformaciones ambiguas o destructivas;
4. valide el resultado mediante E1-S1;
5. obtenga un `Target` canónico;
6. derive branch y worktree name/path mediante patrones configurados;
7. valide que los valores derivados sean seguros antes de que E2 ejecute Git.

Al finalizar E1-S2, el producto debe poder transformar una entrada razonable en una identidad canónica y derivar de ella nombres operativos sin conocer convenciones específicas de un proyecto concreto.

---

## 4. Alcance

### 4.1 Incluido

- `trim`.
- reemplazo de espacios por separador configurable.
- compactación de guiones repetidos.
- `lowercase_slug`.
- definición explícita de orden del pipeline.
- validación posterior mediante E1-S1.
- patrones de branch.
- patrones de worktree.
- placeholder `{target}`.
- derivación determinista.
- validaciones básicas de seguridad de naming.
- detección de normalizaciones que produzcan vacío.
- mensajes que permitan observar el valor raw y el canónico.
- pruebas con distintos proyectos.

### 4.2 Fuera de alcance

- Creación de branch.
- `git worktree add`.
- filesystem mutations.
- asignación de puertos.
- capabilities.
- parsing de IDs de Jira/GitHub.
- transliteración arbitraria.
- generación por IA.
- deducción semántica del target.
- renombrado automático de targets ya existentes.

---

## 5. Principios e invariantes

### INV-01 — La normalización es opt-in por regla

Cada transformación debe estar habilitada explícitamente por la configuración del proyecto o ser una operación universal no destructiva definida por el contrato.

### INV-02 — Orden determinista

Las reglas se ejecutan siempre en el mismo orden.

### INV-03 — Validación al final

La salida normalizada no se considera target hasta que E1-S1 la valida.

### INV-04 — No interpretación semántica

El normalizador transforma sintaxis; no interpreta el significado del ticket, issue o slug.

### INV-05 — Identidad canónica única

Una vez validado, el resultado canónico es el valor utilizado para derivar branch y worktree.

### INV-06 — Derivación pura

Mismo config + mismo target canónico = mismos nombres derivados.

### INV-07 — No filesystem/Git mutations

E1-S2 calcula y valida nombres; E2 ejecutará las operaciones.

### INV-08 — Las transformaciones deben ser observables

El usuario debe poder saber si su entrada fue normalizada.

---

# 6. Requirements

## R1 — Configuración de normalización

El proyecto puede declarar:

```toml
[target.normalization]
trim = true
lowercase_slug = true
replace_spaces = "-"
collapse_dashes = true
```

Todas las propiedades deben tener tipos estrictos.

---

## R2 — Orden del pipeline

El orden canónico será:

```text
1. trim
2. replace_spaces
3. collapse_dashes
4. lowercase_slug
5. validación E1-S1
```

El orden no depende del orden de claves en TOML.

---

## R3 — `trim`

Cuando esté habilitado:

```text
"  FEATURE-123-login  "
→
"FEATURE-123-login"
```

Cuando esté deshabilitado, el valor se conserva y probablemente será rechazado por la regex si los espacios no son válidos.

---

## R4 — `replace_spaces`

Cuando esté habilitado con `"-"`:

- cada secuencia de whitespace interno permitida por la regla se convierte en `-`;
- no debe ejecutarse shell ni regex proporcionada por el usuario para esta transformación.

Ejemplo:

```text
FEATURE-123-login page
→
FEATURE-123-login-page
```

---

## R5 — `collapse_dashes`

Cuando esté habilitado:

```text
FEATURE-123---login
→
FEATURE-123-login
```

La regla aplica al carácter `-`, no a otros separadores salvo extensión futura explícita.

---

## R6 — `lowercase_slug`

Debe permitir normalizar solamente la porción considerada slug sin destruir segmentos cuyo case forme parte de la convención.

### Contrato inicial

El proyecto debe poder declarar cómo identificar el slug de manera compatible con su target.

Para E1 se adopta una estrategia mínima:

```toml
[target.normalization]
lowercase_slug = true
slug_separator = "-"
preserve_prefix_segments = 2
```

Ejemplo SiVale:

```text
E7-S8-Convergencia-Schema-Tests
→
E7-S8-convergencia-schema-tests
```

Ejemplo FEATURE:

```text
FEATURE-123-Login-Page
→
FEATURE-123-login-page
```

`preserve_prefix_segments` es configurable para no codificar estructuras específicas en el core.

---

## R7 — Transformación conservadora

Si una configuración de normalización no puede aplicarse de forma inequívoca, la operación debe fallar en vez de inventar una forma canónica.

Código:

```text
TARGET_NORMALIZATION_FAILED
```

---

## R8 — Resultado vacío

Si la normalización produce cadena vacía, debe fallar antes de construir `Target`.

Código:

```text
TARGET_NORMALIZATION_EMPTY
```

---

## R9 — Validación posterior

Todo resultado de normalización debe pasar por `TargetValidator`.

Una entrada transformable pero incompatible con la regex termina como `TARGET_INVALID`.

---

## R10 — Resultado de normalización

La operación debe poder representar:

```text
raw_value
normalized_value
changed
target
```

Esto permite que CLI informe una transformación sin alterar la lógica de dominio.

---

## R11 — Branch pattern

La configuración debe aceptar:

```toml
[branch]
pattern = "spec/{target}"
```

Debe existir `{target}` exactamente como placeholder mínimo soportado en E1.

Ejemplo:

```text
target = E7-S8-convergencia-schema-tests
pattern = spec/{target}

→ spec/E7-S8-convergencia-schema-tests
```

---

## R12 — Worktree pattern

La configuración debe aceptar:

```toml
[worktree]
directory = ".local-wt"
pattern = "{target}"
```

La derivación produce conceptualmente:

```text
<resolved worktree directory>/<expanded pattern>
```

E1-S2 no crea el directorio.

---

## R13 — Patrones inválidos

Debe rechazarse:

- patrón vacío;
- patrón sin `{target}` cuando el contrato exija identidad por target;
- placeholders desconocidos;
- resultados vacíos;
- resultados que intenten escapar del boundary configurado.

Errores:

```text
BRANCH_PATTERN_INVALID
WORKTREE_PATTERN_INVALID
```

---

## R14 — Seguridad del nombre de branch

El nombre derivado debe cumplir las restricciones fundamentales de Git ref names antes de llegar a E2.

La implementación puede delegar validación a Git de forma read-only o implementar reglas equivalentes centralizadas.

No debe crear la branch durante E1-S2.

Código:

```text
DERIVED_BRANCH_INVALID
```

---

## R15 — Seguridad del path de worktree

El path derivado debe:

- resolverse de forma determinista respecto al repository root o boundary configurado;
- impedir `..` que escape del directorio permitido;
- impedir path vacío;
- impedir que el patrón apunte al root del repositorio actual;
- no seguir symlinks para “autorizar” escapes.

La seguridad profunda de path boundaries se fortalecerá en E7-S2, pero E1-S2 debe impedir derivaciones evidentemente inseguras.

Código:

```text
DERIVED_WORKTREE_PATH_INVALID
```

---

## R16 — Colisiones fuera de alcance

E1-S2 no decide si el branch o path ya existen.

Eso pertenece a E2.

Su responsabilidad termina en producir nombres sintáctica y estructuralmente válidos.

---

## R17 — Observabilidad

Si `raw_value != normalized_value`, la capa CLI debe poder mostrar una indicación equivalente a:

```text
Target normalizado:
  entrada:   E7-S8-Convergencia Schema Tests
  canónico:  E7-S8-convergencia-schema-tests
```

La salida exacta final se ajustará al contrato de CLI definido en E0-S1.

---

## R18 — Idempotencia

Normalizar un valor ya canónico debe devolver el mismo valor:

```text
normalize(normalize(x)) == normalize(x)
```

para toda entrada que produzca un target válido.

---

## R19 — Convenciones distintas

La suite debe demostrar que la misma implementación soporta, al menos:

```text
E7-S8-convergencia-schema-tests
FEATURE-123-login
TASK-15-retries
```

con configuraciones distintas.

---

# 7. Diseño

## 7.1 Componentes conceptuales

```text
core/
└── target.py
    ├── Target
    ├── TargetNormalizer
    └── TargetNormalizationResult

config/
└── models.py
    ├── TargetNormalizationConfig
    ├── BranchConfig
    └── WorktreeConfig
```

Puede existir además un servicio de naming:

```text
WorkspaceNaming
├── derive_branch(target, config)
└── derive_worktree_path(target, config)
```

---

## 7.2 Pipeline

```text
raw
 ↓
trim?
 ↓
replace spaces?
 ↓
collapse dashes?
 ↓
lowercase slug?
 ↓
TargetValidator
 ↓
Target canónico
 ├──────────────→ branch pattern
 └──────────────→ worktree pattern
```

---

## 7.3 Lowercase del slug

No se codificarán expresiones como:

```text
si empieza con E\d+-S\d+ entonces...
```

El core sólo utilizará parámetros genéricos como `preserve_prefix_segments`.

Esto conserva la independencia respecto a SiVale.

---

## 7.4 Naming

La expansión inicial soportará exclusivamente:

```text
{target}
```

No se incorporarán placeholders especulativos como `{user}`, `{port}`, `{date}` o `{project}` hasta que una spec los justifique.

---

## 7.5 Resolución del directorio de worktrees

`worktree.directory` puede ser relativo.

Un valor relativo se interpreta respecto al repository root descubierto en E1-S0.

Ejemplo:

```text
repo = /projects/app
directory = .local-wt
target = FEATURE-123-login

→ /projects/app/.local-wt/FEATURE-123-login
```

La política puede evolucionar posteriormente si se decide soportar worktrees fuera del repositorio, pero E1 no debe introducir paths globales específicos.

---

## 7.6 Validación de branch

El servicio de naming debe validar el ref derivado sin mutar Git.

La implementación debe centralizar esa validación en la capa Git/naming apropiada y evitar shell injection.

---

## 7.7 Path boundaries

Antes de E2, el path final calculado debe pasar validaciones léxicas/canónicas suficientes para impedir escapes obvios.

E7-S2 añadirá hardening contra escenarios avanzados de symlinks y límites.

---

## 7.8 Resultado agregado

El lifecycle futuro podrá consumir una estructura equivalente a:

```text
ResolvedWorkspaceIdentity
├── target
├── branch_name
└── worktree_path
```

Esta spec puede introducirla si simplifica el contrato sin crear estado persistente prematuro.

---

# 8. Criterios de aceptación

## AC-01

Un target ya canónico permanece idéntico tras normalización.

## AC-02

`trim` funciona sólo cuando está habilitado.

## AC-03

Espacios internos se convierten al separador configurado cuando `replace_spaces` está activo.

## AC-04

Guiones repetidos se compactan cuando la regla está activa.

## AC-05

`lowercase_slug` conserva los segmentos configurados y baja únicamente el resto.

## AC-06

El resultado siempre pasa por E1-S1.

## AC-07

Una normalización inválida produce `TARGET_NORMALIZATION_FAILED` o el error de validación correspondiente.

## AC-08

El patrón `spec/{target}` deriva una branch determinista.

## AC-09

Un patrón con placeholder desconocido es rechazado.

## AC-10

Un branch name inválido es rechazado antes de E2.

## AC-11

Un worktree path con escape fuera del boundary es rechazado.

## AC-12

La misma implementación soporta tres convenciones de proyecto distintas.

## AC-13

Ninguna operación de E1-S2 crea branch, directorio o worktree.

## AC-14

La normalización es idempotente.

---

# 9. Casos de prueba mínimos

### CT-01 — Canonical no-op
Target ya válido.

### CT-02 — Trim
Espacios externos.

### CT-03 — Replace spaces
Slug con espacios.

### CT-04 — Collapse
Guiones repetidos.

### CT-05 — SiVale lowercase slug
Preservar `E7-S8`.

### CT-06 — FEATURE lowercase slug
Preservar `FEATURE-123`.

### CT-07 — TASK lowercase slug
Preservar `TASK-15`.

### CT-08 — Normalización produce inválido
Transformable sintácticamente pero regex final falla.

### CT-09 — Idempotencia
Dos normalizaciones iguales.

### CT-10 — Branch válido
`spec/{target}`.

### CT-11 — Branch pattern vacío
Error.

### CT-12 — Placeholder desconocido
Error.

### CT-13 — Branch ref inválido
Ejemplo con secuencia prohibida por Git.

### CT-14 — Worktree path válido
Dentro de `.local-wt`.

### CT-15 — Path traversal
`../outside/{target}`.

### CT-16 — Path al root
Pattern que resuelva al checkout principal.

### CT-17 — Sin mutations
Verificar que no aparecen refs/directorios nuevos.

---

# 10. Tasks

## T1 — Extender modelo de configuración de normalización
Agregar reglas y parámetros genéricos necesarios.

## T2 — Implementar `TargetNormalizer`
Pipeline fijo y configurable.

## T3 — Implementar `TargetNormalizationResult`
Raw, normalized, changed y Target.

## T4 — Integrar con `TargetValidator`
Toda salida se valida mediante E1-S1.

## T5 — Implementar lowercase genérico de slug
Sin reglas específicas de SiVale.

## T6 — Implementar parser/validator de patterns
Soporte inicial exclusivo de `{target}`.

## T7 — Implementar derivación de branch
Determinista y sin mutation.

## T8 — Implementar validación read-only de branch name
Compatible con restricciones Git.

## T9 — Implementar derivación de worktree path
Respecto al root y directory configurado.

## T10 — Implementar validación inicial de boundary
Traversal, vacío y root collision.

## T11 — Integrar observabilidad con CLI
Exponer raw/canónico cuando cambie.

## T12 — Tests unitarios de normalización
Reglas, orden, idempotencia.

## T13 — Tests unitarios de naming
Patterns, refs y paths.

## T14 — Tests parametrizados multi-proyecto
SiVale-like, FEATURE y TASK.

## T15 — Test de cero mutations
Confirmar que E1-S2 no crea recursos.

---

# 11. Verificación

La spec se considera completa cuando:

- el pipeline es determinista e idempotente;
- no contiene reglas específicas de SiVale;
- todo target canónico está validado por E1-S1;
- branch y worktree path se derivan sin mutaciones;
- los patterns inválidos fallan temprano;
- los boundaries mínimos están cubiertos;
- tres configuraciones distintas producen resultados correctos con el mismo core.

Los comandos exactos de test/lint se definirán conforme al toolchain Python formalmente adoptado.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R6 | 7.1-7.3 | T1-T5 | AC-01..06 |
| R7-R10 | 7.2, 7.8 | T2-T4 | AC-06,07 |
| R11-R14 | 7.4, 7.6 | T6-T8 | AC-08..10 |
| R15-R16 | 7.5, 7.7 | T9-T10 | AC-11,13 |
| R17 | 7.8 | T11 | AC-01 |
| R18 | 7.2 | T12 | AC-14 |
| R19 | 7.3 | T14 | AC-12 |

---

# 13. Resultado esperado

Después de E1-S2, la Etapa 1 debe poder producir, para una entrada válida o razonablemente normalizable:

```text
raw target
    ↓
target canónico validado
    ↓
branch name derivado
    ↓
worktree path derivado
```

sin crear todavía ningún recurso.

Con esto queda cerrado el contrato de proyecto cliente y targets necesario para que E2 implemente `init`, `adopt` y `destroy` sobre identidades ya resueltas y seguras.
