# Checklist: adopción de un segundo proyecto real (E9-S0)

Esta guía cierra la parte **operacional** de E9-S0: demostrar que un **segundo
proyecto real** de iMass —materialmente distinto a SiVale— puede adoptar
`ramalio` sólo por configuración y operarse cotidianamente, sin
conocimiento del proyecto embebido en el core.

El fixture sintético `pylib-tools` (`tests/conformance/test_second_pilot.py`) ya
prueba la **genericidad del core** en CI, pero no es evidencia de adopción real
(§2, R2, R12). Este checklist produce esa evidencia.

## 1. Seleccionar el proyecto (R1, §5, AC-01)

Elige un repo real que difiera de SiVale en **al menos tres** dimensiones y que
**no** sea un clon operativo de SiVale. Candidatos naturales:

- CLI/worker/library en lugar de aplicación web.
- Sin runtime containerizado (o distinto a docker-compose).
- Sin tmux/Kiro obligatorios; sin puertos exclusivos; sin zrok.
- Convención de target y/o branch naming distintos.
- Bootstrap y teardown distintos.

Registra por escrito por qué el perfil es suficientemente distinto (R1).

## 2. Inventariar el lifecycle actual (R2)

Documenta, tal como se opera hoy (antes de adoptar `ramalio`):

| Aspecto | Valor real del proyecto |
|---|---|
| Unidad de trabajo (target) | |
| Branch base | |
| Naming de branch | |
| Ubicación de worktrees | |
| Bootstrap actual | |
| Provisioning necesario para considerar el workspace listo | |
| Readiness / artifacts / permisos | |
| Procesos administrados | |
| Runtime | |
| Puertos | |
| Herramientas de desarrollo | |
| Teardown | |
| Riesgos conocidos | |

## 3. Escribir `.ramalio.toml` (R3, AC-02)

Adopta una configuración **sólo por contrato**, sin cambios al core. Si algo no
encaja, clasifícalo en el paso 6 en lugar de parchear el core o crear un wrapper
privado indispensable (R9/INV-05).

## 4. Ejecutar el lifecycle mínimo completo (R5, AC-03..AC-08)

Sobre el repo real, y capturando salida:

```bash
ramalio doctor
ramalio init  <TARGET-A>        # primer workspace
# preparar un escenario branch-only para TARGET-B (branch existente sin worktree):
git branch <BRANCH-DE-TARGET-B> <base>   # o destruir su worktree conservando branch
ramalio adopt <TARGET-B>        # incorpora la branch preexistente creando su worktree
# en este punto coexisten dos workspaces (A por init, B por adopt) -> aislamiento (R7)
ramalio list
ramalio status <TARGET-A>
ramalio status <TARGET-B>
ramalio start <TARGET-A>        # si aplican capabilities
ramalio stop  <TARGET-A>
ramalio destroy <TARGET-A>
ramalio destroy <TARGET-B>
```

> Nota: no encadenes `adopt <T>` seguido de `init <T>` sobre el mismo target: tras
> un `adopt` exitoso el workspace ya existe y `init` fallaría con
> `WORKSPACE_ALREADY_EXISTS`. Usa `init` para A y `adopt` para B (o dos `init`
> distintos) para obtener dos workspaces simultáneos.

Verifica: identidades derivadas, aislamiento branch/path (y de cualquier recurso
configurado), y que `destroy` conserva la seguridad ante trabajo local.

## 5. Operación sin capabilities innecesarias (R6, AC-09)

Confirma que las capabilities no requeridas permanecen deshabilitadas y que el
lifecycle Git-only sigue funcionando; una capability opcional nunca debe
convertirse en dependencia.

## 6. Clasificar gaps (R8, AC-11)

Cada divergencia se clasifica como uno de:

`CORE_GAP` · `CONFIG_GAP` · `CAPABILITY_GAP` · `INTEGRATION_GAP` ·
`PROJECT_LOCAL` · `OUT_OF_SCOPE`.

Antes de usar `PROJECT_LOCAL`, verifica si la divergencia es **preparación reusable del workspace**. Un bootstrap distinto no es automáticamente local: si varios proyectos podrían necesitar la misma clase de preparación, clasifícalo como `CAPABILITY_GAP`/provisioning y resuélvelo de forma general. Sólo lógica de negocio, build de producto o deploy debe permanecer `PROJECT_LOCAL` por esa razón.

Un `CORE_GAP` legítimo se corrige de forma **general** (nunca con una condición
por nombre/stack del proyecto, INV-01/AC-10) y luego se revalida SiVale (paso 7).

## 7. No regresión SiVale (R11, INV-04, AC-12)

Tras cualquier corrección general:

```bash
pytest                              # suite completa
pytest tests/conformance            # conformance
```

Ambas deben quedar verdes. Si aplica, re-ejecuta el piloto real de SiVale
(`scripts/validate-sivale-pilot.sh`).

## 8. Archivar evidencia (R12, §11)

Guarda la salida capturada y el veredicto en `docs/evidence/second-pilot-<slug>-<fecha>.md`,
y actualiza `docs/specs/implementation-status.json` (campo `evidence`) para
E9-S0 cuando exista la evidencia real.

El piloto sólo se considera **PASS** cuando el proyecto real puede operar
cotidianamente con `ramalio`, incluyendo el provisioning necesario para dejar
el workspace utilizable, sin scripts indispensables de lifecycle fuera del contrato
y sin conocimiento del proyecto dentro del core (R12).
