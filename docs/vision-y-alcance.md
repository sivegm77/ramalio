# Documento de Visión y Alcance — ramalio

## 1. Propósito del documento

Este documento define la visión y el alcance de **ramalio** antes de tomar decisiones de arquitectura, tecnologías o implementación.

Su objetivo es responder con claridad a dos preguntas:

1. **¿Qué estamos construyendo?**
2. **¿Qué problema resuelve?**

Este documento describe el producto desde la perspectiva de operación y valor para los equipos de desarrollo que lo adoptan.

## 2. Visión

**ramalio** será una herramienta estándar de desarrollo para crear, adoptar, operar y retirar espacios de trabajo aislados basados en Git worktrees.

Su propósito es permitir que un desarrollador —humano o asistido por IA— pueda trabajar en múltiples cambios de un mismo repositorio de manera simultánea, ordenada, repetible y segura, sin depender de configuraciones manuales específicas de cada proyecto.

La herramienta debe convertirse en una forma común de trabajar en cualquier equipo de desarrollo, independientemente de:

- lenguaje de programación;
- framework;
- herramienta de IA;
- editor o IDE;
- uso o no de Docker;
- uso o no de procesos auxiliares;
- infraestructura específica del proyecto.

Cada proyecto podrá declarar sus propias reglas operativas, mientras que el comportamiento general del ciclo de vida será consistente en todos los proyectos.

## 3. Problema que queremos resolver

Actualmente, trabajar con múltiples ramas y múltiples sesiones de desarrollo en paralelo puede requerir una combinación de:

- comandos Git manuales;
- creación y eliminación manual de worktrees;
- convenciones de nombres recordadas por cada desarrollador;
- configuración de puertos;
- preparación de variables de entorno;
- levantamiento y apagado de servicios;
- manejo de sesiones persistentes;
- ejecución de procesos auxiliares;
- apertura de herramientas de desarrollo o agentes de IA;
- limpieza posterior del entorno.

En algunos proyectos estas tareas terminan resueltas mediante scripts Bash específicos del repositorio.

Esto funciona, pero genera varios problemas.

### 3.1 Acoplamiento al proyecto

Los scripts terminan incorporando conocimiento particular de rutas, estructura del repositorio, nombres de branches, rangos de puertos, runtimes, herramientas, bootstrap y convenciones internas.

El resultado no se puede reutilizar fácilmente en otros proyectos.

### 3.2 Operación inconsistente

Cada repositorio puede terminar resolviendo de forma distinta cómo crear un worktree, dónde colocarlo, cómo nombrarlo, cómo levantarlo, cómo detenerlo, cómo destruirlo y cómo recuperar un trabajo existente.

Esto obliga al desarrollador a aprender procedimientos diferentes por proyecto.

### 3.3 Mayor riesgo operativo

Los pasos manuales pueden provocar trabajo en la branch equivocada, ejecución de procesos en el checkout incorrecto, colisiones de puertos, servicios compartidos involuntariamente, entornos contaminados, worktrees abandonados, procesos huérfanos o destrucción accidental de trabajo todavía útil.

### 3.4 Dificultad para trabajar con varias IAs o tareas simultáneas

Cuando un desarrollador ejecuta varias sesiones de IA sobre el mismo repositorio, cada tarea necesita un espacio independiente.

Sin un estándar, el aislamiento depende demasiado de disciplina manual, especialmente cuando cada espacio necesita además su propio runtime, puerto, procesos, sesión persistente o acceso externo temporal.

### 3.5 Conocimiento operativo duplicado

Los mismos conceptos se vuelven a implementar en distintos repositorios: creación de worktrees, validación de nombres, rollback, selección de puertos, bootstrap, start/stop y teardown.

Ese conocimiento debería existir una sola vez como capacidad común y reutilizable.

## 4. Qué estamos construyendo

Estamos construyendo un **gestor de espacios de trabajo de desarrollo basado en Git worktrees**.

La herramienta proporcionará un ciclo de vida común para administrar una unidad de trabajo identificada por un `target`.

Ejemplos de targets:

```text
E7-S8-convergencia-schema-tests
FEATURE-123-login
BUG-482-stripe-webhook
TASK-15-retries
```

El formato permitido será definido por cada proyecto.

El desarrollador interactuará con una interfaz común:

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

La herramienta podrá además integrar capacidades opcionales, por ejemplo:

```bash
ramalio init TASK-123 --open kiro
```

Estas integraciones serán complementarias. El producto no dependerá de ellas para cumplir su función principal.

## 5. Propuesta de valor

> **Una sola forma de crear y operar entornos de trabajo aislados para cualquier proyecto, dejando que cada repositorio declare sus particularidades sin reimplementar el lifecycle.**

