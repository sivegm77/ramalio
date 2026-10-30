# E9-S2 — Estándar de adopción iMass

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E9 — Estandarización y adopción en iMass
- **Spec:** E9-S2
- **Nombre:** Estándar de adopción para nuevos proyectos
- **Dependencias:** E9-S0, E9-S1
- **Bloquea a:** Consolidación de imass-worktree como estándar interno
- **Estado inicial:** Planificada

---

## 2. Contexto

La herramienta sólo puede convertirse en estándar empresarial si un equipo nuevo puede adoptarla sin conocer la historia de SiVale, sin copiar scripts de otro repositorio y sin requerir intervención del equipo que creó el producto para cada proyecto.

Esta spec formaliza la documentación, plantilla, checklist y proceso de onboarding necesarios para que la adopción sea repetible.

---

## 3. Objetivo

Entregar un estándar de adopción que permita a un proyecto nuevo:

1. entender qué resuelve `imass-worktree`;
2. verificar prerrequisitos;
3. instalar el CLI;
4. crear su `.imass-worktree.toml`;
5. definir target/naming/lifecycle;
6. habilitar sólo capabilities necesarias;
7. validar con `doctor` y suite/checklist de conformidad;
8. migrar desde scripts existentes si aplica;
9. operar el lifecycle común;
10. saber cómo extender el estándar sin contaminar el core.

---

## 4. Alcance

### 4.1 Incluido

- Guía oficial de adopción.
- Plantilla mínima de `.imass-worktree.toml`.
- Plantillas/examples por perfiles de proyecto.
- Checklist de conformidad.
- Guía de migración desde scripts existentes.
- Catálogo inicial de capabilities/integrations soportadas.
- Troubleshooting.
- Proceso para proponer nuevas capabilities/integrations.
- Reglas de gobernanza de configuración.
- Política de secretos/configuración personal.
- Definición de soporte y compatibilidad.
- Validación de onboarding mediante un ejercicio reproducible.

### 4.2 Fuera de alcance

- Convertir `imass-worktree` en gestor de proyectos.
- Documentar stacks específicos como requisitos universales.
- Crear una mega-plantilla que active todas las capabilities.
- Automatizar CI/CD del proyecto cliente.
- Gestionar secretos del proyecto.
- Reemplazar documentación propia del proyecto cliente.

---

## 5. Principios e invariantes

### INV-01 — Configuración antes que forks

Adoptar un proyecto no debe requerir forkear/modificar el core.

### INV-02 — Plantilla mínima

La plantilla default debe contener sólo lo necesario para empezar y no activar capacidades opcionales por defecto.

### INV-03 — Misma experiencia CLI

La documentación debe enseñar el lifecycle común, no wrappers específicos.

### INV-04 — Secretos fuera del repo

La guía debe dejar explícito que tokens/credenciales no pertenecen al TOML versionado.

### INV-05 — Extensibilidad gobernada

Una necesidad nueva debe clasificarse antes de agregarse al producto.

---

## 6. Requirements

### R1 — Guía de adopción

Debe existir una guía oficial que cubra desde instalación hasta primer lifecycle exitoso.

### R2 — Prerrequisitos

La guía debe distinguir:

- requisitos universales;
- requisitos de capabilities habilitadas;
- requisitos propios del proyecto cliente.

### R3 — Plantilla mínima TOML

Debe incluir como mínimo conceptos equivalentes a:

```toml
[project]
name = "example"
base_branch = "main"

[target]
regex = "..."
example = "..."
case_sensitive = true

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "spec/{target}"
```

Los valores son ejemplo; la plantilla debe señalar claramente cuáles requieren decisión del proyecto.

### R4 — Capabilities opt-in

La plantilla mínima no debe habilitar tmux, runtime, zrok ni processes salvo en ejemplos específicos.

### R5 — Perfiles de ejemplo

Debe haber ejemplos para al menos:

1. proyecto Git-only;
2. aplicación con runtime/procesos;
3. proyecto CLI/Python sin Docker.

### R6 — Checklist de adopción

Debe cubrir:

- config válida;
- target/naming;
- paths;
- branch base;
- doctor;
- init;
- adopt;
- start/stop;
- destroy seguro;
- múltiples workspaces cuando aplique;
- capabilities habilitadas;
- secretos fuera del TOML.

### R7 — Definition of adopted

Un proyecto sólo se considera adoptado cuando puede operar el lifecycle acordado sin depender de scripts legacy indispensables para las mismas funciones.

### R8 — Migración desde scripts

La guía debe explicar cómo inventariar scripts existentes y clasificarlos en:

```text
reemplazado por core
configuración cliente
capability
integration
se mantiene fuera de alcance
```

### R9 — Retiro gradual

No se debe retirar un script anterior hasta validar paridad de invariantes relevantes.

### R10 — Doctor como gate

`imass-wt doctor` debe formar parte explícita del proceso de onboarding y troubleshooting.

### R11 — Troubleshooting

Debe cubrir al menos:

