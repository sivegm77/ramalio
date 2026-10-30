# E5-S2 — Integraciones iniciales: Kiro, VS Code, Codex y Claude

## 1. Identificación
- Proyecto: imass-worktree
- Etapa: E5 — Integraciones de experiencia de desarrollo
- Spec: E5-S2
- Nombre: Integraciones iniciales
- Dependencias: E5-S1

## 2. Contexto
Con el contrato genérico de E5-S1, el producto puede incorporar adaptadores concretos sin alterar el core. Las primeras integraciones previstas son Kiro, VS Code, Codex y Claude.

## 3. Objetivo
Implementar una primera familia de integraciones opcionales para:
- Kiro;
- VS Code;
- Codex;
- Claude;
respetando un contrato común y permitiendo habilitar sólo las que cada proyecto necesite.

## 4. Alcance
Incluye adapters, comandos configurables/defaults razonables, disponibilidad, `doctor`, apertura desde worktree y tests. Fuera de alcance: instalar las herramientas, autenticar cuentas, gestionar sesiones internas propias de cada producto o imponer flags no portables.

## 5. Invariantes
- Todas son opcionales.
- Cada adapter sólo conoce su herramienta.
- El core no importa módulos concretos de Kiro/VS Code/Codex/Claude.
- Los comandos del proyecto pueden sobrescribir defaults de forma explícita.
- No registrar secretos ni tokens en logs.

## 6. Requirements
### R1 — Kiro integration
Debe poder configurarse, por ejemplo:
```toml
[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
```
Debe abrirse con cwd del worktree.

### R2 — VS Code integration
Debe soportar una configuración equivalente a:
```toml
[integrations.vscode]
enabled = true
command = ["code", "."]
```
El `.` debe resolverse desde cwd del worktree, no desde el checkout principal.

### R3 — Codex integration
Debe soportar comando configurable para lanzar Codex desde el worktree.

### R4 — Claude integration
Debe soportar comando configurable para lanzar Claude desde el worktree.

### R5 — Defaults
Pueden existir defaults de comando sólo cuando sean convenciones ampliamente válidas y fáciles de sobrescribir. No deben codificarse rutas personales.

### R6 — Availability
Cada adapter verifica su ejecutable principal sin abrir la herramienta.

### R7 — Doctor
Si una integración está habilitada pero su ejecutable no está disponible, `doctor` debe reportar FAIL o WARN conforme al contrato de readiness definido; la decisión debe ser consistente y documentada.

### R8 — Disabled tools
Una integración deshabilitada no participa en doctor ni afecta lifecycle.

### R9 — Open
Todas deben reutilizar E5-S1 y devolver un resultado común:
```text
integration
command
cwd
launched
error?
```

### R10 — Interactive tools
El diseño debe permitir herramientas interactivas. No se debe capturar o bloquear su TTY de forma incompatible con el uso normal.

### R11 — tmux coexistence
Si tmux está habilitado, la arquitectura debe permitir que una integración pueda abrirse dentro o fuera de tmux según política futura/configurada, sin hacer de esa combinación un requisito de esta spec.

### R12 — No lifecycle ownership
Cerrar Kiro/VS Code/Codex/Claude no equivale a `stop` o `destroy` del workspace.

### R13 — Extensibilidad
Una quinta integración futura debe poder copiar el mismo patrón sin cambiar el core.

## 7. Diseño
- `integrations/kiro.py`
- `integrations/vscode.py`
- `integrations/codex.py`
- `integrations/claude.py`
- Todos implementan el contrato de E5-S1.
- El registry se construye por registro explícito o discovery controlado.
- Cada adapter transforma config → argv y delega ejecución a un runner común.

## 8. Criterios de aceptación
- Cada integración puede habilitarse de forma independiente.
- `--open kiro|vscode|codex|claude` resuelve el adapter correcto.
- Cwd siempre es el worktree.
- Herramienta ausente se diagnostica sin afectar otras integraciones.
- No existen rutas personales hardcodeadas.
- Proyecto sin ninguna integración sigue operando normalmente.

## 9. Tasks
1. Implementar `KiroIntegration`.
2. Implementar `VsCodeIntegration`.
3. Implementar `CodexIntegration`.
4. Implementar `ClaudeIntegration`.
5. Registrar adapters.
6. Definir defaults/config overrides.
7. Integrar availability/doctor.
8. Cubrir TTY/launch semantics.
9. Unit tests con runner fake.
10. Integration/smoke tests cuando binarios estén disponibles.

## 10. Verificación
La spec termina cuando las cuatro herramientas comparten exactamente el mismo contrato operativo y ninguna altera el core ni el lifecycle fundamental.

## 11. Resultado esperado
Un proyecto puede declarar una o varias herramientas de desarrollo y abrirlas desde el workspace mediante la misma interfaz `--open`, sin convertir ninguna en dependencia de `imass-worktree`.
