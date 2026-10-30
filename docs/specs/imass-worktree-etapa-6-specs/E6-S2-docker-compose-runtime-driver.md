# E6-S2 — Docker Compose runtime driver

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E6 — Runtimes, exposición y recursos opcionales
- **Spec:** E6-S2
- **Nombre:** Docker Compose runtime driver
- **Dependencias:** E6-S0, E6-S1, E4 completada
- **Bloquea a:** E6-S3 en proyectos que expongan runtime, E7

## 2. Contexto
Docker Compose es un caso importante para proyectos web, pero `imass-worktree` no debe convertirlo en requisito universal. Debe implementarse como driver del contrato de runtime establecido en E6-S0.

## 3. Objetivo
Implementar un driver opcional `docker-compose` que pueda arrancar, detener, inspeccionar y limpiar el runtime de un workspace de forma aislada por target.

## 4. Alcance
Incluye: disponibilidad de Docker/Compose, project name aislado, archivos Compose configurables, environment derivado, start/stop/status/cleanup, integración de puertos, doctor y tests con command runner simulado/integración condicionada. Excluye: Docker Swarm, Kubernetes, build/release productivo y administración del daemon.

## 5. Invariantes
- Docker no es dependencia del core.
- Cada target usa un Compose project name único y determinista.
- No usar un project name compartido entre worktrees.
- `stop` preserva workspace y puede liberar procesos sin destruir Git.
- `destroy` limpia recursos Compose del target, no de otros proyectos.
- No ejecutar `docker compose down` sin identidad de proyecto explícita.

## 6. Requirements
### R1 — Configuración
Ejemplo conceptual:
```toml
[capabilities.runtime]
driver = "docker-compose"
compose_file = "compose.yaml"
project_pattern = "{project}-{target}"
```
La configuración exacta puede alinearse con el modelo final de E6-S0.

### R2 — Disponibilidad
Doctor debe comprobar:
- `docker` ejecutable;
- soporte `docker compose`;
- compose file configurado existente.

### R3 — Project name
Debe derivarse de proyecto + target mediante naming seguro y determinista. Debe validarse contra restricciones de Compose.

### R4 — CWD
Todos los comandos se ejecutan desde el worktree del target.

### R5 — Start
Contrato equivalente a:
```bash
docker compose -p <project> -f <file> up -d
```
Los argumentos exactos deben ejecutarse mediante argv seguro, no shell concatenado.

### R6 — Stop
Debe detener runtime preservando la posibilidad de reanudación. La política exacta (`stop` vs operación equivalente) debe evitar eliminar recursos que la configuración espere conservar entre stop/start.

### R7 — Cleanup
En destroy debe retirar los recursos Compose administrados por el target. Volúmenes persistentes no deben eliminarse por defecto salvo configuración explícita y segura futura.

### R8 — Status
Debe mapear estado Compose a estados del runtime contract: RUNNING/STOPPED/DEGRADED/FAILED/UNKNOWN.

### R9 — Puertos
Debe poder recibir el puerto reservado por E6-S1 como variable/configuración del runtime sin hardcodear nombres de variables de SiVale.

### R10 — Environment
Las variables derivadas por `imass-worktree` deben ser explícitas. Secretos no se escriben al TOML versionado.

### R11 — No commands globales ambiguos
Prohibido operar sin `-p`/identidad equivalente cuando eso pudiera afectar otros workspaces.

### R12 — Idempotencia
Start/stop/cleanup repetidos deben ajustarse al contrato E6-S0.

### R13 — Fallos
Deben preservarse códigos de runtime y detalles de Compose sin filtrar secretos.

### R14 — Tests
La mayoría del comportamiento debe poder probarse con runner simulado; integración real con Docker será opcional/condicionada al entorno.

## 7. Diseño
Componente:
```text
capabilities/runtime/docker_compose.py
```
Flujo start:
```text
workspace
→ resolve compose config
→ resolve compose project name
→ inject derived non-secret env
→ docker compose up
→ docker compose status
→ runtime result
```
El driver no conoce Kiro, tmux ni zrok.

## 8. Criterios de aceptación
- AC-01: proyecto sin Docker sigue usando `none`.
- AC-02: project name difiere entre targets.
- AC-03: start usa worktree correcto.
- AC-04: stop no afecta otro target.
- AC-05: cleanup no elimina recursos de otro project name.
- AC-06: status mapea estados correctamente.
- AC-07: doctor detecta Docker/Compose ausente.
- AC-08: puerto reservado puede inyectarse sin regla SiVale-specific.
- AC-09: no se eliminan volúmenes por defecto.

## 9. Tasks
1. Extender configuración del runtime Compose.
2. Implementar naming seguro de Compose project.
3. Implementar doctor del driver.
4. Implementar start.
5. Implementar stop.
6. Implementar status.
7. Implementar cleanup conservador.
8. Integrar port reservation como input opcional.
9. Tests con runner falso.
10. Tests integración condicionados a Docker disponible.

## 10. Verificación
Debe demostrarse aislamiento entre al menos dos targets con project names distintos y ausencia de dependencia Docker en proyectos que no activan el driver.

## 11. Resultado esperado
Docker Compose queda disponible como runtime opcional y aislado, sin contaminar el core ni la experiencia de proyectos no containerizados.