- no repo;
- TOML ausente/inválido;
- target inválido;
- base branch ausente;
- branch/worktree collision;
- dirty destroy block;
- capability dependency missing;
- config/version incompatibility.

### R12 — Config personal

Debe documentarse dónde termina la configuración compartida y dónde comienza la configuración personal.

### R13 — Secretos

Debe haber una regla explícita:

```text
No secrets in .imass-worktree.toml
```

### R14 — Catálogo de capabilities

Debe existir un catálogo inicial con:

- nombre;
- propósito;
- lifecycle en el que participa;
- dependencias;
- configuración;
- comportamiento de doctor/status;
- cleanup.

### R15 — Catálogo de integrations

Debe documentar herramientas soportadas para `--open` y su carácter opcional.

### R16 — Nueva capability/integration

La documentación debe definir un proceso de propuesta que responda:

- ¿es universal?
- ¿es config?
- ¿es capability?
- ¿es integration?
- ¿es responsabilidad del proyecto cliente?

### R17 — Compatibilidad

La guía debe enlazar/explicar política de versiones y config schema de E9-S1.

### R18 — Soporte

Debe definirse qué se considera:

- bug del core;
- configuración inválida del proyecto;
- dependencia externa ausente;
- feature request.

### R19 — Onboarding reproducible

Una persona que no haya participado en el desarrollo debe poder seguir la guía sobre un fixture/proyecto piloto y completar el checklist sin conocimiento tribal.

### R20 — Documentación orientada a operación

Debe priorizar comandos, decisiones y troubleshooting; evitar documentación ornamental o duplicada.

---

## 7. Diseño de la documentación

Estructura sugerida:

```text
docs/
├── getting-started.md
├── configuration.md
├── lifecycle.md
├── capabilities.md
├── integrations.md
├── adoption-guide.md
├── migration-from-scripts.md
├── troubleshooting.md
└── versioning-and-compatibility.md
```

La estructura concreta puede adaptarse, evitando duplicación.

---

## 8. Flujo de adopción oficial

```text
instalar imass-wt
      ↓
inventariar proyecto
      ↓
definir target + naming
      ↓
crear .imass-worktree.toml
      ↓
habilitar sólo capabilities necesarias
      ↓
imass-wt doctor
      ↓
probar init/adopt
      ↓
probar list/status
      ↓
probar stop/start
      ↓
probar destroy
      ↓
validar paralelismo cuando aplique
      ↓
retirar wrappers reemplazados
      ↓
marcar proyecto como adoptado
```

---

## 9. Criterios de aceptación

- **AC-01:** Existe una guía completa de adopción.
- **AC-02:** Existe plantilla mínima de TOML sin capabilities obligatorias.
- **AC-03:** Existen al menos tres perfiles de ejemplo.
- **AC-04:** Existe checklist de conformidad.
- **AC-05:** Existe guía de migración desde scripts.
- **AC-06:** Existe troubleshooting de fallos principales.
- **AC-07:** Secretos/config personal están claramente separados.
- **AC-08:** Existen catálogos de capabilities e integrations soportadas.
- **AC-09:** El proceso para proponer extensiones preserva las fronteras arquitectónicas.
- **AC-10:** Un desarrollador ajeno al desarrollo puede completar onboarding siguiendo sólo la documentación.
- **AC-11:** El proyecto adoptado no necesita copiar el motor ni scripts de SiVale.
- **AC-12:** La documentación refleja la política de versionado/compatibilidad vigente.

---

## 10. Tasks

1. Redactar getting started.
2. Consolidar referencia de configuración.
3. Documentar lifecycle común.
4. Crear plantilla mínima TOML.
5. Crear ejemplo Git-only.
6. Crear ejemplo con runtime/procesos.
7. Crear ejemplo CLI/Python.
8. Crear checklist de adopción/conformidad.
9. Redactar guía de migración desde scripts.
10. Documentar capabilities soportadas.
11. Documentar integrations soportadas.
12. Redactar troubleshooting.
13. Documentar configuración personal y secretos.
14. Documentar versionado/compatibilidad.
15. Definir proceso para nuevas capabilities/integrations.
16. Definir categorías de soporte.
17. Ejecutar onboarding de prueba con una persona/proceso ajeno al desarrollo.
18. Corregir ambigüedades detectadas.
19. Validar que la documentación no dependa de conocimiento de SiVale.
20. Declarar criterios de proyecto adoptado.

---

## 11. Verificación

La spec se considera cerrada cuando un proyecto nuevo puede adoptar el estándar principalmente mediante instalación, configuración y documentación, sin copiar scripts de otro repositorio ni modificar el core.

---

## 12. Cierre de Etapa 9

Con E9-S0, E9-S1 y E9-S2 completadas, `imass-worktree` puede considerarse preparado para consolidarse como estándar interno de iMass:

```text
producto reusable
+
distribución oficial
+
configuración por proyecto
+
capabilities/integrations opcionales
+
proceso de adopción repetible
```

El criterio principal sigue siendo el definido desde la visión: una interfaz común para administrar workspaces aislados mientras cada proyecto conserva sus propias reglas sin contaminar el core.
