# E1-S1 — Validación de target

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E1 — Configuración y targets
- **Spec:** E1-S1
- **Nombre:** Validación de target
- **Dependencias:** E1-S0
- **Bloquea a:** E1-S2 y lifecycle E2
- **Estado inicial:** Planificada

---

## 2. Contexto

Cada proyecto cliente puede adoptar una convención distinta para identificar unidades de trabajo.

Ejemplos:

```text
E7-S8-convergencia-schema-tests
FEATURE-123-login
BUG-482-stripe-webhook
TASK-15-retries
```

`imass-worktree` no debe imponer una convención universal.

Esta spec define el contrato mediante el cual el proyecto declara qué constituye un target válido y cómo el producto valida de forma determinista una entrada ya preparada para validación.

La normalización de entradas pertenece a E1-S2. Esta spec valida el valor recibido contra la política configurada.

---

## 3. Objetivo

Implementar una abstracción de `Target` y un validador configurable que:

1. reciba una cadena candidata;
2. aplique reglas de sensibilidad a mayúsculas/minúsculas según configuración;
3. valide el valor completo contra la regex del proyecto;
4. produzca un `Target` válido o un error de dominio;
5. emita mensajes útiles usando el ejemplo configurado;
6. no infiera targets desde contexto, historial ni nombres parciales.

---

## 4. Alcance

### 4.1 Incluido

- Modelo de dominio `Target`.
- Regex configurable por proyecto.
- Validación de coincidencia completa.
- `case_sensitive`.
- `example`.
- Validación de configuración de regex.
- Mensajes de error estables.
- Pruebas unitarias parametrizadas con convenciones distintas.
- Protección contra valores vacíos o ambiguos.

### 4.2 Fuera de alcance

- Trim y transformación de espacios.
- Lowercase del slug.
- Collapse de guiones.
- Derivación de branch/worktree.
- Creación Git.
- Inferencia del target desde branch actual.
- Resolución de “latest”, slugs parciales o contexto conversacional.
- Capabilities e integrations.

---

## 5. Principios e invariantes

### INV-01 — La política pertenece al proyecto

El core no define una regex universal.

### INV-02 — Validación exacta

La regex debe validar el target completo, no una subcadena.

### INV-03 — No inferencia

El sistema no completará un target parcial ni escogerá automáticamente uno entre varios.

### INV-04 — Un target válido es un valor de dominio

Una vez creado, un objeto `Target` representa una cadena ya validada bajo la política efectiva del proyecto.

### INV-05 — Errores diagnósticos

Un rechazo debe explicar qué valor fue inválido y, cuando exista, mostrar un ejemplo válido.

### INV-06 — Sin transformación silenciosa

Esta spec no modifica la entrada. Las transformaciones pertenecen a E1-S2.

---

# 6. Requirements

## R1 — Configuración requerida

La configuración de target debe poder expresar:

```toml
[target]
regex = "^..."
example = "..."
case_sensitive = true
```

### Reglas

- `regex` es obligatorio.
- `example` es obligatorio.
- `case_sensitive` debe ser booleano.
- regex vacía es inválida.
- ejemplo vacío es inválido.

---

## R2 — Regex compilable

La regex configurada debe poder compilarse con el motor adoptado.

Una regex inválida debe rechazarse al cargar/validar la configuración, antes de operar lifecycle.

Código de error:

```text
TARGET_REGEX_INVALID
```

---

## R3 — Coincidencia completa

La validación debe exigir que el valor completo cumpla la expresión.

No debe aceptarse:

```text
xxxFEATURE-123-loginzzz
```

si sólo `FEATURE-123-login` corresponde al patrón.

Incluso si el proyecto omite anchors en su regex, la API de validación debe aplicar semántica de full match.

---

## R4 — Target vacío

Debe rechazarse:

- cadena vacía;
- valor compuesto sólo por espacios cuando llegue sin normalización;
- ausencia del argumento.

Errores de parsing CLI y de dominio pueden distinguirse, pero nunca se crea un `Target` vacío.

---

## R5 — Sensibilidad a mayúsculas/minúsculas

`case_sensitive = true`:

- la regex se evalúa respetando case.

`case_sensitive = false`:

