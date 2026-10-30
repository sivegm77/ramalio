# Estándar operativo — ramalio

## 1. Propósito y autoridad

Este documento materializa la Etapa 0 del producto `ramalio`. Define el
lenguaje y las invariantes que deben respetar las etapas posteriores. No define
todavía el contrato TOML, una sintaxis universal de target, naming de branches,
operaciones Git concretas, runtimes, procesos, puertos, sesiones, túneles ni
integraciones.

La separación rectora es:

```text
core genérico
+ configuración del proyecto cliente
+ capabilities opcionales
+ integrations opcionales
```

Si una necesidad futura contradice este estándar o los documentos rectores del
producto, debe tratarse como un cambio deliberado del marco y no como una
excepción silenciosa en una implementación particular.

## 2. Glosario oficial

### Proyecto cliente

Repositorio que adopta `ramalio` y declara sus reglas particulares mediante
configuración compartida versionable y, cuando aplique, configuración personal
separada. El proyecto cliente no modifica el core para expresar convenciones
propias.

### Target

Identificador lógico de una unidad de trabajo solicitada por el usuario. Su
sintaxis, validación y normalización pertenecen al proyecto cliente. El core no
impone una convención universal.

### Branch asociada

Branch Git que representa el trabajo del target conforme a las reglas del
proyecto. Git conserva autoridad sobre su existencia, nombre, commits, historial
y estado real.

### Worktree

Checkout adicional asociado por Git a una branch. Git conserva autoridad sobre
la existencia y asociación real de los Git worktrees.

### Workspace administrado

Unidad operativa que `ramalio` reconoce como perteneciente a un target y
que, como mínimo, mantiene una relación determinista:

```text
target → branch → worktree
```

Puede además poseer recursos opcionales inequívocamente asociados al target.

### Recurso asociado

Elemento operativo cuya existencia o asignación pertenece inequívocamente a un
workspace y que puede requerir observación, arranque, parada o cleanup. Ejemplos
futuros incluyen procesos, puertos, runtimes, sesiones persistentes y túneles.

### Configuración compartida

Reglas versionables del proyecto cliente. No es un almacén de secretos ni de
preferencias personales.

### Configuración personal

Preferencias, rutas locales u opciones propias de un desarrollador que no deben
forzarse al equipo ni convertirse en reglas compartidas del repositorio.

### Capability

Funcionalidad opcional que participa en uno o más momentos del lifecycle y puede
tener estado técnico asociado al target. Una capability no es requisito del core
por el hecho de existir.

### Workspace provisioning

Preparación opcional y declarativa necesaria para convertir un worktree Git válido en un workspace listo para trabajar conforme a las necesidades del proyecto cliente. Puede coordinar configuración local, runtime, dependencias, datos y readiness mediante capabilities; no convierte esas tecnologías en responsabilidades del core.

### Integration

Herramienta externa que puede abrirse o utilizarse desde un workspace, pero que
no es una dependencia del lifecycle fundamental.

### Fallo

Resultado no exitoso de una operación. Un fallo debe ser observable y nunca debe
presentarse como éxito.

### Inconsistencia

Situación en la que la realidad observable no coincide con la identidad o
condición esperada del workspace.

### Recuperación

Acción deliberada para llevar un workspace inconsistente o parcialmente operado
a un estado conocido y seguro, sin ocultar pérdida de información ni asumir un
éxito inexistente.

## 3. Modelo de autoridad

1. **Git es autoridad sobre Git.** `ramalio` no mantiene una segunda
   fuente de verdad sobre commits, historial, branches o worktrees cuando ese
   dato puede derivarse de Git de forma confiable.
2. **El proyecto cliente es autoridad sobre sus reglas.** Convenciones de
   target, naming, ubicación, bootstrap, capabilities e integrations pertenecen
   a configuración del proyecto.
3. **Cada capability es autoridad técnica sobre sus recursos cuando aplique.**
   El estado observado debe provenir de la herramienta o recurso real siempre
   que exista una fuente suficiente.
4. **Estado propio sólo cuando aporta información no derivable.** Persistencia
   interna se justifica únicamente para identidad, coordinación o recuperación
   que no pueda obtenerse de una autoridad externa suficiente.

## 4. Identidad target → branch → worktree

Para el mismo proyecto y la misma configuración efectiva, un target canónico
debe derivar de forma determinista la identidad esperada de su workspace. La
fórmula concreta se define en Etapa 1.

