# E4-S2 — Procesos administrados

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E4 — Capacidades y procesos
- **Spec:** E4-S2
- **Nombre:** Capability genérica de procesos administrados
- **Dependencias:** E4-S0, E4-S1
- **Bloquea a:** E5, E6 y capacidades de procesos reales de proyectos cliente
- **Estado inicial:** Planificada

---

## 2. Contexto

Muchos proyectos necesitan ejecutar procesos adicionales por workspace:

- queue workers;
- frontend dev servers;
- watchers;
- servicios auxiliares.

No deben convertirse en conceptos del core.

E4-S2 implementa la primera capability real y genérica del producto, demostrando que el modelo de E4 permite coordinar procesos asociados inequívocamente a un target.

---

## 3. Objetivo

Implementar una capability `processes` configurable por proyecto capaz de:

1. declarar procesos por nombre;
2. arrancarlos por workspace;
3. detenerlos;
4. consultar estado;
5. asociarlos inequívocamente al target;
6. integrarlos con start/stop/status/destroy/doctor;
7. evitar heurísticas inseguras de `pkill` global;
8. mantener el core independiente del comando concreto.

---

## 4. Alcance

### Incluido

- Configuración de procesos.
- Command argv.
- cwd.
- environment no secreto explícito.
- start.
- stop.
- status.
- ownership por workspace.
- PID/process metadata mínima.
- stop timeout.
- terminación controlada.
- doctor checks.
- lifecycle integration.
- tests con procesos fake/reales temporales.

### Fuera de alcance

- tmux — E5.
- systemd/supervisor.
- Docker Compose — E6.
- Procesos remotos.
- Reinicio automático continuo.
- Log aggregation avanzada.
- Secret store.
- Shell scripts arbitrarios interpretados como string por `/bin/sh -c` por defecto.

---

## 5. Principios e invariantes

### INV-01 — Proceso pertenece a un target

No se puede detener un proceso sólo por nombre global.

### INV-02 — argv seguro

Los comandos deben modelarse como argv cuando sea posible.

### INV-03 — Stop conservador

Sólo se termina un proceso cuya identidad/ownership pueda verificarse.

### INV-04 — Configuración por proyecto

El core no conoce queue workers ni Vite.

### INV-05 — Status real

ACTIVE/STOPPED deriva del proceso real, no de una bandera ficticia.

### INV-06 — Destroy limpia recursos propios

Un proceso del target debe detenerse antes de retirar el worktree.

---

# 6. Requirements

## R1 — Configuración

Ejemplo conceptual:

```toml
[capabilities.processes]
enabled = true

[[capabilities.processes.items]]
name = "frontend"
command = ["npm", "run", "dev"]
cwd = "."
start_on_init = false
start_on_start = true
stop_on_stop = true
stop_on_destroy = true
```

---

## R2 — Nombre único por proyecto

Cada process item debe tener `name` único.

Error:

```text
PROCESS_DUPLICATE_NAME
```

---

## R3 — Command argv

`command` debe ser lista no vacía de strings.

No aceptar un string shell arbitrario como contrato inicial.

---

## R4 — cwd

`cwd` relativo se resuelve respecto al worktree del target.

Debe permanecer dentro del boundary del worktree salvo que una spec futura permita explícitamente otra cosa.

---

## R5 — Environment

Puede declararse un mapa de variables no secretas:

```toml
environment = { APP_MODE = "dev" }
```

No debe requerir secretos versionados.

---

## R6 — Process identity

Al arrancar debe conservar metadata suficiente para comprobar ownership:

```text
target
process_name
pid
start marker / fingerprint
cwd
```

La estrategia exacta puede incluir PID + process start time/fingerprint para evitar PID reuse.

---

## R7 — Metadata local

A diferencia del estado Git, la identidad de un proceso no tiene una autoridad externa suficiente para reconstruirse siempre.

Por ello E4-S2 puede introducir metadata administrativa local no versionada.

Debe vivir fuera de archivos compartidos/versionados del proyecto y estar namespaced por proyecto + target.

---

## R8 — Start

Al iniciar:

- verificar que no hay instancia activa propia;
- validar executable;
- lanzar proceso con cwd correcto;
- registrar metadata sólo después de obtener identidad verificable;
- confirmar que no terminó inmediatamente cuando sea razonable.

---

## R9 — Start idempotente

Si el proceso propio ya está activo:

```text
already_active
```

sin duplicarlo.

---

## R10 — Stop

Debe:

1. leer metadata;
2. verificar que PID/fingerprint sigue correspondiendo al proceso;
3. enviar terminación normal;
4. esperar timeout;
5. escalar sólo según política explícita.

---

## R11 — No matar PID reutilizado

Si metadata apunta a PID que ya pertenece a otro proceso:

```text
PROCESS_OWNERSHIP_MISMATCH
```

No enviar señal.

---

## R12 — Stop timeout

Configurable con default seguro, por ejemplo:

```text
10s
```

Después puede escalar a kill sólo si ownership continúa verificado y la política lo permite.

