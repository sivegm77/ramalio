# Plan Macro de Desarrollo — ramalio

## 1. Propósito

Este documento define el **eje rector de desarrollo de ramalio**.

Su función es establecer el orden macro de construcción del producto, las dependencias entre etapas, los resultados esperados y las condiciones que deben cumplirse antes de avanzar.

No sustituye las especificaciones detalladas de cada etapa ni pretende fijar todavía la arquitectura interna o decisiones tecnológicas finas. Cada etapa deberá desglosarse posteriormente en unidades de trabajo implementables.

La visión que gobierna este plan es:

> **ramalio será una forma estándar, reusable y configurable de crear, adoptar, operar, suspender, reanudar y retirar espacios de trabajo aislados basados en Git worktrees, sin quedar amarrada a un framework, runtime, herramienta de IA o infraestructura específica.**

---

## 2. Principios rectores del plan

Todas las etapas deberán respetar estos principios.

### 2.1 Core genérico
El producto base no dependerá obligatoriamente de Laravel, PHP, Python, Node, Docker, Kiro, Codex, Claude, VS Code, tmux, zrok u otra herramienta específica.

### 2.2 Proyecto cliente configurable
Cada repositorio compatible declarará sus particularidades mediante configuración versionable, prevista inicialmente como `.ramalio.toml`.

### 2.3 Interfaz común
La experiencia del desarrollador deberá mantenerse consistente entre proyectos:

```bash
ramalio init <target>
ramalio adopt <target>
ramalio destroy <target>
ramalio list
ramalio status <target>
ramalio doctor
ramalio start <target>
ramalio stop <target>
```

También se contemplarán integraciones opcionales, por ejemplo `ramalio init TASK-123 --open kiro`.

### 2.4 Seguridad antes que conveniencia
Las automatizaciones que puedan eliminar worktrees, branches, procesos o recursos deberán operar de forma conservadora y explícita.

### 2.5 Estado observable
La automatización no debe convertir el entorno en una caja negra. El usuario debe poder conocer qué existe, qué está activo y qué recursos pertenecen a cada target.

### 2.6 Extensibilidad deliberada
Capacidades nuevas deberán incorporarse sin obligar a modificar el core para cada herramienta concreta.

### 2.7 Configuración compartida y personal separadas
Las reglas comunes pertenecen al proyecto cliente. Preferencias personales, rutas locales, tokens y secretos pertenecen al entorno del desarrollador.

### 2.8 Proyecto declara; producto ejecuta responsabilidades reutilizables
Cuando una necesidad pertenece al lifecycle reusable del workspace, el proyecto la declara y `ramalio` la ejecuta mediante contratos/capabilities soportados. No se devuelve esa responsabilidad al cliente como scripts propios de worktree.

---

# 3. Vista general de etapas

```text
ETAPA 0  Definición del estándar operativo
   ↓
ETAPA 1  Contrato del proyecto cliente y targets
   ↓
ETAPA 2  Lifecycle fundamental de worktrees
   ↓
ETAPA 3  Control operativo y reanudación
   ↓
ETAPA 4  Modelo de capacidades y procesos
   ↓
ETAPA 5  Integraciones de experiencia de desarrollo
   ↓
ETAPA 6  Runtimes, exposición y recursos opcionales
   ↓
ETAPA 7  Robustez, recuperación y conformidad
   ↓
ETAPA 8  Piloto real sobre SiVale
   ↓
ETAPA 9  Estandarización y adopción en iMass
   ↓
ETAPA 10 Convergencia de workspace provisioning
```

El orden es intencional. No se construyen primero integraciones concretas para después extraer un core. E10 tampoco redefine E0–E9: corrige una brecha descubierta al contrastar el resultado de E8 con el lifecycle real que E8 debía reemplazar.

---

# 4. ETAPA 0 — Definición del estándar operativo

## Objetivo
Convertir la visión del producto en un **contrato operativo suficientemente preciso** para que la implementación posterior no dependa de decisiones improvisadas.

Esta etapa responde: **¿Qué significa para iMass administrar correctamente un workspace de desarrollo?**

## Alcance
Definir conceptualmente workspace administrado, target, proyecto cliente, worktree, branch asociada, estado, recursos, lifecycle, creación, adopción, suspensión, reanudación, destrucción, configuración compartida/personal, capacidad opcional, integración, fallo y recuperación.

