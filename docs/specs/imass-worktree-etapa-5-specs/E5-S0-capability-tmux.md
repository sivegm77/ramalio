# E5-S0 — Capability tmux

## 1. Identificación
- Proyecto: imass-worktree
- Etapa: E5 — Integraciones de experiencia de desarrollo
- Spec: E5-S0
- Nombre: Capability tmux
- Dependencias: E4-S0, E4-S1, E4-S2

## 2. Contexto
`tmux` es una capacidad opcional para mantener sesiones persistentes por target, especialmente útil ante desconexiones SSH. No forma parte del core ni puede convertirse en dependencia obligatoria.

## 3. Objetivo
Implementar una capability `tmux` configurable por proyecto que pueda participar en `init`, `start`, `status`, `stop` y `destroy`, manteniendo una sesión inequívocamente asociada al target.

## 4. Alcance
Incluye creación opcional, naming, detección, attach/re-attach, estado, stop y cleanup. Fuera de alcance: instalar tmux, administrar panes complejos, ejecutar herramientas de IA por defecto, runtime Docker o túneles.

## 5. Invariantes
- El core funciona sin tmux.
- Una sesión pertenece a un solo target.
- Naming determinista y configurable.
- `status` refleja existencia/estado real.
- `stop` y `destroy` respetan políticas distintas.
- Nunca matar sesiones ajenas.

## 6. Requirements
### R1 — Configuración
Debe aceptarse una sección como:
```toml
[capabilities.tmux]
enabled = true
session_pattern = "imass-{target}"
create_on_init = true
attach_on_init = false
stop_policy = "keep"
destroy_policy = "kill"
```

### R2 — Availability
`doctor` debe detectar si `tmux` está disponible cuando la capability está habilitada.

### R3 — Naming
La sesión se deriva determinísticamente del target y patrón configurado. Deben rechazarse nombres inválidos o ambiguos.

### R4 — Init
Si `create_on_init=true`, `after_init` crea la sesión si no existe. Si existe y corresponde al target, la operación debe ser idempotente.

### R5 — Start
`start` debe asegurar que la sesión requerida exista según política configurada.

### R6 — Status
Debe reportar al menos `AVAILABLE`, `MISSING`, `RUNNING`, `DISABLED` o `ERROR` según aplique.

### R7 — Attach
La capability debe exponer una operación de attach/re-attach sin obligar al lifecycle general a usarla automáticamente.

### R8 — Stop
`stop_policy` debe permitir al menos `keep` y `kill`. Default seguro: `keep`.

### R9 — Destroy
`destroy_policy` debe permitir al menos `keep` y `kill`. Si `kill`, sólo se elimina la sesión derivada del target.

### R10 — No ownership ambiguity
Si el nombre derivado colisiona con una sesión preexistente que no puede atribuirse con seguridad al workspace, la operación debe bloquear en vez de matarla o reutilizarla silenciosamente.

### R11 — CLI output
Los resultados de lifecycle deben poder incluir el estado de tmux sin mezclar stdout crudo.

### R12 — Idempotencia
Crear/start/stop/destroy repetidos no deben producir efectos duplicados o destructivos fuera del target.

## 7. Diseño
- Implementar `TmuxCapability` usando el contrato de E4.
- Encapsular ejecución externa en argv seguro.
- Integrarse mediante hooks/lifecycle existentes.
- No introducir lógica tmux en `core/` ni `lifecycle/`.
- Mantener ownership por target mediante naming determinista y observación real.

## 8. Criterios de aceptación
- Proyecto sin tmux sigue operando igual.
- Capability habilitada crea sesión según política.
- `status` refleja sesión real.
- `stop` respeta `keep|kill`.
- `destroy` sólo puede limpiar su sesión.
- `doctor` detecta ausencia de tmux.
- Operaciones repetidas son idempotentes.

## 9. Tasks
1. Extender configuración tmux.
2. Implementar adapter/runner tmux seguro.
3. Implementar `TmuxCapability`.
4. Integrar init/start/status/stop/destroy.
5. Implementar attach/re-attach.
6. Integrar checks de doctor.
7. Crear unit tests con runner simulado.
8. Crear integration tests cuando tmux esté disponible.

## 10. Verificación
La spec termina cuando tmux puede habilitarse o deshabilitarse por proyecto sin cambiar el core y su lifecycle completo queda cubierto por tests.

## 11. Resultado esperado
Un proyecto puede asociar opcionalmente una sesión tmux persistente a cada target sin hacer de tmux un requisito universal.