No existe naming universal en el core: no se presuponen prefijos como `spec/`,
`feature/`, rutas `.local-wt` ni formatos `E7-S8-*`.

Una operación nunca puede apropiarse silenciosamente de una branch, worktree o
directorio que contradiga la identidad esperada. Una colisión o contradicción
obliga a bloquear, adoptar deliberadamente o entrar en una ruta explícita de
recuperación.

## 5. Estados conceptuales

Los estados son semánticos; no obligan todavía a un enum persistido.

### ABSENT

No existe una unidad administrada válida y utilizable para el target en el
proyecto actual. Puede existir una branch relacionada sin que ello constituya un
workspace administrado.

### READY

Existe una relación válida target → branch → worktree y la unidad puede usarse
para trabajar. No exige capabilities activas.

### ACTIVE

El workspace está READY y los recursos que deban estar activos para la operación
actual están activos según la configuración. En un proyecto sin recursos
suspendibles no es obligatorio distinguir artificialmente READY de ACTIVE.

### STOPPED

Se preservan target, branch, worktree y trabajo local, pero los recursos
suspendibles fueron detenidos intencionalmente.

### DEGRADED

Existe evidencia suficiente para reconocer el workspace, pero una condición
esperada no coincide con la realidad o una operación quedó parcialmente
aplicada. Requiere diagnóstico y recuperación explícita; no se presenta como
estado sano.

## 6. Lifecycle conceptual

```text
                 adopt
        ┌──────────────────────┐
        │                      ▼
ABSENT ─┴─ init ─────────────> READY
                                │
                                │ start (cuando aplique)
                                ▼
                              ACTIVE
                                │
                                │ stop
                                ▼
                              STOPPED
                                │
                                └──── start ────> ACTIVE

READY / ACTIVE / STOPPED / DEGRADED
                │
                │ destroy + safety gate
                ▼
              ABSENT
```

### init

Crea una nueva unidad administrada conforme a las reglas del proyecto. No se
apropia ambiguamente de trabajo existente. El éxito implica un workspace válido
y observable; el fallo no puede ocultar un estado parcial.

### adopt

Incorpora deliberadamente trabajo existente al modelo administrado, validando la
identidad en lugar de recrearlo o apropiárselo sin inspección.

### stop

Libera recursos suspendibles sin eliminar target, branch, worktree, cambios
locales ni identidad del workspace.

### start

Reactiva los recursos de un workspace existente sin reconstruir el worktree.

### destroy

Cierra de forma controlada la unidad y limpia los recursos administrados cuando
aplique. Es una operación conservadora y nunca equivale a «borrar sin
inspección».

### list / status / doctor

Forman el contrato de observabilidad. Deben permitir conocer qué existe, qué
está activo o detenido, qué está degradado y qué condiciones impiden operar o
destruir con seguridad.

## 7. Invariantes de seguridad

### INV-001 — No pérdida silenciosa de trabajo

Una operación destructiva no elimina trabajo local útil silenciosamente. Ante
riesgo detectable debe bloquearse o usar un mecanismo explícito definido por una
spec posterior.

### INV-002 — stop preserva identidad y trabajo

`stop` no elimina worktree, branch ni cambios locales.

### INV-003 — destroy es conservador

`destroy` inspecciona las condiciones relevantes y prefiere rechazar una
operación dudosa antes que destruir información útil.

### INV-004 — No overwrite implícito

`init` no sobrescribe worktrees, directories o branches existentes para «hacer
que funcione».

### INV-005 — Fallo observable

Una operación fallida no devuelve semántica de éxito.

### INV-006 — Fallo parcial no se oculta

Si una operación modifica parcialmente el entorno y no puede completar o
revertir, el resultado queda diagnosticable como inconsistente/degradado.

### INV-007 — Core agnóstico

El core no requiere Laravel, PHP, el Python de la aplicación cliente, Node,
Docker, Kiro, Codex, Claude, VS Code, tmux, zrok ni otra tecnología concreta. Que
`ramalio` esté implementado en Python no convierte Python en requisito del
stack del proyecto cliente.

### INV-008 — Secretos fuera de configuración compartida

Tokens, credenciales y secretos no deben requerir almacenamiento en la
configuración versionable del proyecto.

### INV-009 — Capability opcional sigue siendo opcional

Añadir una capability no rompe ni condiciona proyectos que no la habilitan.

### INV-010 — Autoridad externa antes que duplicación

No se mantienen copias innecesarias de información cuya autoridad clara sea Git
o un recurso externo observable.