- la evaluación puede ser case-insensitive;
- la cadena original no se transforma ni reescribe en esta spec.

---

## R6 — Ejemplo válido

El `example` configurado debe cumplir la misma política que se utiliza para validar targets.

Si el ejemplo no es válido, la configuración del proyecto debe rechazarse.

Código:

```text
TARGET_EXAMPLE_INVALID
```

---

## R7 — Modelo Target

Debe existir una representación de dominio equivalente a:

```text
Target(value)
```

que sólo pueda producirse por una ruta validada o un constructor interno explícitamente seguro.

El resto del lifecycle no debe recibir strings arbitrarios donde se espere un target validado.

---

## R8 — Error de target inválido

Un target candidato que no cumpla la política debe producir:

```text
TARGET_INVALID
```

El mensaje para humanos debe incluir:

- valor recibido;
- política general o referencia al patrón;
- ejemplo válido configurado.

No es necesario imprimir la regex completa si ello deteriora la legibilidad, pero debe estar disponible para diagnóstico detallado.

---

## R9 — No inferencia

El validador no debe:

- consultar branches;
- revisar worktrees;
- buscar specs;
- buscar “el target más parecido”;
- completar slugs;
- interpretar “latest”;
- usar historial previo.

---

## R10 — Reutilización

CLI, lifecycle y comandos futuros deben compartir el mismo servicio/función de validación.

No se permiten validaciones duplicadas con regex distintas distribuidas por comandos.

---

## R11 — Convenciones múltiples

La suite debe demostrar al menos estas familias:

### Familia A — Etapa/spec

```text
E7-S8-convergencia-schema-tests
```

### Familia B — Feature

```text
FEATURE-123-login
```

### Familia C — Task

```text
TASK-15-retries
```

Cada fixture usa su propia regex sin cambios al core.

---

## R12 — Límites razonables

La implementación debe impedir targets patológicamente grandes.

Se deberá definir una longitud máxima de producto suficientemente amplia para nombres de trabajo reales y suficientemente pequeña para evitar entradas absurdas.

### Decisión inicial

```text
MAX_TARGET_LENGTH = 200
```

Esta constante pertenece al producto, no al proyecto, porque protege CLI, logs, paths derivados y diagnóstico.

Una entrada superior debe producir:

```text
TARGET_TOO_LONG
```

---

# 7. Diseño

## 7.1 Componentes conceptuales

```text
core/
└── target.py

config/
└── validation.py
```

Responsabilidades:

```text
TargetPolicy
├── regex
├── example
└── case_sensitive

TargetValidator
└── validate(candidate, policy) -> Target
```

---

## 7.2 Flujo

```text
candidate string
      ↓
validar presencia / longitud
      ↓
obtener TargetPolicy resuelta
      ↓
full-match según case policy
      ↓
válido ──────────────→ Target
      │
      └─ inválido ───→ TARGET_INVALID
```

---

## 7.3 Separación respecto a E1-S2

E1-S1 responde:

> ¿Este valor es válido?

E1-S2 responderá:

> ¿Cómo podemos transformar una entrada razonable hacia su forma canónica antes de validarla?

Por tanto:

```text
raw input
   ↓
normalization (E1-S2)
   ↓
validation (E1-S1)
   ↓
Target
```

El validador debe ser reusable tanto directamente como detrás del normalizador.

---

## 7.4 Identidad

En E1, `Target.value` será la identidad canónica utilizada por derivaciones posteriores.

No se diseñará todavía persistencia propia de targets.

---

## 7.5 Regex y seguridad

La implementación debe usar la biblioteca estándar o dependencia aprobada del proyecto.

No debe ejecutar regex mediante shell.

Si el motor elegido ofrece mecanismos razonables para evitar patrones problemáticos, deberán aprovecharse sin cambiar el contrato externo.

La configuración es confiable a nivel de proyecto versionado, pero los valores de usuario no lo son.

---

## 7.6 Mensajería

Ejemplo conceptual:

```text
Target inválido: "feature 123 login".
Esperado un valor compatible con la convención del proyecto.
Ejemplo: FEATURE-123-login
```

No se debe “corregir” automáticamente aquí.

---

