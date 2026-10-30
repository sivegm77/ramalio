# E6-S3 — Tunnel capability + zrok

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E6 — Runtimes, exposición y recursos opcionales
- **Spec:** E6-S3
- **Nombre:** Contrato de túneles y provider zrok
- **Dependencias:** E4 completada, E6-S0, E6-S1; E6-S2 sólo cuando el proyecto use Compose
- **Bloquea a:** cierre de E6 y robustez E7

## 2. Contexto
Algunos workspaces necesitan exposición temporal de un servicio local. `zrok` será el primer provider, pero el producto debe modelar la exposición como capability genérica para permitir alternativas futuras.

## 3. Objetivo
Definir un contrato de tunnel provider e implementar `zrok` como primera integración capaz de iniciar, observar, detener y limpiar una exposición asociada inequívocamente a un target.

## 4. Alcance
Incluye: capability de túnel, provider registry, configuración, zrok availability, start/stop/status/cleanup, relación con puerto, URL pública observable, doctor, manejo de procesos/identidad. Excluye: DNS corporativo, certificados propios, cloudflared real, balanceadores y publicación productiva.

## 5. Invariantes
- Túneles son opcionales.
- Un túnel pertenece a un target y puerto concretos.
- `destroy` debe cerrar el túnel antes de liberar el workspace.
- `stop` debe cerrar exposición temporal salvo configuración futura explícita.
- No compartir un mismo túnel entre targets por accidente.
- Credenciales/tokens no se guardan en TOML versionado.

## 6. Requirements
### R1 — Configuración
Ejemplo conceptual:
```toml
[capabilities.tunnel]
provider = "zrok"
enabled = false
```
Puede coexistir con configuración provider-specific en namespace propio.

### R2 — Contrato
```text
TunnelProvider
├── doctor(context)
├── start(workspace, local_endpoint)
├── stop(workspace)
├── status(workspace)
└── cleanup(workspace)
```

### R3 — Estado
Mínimo:
```text
DISABLED
STOPPED
STARTING
ACTIVE
DEGRADED
FAILED
UNKNOWN
```
Cuando ACTIVE debe poder exponer `public_url`.

### R4 — Endpoint local
El provider recibe un endpoint ya resuelto, normalmente desde E6-S1/runtime:
```text
host + port
```
No asigna puertos por su cuenta.

### R5 — Provider zrok
Debe implementar el contrato sin filtrar conocimiento zrok al core.

### R6 — Doctor zrok
Debe comprobar ejecutable/configuración necesaria sin imprimir secretos.

### R7 — Start
Debe iniciar una exposición para el endpoint del target y capturar identidad suficiente para status/stop.

### R8 — Asociación
La identidad del túnel debe vincularse a proyecto + target de forma determinista o registrarse como recurso administrado propio cuando el provider genere IDs dinámicos.

### R9 — Stop
Debe cerrar sólo el túnel del target solicitado.

### R10 — Cleanup
Debe ser idempotente y eliminar estado local administrado del túnel después de cerrar exposición.

### R11 — Status
Debe diferenciar túnel activo, caído, inexistente y desconocido.

### R12 — Lifecycle
- `init`: no necesita exponer por defecto.
- `start`: puede iniciar túnel después de que runtime/endpoint local esté disponible.
- `stop`: detiene túnel antes o durante la suspensión de recursos.
- `destroy`: cleanup obligatorio antes de liberar puerto/worktree.

### R13 — Orden
Cuando coexistan runtime + túnel:
```text
start: runtime → endpoint ready → tunnel
stop: tunnel → runtime
```
La implementación debe usar hooks/capability ordering de E4.

### R14 — Credenciales
Tokens de zrok se obtienen de configuración personal/entorno seguro; nunca se escriben al TOML compartido ni se muestran en logs.

### R15 — Fallos
Un fallo de túnel no debe destruir automáticamente el runtime/worktree. Debe reportarse como capability FAILED/DEGRADED según contrato.

### R16 — Providers futuros
Agregar otro provider no debe requerir cambiar lifecycle central.

## 7. Diseño
Componentes conceptuales:
```text
capabilities/tunnels/
├── base.py
├── registry.py
└── zrok.py
```
Estado dinámico del provider que no pueda derivarse externamente puede persistirse como recurso propio mínimo, con ownership por target.

Flujo start:
```text
workspace READY
→ runtime RUNNING cuando aplique
→ resolve local endpoint/port
→ zrok.start
→ capture public URL/resource identity
→ status ACTIVE
```

## 8. Criterios de aceptación
- AC-01: disabled no requiere zrok instalado.
- AC-02: enabled + zrok ausente falla doctor claramente.
- AC-03: start usa el puerto del target.
- AC-04: dos targets no comparten identidad de túnel.
- AC-05: stop de A no afecta B.
- AC-06: destroy limpia túnel propio.
- AC-07: status expone public URL cuando está activa.
- AC-08: secretos no aparecen en salida/logs.
- AC-09: otro provider falso puede registrarse sin cambiar lifecycle.

## 9. Tasks
1. Definir `TunnelProvider` y estados.
2. Implementar provider registry.
3. Integrar configuración genérica.
4. Implementar provider zrok.
5. Integrar endpoint/puerto E6-S1.
6. Integrar ordering lifecycle E4.
7. Implementar status/public URL.
8. Implementar stop/cleanup idempotentes.
9. Integrar doctor.
10. Tests con provider falso y runner zrok simulado.
11. Tests de aislamiento multi-target.

## 10. Verificación
La spec se cierra cuando un proyecto puede habilitar exposición temporal por target y otro proyecto puede ignorar completamente la capability sin instalar zrok.

## 11. Resultado esperado
Con E6-S3, la Etapa 6 demuestra que runtime, puertos y exposición pueden asociarse a un workspace mediante capacidades opcionales sin alterar el core genérico.