---

## R13 — Status

Por process item:

```text
ACTIVE
STOPPED
STALE
ERROR
```

`STALE` cuando existe metadata pero no proceso válido correspondiente.

---

## R14 — Capability aggregate status

Reglas iniciales:

- todos activos esperados → ACTIVE;
- todos detenidos → STOPPED;
- mezcla válida → DEGRADED;
- ownership/error → ERROR/DEGRADED según severidad.

---

## R15 — `start_on_init`

Si true, el proceso participa en `after_init`.

---

## R16 — `start_on_start`

Si true, se arranca durante start.

---

## R17 — `stop_on_stop`

Si true, se detiene durante stop.

---

## R18 — `stop_on_destroy`

Si true, debe detenerse en `before_destroy`.

Un fallo que impida verificar/terminar un proceso requerido bloquea destroy.

---

## R19 — Process logs

Como mínimo debe permitirse configurar o resolver stdout/stderr de forma que el proceso no bloquee al padre.

Puede dirigirse a archivos locales administrados por workspace/process.

No se requiere UI de logs.

---

## R20 — Metadata cleanup

Después de stop confirmado:

- eliminar metadata activa;
- conservar sólo lo necesario para diagnóstico si el diseño lo requiere.

No borrar logs por defecto durante stop.

Destroy puede limpiar metadata propia tras confirmar terminación.

---

## R21 — Doctor

Checks:

- executable principal disponible;
- cwd config válida;
- command no vacío;
- metadata directory utilizable sin escribir durante doctor cuando sea posible.

---

## R22 — Status integration

`imass-wt status <target>` debe mostrar process items y estados.

---

## R23 — List integration

`list` puede resumir capability como ACTIVE/STOPPED/DEGRADED sin detallar cada proceso.

---

## R24 — Sin dependencia de tmux

Los procesos deben poder funcionar sin tmux.

E5 podrá ofrecer tmux como otra capability/integración, no como requisito.

---

# 7. Diseño

## 7.1 Estructura conceptual

```text
capabilities/processes/
└── capability.py
```

con servicios internos si se requiere:

```text
ProcessLauncher
ProcessIdentityStore
ProcessInspector
ProcessTerminator
```

---

## 7.2 Metadata

Ejemplo conceptual fuera del repo versionado:

```text
<user-state>/imass-worktree/<project-id>/<target>/processes/<name>.json
```

Debe contener sólo metadata operativa, nunca secretos.

---

## 7.3 Fingerprint

La identidad no puede basarse únicamente en PID.

Debe incluir al menos otra señal disponible de manera portable en la plataforma soportada.

Si no puede verificarse ownership con suficiente confianza, fail closed.

---

## 7.4 Lifecycle mapping

```text
after_init
  → start items start_on_init

after_start
  → start items start_on_start

before_stop
  → stop items stop_on_stop

before_destroy
  → stop items stop_on_destroy
```

---

## 7.5 Compensación

Si se arrancan varios procesos y uno falla:

- detener en orden inverso los iniciados por esa operación;
- no tocar procesos preexistentes.

---

# 8. Criterios de aceptación

## AC-01

Puede declarar dos procesos distintos por proyecto.

## AC-02

Start lanza proceso en cwd del worktree correcto.

## AC-03

Segundo start no duplica.

## AC-04

Stop termina sólo proceso propio.

## AC-05

PID reutilizado no es terminado.

## AC-06

Status refleja ACTIVE/STOPPED/STALE.

## AC-07

Destroy bloquea si un proceso requerido no puede detenerse con seguridad.

## AC-08

Doctor valida command availability/config.

## AC-09

No requiere tmux/Docker.

## AC-10

Fallo parcial de start compensa sólo procesos creados en esa ejecución.

---

# 9. Tasks

## T1 — Extender config de processes
Items y flags lifecycle.

## T2 — Definir modelos de process item/status
Config/runtime.

## T3 — Implementar metadata store local
Namespaced por project/target.

## T4 — Implementar launcher
argv/cwd/env.

## T5 — Implementar fingerprint/ownership
Protección PID reuse.

## T6 — Implementar inspector
ACTIVE/STOPPED/STALE.

## T7 — Implementar terminator
TERM/timeout/escalation segura.

## T8 — Implementar capability aggregate
Status y errores.

## T9 — Integrar hooks
init/start/stop/destroy.

## T10 — Integrar doctor
Checks.

## T11 — Integrar status/list
Detalle/resumen.

## T12 — Implementar compensación
Start parcial.

## T13 — Tests unitarios
Ownership/config/status.

## T14 — Tests integración
Procesos reales temporales.

---

# 10. Verificación

La spec está completa cuando procesos reales pueden asociarse a dos targets distintos y start/stop/destroy actúan únicamente sobre los procesos que pertenecen al target correcto.

---

# 11. Resultado esperado

Después de E4-S2, `imass-worktree` demuestra que el modelo de capabilities funciona con una capacidad real y genérica, sin incorporar todavía tmux, Docker Compose ni zrok al core.
