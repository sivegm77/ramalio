# E9-S0 — Segundo proyecto piloto

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E9 — Estandarización y adopción en iMass
- **Spec:** E9-S0
- **Nombre:** Segundo proyecto piloto
- **Dependencias:** E8-S0, E8-S1, E8-S2
- **Bloquea a:** E9-S1, E9-S2
- **Estado inicial:** Planificada

---

## 2. Contexto

SiVale es el primer proyecto cliente real de `imass-worktree`, pero no basta para demostrar que el producto es genérico. La Etapa 9 debe validar explícitamente que el core no quedó contaminado por supuestos de SiVale, Laravel, Docker, Kiro, tmux o cualquier combinación particular del piloto inicial.

Esta spec adopta `imass-worktree` en un segundo proyecto con características materialmente distintas a SiVale y utiliza esa adopción como prueba de desacoplamiento del estándar.

El objetivo no es agregar features por conveniencia del segundo proyecto. Si aparece una necesidad nueva debe clasificarse deliberadamente como:

```text
core universal
configuración del proyecto cliente
capability opcional
integration opcional
fuera de alcance de imass-worktree
```

---

## 3. Objetivo

Demostrar que un proyecto diferente a SiVale puede adoptar `imass-worktree` principalmente mediante configuración, documentación y capabilities/integrations ya soportadas, sin modificar el core para incorporar reglas particulares del nuevo repositorio.

La validación debe detectar y eliminar acoplamientos ocultos antes de declarar el producto estándar interno.

---

## 4. Alcance

### 4.1 Incluido

- Selección de un segundo proyecto con perfil distinto a SiVale.
- Inventario de su lifecycle actual.
- Creación de `.imass-worktree.toml` para el piloto.
- Mapeo de target, branch, worktree, bootstrap y recursos aplicables.
- Uso de capabilities e integrations únicamente cuando correspondan.
- Pruebas de `init`, `adopt`, `list`, `status`, `doctor`, `start`, `stop` y `destroy`.
- Validación de múltiples workspaces simultáneos cuando el proyecto lo permita.
- Registro de gaps encontrados.
- Clasificación de cada gap según frontera arquitectónica.
- Corrección de acoplamientos universales descubiertos, si existen, mediante specs/changes explícitos y no mediante excepciones para el proyecto piloto.
- Matriz de conformidad del segundo proyecto.

### 4.2 Fuera de alcance

- Convertir el segundo proyecto en nueva fuente de reglas universales.
- Copiar scripts de SiVale.
- Agregar condiciones del tipo `if project == ...` en el core.
- Reescribir el stack del proyecto piloto.
- Imponer Docker, tmux, zrok o IA si el proyecto no los necesita.
- Definir todavía el mecanismo final de distribución empresarial — E9-S1.
- Definir todavía la guía definitiva de adopción — E9-S2.

---

## 5. Criterios para seleccionar el piloto

El proyecto seleccionado debe diferir de SiVale en varias dimensiones. Debe cumplir al menos tres de las siguientes condiciones:

- runtime distinto o ausencia de runtime containerizado;
- lenguaje/framework distinto;
- sin Kiro obligatorio;
- sin tmux obligatorio;
- sin puertos exclusivos;
- sin zrok/túneles;
- estructura de targets diferente;
- branch naming diferente;
- bootstrap diferente;
- proyecto CLI/worker/library en lugar de aplicación web;
- menor complejidad operativa.

Debe evitarse elegir un clon operativo de SiVale porque no probaría el desacoplamiento.

---

## 6. Invariantes

### INV-01 — Cero reglas por nombre de proyecto

El core no puede contener ramas condicionales basadas en identidad del piloto.

### INV-02 — Adopción por contrato

Las diferencias deben expresarse por `.imass-worktree.toml`, configuración personal, capabilities o integrations existentes.

### INV-03 — Misma CLI

El proyecto debe utilizar la misma superficie pública:

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

### INV-04 — No regresión SiVale

Cualquier corrección general derivada del segundo piloto debe mantener la conformidad del piloto SiVale.

### INV-05 — Gaps explícitos

Un comportamiento no soportado no puede resolverse silenciosamente con scripts ad hoc fuera del estándar y luego declararse éxito.

---

## 7. Requirements

### R1 — Selección documentada

Debe quedar registrado por qué el segundo proyecto constituye un perfil suficientemente distinto a SiVale.

### R2 — Inventario operativo

Antes de configurar `imass-worktree`, documentar como mínimo:

- formato de unidad de trabajo;
- branch base;
- naming de branches;
- ubicación actual/deseada de worktrees;
- bootstrap;
- procesos;
- runtime;
- puertos;
- herramientas de desarrollo;
- teardown;
- riesgos conocidos.

### R3 — Configuración cliente

