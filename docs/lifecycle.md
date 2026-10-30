# Lifecycle común de `ramalio`

Superficie pública estable (misma para todos los proyectos, INV-03):

| Comando | Efecto | Notas de seguridad |
|---|---|---|
| `ramalio init <target>` | Crea branch + worktree canónicos; ejecuta capabilities `after_init` (incluye provisioning opt-in: runtime, data, bootstrap). | No sobrescribe recursos existentes; rollback transaccional ante fallo. |
| `ramalio adopt <target>` | Incorpora branch/worktree preexistente al modelo; ejecuta capabilities `after_adopt` (mismo provisioning que init). | Conserva trabajo dirty; nunca renombra/mueve; rollback sólo de lo creado. |
| `ramalio list` | Vista agregada de workspaces reconocidos. | Read-only; anomalías visibles (DETACHED/PRUNABLE/INCONSISTENT/UNRECOGNIZED). |
| `ramalio status <target>` | Diagnóstico detallado de un target. | Read-only; expected vs observed; destroy-safety; acción sugerida. |
| `ramalio start <target>` | Reactiva recursos de capabilities. | No recrea el workspace Git; idempotente. |
| `ramalio stop <target>` | Suspende recursos de capabilities. | Conserva branch/worktree/trabajo local; idempotente. |
| `ramalio destroy <target>` | Cierre seguro: retira worktree y, opcionalmente, la branch. | Bloquea con trabajo dirty; branch cleanup opt-in y no forzado; limpia recursos propios. |
| `ramalio doctor` | Diagnóstico read-only de proyecto/entorno. | PASS/WARN/FAIL; nunca repara. |
| `--open <tool>` (en init/start) | Abre una integración tras preparar el workspace. | Fallo de apertura no destruye el workspace. |

## Orden de capabilities

El orden de registro (setup: `init`/`adopt`/`start`) es
`processes → tmux → ports → runtime → data → bootstrap → tunnel`. En provisioning
(`after_init`/`after_adopt`) el runtime se prepara antes que `data` (que restaura
la base sobre el runtime) y `bootstrap` (que instala dependencias). En `start`, el
runtime se levanta antes que el túnel; en teardown (`stop`/`destroy`) el orden se
invierte (`tunnel → bootstrap → data → runtime → ports → tmux → processes`), de modo
que el túnel se cierra antes que el runtime y el worktree Git se retira al final.
Los procesos administrados y las sesiones tmux se detienen en `stop`/`before_destroy`
según su configuración.

## Workspace listo (provisioning)

Un proyecto Git-only considera `READY` al workspace en cuanto existe
`target → branch → worktree`. Un proyecto con capabilities de provisioning
(runtime/data/bootstrap) sólo devuelve éxito de `init`/`adopt` cuando esas
capabilities terminan: `init`/`adopt` no reportan éxito si un hook requerido
falla. `start` reactiva recursos y **no** repite el provisioning inicial
destructivo.

## Exit codes (contrato estable)

`0` OK · `2` USAGE_ERROR · `3` CONFIGURATION_ERROR · `4` STATE_ERROR ·
`5` SAFETY_BLOCKED · `6` OPERATION_FAILED · `70` INTERNAL_ERROR ·
`78` NOT_IMPLEMENTED.

Los estados `MISSING` de `status` se reportan como consulta exitosa (exit 0), no
como error.
