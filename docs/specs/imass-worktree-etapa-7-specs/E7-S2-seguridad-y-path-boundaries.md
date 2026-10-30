# E7-S2 — Seguridad y path boundaries

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E7 — Robustez, recuperación y conformidad
- **Spec:** E7-S2
- **Nombre:** Seguridad y path boundaries
- **Dependencias:** E1, E2, E4, E5, E6, E7-S0
- **Estado inicial:** Planificada

## 2. Contexto

`imass-worktree` ejecuta comandos externos y administra paths, worktrees, procesos, runtimes y archivos derivados de configuración. La robustez requiere endurecer límites para impedir escapes de directorio, symlink tricks, command injection, lectura/escritura accidental de secretos y destrucción fuera del workspace autorizado.

## 3. Objetivo

Establecer un modelo de seguridad local para inputs, paths y comandos externos que aplique de forma uniforme a core, capabilities e integrations.

## 4. Invariantes

- Configuración es datos, no código.
- No shell concatenation para comandos estructurados.
- Todo path mutable debe pertenecer a un boundary autorizado.
- Symlinks no pueden usarse para escapar del boundary.
- Secrets no se leen/escriben por defecto.
- `destroy` nunca opera sobre un path no verificado.

## 5. Requirements

### R1 — Canonical path service
Debe existir una utilidad central para resolver y comparar paths autorizados.

### R2 — Worktree boundary
Todo worktree derivado debe quedar dentro del boundary configurado para worktrees, salvo un futuro modo explícito con contrato equivalente.

### R3 — Symlink-aware validation
La validación debe considerar componentes existentes y symlinks antes de mutar.

### R4 — No root/current checkout destruction
Nunca permitir que worktree path resuelva al repository root, home, filesystem root o checkout invocador protegido.

### R5 — Path traversal
Rechazar `..`/expansiones que escapen del boundary.

### R6 — Resource paths
Runtime/process/tunnel integrations que acepten cwd/files deben recibir paths ya validados.

### R7 — argv execution
Comandos externos deben ejecutarse con argv estructurado y `shell=False` por defecto.

### R8 — Shell opt-in
Si una capability genérica de procesos requiere shell, debe declararse explícitamente y quedar aislada como riesgo de proyecto cliente; no mezclar input dinámico no confiable sin escaping/contrato.

### R9 — Target as data
El target no debe interpolarse en shell strings sin frontera segura.

### R10 — Secrets boundaries
No leer ni escribir por defecto `.env*`, private keys, credentials directories ni secretos fuera de contratos explícitos.

### R11 — TOML secrets policy
`.imass-worktree.toml` no debe requerir credenciales.

### R12 — Destructive command guard
Antes de remove/delete/cleanup debe comprobarse resource identity + boundary + ownership.

### R13 — Environment inheritance
Procesos externos deben recibir un entorno controlado; variables del host no relacionadas no deben convertirse automáticamente en configuración del producto.

### R14 — Sensitive diagnostics
Errores/logs no deben volcar secretos o environment completo.

### R15 — Executable resolution
`doctor` debe poder validar ejecutables declarados sin ejecutar comandos arbitrarios durante discovery.

### R16 — File permissions
Los archivos de estado/locks personales que puedan contener metadata operacional deben crearse con permisos apropiados para el usuario.

### R17 — Malicious config tests
La suite debe cubrir patterns, paths y commands hostiles.

## 6. Diseño

Servicios conceptuales:

```text
PathBoundaryPolicy
SafePathResolver
CommandSpec(argv, cwd, env, timeout)
SafeProcessRunner
```

Toda capability debe consumir estas fronteras en lugar de construir subprocess y paths independientemente.

## 7. Criterios de aceptación

- AC-01 `../` no escapa del worktree boundary.
- AC-02 symlink dentro del boundary que apunta afuera no autoriza escritura/destrucción externa.
- AC-03 repository root nunca puede ser target de destroy.
- AC-04 target con metacaracteres no se ejecuta como shell.
- AC-05 diagnostics no imprimen environment/secrets completos.
- AC-06 TOML no exige secretos.
- AC-07 procesos usan runner central salvo excepción explícitamente justificada.

## 8. Casos de prueba mínimos

- Path traversal.
- Absolute path fuera de boundary.
- Symlink escape.
- Nested symlink.
- Path igual al repo root.
- Target con `;`, `$()`, backticks, whitespace extraño.
- Process command con argumentos separados.
- Environment con secret marker.
- Error de subprocess sin secret leakage.
- State/lock file permissions.

## 9. Tasks

1. Definir boundary model.
2. Implementar path resolver canonical/symlink-aware.
3. Integrar validación en naming/lifecycle/destroy.
4. Centralizar subprocess runner seguro.
5. Migrar capabilities/integrations al runner.
6. Definir política de shell opt-in.
7. Implementar environment filtering/merging explícito.
8. Implementar redacción de diagnostics sensibles.
9. Endurecer permisos de estado/locks.
10. Crear security regression suite.

## 10. Resultado esperado

El producto puede operar sobre configuración versionada y entradas de usuario sin permitir que paths o comandos se conviertan en mecanismos de escape/destrucción accidental.