## 8. Clasificación obligatoria de nuevas necesidades

```text
¿Es comportamiento universal del lifecycle?
        └─ sí → CORE

¿Es una regla particular del repositorio?
        └─ sí → CONFIGURACIÓN DEL PROYECTO CLIENTE

¿Es comportamiento opcional asociado al lifecycle?
        └─ sí → CAPABILITY

¿Es una herramienta externa que se abre/usa desde el workspace?
        └─ sí → INTEGRATION

Si no encaja:
        └─ justificar si realmente pertenece a ramalio
```

SiVale será un proyecto cliente de referencia y no una fuente automática de
reglas universales. Una necesidad descubierta en su piloto debe pasar por esta
clasificación antes de entrar al producto.

## 9. Límites explícitos

`ramalio` no es un reemplazo de Git, un sistema CI/CD, un gestor de
proyectos, una herramienta exclusiva para IA, un orquestador universal de
infraestructura, un framework que impone stack ni un almacén de secretos.

Puede coordinar herramientas especializadas mediante capabilities o integrations
sin convertirse en ellas.

## 10. Criterio operativo de Etapa 0

El estándar permite describir, sin depender de un proyecto concreto, el camino
conceptual desde `init` hasta un `destroy` seguro, incluyendo adopción,
suspensión, reanudación, observabilidad, fallos, inconsistencias y recuperación.

La implementación ejecutable de E0 congela además la superficie pública del CLI
y sus contratos de resultado; las operaciones reales se incorporan en las
etapas propietarias sin redefinir estas reglas.


## 11. Workspace provisioning y frontera de responsabilidades

El hecho de que exista una branch y un worktree válidos no implica necesariamente que el workspace esté listo para trabajar. Un proyecto Git-only puede considerar `READY` al workspace una vez satisfecha su identidad Git; un proyecto con capabilities de provisioning sólo puede considerarlo completamente listo cuando las responsabilidades declaradas y aplicables hayan terminado correctamente.

### 11.1 Regla de responsabilidad

El proyecto cliente **declara qué necesita** mediante configuración versionable. El proyecto cliente **no debe reimplementar el lifecycle de worktrees** mediante scripts indispensables cuando esa responsabilidad es reutilizable y pertenece al estándar.

La frontera normativa es:

| Necesidad | Clasificación |
|---|---|
| target, branch, worktree, locks, safety y transacción | core |
| reglas de naming y selección de capacidades | configuración del proyecto |
| preparación opcional reutilizable del workspace | capability |
| implementación tecnológica de una capability | driver/provider de esa capability |
| apertura de IDE/agente/herramienta | integration |
| lógica de negocio, deploy y build de producto | proyecto cliente / fuera de alcance |

### 11.2 Prohibición de branching por framework o proyecto

Una tecnología seleccionada por un proyecto no se convierte en conocimiento del core. No son válidos condicionales centrales por nombre de proyecto, framework o stack, por ejemplo `if project == "sivale"` o `if framework == "laravel"`.

Una necesidad tecnológica legítima debe expresarse mediante configuración y una capability/driver/provider opcional, conservando INV-007 e INV-009.

### 11.3 Lifecycle conceptual del provisioning

Cuando aplique:

```text
init  → crear identidad Git → provisioning requerido → workspace listo
adopt → incorporar identidad Git → provisioning requerido → workspace listo
start → reactivar recursos suspendibles sin repetir bootstrap destructivo
stop  → suspender recursos preservando identidad y trabajo
destroy → limpiar recursos propios → retirar workspace cuando sea seguro
```

La implementación detallada de estas fases pertenece a specs posteriores. Este estándar no autoriza un segundo motor de locks, transacciones, ejecución de procesos o estado paralelo; las capacidades nuevas deben reutilizar los contratos existentes.

### 11.4 Idempotencia, ownership y rollback

- repetir una operación no debe duplicar recursos ya satisfechos;
- cada recurso mutable debe poder atribuirse al proyecto/target correcto;
- un fallo parcial debe usar el modelo de rollback ya existente;
- `status` y `doctor` deben permanecer observables;
- los secretos siguen fuera del TOML compartido.

### 11.5 Fuera de alcance del provisioning

No pertenece al provisioning de `ramalio`:

- CI/CD y deploy;
- inicialización de negocio;
- migraciones o seeds productivos arbitrarios;
- detección automática de framework;
- plugin marketplace o ejecución dinámica de código no registrado;
- soporte preventivo para tecnologías que ningún proyecto soportado necesita.