# 8. Criterios de aceptación

## AC-01

Una regex válida y un candidato compatible producen un `Target`.

## AC-02

Un candidato que sólo contiene una coincidencia parcial es rechazado.

## AC-03

Una regex inválida produce `TARGET_REGEX_INVALID` durante validación de configuración.

## AC-04

Un ejemplo incompatible con la regex produce `TARGET_EXAMPLE_INVALID`.

## AC-05

`case_sensitive = true` distingue mayúsculas/minúsculas.

## AC-06

`case_sensitive = false` permite matching insensitive sin modificar la cadena recibida.

## AC-07

Un target inválido devuelve `TARGET_INVALID` y muestra el ejemplo del proyecto.

## AC-08

Un target con más de 200 caracteres devuelve `TARGET_TOO_LONG`.

## AC-09

Tres proyectos con regex diferentes usan la misma implementación de `TargetValidator`.

## AC-10

Ninguna ruta de validación consulta Git, worktrees, historial o herramientas externas.

---

# 9. Casos de prueba mínimos

### CT-01 — SiVale válido
`E7-S8-convergencia-schema-tests`.

### CT-02 — SiVale inválido
`E7-convergencia`.

### CT-03 — Feature válida
`FEATURE-123-login`.

### CT-04 — Task válida
`TASK-15-retries`.

### CT-05 — Match parcial
Prefijo/sufijo extra.

### CT-06 — Regex rota
Patrón no compilable.

### CT-07 — Example roto
Example no coincide.

### CT-08 — Case sensitive
Valor con case incorrecto.

### CT-09 — Case insensitive
Mismo valor con case alternativo.

### CT-10 — Vacío
`""`.

### CT-11 — Sólo espacios
`"   "`.

### CT-12 — 200 caracteres
Boundary permitido si además cumple regex.

### CT-13 — 201 caracteres
`TARGET_TOO_LONG`.

### CT-14 — No inferencia
Target parcial debe fallar aunque exista una branch parecida en fixture.

---

# 10. Tasks

## T1 — Definir `TargetPolicy`
Modelo proveniente de configuración resuelta.

## T2 — Definir `Target`
Value object validado.

## T3 — Implementar compilación segura de regex
Con semántica de full match.

## T4 — Implementar validación de configuración de target
Regex, example y case sensitivity.

## T5 — Implementar `TargetValidator`
Presencia, longitud y match.

## T6 — Incorporar errores
`TARGET_REGEX_INVALID`, `TARGET_EXAMPLE_INVALID`, `TARGET_INVALID`, `TARGET_TOO_LONG`.

## T7 — Integrar con configuración E1-S0
El validador consume `ResolvedProjectConfig`.

## T8 — Tests unitarios parametrizados
Familias A/B/C y boundaries.

## T9 — Test de no inferencia
Demostrar que el resultado depende sólo de candidato + policy.

## T10 — Documentar mensajes esperados
Incluir ejemplos para usuario final.

---

# 11. Verificación

La spec está completa cuando:

- no existen regex de target hardcodeadas por proyecto en el core;
- el mismo validador soporta múltiples convenciones;
- toda creación normal de `Target` pasa por validación;
- full-match está cubierto por tests;
- los errores son deterministas;
- no existe inferencia desde Git ni estado previo.

Los comandos exactos de test/lint se definirán conforme al toolchain Python formalmente adoptado.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R2 | 7.1, 7.5 | T1, T3, T4 | AC-03,04 |
| R3-R6 | 7.2, 7.6 | T3-T5 | AC-01,02,05,06 |
| R7 | 7.1, 7.4 | T2, T5 | AC-01 |
| R8 | 7.6 | T6, T10 | AC-07 |
| R9-R10 | 7.3 | T5, T7, T9 | AC-09,10 |
| R11 | 7.1 | T8 | AC-09 |
| R12 | 7.2 | T5, T6 | AC-08 |

---

# 13. Resultado esperado

Después de E1-S1, `imass-worktree` debe poder responder de forma uniforme:

```text
¿Este target pertenece a la convención declarada por este proyecto?
```

sin imponer una convención empresarial universal y sin consultar estado externo para intentar adivinar la intención del usuario.
