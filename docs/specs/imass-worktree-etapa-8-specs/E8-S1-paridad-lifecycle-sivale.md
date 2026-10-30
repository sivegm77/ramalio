# E8-S1 — Paridad con lifecycle existente de SiVale

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E8 — Piloto real sobre SiVale
- **Spec:** E8-S1
- **Nombre:** Paridad con lifecycle existente
- **Dependencias:** E8-S0
- **Bloquea a:** E8-S2

## 2. Contexto
SiVale ya posee un lifecycle de worktrees con garantías operativas acumuladas. La adopción de `imass-worktree` no puede basarse sólo en que los comandos “funcionen”; debe demostrarse que conserva los invariantes relevantes.

El mecanismo existente se mantiene disponible durante esta spec. No se retiran wrappers/scripts hasta demostrar paridad suficiente.

## 3. Objetivo
Comparar de forma reproducible:

```text
lifecycle actual de SiVale
vs.
imass-wt + configuración SiVale
```

para `init`, `adopt`, `start`, `stop`, `status`, `doctor` y `destroy`, incluyendo aislamiento, puertos, runtime y capacidades configuradas.

## 4. Alcance
Incluye:
- matriz de paridad;
- escenarios equivalentes;
- múltiples worktrees simultáneos;
- fallos parciales relevantes;
- branch/worktree naming;
- aislamiento de recursos;
- bootstrap;
- start/stop;
- tmux y Kiro cuando estén habilitados;
- rollback y cleanup;
- evidencia automatizable.

Fuera de alcance:
- retirar el harness actual;
- rediseñar el workflow de specs de SiVale;
- cambiar funcionalidad de negocio del proyecto;
- flexibilizar invariantes sólo para obtener PASS.

## 5. Invariantes de paridad
1. `stdout/stderr` y exit codes deben ser predecibles según contrato de `imass-wt`.
2. Un target identifica inequívocamente su workspace.
3. No hay colisiones de branch, path, puertos o runtime entre workspaces simultáneos.
4. Un fallo parcial no destruye recursos preexistentes.
5. `destroy` nunca borra trabajo útil silenciosamente.
6. `stop` conserva branch, worktree y trabajo local.
7. `start` reanuda recursos sin recrear el workspace Git.
8. Capacidades opcionales pertenecen al target correcto.

## 6. Requirements
### R1 — Matriz de comportamiento
Debe existir una tabla por operación con:
- precondición;
- lifecycle actual;
- `imass-wt`;
- resultado esperado;
- evidencia;
- paridad PASS/FAIL/GAP.

### R2 — Init
Comparar creación de branch/worktree, bootstrap, puertos y runtime configurado.

### R3 — Adopt
Comparar incorporación de branch/worktree existente y protección de trabajo dirty.

### R4 — Start/stop
Verificar que los recursos configurados pueden suspenderse/reanudarse sin destruir identidad.

### R5 — Destroy
Comparar guards, cleanup, branch policy y protección de trabajo local.

### R6 — Paralelismo
Ejecutar al menos dos targets simultáneos y demostrar aislamiento.

### R7 — Puertos
Cuando estén habilitados, cada target obtiene recursos no colisionantes y los libera conforme al lifecycle.

### R8 — Runtime
Los nombres/identidades del runtime deben ser únicos por target y limpiarse correctamente.

### R9 — tmux
Si está habilitado, sesión por target, reattach y cleanup según policy.

### R10 — Kiro/open
La integración debe abrirse desde el worktree correcto y no alterar lifecycle si no se usa.

### R11 — Fallos inducidos
Debe probarse al menos un fallo en init/start/stop/destroy donde exista rollback o cleanup relevante.

### R12 — Gaps
Todo gap debe clasificarse como:
- bug de `imass-worktree`;
- configuración SiVale incorrecta;
- capability faltante legítima;
- comportamiento legado que no debe preservarse.

No se acepta resolver gaps con acoplamiento SiVale en core.

## 7. Diseño de validación
La suite debe crear escenarios reproducibles sobre repositorios/worktrees de prueba o un fixture controlado de SiVale.

La matriz debe cubrir como mínimo:

```text
init nuevo
init duplicado
adopt branch-only
adopt worktree dirty
2 worktrees paralelos
stop/start
status
runtime/puerto si aplica
destroy clean
destroy dirty bloqueado
fallo parcial + rollback
```

## 8. Criterios de aceptación
- AC-01: init conserva invariantes relevantes.
- AC-02: adopt conserva trabajo preexistente.
- AC-03: dos workspaces simultáneos no colisionan.
- AC-04: start/stop funcionan con capabilities configuradas.
- AC-05: destroy bloquea pérdida de trabajo.
- AC-06: fallos parciales tienen salida determinista.
- AC-07: todos los gaps están clasificados.
- AC-08: no se modifica core con excepciones SiVale.

## 9. Tasks
1. Extraer invariantes del lifecycle existente.
2. Construir matriz de paridad.
3. Crear fixtures/escenarios reproducibles.
4. Ejecutar init/adopt/status/start/stop/destroy equivalentes.
5. Ejecutar escenarios paralelos.
6. Inyectar fallos relevantes.
7. Registrar divergencias.
8. Reparar producto o configuración según clasificación.
9. Repetir hasta cerrar blockers de paridad.
10. Emitir reporte final PASS/GAP justificado.

## 10. Verificación
La spec termina cuando las garantías que realmente deben conservarse están cubiertas por evidencia y las divergencias restantes están explícitamente justificadas como no-paridad intencional.

## 11. Resultado esperado
Una matriz verificable que demuestre que `imass-wt` puede sustituir funcionalmente el lifecycle específico de SiVale sin absorber sus particularidades en el core.


## 12. Estado de paridad post-auditoría — GAP de provisioning

La implementación histórica de E8-S1 fue mergeada, pero su cierre operacional queda **bloqueado por E10-S4**.

La auditoría posterior confirmó que R2 exige comparar explícitamente `branch/worktree + bootstrap + puertos + runtime`. La matriz existente probó correctamente varias invariantes, pero no descompuso todo el bootstrap real de SiVale. En particular quedan pendientes hasta E10:

- materialización/configuración runtime necesaria por workspace;
- data provisioning PostgreSQL aislado;
- runtime build/start durante `init/adopt` cuando corresponda;
- dependency provisioning;
- permission/readiness y artifacts;
- cleanup equivalente de runtime/data.

Estos puntos son `CAPABILITY_GAP`/`CONFIG_GAP` a resolver de forma genérica, no autorización para acoplar SiVale al core. `docs/examples/sivale-parity-matrix.md` registra el detalle por responsabilidad.
