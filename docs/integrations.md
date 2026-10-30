# Catálogo de integrations soportadas (E9-S2 R15)

Las integrations abren una herramienta externa en el worktree ya listo, vía
`ramalio init|start <target> --open <tool>`. Son **opcionales**: ninguna es
dependencia del core y su ausencia no invalida el lifecycle. Un fallo al abrir
la herramienta nunca destruye el workspace.

Se habilitan en `[integrations.<name>]` con `enabled = true` y un `command`
opcional (argv estructurado) que sobrescribe el default.

| Integration | `--open` | Comando por defecto | Notas |
|---|---|---|---|
| Kiro | `--open kiro` | `["kiro-cli"]` | Abre en el worktree del target. |
| VS Code | `--open vscode` | `["code", "."]` | `.` resuelve al worktree, no al checkout principal. |
| Codex | `--open codex` | `["codex"]` | Herramienta interactiva. |
| Claude | `--open claude` | `["claude"]` | Herramienta interactiva. |

## Contrato de `command` (argv estructurado)

`command` es una **lista no vacía de strings** donde cada elemento es
exactamente un argumento. La configuración es datos: no se interpreta como
string de shell ni se aplica separación implícita (`str.split`/`shlex.split`).

```toml
[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]   # opcional; por defecto ["kiro-cli"]
```

Reglas de validación (fail-closed):

- `command` debe ser un array; contener al menos un elemento; y todos sus
  elementos deben ser strings no vacíos.
- Un string como `command = "kiro-cli --v3"` **no** es el formato canónico y se
  rechaza con `PROJECT_CONFIG_INVALID`.

## Environment controlado y `pass_env`

Por defecto una integration recibe únicamente un environment base controlado
(una allowlist de variables esenciales del host); nunca hereda automáticamente
el environment completo del host.

Para reenviar variables adicionales del host se declara `pass_env`, una
**allowlist de nombres** de variables (nunca valores; los valores se leen del
environment de ejecución y no se persisten):

```toml
[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
pass_env = ["AWS_PROFILE", "AWS_REGION"]
```

- `pass_env` es opcional y su default es vacío.
- Debe ser un array de nombres de variable no vacíos; no acepta entradas inline
  tipo `KEY=value`. No se impone una convención de shell: cualquier nombre
  válido para el environment del sistema es aceptado.
- Si un nombre declarado no existe en el environment actual, simplemente no se
  reenvía: el core no inventa un valor ni lee archivos alternativos.
- Las variables sensibles copiadas vía `pass_env` no se imprimen en errores,
  `doctor`, status ni resultados de launch.

> `inherit_env` **no** forma parte del contrato público. Una configuración que
> lo declare se rechaza como clave no soportada dentro de la integration.

- `doctor` valida la disponibilidad del comando de cada integration habilitada
  a partir del primer elemento del argv (FAIL si el ejecutable no está, sin
  lanzar la herramienta); las deshabilitadas no participan.
- Cerrar la herramienta **no** equivale a `stop`/`destroy` del workspace.
- Los defaults son convenciones ampliamente válidas; nunca rutas personales.

## Proponer una nueva integration

Ver el proceso de gobernanza en [`adoption-guide.md`](adoption-guide.md#proponer-una-extensión).