## Entregables
- estándar de lifecycle;
- glosario oficial;
- contrato funcional de comandos;
- reglas generales de seguridad;
- estados conceptuales;
- casos fuera de alcance.

## Criterio de salida
Puede describirse, sin hablar de un proyecto concreto, qué ocurre desde `init` hasta un `destroy` seguro.

---

# 5. ETAPA 1 — Contrato del proyecto cliente y targets

## Objetivo
Definir cómo un repositorio adopta `ramalio` sin modificar el producto base.

## Alcance
Definir identidad del proyecto, base branch, ubicación de worktrees, naming de branches, target/regex/example/case sensitivity/normalización, capabilities habilitadas, recursos requeridos, bootstrap del proyecto y comportamiento general de start/stop.

La ruta del repositorio debe derivarse del contexto y no de variables específicas como `KIRO_PROJECT_ROOT`.

## Normalización
Debe poder expresar trim, espacios a guiones, collapse de guiones, normalización del slug, preservación de segmentos y validación final por regex.

## Entregables
- contrato TOML;
- precedencia de config;
- target/normalización;
- mensajes de validación;
- ejemplos de varios tipos de proyecto.

## Criterio de salida
Dos proyectos con convenciones distintas pueden describirse sin cambios al core.

---

# 6. ETAPA 2 — Lifecycle fundamental de worktrees

## Objetivo
Construir el núcleo mínimo útil: `init`, `adopt`, `destroy`.

## Invariantes mínimos
- identidad determinista;
- no sobrescritura accidental;
- no pérdida silenciosa;
- fallos parciales diagnosticables;
- resultados claros;
- comportamiento repetible;
- respeto a reglas del proyecto.

## Entregables
`init`, `adopt`, `destroy`, errores, rollback básico y pruebas del lifecycle fundamental.

## Criterio de salida
Un proyecto sin capabilities opcionales puede operar:

```text
crear → trabajar → destruir
trabajo preexistente → adoptar → continuar → destruir
```

## Hito
Primer núcleo utilizable.

---

# 7. ETAPA 3 — Control operativo y reanudación

## Objetivo
Pasar a un gestor observable de workspaces.

## Alcance
Implementar `list`, `status`, `doctor`, `start`, `stop`; definir estado administrativo mínimo y derivar de autoridades externas todo lo que no deba persistirse.

## Entregables
Los cinco comandos, modelo de estado y detección de inconsistencias.

## Criterio de salida
El desarrollador sabe qué existe, qué está activo/detenido, qué target corresponde a cada worktree y qué puede reanudarse/destruirse.

## Hito
MVP operativo.

---

# 8. ETAPA 4 — Modelo de capacidades y procesos

## Objetivo
Permitir comportamiento adicional sin acoplar el core a herramientas concretas.

## Alcance
Capability contract, registry, hooks y procesos asociados a target.

Eventos base:

```text
before_init
after_init
before_start
after_start
before_stop
after_stop
before_destroy
after_destroy
```

## Reglas
- optional sigue optional;
- cada capability declara lifecycle;
- status/doctor la observan;
- stop/destroy limpian de forma controlada;
- fallos tienen semántica explícita;
- procesos pertenecen a un target.

## Criterio de salida
Una capability de prueba se añade sin ramificar la lógica central por herramienta.

---

# 9. ETAPA 5 — Integraciones de experiencia de desarrollo

## Objetivo
Conectar tmux y herramientas de trabajo al lifecycle estabilizado.

## Alcance
Tmux por target y mecanismo genérico `--open` para Kiro, VS Code, Codex, Claude u otras integraciones.

## Criterio de salida
Un proyecto puede habilitar tmux/herramientas sin afectar proyectos que no las usan.

---

# 10. ETAPA 6 — Runtimes, exposición y recursos opcionales

## Objetivo
Asociar recursos externos al target sin hacerlos universales.

## Alcance
- runtime contract con `none` como base;
- primer driver Docker Compose;
- puertos por target;
- túneles/proveedores como zrok;
- identidad y cleanup conservador.

## Reglas
Docker no es obligatorio, los recursos tienen ownership por target y el core no incorpora reglas del primer piloto.

## Criterio de salida
Un proyecto puede usar runtime/puertos/túnel por configuración y otro proyecto puede no usar ninguno.

---

# 11. ETAPA 7 — Robustez, recuperación y conformidad