El desarrollador debería poder cambiar de proyecto y conservar el mismo modelo mental:

```text
crear → trabajar → detener/reanudar → destruir
```

El proyecto define sus reglas. La herramienta ejecuta esas reglas de forma consistente.

## 6. Usuarios objetivo

### 6.1 Desarrolladores
Personas que trabajan en uno o varios cambios simultáneos dentro de un repositorio.

### 6.2 Desarrolladores asistidos por IA
Personas que utilizan Kiro, Codex, Claude u otras herramientas y necesitan aislar cada tarea o agente en su propio workspace.

### 6.3 Equipos técnicos
Equipos que quieren adoptar una convención uniforme para operar branches y worktrees.

### 6.4 Responsables técnicos
Personas que necesitan establecer reglas comunes sin imponer a todos los proyectos el mismo stack tecnológico.

## 7. Principios del producto

### 7.1 El proyecto cliente define sus particularidades
Cada repositorio podrá declarar su configuración mediante un archivo versionado, por ejemplo:

```text
.ramalio.toml
```

La herramienta no debe contener reglas específicas de SiVale, Laravel u otro proyecto concreto.

### 7.2 El core debe ser agnóstico
El funcionamiento base no dependerá de Laravel, PHP, Python, Node, Docker, Kiro, VS Code, Codex, Claude, tmux o zrok.

Estas tecnologías podrán integrarse cuando un proyecto las necesite.

### 7.3 Convención por proyecto, interfaz común para todos los proyectos
Cada proyecto podrá definir formato del target, normalización, naming de branch, ubicación de worktrees, requisitos de bootstrap/provisioning, recursos y procesos adicionales.

El desarrollador seguirá utilizando los mismos comandos.

### 7.4 Automatizar sin ocultar el estado
La herramienta debe reducir pasos manuales, pero el usuario debe poder conocer claramente qué worktrees existen, qué branch utiliza cada uno, qué recursos están asociados y si el espacio puede destruirse con seguridad.

### 7.5 Destrucción segura
`destroy` no debe significar simplemente “borrar”. Debe representar un cierre controlado de la unidad de trabajo y sus recursos asociados.

### 7.6 Extensibilidad
Nuevas capacidades deben poder incorporarse sin convertirlas en requisitos universales.

Ejemplos: tmux, Docker Compose, zrok, cloudflared, queue workers, frontend dev servers, Kiro, Codex o VS Code.

### 7.7 Configuración portable y configuración personal separadas
Las reglas compartidas del proyecto deben poder versionarse. Las configuraciones personales, secretos, tokens o rutas específicas del desarrollador deben permanecer fuera del repositorio.

### 7.8 Proyecto declara; producto ejecuta el lifecycle reusable
El proyecto cliente declara **qué** necesita su workspace. Cuando una preparación es parte reutilizable del lifecycle del workspace, `ramalio` debe ejecutarla mediante capabilities/providers soportados; el proyecto no debe verse obligado a reimplementar `init/adopt/destroy` en scripts propios.

Esta regla no mueve a `ramalio` el build de release, deploy ni lógica de negocio del proyecto.

## 8. Alcance funcional inicial

### 8.1 Crear un workspace administrado

```bash
ramalio init <target>
```

Debe permitir iniciar una nueva unidad de trabajo a partir de las reglas del proyecto. El resultado esperado es un workspace aislado y listo para trabajar.

Cuando el proyecto declara provisioning soportado, “listo para trabajar” incluye completar ese provisioning antes de reportar éxito.

### 8.2 Adoptar trabajo existente

```bash
ramalio adopt <target>
```

Debe permitir incorporar al modelo administrado un trabajo que ya existe pero que todavía no fue creado mediante `ramalio`.

Cuando el proyecto declara provisioning soportado, `adopt` debe completar lo que falte sin destruir ni reemplazar el trabajo preexistente.

### 8.3 Destruir un workspace

```bash
ramalio destroy <target>
```

Debe cerrar y retirar de manera controlada el workspace y los recursos administrados asociados. La destrucción debe proteger contra pérdida accidental de trabajo.

### 8.4 Listar workspaces

```bash
ramalio list
```

Debe proporcionar una vista rápida de los workspaces administrados del proyecto.

### 8.5 Consultar estado

```bash
ramalio status <target>
```

Debe responder en qué estado se encuentra la unidad de trabajo, incluyendo cuando aplique worktree, branch, estado Git, recursos, procesos y capacidades asociadas.

### 8.6 Diagnosticar el entorno

```bash
ramalio doctor
```

