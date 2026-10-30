# Instalación y distribución de `ramalio` (E9-S1)

El motor `ramalio` se instala una sola vez por desarrollador y expone el
comando `ramalio`. Cada repositorio cliente solamente aporta su
`.ramalio.toml`; **el repositorio no contiene una copia del motor**
(INV-01).

## 1. Prerrequisitos

- Python `>= 3.11`.
- Git.
- (Opcional, recomendado) [`pipx`](https://pipx.pypa.io/) para instalar el CLI
  en un entorno aislado, fuera del virtualenv de cualquier proyecto (R7).

Las dependencias opcionales de capabilities/integrations (Docker, tmux, zrok,
Kiro) **no** se instalan con el motor y siguen siendo opcionales (INV-06/AC-11).

## 2. Método oficial de instalación (R6)

Instalación aislada con `pipx` desde la fuente autorizada interna (R14):

```bash
pipx install ramalio            # última versión publicada internamente
pipx install ramalio==0.1.0     # versión concreta (pinning, R9/AC-04)
```

Alternativa sin `pipx` (entorno virtual dedicado del usuario, no del proyecto):

```bash
python -m venv ~/.venvs/ramalio
~/.venvs/ramalio/bin/pip install ramalio
# añade ~/.venvs/ramalio/bin al PATH
```

Verifica la instalación (R3/AC-02):

```bash
ramalio --version
```

## 3. Upgrade (R8/AC-05)

```bash
pipx upgrade ramalio            # a la última
pipx install --force ramalio==0.2.0   # a una versión concreta
```

El upgrade es explícito: el CLI nunca cambia de versión durante un comando de
lifecycle (INV-03).

## 4. Reinstalación idempotente (R10/AC-06)

Reinstalar la misma versión no duplica configuración ni rompe el ejecutable:

```bash
pipx install --force ramalio==0.1.0
```

## 5. Versionado (R4/R5)

- Fuente única de verdad: `ramalio.__version__`; `pyproject.toml` la
  deriva dinámicamente.
- Política **SemVer**:
  - *patch*: correcciones compatibles;
  - *minor*: capacidades compatibles;
  - *major*: cambios incompatibles de contrato (CLI o schema de config).

## 6. Compatibilidad de configuración (R11/R12/INV-05)

La configuración puede declarar su versión de schema:

```toml
[meta]
schema_version = 1
```

- Ausente ⇒ se asume la versión soportada por el CLI (compatibilidad hacia
  atrás con configs existentes).
- `schema_version` mayor que la soportada por el CLI ⇒ **fail-closed** con
  `CONFIG_VERSION_UNSUPPORTED`: hay que actualizar el CLI (R12).
- Downgrade del CLI frente a una config más nueva: falla cerrado por la misma
  vía; nunca se interpreta un contrato desconocido (R17/AC-08).

Diagnóstico:

```bash
ramalio doctor      # incluye CLI_VERSION y CONFIG_SCHEMA (R13/AC-09)
```

## 7. Releases y distribución interna (R14/R15/R16/AC-12)

- Cada release oficial se identifica por versión SemVer y **ejecuta la suite de
  conformidad** antes de distribuirse (gate de calidad, AC-12).
- Los artefactos se publican en el canal interno autorizado de iMass; cuando el
  canal soporte checksums/firmas, se incorporan (R15).
- Cada release lleva notas de cambios de comportamiento y compatibilidad
  (`CHANGELOG.md`, R16).
- El empaquetado no incluye tokens, credenciales ni configuración personal
  (R18/AC- seguridad).

## 8. Plataformas soportadas (R19)

- Linux y macOS con Python `>= 3.11`.
- La suite se ejecuta en CI con Git + Python; las integraciones reales
  (docker/tmux/zrok/kiro) son perfiles opcionales y no condicionan el core.

## 9. Uninstall (R20/AC-10)

```bash
pipx uninstall ramalio
```

Desinstalar el CLI **no** toca los `.ramalio.toml` ni los worktrees de
los proyectos: solamente retira el motor.

## 10. Separación motor/proyecto (§7.1)

```text
Máquina del desarrollador
└── paquete ramalio instalado  →  ramalio

Repositorio del proyecto
└── .ramalio.toml   (única contribución del repo)
```