El proyecto debe adoptar una `.imass-worktree.toml` válida sin requerir cambios específicos en el core.

### R4 — Target distinto

La validación debe incluir una convención de target diferente a la de SiVale cuando el proyecto lo permita.

### R5 — Lifecycle mínimo completo

Deben verificarse:

```text
init
adopt
list
status
doctor
start
stop
destroy
```

### R6 — Operación sin capabilities innecesarias

Si el proyecto no requiere una capability, ésta debe permanecer deshabilitada y el lifecycle debe seguir funcionando.

### R7 — Múltiples workspaces

Cuando Git y la naturaleza del proyecto lo permitan, validar al menos dos workspaces simultáneos y confirmar aislamiento de branch/path y de cualquier recurso configurado.

### R8 — Gap classification

Cada gap debe clasificarse como:

```text
CORE_GAP
CONFIG_GAP
CAPABILITY_GAP
INTEGRATION_GAP
PROJECT_LOCAL
OUT_OF_SCOPE
```

### R9 — Prohibición de workaround oculto

No se considera resuelto un gap mediante wrapper privado no documentado si ese wrapper es indispensable para operar el lifecycle.

### R10 — Conformidad

Debe existir una matriz PASS/FAIL que cubra los contratos relevantes de E0–E7.

### R11 — Regresión SiVale

Después de cualquier corrección general, ejecutar la suite/conformidad relevante del piloto SiVale y asegurar que no hay regresión.

### R12 — Resultado de piloto

El piloto sólo se considera PASS si el proyecto puede operar cotidianamente con `imass-wt` sin conocimiento especial embebido en el core.

---

## 8. Diseño de validación

### 8.1 Secuencia

```text
seleccionar proyecto
      ↓
inventariar lifecycle
      ↓
modelar configuración
      ↓
run doctor
      ↓
probar lifecycle
      ↓
probar paralelismo aplicable
      ↓
clasificar gaps
      ↓
corregir sólo mediante frontera correcta
      ↓
revalidar segundo piloto + SiVale
      ↓
matriz de conformidad
```

### 8.2 Matriz mínima

| Área | Evidencia esperada |
|---|---|
| Config | TOML válido y suficiente |
| Target | validación/normalización correcta |
| Git | branch/worktree deterministas |
| Lifecycle | init/adopt/destroy |
| Operación | list/status/start/stop |
| Diagnóstico | doctor |
| Extensibilidad | capabilities sólo si aplican |
| Seguridad | no pérdida de trabajo |
| Concurrencia | aislamiento cuando aplique |
| Core | sin reglas específicas del proyecto |

---

## 9. Criterios de aceptación

- **AC-01:** El proyecto seleccionado difiere materialmente de SiVale.
- **AC-02:** Puede cargar su configuración sin cambios específicos al core.
- **AC-03:** `doctor` identifica correctamente readiness y dependencias aplicables.
- **AC-04:** `init` crea un workspace correcto.
- **AC-05:** `adopt` incorpora trabajo compatible existente.
- **AC-06:** `list` y `status` reflejan realidad observable.
- **AC-07:** `start`/`stop` operan según capabilities realmente configuradas.
- **AC-08:** `destroy` conserva las garantías de seguridad.
- **AC-09:** Las capabilities no necesarias no se convierten en dependencias.
- **AC-10:** No existen condiciones del core basadas en nombre/stack del piloto.
- **AC-11:** Los gaps están clasificados y cerrados o explícitamente fuera de alcance.
- **AC-12:** SiVale conserva conformidad después de cualquier cambio general.

---

## 10. Tasks

1. Seleccionar y justificar el segundo proyecto piloto.
2. Levantar inventario del lifecycle actual.
3. Mapear requisitos a contratos de `imass-worktree`.
4. Crear `.imass-worktree.toml` del piloto.
5. Ejecutar `doctor` y cerrar errores de configuración.
6. Validar `init`.
7. Validar `adopt`.
8. Validar `list` y `status`.
9. Validar `start` y `stop`.
10. Validar `destroy`.
11. Validar workspaces simultáneos cuando aplique.
12. Documentar y clasificar gaps.
13. Corregir únicamente gaps universales autorizados.
14. Re-ejecutar conformidad del segundo piloto.
15. Re-ejecutar regresión de SiVale.
16. Emitir matriz final PASS/FAIL.

---

## 11. Verificación

La spec termina cuando el segundo proyecto opera mediante `imass-wt` sin scripts indispensables específicos fuera del contrato y sin introducir conocimiento del proyecto dentro del core.

---

## 12. Resultado esperado

Al cerrar E9-S0 existe evidencia real de que `imass-worktree` es reusable fuera de SiVale y que su separación entre core, configuración, capabilities e integrations funciona en más de un perfil de proyecto.