Debe verificar si el proyecto y la máquina tienen las condiciones necesarias para utilizar las capacidades configuradas.

### 8.7 Iniciar recursos de un workspace existente

```bash
ramalio start <target>
```

Debe permitir reactivar los recursos y procesos asociados sin recrear el worktree.

### 8.8 Detener recursos sin destruir el workspace

```bash
ramalio stop <target>
```

Debe permitir liberar recursos temporalmente conservando worktree, branch, trabajo local e identidad del target.

### 8.9 Abrir una herramienta asociada

La herramienta podrá permitir acciones como:

```bash
ramalio init TASK-123 --open kiro
```

La apertura de herramientas será opcional y configurable.

## 9. Targets y convenciones por proyecto

Cada proyecto podrá establecer qué constituye un target válido.

Por ejemplo, SiVale puede utilizar:

```text
E7-S8-convergencia-schema-tests
```

mientras otro proyecto puede utilizar:

```text
FEATURE-123-login
```

La herramienta no impondrá una convención universal.

El proyecto podrá definir expresión regular aceptada, ejemplo, sensibilidad a mayúsculas/minúsculas y reglas de normalización.

La normalización podrá permitir convertir entradas razonables a la convención canónica del proyecto antes de validarlas, por ejemplo eliminando espacios, convirtiendo espacios a guiones, compactando guiones repetidos o normalizando el slug.

## 10. Capacidades opcionales

Un workspace puede requerir más que un directorio y una branch. Por ello, el producto deberá contemplar capacidades adicionales configurables.

### 10.1 Sesiones persistentes
Ejemplo: `tmux`.

Un proyecto podrá querer crear una sesión por target, reconectarse a ella, mantener procesos vivos ante una desconexión SSH y eliminarla al cerrar definitivamente el workspace.

### 10.2 Exposición temporal
Ejemplo: `zrok`.

Un proyecto podrá querer exponer temporalmente un servicio local, asociar el túnel al target, conocer su estado y cerrarlo al detener o destruir el workspace.

### 10.3 Procesos adicionales
Un proyecto podrá necesitar queue workers, dev servers, watchers, procesos de assets o servicios auxiliares asociados al lifecycle del target.

### 10.4 Herramientas de desarrollo
Ejemplos: Kiro, Codex, Claude y VS Code.

La herramienta podrá facilitar su apertura sin convertirlas en una dependencia.

### 10.5 Workspace provisioning
Un proyecto podrá requerir preparación adicional antes de que un worktree sea utilizable: runtime, dependencias, datos y readiness. Esas responsabilidades deben modelarse como capabilities/providers opcionales, no como conocimiento de un framework dentro del core.

## 11. Qué NO estamos construyendo

### 11.1 Un reemplazo de Git
Git continúa siendo la autoridad sobre commits, branches, merges e historial.

### 11.2 Un sistema de CI/CD
No es responsable de pipelines, despliegues, promociones de ambiente ni releases productivos.

### 11.3 Un gestor de proyectos
No sustituye Jira, GitHub Issues, Linear u otras herramientas de planificación.

### 11.4 Una herramienta exclusiva para IA
Debe ser igualmente útil para desarrollo tradicional.

### 11.5 Un orquestador universal de infraestructura
Podrá administrar recursos relacionados con el workspace, pero no pretende reemplazar herramientas de infraestructura.

### 11.6 Un framework que imponga el stack
No determinará qué lenguaje, framework, runtime o editor debe utilizar un proyecto.

### 11.7 Un detector automático de frameworks
No se detectará Laravel, Node, Python u otro stack para activar comportamiento central. La conducta se deriva de configuración/capabilities explícitas.

## 12. Configuración del proyecto cliente

Cada repositorio podrá declarar la forma en que desea adoptar el estándar.

Ejemplos de aspectos configurables:

- formato del target;
- normalización;
- branch base;
- convención de branch;
- directorio de worktrees;
- recursos;
- puertos;
- procesos;
- bootstrap/provisioning;
- capacidades opcionales;
- comportamiento de start/stop;
- herramientas que pueden abrirse.

El archivo de configuración pertenece al proyecto cliente porque expresa sus reglas compartidas.

Declarar provisioning no implica mantener scripts de lifecycle propios; el producto ejecuta las capabilities/providers soportados que el proyecto selecciona.

## 13. Configuración personal

La herramienta debe distinguir entre configuración compartida, configuración del desarrollador y secretos.

La configuración compartida será versionable y aplicable al proyecto, por ejemplo `.ramalio.toml`.

La configuración personal podrá incluir nombre del desarrollador, preferencias, herramientas disponibles, ubicaciones locales o archivos de integración.

Los secretos nunca deberán requerir ser almacenados en el TOML versionado.

