# Versionado y compatibilidad (E9-S2 R17)

Complementa [`installation.md`](installation.md).

## Versión del producto (SemVer)

- Fuente única: `ramalio.__version__` (`pyproject.toml` la deriva).
- `ramalio --version` reporta la versión instalada.
- *patch*: correcciones compatibles · *minor*: capacidades compatibles ·
  *major*: cambios incompatibles de contrato (CLI o schema de config).

## Schema de configuración

El proyecto puede declarar la versión de schema:

```toml
[meta]
schema_version = 1
```

- **Ausente** ⇒ se asume el schema soportado por el CLI (compatibilidad hacia
  atrás con configs existentes).
- **Mayor que el soportado** ⇒ `CONFIG_VERSION_UNSUPPORTED` (fail-closed):
  actualiza el CLI.
- **Downgrade del CLI** frente a una config más nueva ⇒ falla cerrado por la
  misma vía; nunca se interpreta un contrato desconocido.

`ramalio doctor` incluye `CLI_VERSION` y `CONFIG_SCHEMA`.

## Compatibilidad de configuración entre versiones

- Una versión *minor* puede añadir claves/capabilities opcionales manteniendo
  válidas las configs anteriores.
- Un cambio incompatible de schema incrementa `schema_version` (y la *major* del
  producto), y las configs deben declararlo explícitamente.
