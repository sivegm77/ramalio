# E8-S0 — Configuración SiVale

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E8 — Piloto real sobre SiVale
- **Spec:** E8-S0
- **Nombre:** Configuración SiVale
- **Dependencias:** E0–E7 completadas
- **Bloquea a:** E8-S1, E8-S2

## 2. Contexto
SiVale será el primer proyecto cliente de referencia de `imass-worktree`. Esta etapa debe demostrar que el producto puede absorber un lifecycle real ya maduro sin trasladar reglas específicas de SiVale al core.

La configuración del proyecto deberá vivir principalmente en `.imass-worktree.toml`. El core seguirá siendo agnóstico a Laravel, Kiro, Docker, tmux y zrok.

## 3. Objetivo
Definir e implementar la configuración real de SiVale sobre `imass-worktree`, expresando sus convenciones de target, naming, worktrees, runtime, puertos, bootstrap, procesos, tmux e integraciones únicamente mediante configuración y capabilities existentes.

## 4. Alcance
Incluye:
- `.imass-worktree.toml` de SiVale;
- target regex y ejemplo;
- normalización;
- branch naming;
- worktree directory;
- base branch;
- puertos;
- runtime Docker Compose si aplica;
- tmux si está habilitado;
- integración opcional con Kiro;
- bootstrap y procesos declarables mediante capabilities existentes;
- `doctor` específico derivado de las capabilities configuradas.

Fuera de alcance:
- agregar reglas SiVale al core;
- modificar el harness legado para acomodar al nuevo producto;
- retirar todavía los scripts actuales;
- alterar contratos funcionales de SiVale;
- introducir capacidades nuevas sin justificar primero que faltan en E4–E7.

## 5. Invariantes
1. SiVale es cliente, no framework del producto.
2. Toda regla específica debe clasificarse como configuración, capability o integration.
3. Ninguna ruta, regex o comando SiVale puede quedar hardcodeado en el core.
4. Los secretos no se almacenan en `.imass-worktree.toml`.
5. El lifecycle público sigue siendo `init/adopt/start/stop/status/destroy`.
6. La configuración debe ser versionable y portable entre desarrolladores, salvo preferencias personales y secretos.

## 6. Requirements
### R1 — Identidad de proyecto
Debe declararse una identidad estable y `base_branch = "main"` salvo que el repositorio real establezca otra autoridad.

### R2 — Target SiVale
Debe soportarse la convención:
`E<etapa>-S<spec>-<slug>`
con regex equivalente a la ya utilizada por el proyecto y ejemplo válido.

### R3 — Normalización
Debe preservar `E<n>-S<n>` y normalizar el slug según reglas configurables, sin lógica especial en el core.

### R4 — Branch naming
Debe representar la convención de branch adoptada por SiVale usando patterns soportados por E1.

### R5 — Worktree directory
Debe representar la ubicación canónica elegida para worktrees de SiVale y respetar los path boundaries de E7-S2.

### R6 — Puertos
SiVale debe declarar el rango/pool de puertos necesario para workspaces paralelos mediante E6-S1.

### R7 — Runtime
Si el lifecycle real requiere Docker Compose, debe configurarse usando el runtime driver de E6-S2, sin volver Docker obligatorio para otros proyectos.

### R8 — Bootstrap
El bootstrap requerido por SiVale debe expresarse usando capacidades/procesos ya soportados. Si una necesidad no cabe en el contrato, debe documentarse como gap y no resolverse con un `if project == sivale`.

### R9 — tmux
Si se habilita, la sesión debe asociarse al target mediante E5-S0 y participar de start/stop/status/destroy.

### R10 — Kiro
La apertura de Kiro debe usar la integration de E5, por ejemplo `--open kiro`, sin convertir Kiro en requisito.

### R11 — doctor
`imass-wt doctor` en SiVale debe validar todas las capabilities realmente habilitadas.

### R12 — Sin secretos versionados
Tokens, `.env`, credenciales y claves permanecen fuera del TOML.

## 7. Diseño
La spec debe producir una configuración cliente equivalente conceptualmente a:

```toml
[project]
name = "sivale-zurich"
base_branch = "main"

[target]
regex = "^E[0-9]+-S[0-9]+-[a-z0-9]+(-[a-z0-9]+)*$"
example = "E7-S8-convergencia-schema-tests"
case_sensitive = true

[target.normalization]
trim = true
lowercase_slug = true
replace_spaces = "-"
collapse_dashes = true
preserve_prefix_segments = 2

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "spec/{target}"
```

Las secciones de puertos/runtime/tmux/Kiro se completarán con los nombres exactos definidos por las specs E4–E6 implementadas.

## 8. Criterios de aceptación
- AC-01: `doctor` reconoce el proyecto SiVale con configuración válida.
- AC-02: target SiVale válido se normaliza y valida sin código especial.
- AC-03: branch/path se derivan desde configuración.
- AC-04: capabilities requeridas aparecen en `status` y `doctor`.
- AC-05: otro proyecto sin Docker/tmux/Kiro sigue funcionando sin cambios.
- AC-06: no existen secretos en el TOML.
- AC-07: no se introducen condicionales específicos de SiVale en el core.

## 9. Tasks
1. Inventariar las reglas operativas reales del lifecycle actual de SiVale.
2. Clasificarlas en core/config/capability/integration/out-of-scope.
3. Crear `.imass-worktree.toml`.
4. Configurar target, normalization, branch y worktree.
5. Configurar puertos/runtime requeridos.
6. Configurar tmux si aplica.
7. Configurar Kiro como integration opcional.
8. Configurar bootstrap/procesos soportados.
9. Ejecutar `doctor` y corregir sólo configuración o gaps legítimos del producto.
10. Crear tests/fixtures de SiVale como proyecto cliente.

## 10. Verificación
La spec termina cuando SiVale puede ser descrito completamente como proyecto cliente sin modificar el core por razones específicas del repositorio.

## 11. Resultado esperado
Un `.imass-worktree.toml` real de SiVale que materializa sus reglas usando contratos ya estabilizados en E0–E7.


## 12. Nota de convergencia post-auditoría (E10)

La implementación histórica de esta spec fue mergeada. Una auditoría posterior de la paridad contra `docs/context/snapshot-scripts.txt` detectó que la frase “bootstrap mediante capabilities existentes” sobreestimó la cobertura real disponible en E7/E8: el producto podía expresar Git, puertos, runtime, tmux e integrations, pero no toda la preparación necesaria para dejar SiVale listo (data provisioning, dependency bootstrap y readiness).

Este hallazgo **no cambia el objetivo original** ni autoriza excepciones SiVale en core. La resolución se planifica en E10 mediante capabilities/providers genéricos. E8-S0 permanece histórica/mergeada y E10-S4 será quien actualice la configuración SiVale una vez que los contratos E10 existan.