## 14. Experiencia objetivo

En un proyecto:

```bash
cd proyecto-a
ramalio init FEATURE-123-login
```

El producto deriva target, branch y worktree, aplica las capabilities configuradas y devuelve éxito sólo cuando el workspace satisface el contrato requerido por ese proyecto.

Y posteriormente:

```bash
ramalio status FEATURE-123-login
ramalio stop FEATURE-123-login
ramalio start FEATURE-123-login
ramalio destroy FEATURE-123-login
```

En otro repositorio:

```bash
cd proyecto-b
ramalio init E7-S8-convergencia-schema-tests
```

Los comandos son iguales. Las reglas internas son distintas. La herramienta las obtiene del proyecto.

## 15. Beneficios esperados

### Para el desarrollador
- menos comandos manuales;
- menor carga mental;
- menor riesgo de trabajar en el checkout incorrecto;
- forma consistente de operar múltiples tareas;
- visibilidad clara de workspaces y recursos;
- facilidad para suspender y retomar trabajo.

### Para equipos que trabajan con IA
- un workspace aislado por tarea o agente;
- menor interferencia entre sesiones;
- capacidad de trabajar simultáneamente;
- asociación clara entre target, branch, runtime y procesos.

### Para la organización que lo adopta
- un estándar común;
- menos scripts duplicados;
- conocimiento operativo centralizado;
- onboarding más sencillo;
- mejores condiciones para automatizar;
- posibilidad de evolucionar capacidades una sola vez y reutilizarlas en varios proyectos.

## 16. Criterios de éxito del producto

Consideraremos que el producto cumple su objetivo cuando:

1. Un proyecto nuevo pueda adoptar el estándar principalmente mediante configuración, sin modificar el core.
2. Dos proyectos con stacks distintos puedan utilizar el mismo CLI.
3. El desarrollador no tenga que recordar comandos Git específicos para administrar los worktrees cotidianos.
4. Un mismo repositorio pueda mantener varias unidades de trabajo aisladas simultáneamente.
5. `stop` y `start` permitan suspender y retomar trabajo sin reconstruir el workspace.
6. `destroy` pueda retirar de forma segura los recursos asociados al target.
7. Una capacidad como tmux, zrok o una nueva herramienta pueda añadirse sin convertirse en dependencia obligatoria para todos los proyectos.
8. Las reglas de naming y normalización puedan definirse por proyecto.
9. La herramienta pueda mostrar con claridad qué workspaces existen y cuál es su estado.
10. El procedimiento de trabajo sea suficientemente consistente para convertirse en una convención de desarrollo del equipo.
11. Un proyecto que requiere provisioning soportado pueda quedar listo sin introducir lógica por framework/proyecto en el core ni exigir scripts de lifecycle propios.

## 17. Alcance de la primera etapa

La primera etapa debe enfocarse en demostrar el estándar sobre el ciclo fundamental:

```text
init
↓
trabajo
↓
stop / start
↓
destroy
```

incluyendo `adopt` para incorporar trabajo existente.

También deberá existir visibilidad operativa mediante `list`, `status` y `doctor`.

Las integraciones adicionales deberán contemplarse desde el diseño del producto, pero su implementación podrá incorporarse progresivamente.

## 18. Visión de evolución

A medida que el estándar madure, distintos proyectos podrán incorporar capacidades adicionales sin alterar la experiencia básica.

```text
Proyecto A
├── Git worktree
├── tmux
└── Kiro

Proyecto B
├── Git worktree
├── Docker Compose
├── zrok
└── VS Code

Proyecto C
├── Git worktree
├── procesos Python
└── Codex
```

Los tres siguen utilizando:

```bash
ramalio init
ramalio start
ramalio stop
ramalio status
ramalio destroy
```

Esa consistencia es el objetivo principal del producto.

Provisioning amplía las capacidades opcionales de algunos proyectos sin cambiar esa interfaz ni convertir el stack del primer piloto en identidad del producto.

## 19. Declaración final de visión

> **ramalio busca convertir el manejo de worktrees y sus recursos asociados en una capacidad estándar, reusable y configurable para equipos de desarrollo.**
>
> Cada proyecto conserva sus propias reglas y herramientas, mientras que el desarrollador obtiene una forma única y predecible de crear, adoptar, operar, suspender, reanudar y cerrar espacios de trabajo aislados.
>
> El resultado esperado no es solamente una utilidad para Git, sino un estándar operativo que facilite el desarrollo paralelo, el trabajo con agentes de IA y la evolución de nuevas capacidades sin acoplar la forma de trabajo del equipo a un framework, runtime o herramienta específica.