## Objetivo
Hacer confiable el lifecycle ante fallos parciales, concurrencia, paths inseguros y procesos externos.

## Alcance
Transacciones/rollback, locks por recurso, boundaries symlink-aware, ejecución segura, ownership y suite de conformidad multi-perfil.

## Criterio de salida
Fallos, rollback y concurrencia quedan cubiertos sistemáticamente sin introducir conocimiento de proyecto.

---

# 12. ETAPA 8 — Piloto real sobre SiVale

## Objetivo
Validar el estándar contra un proyecto real complejo sin convertirlo en el core.

## Alcance
- configuración SiVale;
- paridad con lifecycle existente;
- migración operativa sólo cuando no quede responsabilidad exclusiva en el harness legacy.

## Criterio de salida original
SiVale puede operar su lifecycle cotidiano mediante `ramalio` sin conocimiento específico embebido en el core.

## Estado post-auditoría
La implementación histórica de E8 está mergeada, pero la auditoría posterior detectó un **provisioning parity gap**: la evidencia existente no demuestra todavía toda la preparación que el harness legacy realiza antes de considerar el workspace listo.

E8-S1 y E8-S2 conservan su historia, pero su cierre operacional queda bloqueado hasta E10-S4.

---

# 13. ETAPA 9 — Estandarización y adopción en iMass

## Objetivo
Pasar de una herramienta validada a un estándar interno adoptable por otros equipos.

## Alcance
Instalación/upgrade, versionado, guía de adopción, plantilla TOML, onboarding, compatibilidad, proceso para capabilities, troubleshooting, soporte y gobernanza.

## Validación multi-proyecto
Antes de consolidar el estándar debe existir evidencia de proyectos con perfiles distintos. El fixture sintético `pylib-tools` no sustituye la adopción de un segundo proyecto real de iMass.

## Entregables
Distribución, documentación oficial, plantilla, migración desde scripts, política de versiones, catálogo de capabilities y pilotos.

## Criterio de salida
Un proyecto nuevo adopta principalmente mediante instalación, configuración y documentación, sin copiar scripts de otro repositorio ni modificar el core.

---

# 14. Dependencias y paralelización

Camino histórico:

```text
E0 → E1 → E2 → E3 → E4 → E7 → E8 → E9
```

E5/E6 pudieron desarrollarse en paralelo después de E4 y converger antes de E7.

Con la brecha post-auditoría, la convergencia adicional es:

```text
E9-S3
  ↓
E10-S0
  ├──→ E10-S1 ───→ E10-S3 ─┐
  └──→ E10-S2 ──────────────┼→ E10-S4
                             ┘
```

**DAG normativo E10:**
- S0 depende de E9-S3 cerrado.
- S1 y S2 dependen de S0 y pueden implementarse en paralelo.
- S3 depende de S0 y S1 porque utiliza el runtime execution contract.
- S4 depende de S1, S2 y S3.

---

# 15. Hitos principales

## HITO A — Contrato definido
Después de E1: sabemos qué promete el producto y cómo un proyecto declara sus reglas.

## HITO B — Core utilizable
Después de E2: `init + adopt + destroy`.

## HITO C — MVP operativo
Después de E3: lifecycle + `list/status/doctor/start/stop`.

## HITO D — Plataforma extensible
Después de E4: capabilities sin redefinir el lifecycle.

## HITO E — Experiencia completa
Después de E5/E6: tmux, herramientas, procesos, runtime, puertos y túneles según configuración.

## HITO F — Producto confiable
Después de E7: fallos, recuperación y conformidad cubiertos.

## HITO G — Referencia real
E8 estableció SiVale como referencia; su paridad operacional definitiva se revalida en E10-S4.

## HITO H — Estándar empresarial
Después de E9: adopción repetible y distribución/documentación.

## HITO I — Provisioning convergido
Después de E10: el producto puede preparar un workspace complejo sin scripts de lifecycle en el cliente ni branching por framework/proyecto.

---

# 16. Qué no debe ocurrir durante el desarrollo

### 16.1 No convertir SiVale en el core
Los requisitos de SiVale se clasifican como universal, configuración, capability/provider o particularidad fuera del producto.

### 16.2 No construir primero alrededor de Kiro
Kiro es integration, no identidad del producto.

### 16.3 No hacer Docker obligatorio
Un proyecto sin contenedores debe seguir funcionando.

### 16.4 No hacer tmux obligatorio
Capability opcional.

