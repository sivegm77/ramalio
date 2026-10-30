# E6-S1 — Gestión de puertos

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E6 — Runtimes, exposición y recursos opcionales
- **Spec:** E6-S1
- **Nombre:** Gestión de puertos por target
- **Dependencias:** E4 completada, E3-S1, E3-S3
- **Bloquea a:** E6-S2, E6-S3, E7-S1

## 2. Contexto
Algunos proyectos necesitan un puerto exclusivo por workspace. Esa necesidad no es universal y debe existir como recurso coordinado, observable y liberable por target.

## 3. Objetivo
Implementar un mecanismo determinista para asignar, reservar, observar y liberar puertos dentro de rangos configurados, evitando colisiones entre workspaces del mismo proyecto y detectando uso externo cuando sea posible.

## 4. Alcance
Incluye: configuración de rangos, asignación determinista, reserva, release, detección de colisiones, estado, integración con doctor/status/lifecycle. Excluye: networking de Docker, firewalls, reverse proxies, exposición pública y zrok.

## 5. Invariantes
- Puertos son opcionales.
- Un puerto reservado pertenece a un target.
- No se reasigna silenciosamente un puerto activo a otro target.
- La reserva debe ser determinista y concurrency-safe en la medida definida en E6; hardening final en E7-S1.
- `destroy` libera la reserva propia.

## 6. Requirements
### R1 — Configuración
```toml
[ports]
enabled = true
start = 8100
size = 20
```
Con `enabled=false`, no se asignan puertos.

### R2 — Validación
- `start` entre 1 y 65535.
- `size > 0`.
- rango final <= 65535.
Errores de configuración deben ser fail-fast.

### R3 — Asignación
La estrategia debe ser determinista para un conjunto de reservas dado y no depender de orden accidental de procesos.

### R4 — Reserva
Debe existir una abstracción de reserva por proyecto/target con datos mínimos:
```text
target
port
owner project
```
La implementación puede usar un state/resource store local, siempre separado de Git y limitado a recursos que Git no conoce.

### R5 — Colisiones internas
Un puerto ya reservado por otro target no puede asignarse.

### R6 — Puerto ocupado externamente
Antes de confirmar disponibilidad, debe intentarse detectar si el puerto ya está en uso por un proceso ajeno. No se mata ese proceso.

### R7 — Exhausted range
Si no hay puerto disponible:
```text
PORT_RANGE_EXHAUSTED
```

### R8 — Status
`status` debe mostrar el puerto asociado y su condición observable.

### R9 — Doctor
Debe validar rango y, cuando aplique, detectar conflictos obvios.

### R10 — Lifecycle
- `init`: puede reservar puerto si la configuración lo exige desde creación.
- `start`: conserva/reutiliza la reserva del target.
- `stop`: por default conserva la identidad/reserva para permitir reanudación determinista.
- `destroy`: libera la reserva.

### R11 — Idempotencia
Volver a resolver el puerto para el mismo target devuelve el mismo puerto mientras su reserva exista.

### R12 — Ownership
Release sólo puede liberar la reserva del target solicitado.

## 7. Diseño
Componentes conceptuales:
```text
resources/
├── ports.py
└── locks.py (hardening E7)
```
Flujo:
```text
resolve target
→ load port config
→ lookup existing reservation
→ if exists reuse
→ else scan deterministic candidates
→ check reservation + local socket availability
→ reserve
```
No debe usarse un archivo global específico de SiVale.

## 8. Criterios de aceptación
- AC-01: disabled no asigna puerto.
- AC-02: primer target recibe puerto del rango.
- AC-03: segundo target no colisiona.
- AC-04: mismo target conserva puerto.
- AC-05: puerto externo ocupado se omite/bloquea según algoritmo.
- AC-06: rango agotado falla claramente.
- AC-07: destroy libera sólo reserva propia.
- AC-08: status/doctor reflejan configuración.

## 9. Tasks
1. Extender modelo `[ports]`.
2. Definir `PortReservation` y store mínimo.
3. Implementar allocator determinista.
4. Implementar detection de puerto ocupado.
5. Implementar release con ownership.
6. Integrar init/start/stop/destroy.
7. Integrar status/doctor.
8. Tests de múltiples targets y rango agotado.
9. Dejar hooks para locks de E7-S1.

## 10. Verificación
La spec se cierra cuando varios workspaces simultáneos obtienen puertos únicos y reanudables, sin que un proyecto sin puertos cargue con esta funcionalidad.

## 11. Resultado esperado
E6-S1 aporta el primer recurso compartido administrado por target que no pertenece a Git.
