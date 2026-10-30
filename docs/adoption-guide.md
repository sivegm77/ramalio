# Guía de adopción de `ramalio` (E9-S2)

Estándar para que un proyecto nuevo adopte `ramalio` **por instalación,
configuración y documentación**, sin copiar el motor ni scripts de otro
repositorio y sin modificar el core (INV-01/AC-11).

Documentos relacionados:
[getting-started](getting-started.md) ·
[installation](installation.md) ·
[configuración](configuracion.md) ·
[lifecycle](lifecycle.md) ·
[capabilities](capabilities.md) ·
[integrations](integrations.md) ·
[migración desde scripts](migration-from-scripts.md) ·
[troubleshooting](troubleshooting.md) ·
[versionado y compatibilidad](versioning-and-compatibility.md).

## Prerrequisitos (R2)

- **Universales:** Python `>= 3.11`, Git, `ramalio` instalado.
- **De capabilities habilitadas:** sólo si activas la capability
  (p.ej. `docker` para runtime docker-compose, `tmux`, `zrok`, `kiro-cli`).
- **Del proyecto cliente:** cualquier requisito propio de su stack (no lo impone
  `ramalio`).

## Flujo de adopción (§8)

```text
instalar ramalio → inventariar proyecto → definir target + naming →
crear .ramalio.toml → habilitar sólo capabilities necesarias →
ramalio doctor → init/adopt → list/status → stop/start → destroy →
validar paralelismo cuando aplique → retirar wrappers reemplazados →
marcar proyecto como adoptado
```

## Plantilla mínima (R3)

Copia [`examples/minimal.ramalio.toml`](examples/minimal.ramalio.toml).
No habilita ninguna capability opcional (R4/INV-02). Decide los valores marcados
como `DECIDIR` (nombre, base branch, convención de target, naming de branch y
ubicación de worktrees).

## Perfiles de ejemplo (R5)

1. **Git-only:** la plantilla mínima; también el perfil `pylib-tools`
   ([`examples/second-pilot.ramalio.toml`](examples/second-pilot.ramalio.toml)).
2. **Aplicación con runtime/procesos:** SiVale
   ([`examples/sivale.ramalio.toml`](examples/sivale.ramalio.toml)):
   ports + runtime docker-compose + tmux + Kiro.
3. **CLI/Python sin Docker:** `pylib-tools` (Git-only, sin capabilities).

## Checklist de adopción (R6)

- [ ] `.ramalio.toml` presente y válido (`doctor` → `CONFIG_VALID` PASS).
- [ ] `target.regex`/`example` reflejan la convención del proyecto; un ejemplo
      válido normaliza y valida.
- [ ] `branch.pattern` y `worktree.directory`/`pattern` deciden el naming; el
      path deriva dentro del boundary.
- [ ] `project.base_branch` existe localmente.
- [ ] `ramalio doctor` → Global PASS (o WARN justificado).
- [ ] `ramalio init <target>` crea branch + worktree correctos.
- [ ] `ramalio adopt <target>` incorpora trabajo compatible existente.
- [ ] Si el proyecto requiere preparación adicional para quedar utilizable, clasificarla antes de declarar adopción: si el producto actual no la soporta y corresponde a workspace provisioning reusable, registrar `CAPABILITY_GAP` y **no** declarar adopción completa. Después de implementar E10, `init/adopt` deberán resolver las capacidades E10 soportadas sin scripts manuales de worktree.
- [ ] `ramalio start`/`stop` operan según las capabilities configuradas.
- [ ] `ramalio destroy` bloquea con trabajo dirty y limpia recursos propios.
- [ ] Múltiples workspaces simultáneos aislados (cuando aplique).
- [ ] Sólo las capabilities necesarias están habilitadas.
- [ ] **No hay secretos en el TOML** (ver abajo).

## Configuración compartida vs. personal (R12)

- **Compartida y versionable:** `.ramalio.toml` (naming, capabilities,
  puertos, integrations). Portable entre desarrolladores.
- **Personal / entorno:** identificadores de developer, rango de puertos
  personal, preferencias locales; **no** se versionan en el TOML compartido.

## Secretos (R13)

> **Regla:** No secrets in `.ramalio.toml`.

Tokens, credenciales, `.env` y claves viven fuera del TOML versionado, en el
entorno seguro del desarrollador. El empaquetado del motor tampoco los incluye.

## Definition of adopted (R7)

Un proyecto está **adoptado** cuando puede operar el lifecycle acordado
(`init/adopt/list/status/start/stop/destroy`) mediante `ramalio` sin depender de
scripts legacy indispensables para esas mismas funciones, y sin conocimiento del
proyecto embebido en el core.

Si después de `init` o `adopt` el developer debe ejecutar manualmente un script
indispensable cuya única finalidad sea preparar ese workspace para trabajar, la
adopción está incompleta cuando esa preparación corresponde a workspace
provisioning reusable. Mientras E10 siga planificada, ese caso se registra como
`CAPABILITY_GAP`; no se documenta como feature ya soportada. Scripts de negocio, build de producto o deploy quedan fuera
de esta regla.

## Proponer una extensión

Antes de proponer una nueva capability/integration o un cambio de core,
clasifícala respondiendo (INV-05/R16/AC-09):

1. ¿Es **comportamiento universal** del lifecycle? → posible **core**.
2. ¿Es una **regla del repositorio cliente**? → **configuración**.
3. ¿Es **comportamiento opcional** del lifecycle o preparación reusable del workspace? → **capability / provisioning capability**.
4. ¿Es una **herramienta externa** que se abre desde el workspace? → **integration**.
5. ¿Es build/deploy/lógica de negocio? → **responsabilidad del proyecto cliente**.
6. ¿No encaja? → justificar antes de ampliar el producto.

Sólo (1) toca el core, con una spec explícita y sin condicionales por proyecto.
(2)/(3)/(4) se resuelven por configuración/capability/integration existentes o
nuevas, preservando las fronteras arquitectónicas.

## Onboarding reproducible (R19/AC-10)

Un desarrollador ajeno al desarrollo puede completar este checklist sobre un
repositorio de prueba siguiendo sólo esta documentación, sin conocimiento
tribal. El flujo end-to-end está cubierto de forma automatizada por
`tests/conformance/` (incluyendo el segundo piloto Git-only).
