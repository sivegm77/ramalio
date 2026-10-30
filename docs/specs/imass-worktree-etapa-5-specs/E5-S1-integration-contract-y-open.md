# E5-S1 — Integration contract y `--open`

## 1. Identificación
- Proyecto: imass-worktree
- Etapa: E5 — Integraciones de experiencia de desarrollo
- Spec: E5-S1
- Nombre: Integration contract y `--open`
- Dependencias: E4, E5-S0 no obligatoria funcionalmente

## 2. Contexto
`imass-worktree` debe poder llevar al desarrollador desde un workspace listo hasta la herramienta donde trabajará, sin acoplar el producto a Kiro, VS Code, Codex, Claude u otra herramienta concreta.

## 3. Objetivo
Definir un contrato genérico de integraciones y soportar:
```bash
imass-wt init <target> --open <tool>
imass-wt start <target> --open <tool>
```
cuando corresponda, manteniendo las herramientas como integraciones opcionales.

## 4. Alcance
Incluye registry de integraciones, configuración, validación, comando externo seguro, `--open`, disponibilidad en doctor y resultados estructurados. Fuera de alcance: implementación específica de Kiro/VS Code/Codex/Claude, que pertenece a E5-S2.

## 5. Invariantes
- Ninguna integración es dependencia del core.
- `--open` no cambia la semántica fundamental de init/start.
- Fallar al abrir una herramienta no puede corromper el workspace ya creado.
- Los comandos se ejecutan con cwd del worktree.
- No se usa shell interpolation insegura.

## 6. Requirements
### R1 — Contrato de integración
Debe existir una interfaz/protocolo equivalente a:
```text
Integration
├── name
├── is_available()
├── validate_config()
└── open(workspace_context)
```

### R2 — Registro
Las integraciones deben resolverse por nombre mediante un registry extensible.

### R3 — Configuración
Ejemplo conceptual:
```toml
[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
```
La representación concreta debe evitar comandos shell concatenados cuando sea posible.

### R4 — `--open`
El CLI debe aceptar una integración explícita por nombre.

### R5 — Tool unknown
Nombre no registrado:
```text
INTEGRATION_NOT_FOUND
```

### R6 — Disabled
Integración conocida pero deshabilitada:
```text
INTEGRATION_DISABLED
```

### R7 — Unavailable
Binario/comando no disponible:
```text
INTEGRATION_UNAVAILABLE
```

### R8 — Workspace first
En `init --open`, primero debe quedar creado/verificado el workspace y después abrirse la herramienta.

### R9 — Failure isolation
Si `open` falla después de un `init` exitoso, el workspace no se destruye automáticamente. Debe devolverse resultado parcial claro.

### R10 — Working directory
La integración se abre usando el worktree del target como cwd.

### R11 — Environment
La integración puede recibir un environment explícito y controlado, sin volcar secretos en logs.

### R12 — Doctor
Cada integración habilitada puede aportar un check de disponibilidad.

### R13 — Status
`status` puede mostrar integraciones configuradas/disponibles, pero no fingir que están “running” si el contrato no lo puede observar.

### R14 — Extensibilidad
Agregar una nueva integración no debe requerir modificar `init`, `start`, `stop` o `destroy`.

## 7. Diseño
- `integrations/base.py`: contrato.
- `integrations/registry.py`: lookup por nombre.
- `OpenIntegrationService`: orquestación tras workspace ready.
- `commands` sólo parsea `--open` y delega.
- Los errores de apertura se modelan como resultados estructurados y no como rollback del lifecycle Git.

## 8. Criterios de aceptación
- `init` sin `--open` no cambia.
- `--open foo` resuelve integración por registry.
- Unknown/disabled/unavailable producen errores distintos.
- El cwd usado es el worktree.
- Fallo al abrir no elimina el workspace.
- Doctor puede validar integraciones habilitadas.
- Una integración fake puede añadirse sin tocar lifecycle central.

## 9. Tasks
1. Definir contrato `Integration`.
2. Crear registry.
3. Extender config de integrations.
4. Implementar `OpenIntegrationService`.
5. Añadir `--open` a CLI aplicable.
6. Implementar manejo de resultado parcial.
7. Integrar doctor/status.
8. Crear fake integration para tests.
9. Cubrir unit e integration tests.

## 10. Verificación
La spec termina cuando una integración ficticia puede registrarse y abrirse desde un workspace sin modificar la lógica central del lifecycle.

## 11. Resultado esperado
`imass-worktree` obtiene un mecanismo general para abrir herramientas desde el workspace, manteniendo totalmente opcional cada herramienta concreta.
