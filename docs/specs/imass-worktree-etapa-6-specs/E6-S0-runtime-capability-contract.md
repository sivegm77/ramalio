# E6-S0 — Runtime capability contract

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E6 — Runtimes, exposición y recursos opcionales
- **Spec:** E6-S0
- **Nombre:** Runtime capability contract
- **Dependencias:** E4-S0, E4-S1, E4-S2, E5 completada
- **Bloquea a:** E6-S2, E6-S3 y robustez E7

## 2. Contexto
El producto debe permitir que ciertos proyectos asocien un runtime a cada workspace sin convertir ese runtime en requisito universal. Docker Compose será un driver posterior, no el fundamento del producto.

## 3. Objetivo
Definir e implementar el contrato genérico de runtime para que `init`, `start`, `stop`, `status` y `destroy` puedan coordinar un runtime opcional por target, manteniendo un driver `none` como comportamiento base.

## 4. Alcance
Incluye: interfaz de runtime, lifecycle, estado, errores, configuración, integración con status/start/stop/destroy, driver `none`, pruebas con runtime falso. Excluye: Docker Compose real (E6-S2), puertos (E6-S1), túneles (E6-S3), despliegue, Kubernetes y CI/CD.

## 5. Invariantes
- El core funciona sin runtime.
- Un runtime pertenece inequívocamente a un target.
- `status` refleja estado observado, no una bandera inventada.
- `stop` no destruye el worktree.
- `destroy` limpia runtime antes de retirar el workspace cuando aplique.
- Fallos del runtime tienen comportamiento explícito y fail-closed donde pueda perderse control operativo.

## 6. Requirements
### R1 — Configuración
El proyecto puede declarar un runtime opcional mediante configuración equivalente a:
```toml
[capabilities.runtime]
driver = "none"
```
El default es `none`.

### R2 — Contrato
Debe existir una abstracción equivalente a:
```text
RuntimeDriver
├── doctor(context)
├── start(workspace)
├── stop(workspace)
├── status(workspace)
└── cleanup(workspace)
```

### R3 — Driver none
`none` debe ser funcional, no un caso especial disperso. `start`, `stop` y `cleanup` son no-op exitosos; `status` devuelve `NOT_APPLICABLE` o equivalente.

### R4 — Estados
Contrato mínimo:
```text
NOT_APPLICABLE
STOPPED
STARTING
RUNNING
DEGRADED
FAILED
UNKNOWN
```
No se exige persistirlos.

### R5 — Lifecycle
- `init`: puede preparar runtime si la capability así lo requiere, sin arrancarlo implícitamente salvo contrato/configuración explícita.
- `start`: arranca runtime.
- `status`: observa runtime.
- `stop`: detiene runtime preservando workspace.
- `destroy`: ejecuta cleanup antes de destruir recursos Git cuando el runtime tenga recursos propios.

### R6 — Idempotencia
`start`, `stop` y `cleanup` deben ser idempotentes desde el contrato.

### R7 — Errores
Códigos conceptuales:
```text
RUNTIME_DRIVER_UNKNOWN
RUNTIME_START_FAILED
RUNTIME_STOP_FAILED
RUNTIME_STATUS_FAILED
RUNTIME_CLEANUP_FAILED
```

### R8 — Doctor
El runtime registrado puede aportar checks a `doctor`.

### R9 — Sin acoplamiento
No deben aparecer decisiones Docker-specific en el contrato base.

### R10 — Testing
Debe existir un runtime falso para validar lifecycle y fallos sin herramientas externas.

## 7. Diseño
Componentes conceptuales:
```text
capabilities/runtime/
├── base.py
├── none.py
└── registry.py | integración con capability registry
```
Flujo de start:
```text
workspace status válido
→ resolve runtime driver
→ driver.start
→ observe driver.status
→ return runtime result
```
La capability runtime participa mediante el sistema de E4; no redefine lifecycle.

## 8. Criterios de aceptación
- AC-01: proyecto sin runtime usa `none` y sigue funcionando.
- AC-02: runtime falso puede arrancar/detenerse/consultarse.
- AC-03: start repetido es seguro.
- AC-04: stop repetido es seguro.
- AC-05: cleanup repetido es seguro.
- AC-06: status aparece integrado en `imass-wt status`.
- AC-07: doctor puede ejecutar check del runtime.
- AC-08: no hay dependencia de Docker.

## 9. Tasks
1. Definir `RuntimeDriver` y resultados.
2. Definir estados y errores.
3. Implementar driver `none`.
4. Integrar resolución con capability registry.
5. Integrar start/stop/status/destroy.
6. Integrar doctor.
7. Crear runtime falso para tests.
8. Cubrir idempotencia y fallos inducidos.

## 10. Verificación
La spec se cierra cuando un proyecto Git-only y otro con runtime falso usan el mismo lifecycle sin modificar el core y sin depender de Docker.

## 11. Resultado esperado
E6-S0 deja estable la frontera de runtime sobre la que E6-S2 podrá implementar Docker Compose como un driver opcional.