### 16.5 No hacer zrok obligatorio
Proveedor opcional.

### 16.6 No usar TOML para secretos
Nunca almacenar credenciales/tokens en configuración compartida.

### 16.7 No agregar capacidades sin lifecycle
Toda capability debe definir dónde participa en init/adopt/start/status/stop/destroy cuando aplique.

### 16.8 No avanzar por features aisladas
Las specs materializan este plan; si una necesidad cambia el plan, se modifica primero este documento.

### 16.9 No resolver provisioning con scripts de lifecycle del cliente
El cliente declara necesidades. El producto implementa capacidades reutilizables.

### 16.10 No detectar frameworks para decidir comportamiento
No `framework = laravel`, no branches por `project.name` dentro del core.

### 16.11 No crear infraestructura paralela
E10 reutiliza `CapabilityRegistry`, `HookRunner`, `LifecycleTransaction`, locks, path boundaries y `SafeProcessRunner`.

---

# 17. Regla para descomponer las etapas

Una spec sólo existe con objetivo concreto, alcance, dependencia, criterios de aceptación y relación explícita con el Plan Macro.

Las specs no redefinen la visión. Si una necesidad altera el plan, primero se actualiza deliberadamente el plan y después se generan las specs.

---

# 18. Definición de producto consolidado

`ramalio` podrá considerarse consolidado cuando:

1. lifecycle fundamental seguro y reproducible;
2. proyectos declaran reglas sin modificar core;
3. targets/normalización configurables;
4. ocho comandos públicos coherentes;
5. capabilities con contratos estables;
6. tmux opcional;
7. integrations opcionales;
8. Docker Compose opcional;
9. túneles opcionales por target;
10. procesos adicionales administrables;
11. fallos parciales diagnosticables/recuperables;
12. SiVale funciona sin contaminar el core;
13. otros proyectos distintos pueden adoptar el estándar;
14. distribución/documentación internas adecuadas;
15. provisioning reusable puede dejar listo un workspace complejo sin scripts de lifecycle obligatorios en el cliente.

---

# 19. Resultado esperado

```text
entrar al proyecto
      ↓
identificar target
      ↓
ramalio init <target>
      ↓
workspace listo conforme a capabilities declaradas
      ↓
trabajar
      ↓
ramalio stop / start
      ↓
ramalio destroy <target>
```

Las diferencias entre proyectos se expresan mediante configuración/capabilities. La experiencia fundamental permanece estable.

---

# 20. Declaración rectora

> **El desarrollo de ramalio avanzará desde un lifecycle genérico y seguro hacia capacidades opcionales y adopción empresarial, nunca al revés.**
>
> **Cada nueva funcionalidad deberá justificar si pertenece al core, a la configuración del proyecto cliente o a una capability/provider/integration opcional.**
>
> **Este Plan Macro será el eje rector para ordenar etapas, dependencias y futuras especificaciones.**

---

# 21. ETAPA 10 — Convergencia de workspace provisioning

## Objetivo
Cerrar el gap detectado al revisar E8: permitir que un proyecto que necesita preparación adicional del workspace la exprese mediante configuración y capacidades reutilizables, sin scripts de lifecycle propios y sin conocimiento de framework/proyecto en el core.

## Alcance exacto
- contrato de provisioning sobre hooks existentes;
- `after_adopt` como único evento nuevo requerido por E10-S0;
- runtime provisioning y runtime execution contract para providers;
- bootstrap Composer + readiness genérico requeridos por SiVale;
- data provisioning PostgreSQL requerido por SiVale;
- revalidación completa de paridad SiVale.

## Fuera de alcance
- nuevos comandos;
- workflow engine/DAG genérico;
- plugin discovery dinámico;
- nuevos runtimes o motores de DB/package managers sin caso real;
- CI/CD, deploy, business bootstrap;
- scripts arbitrarios como sustituto de capabilities.

## Specs
```text
E10-S0  contrato provisioning workspace
E10-S1  runtime provisioning lifecycle
E10-S2  bootstrap Composer y readiness
E10-S3  data provisioning PostgreSQL
E10-S4  convergencia de paridad SiVale
```

## Criterio de salida
E10 termina cuando E10-S4 demuestra paridad soportada, Git-only no regresa, no hay coupling SiVale/Laravel y E8-S1/E8-S2 pueden cerrar su evidencia operacional.
