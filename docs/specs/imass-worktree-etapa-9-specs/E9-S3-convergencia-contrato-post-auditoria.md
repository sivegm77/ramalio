# E9-S3 — Convergencia contractual post-auditoría

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E9 — Estandarización y adopción en iMass
- **Spec:** E9-S3
- **Nombre:** Convergencia contractual post-auditoría
- **Dependencias:** E5-S2, E7-S2, E7-S3, E9-S1, E9-S2
- **Bloquea a:** cierre contractual definitivo de `imass-worktree`
- **Estado inicial:** Planificada

---

## 2. Contexto

Durante las auditorías posteriores a la implementación de E0–E9 se introdujeron correcciones legítimas de robustez y seguridad. La mayoría corresponde directamente a requirements existentes de E7 y no necesita una nueva spec.

Sin embargo, algunas reparaciones alteraron de hecho la superficie pública de configuración de las integrations y produjeron una divergencia entre:

```text
specs autoritativas
+
.imass-worktree.toml documentado
+
modelo/config loader
+
implementación efectiva
+
tests
```

En particular:

1. E5-S2 define `integrations.<name>.command` como argv estructurado, por ejemplo `command = ["kiro-cli", "--v3"]`, mientras la implementación/documentación actual convergió parcialmente hacia strings y realiza separación posterior.
2. El hardening de E7-S2 introdujo `pass_env` e `inherit_env` como opciones configurables de integrations aunque no existían como contrato público explícito en las specs originales.
3. `pass_env` resuelve una necesidad legítima de environment controlado mediante allowlist explícita; `inherit_env` amplía innecesariamente el contrato y permite heredar el environment completo del host.

Esta spec no autoriza una nueva ronda de hardening. Su única finalidad es reconciliar el contrato público ya afectado, eliminar la ampliación accidental que no sea necesaria y dejar una única autoridad coherente.

---

## 3. Objetivo

Converger el contrato público de integrations para que specs, configuración, implementación, documentación y pruebas describan exactamente la misma semántica, preservando E7-S2 y evitando convertir decisiones internas de auditoría en nuevas features sin necesidad.

El resultado debe:

- restaurar argv estructurado como representación canónica de `command`;
- conservar únicamente un mecanismo explícito y mínimo de allowlist de environment mediante `pass_env`;
- retirar `inherit_env` del contrato público;
- mantener el environment controlado por defecto;
- validar que ningún otro cambio de auditoría haya creado una superficie pública sin autoridad de spec;
- evitar cualquier cambio de arquitectura o lifecycle no necesario para esta convergencia.

---

## 4. Alcance

### 4.1 Incluido

- Contrato de `integrations.<name>.command`.
- Modelo, loader y validación de integrations.
- Contrato público de `pass_env`.
- Eliminación de `inherit_env` como opción soportada del TOML.
- Política default de environment para integrations.
- Ejecución de integrations mediante argv estructurado y `shell=False`.
- Validación fail-closed de tipos/keys públicas de integrations.
- Documentación y ejemplos TOML relacionados con integrations.
- Compatibilidad/schema version cuando el cambio contractual lo requiera según E9-S1.
- Pruebas unitarias y de conformidad que validen literalmente los ejemplos documentados.
- Inventario final de keys públicas introducidas por auditorías que afecten configuración o CLI, limitado a determinar si poseen autoridad previa o deben retirarse/cubrirse aquí.

### 4.2 Fuera de alcance

- Nuevos comandos CLI.
- Nuevas integrations.
- Nuevas capabilities.
- Nuevas políticas de lifecycle.
- Cambios generales a transactions, rollback, ownership o compensation de E7-S0.
- Cambios generales a locks/concurrencia de E7-S1.
- Nuevos mecanismos de path hardening, redaction o subprocess security de E7-S2 salvo el wiring estrictamente necesario para este contrato.
- Rehacer la suite de conformidad de E7-S3.
- Cerrar evidencia operacional pendiente de E8-S1/E8-S2.
- Ejecutar o sustituir el segundo piloto real pendiente de E9-S0.
- Añadir compatibilidad legacy sólo por conveniencia si no existe una necesidad demostrada.

---

## 5. Principios e invariantes

### INV-01 — Una sola autoridad contractual

Una opción pública soportada por `.imass-worktree.toml` debe existir de forma coherente en spec, loader/modelo, implementación, documentación y tests.

### INV-02 — Configuración es datos

`command` se representa como argv estructurado. No se interpreta como shell string ni se aplica parsing shell implícito.

### INV-03 — Environment mínimo por defecto

Una integration no hereda automáticamente el environment completo del host.

### INV-04 — Allowlist explícita

Sólo las variables nombradas mediante `pass_env` pueden copiarse adicionalmente desde el host al proceso de la integration.

### INV-05 — Sin `inherit_env`

`inherit_env` no forma parte del contrato público después de esta spec. Si aparece en configuración, debe rechazarse de forma diagnosticable según el contrato fail-closed de configuración.

### INV-06 — Sin secretos persistidos

`pass_env` contiene nombres de variables, no valores. Los valores se obtienen únicamente del environment de ejecución y no se persisten ni se imprimen completos.

### INV-07 — Seguridad E7-S2 preservada

Las integrations siguen ejecutándose mediante argv, `shell=False`, cwd del worktree y environment controlado.

### INV-08 — Cambio mínimo

No se refactoriza arquitectura fuera de lo necesario para reconciliar el contrato identificado.

### INV-09 — No regresión

Kiro, VS Code, Codex y Claude siguen siendo opcionales y conservan la semántica de E5-S2/E5-S1 fuera de los puntos expresamente reconciliados aquí.

---

## 6. Requirements

### R1 — `command` canónico como argv

La configuración canónica de una integration debe usar una lista no vacía de strings:

```toml
[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
```

Cada elemento representa exactamente un argumento.

### R2 — Sin split implícito

La implementación no debe convertir un string público en argv mediante `str.split()`, `shlex.split()` ni mecanismo equivalente como comportamiento canónico.

### R3 — Validación de `command`

`command` debe:

- ser una lista/array;
- contener al menos un elemento;
- contener únicamente strings no vacíos;
- rechazarse con error de configuración si viola el contrato.

### R4 — Defaults estructurados

Los defaults de Kiro, VS Code, Codex y Claude deben expresarse internamente como argv estructurado y producir la misma ejecución prevista por E5-S2.

Ejemplos conceptuales:

```text
kiro   -> ["kiro-cli"]
vscode -> ["code", "."]
codex  -> ["codex"]
claude -> ["claude"]
```

Los defaults no contienen rutas personales.

### R5 — `pass_env`

Una integration puede declarar opcionalmente:

```toml
[integrations.kiro]
enabled = true
command = ["kiro-cli", "--v3"]
pass_env = ["AWS_PROFILE", "AWS_REGION"]
```

`pass_env` es una allowlist de nombres de variables del host que pueden agregarse al environment controlado del proceso.

### R6 — Validación de `pass_env`

`pass_env`, si existe, debe:

- ser una lista/array;
- contener únicamente nombres no vacíos;
- no aceptar valores inline tipo `KEY=value` como sustituto;
- no persistir valores de environment;
- ser opcional y default vacío.

La implementación puede validar sintaxis razonable de nombres de variable siempre que no imponga una convención innecesariamente específica de un shell o proyecto.

### R7 — Variable ausente

Si un nombre declarado en `pass_env` no existe en el environment actual, la integration no debe inventar un valor ni leer archivos alternativos para resolverlo.

El comportamiento debe ser determinista y documentado. Salvo que la propia herramienta requiera esa variable y falle posteriormente, la ausencia de una variable allowlisted no convierte por sí sola al core en gestor de credenciales.

### R8 — Retiro de `inherit_env`

La opción:

```toml
inherit_env = true
```

no queda soportada.

Debe eliminarse de:

- modelos o helpers públicos;
- validación positiva;
- documentación;
- ejemplos;
- tests que la presenten como feature.

Una configuración que la declare debe ser rechazada como key/opción no soportada dentro del namespace de integration, con semántica de configuración inválida consistente con el loader vigente.

### R9 — Runner seguro

La ejecución final debe seguir delegándose al runner central de E7-S2 con:

- argv estructurado;
- `shell=False`;
- cwd del worktree validado;
- environment controlado base + `pass_env` explícito.

### R10 — No secret leakage

Errores, `doctor`, status o resultados de launch no deben imprimir el environment completo ni valores sensibles copiados mediante `pass_env`.

### R11 — Doctor

`doctor` valida availability a partir del primer elemento del argv efectivo sin lanzar la integration ni interpretar comandos arbitrarios.

### R12 — Compatibilidad de configuración

La implementación debe evaluar el impacto sobre el config schema de E9-S1.

Si el contrato final constituye un cambio incompatible respecto al schema público ya distribuido, debe incrementarse el schema soportado y documentarse la migración correspondiente. Si todavía no existió una release oficial que haya publicado el contrato divergente, puede conservarse el schema actual, pero la decisión debe quedar explícita y cubierta por prueba.

### R13 — Ejemplos ejecutables como contrato

Los snippets TOML documentados para integrations deben formar parte de tests de conformidad o tests de documentación que carguen exactamente esos ejemplos mediante el loader real.

### R14 — Consistencia documental

Como mínimo deben revisarse y reconciliarse:

- `docs/integrations.md`;
- `docs/configuracion.md` cuando describa el modelo relevante;
- `docs/adoption-guide.md` si referencia configuración de integrations;
- `docs/examples/*.imass-worktree.toml` que contengan integrations;
- `docs/versioning-and-compatibility.md` si existe cambio de schema;
- ejemplos/fixtures de tests equivalentes.

### R15 — Inventario post-auditoría limitado

Antes de cerrar la spec, debe inspeccionarse la superficie pública actual para detectar otras keys/opciones/comandos introducidos por auditorías.

Cada elemento encontrado se clasifica como:

```text
COVERED_BY_EXISTING_SPEC
COVERED_BY_E9_S3
INTERNAL_IMPLEMENTATION_DETAIL
REMOVE_AS_ACCIDENTAL_PUBLIC_CONTRACT
OUT_OF_SCOPE_WITH_EXISTING_OWNER
```

No se implementan nuevas features a partir de ese inventario. Cualquier necesidad material distinta debe reportarse por separado y no ampliar E9-S3.

### R16 — Regresión completa

La suite existente de E0–E9 debe seguir pasando después de la convergencia, incluyendo conformance y seguridad.

---

## 7. Diseño

### 7.1 Contrato efectivo de integration

Modelo conceptual:

```text
IntegrationConfig
├── enabled: bool
├── command: tuple[str, ...] | None
└── pass_env: tuple[str, ...]
```

La representación interna exacta puede adaptarse al modelo existente, pero debe conservar tipos estructurados y semántica inmutable equivalente.

### 7.2 Resolución de argv

```text
config command presente
        ↓
validar list[str]
        ↓
argv exacto

config command ausente
        ↓
default del adapter
        ↓
argv exacto
```

No existe fase de tokenización de string.

### 7.3 Resolución de environment

```text
controlled base env
       +
valores presentes de pass_env
       ↓
SafeProcessRunner
```

No existe `inherit all host env` configurable.

### 7.4 Compatibilidad

La implementación debe escoger una sola estrategia basada en evidencia del estado de distribución:

1. **No release oficial con contrato divergente:** corregir directamente al contrato de esta spec y mantener schema si E9-S1 lo permite.
2. **Release oficial ya distribuida con contrato divergente:** tratar la convergencia como cambio de schema/version y documentar migración explícita.

No se añade soporte dual permanente sólo para evitar decidir.

---

## 8. Criterios de aceptación

- **AC-01:** `command = ["kiro-cli", "--v3"]` carga y ejecuta argv exacto.
- **AC-02:** `command = "kiro-cli --v3"` no es el formato canónico y se rechaza según el contrato final.
- **AC-03:** ningún path de producción usa `command.split()` para construir argv de integration desde configuración pública.
- **AC-04:** una integration sin `pass_env` no recibe variables host no pertenecientes al environment controlado base.
- **AC-05:** `pass_env = ["X"]` copia `X` sólo si existe y no imprime su valor en diagnostics.
- **AC-06:** `inherit_env` es rechazado como opción no soportada.
- **AC-07:** Kiro/VS Code/Codex/Claude conservan apertura desde cwd del worktree.
- **AC-08:** `doctor` comprueba availability sin ejecutar la herramienta.
- **AC-09:** los ejemplos oficiales de integrations son cargados por tests usando el loader real.
- **AC-10:** documentación, fixtures y modelo describen el mismo tipo y semántica de `command`/`pass_env`.
- **AC-11:** la decisión sobre config schema queda explícita y testeada.
- **AC-12:** no se añaden comandos, capabilities, integrations ni comportamiento de lifecycle nuevo.
- **AC-13:** el inventario post-auditoría no deja ninguna superficie pública sin clasificación.
- **AC-14:** suite completa y conformance pasan sin regresiones.

---

## 9. Casos de prueba mínimos

1. Integration con default argv.
2. Override `command` con múltiples argumentos.
3. `command` vacío.
4. `command` string en lugar de array.
5. `command` array con elemento no-string.
6. `pass_env` ausente.
7. `pass_env` vacío.
8. `pass_env` con variable existente.
9. `pass_env` con variable ausente.
10. `pass_env` con tipo inválido.
11. `inherit_env = true` rechazado.
12. Secret marker presente en variable allowlisted y ausente de stdout/stderr/doctor.
13. `doctor` valida executable principal del argv sin launch.
14. Snippets de `docs/integrations.md` cargados literalmente.
15. Profiles/ejemplos E8/E9 relevantes cargan con el contrato final.
16. Conformance completa sin regresiones.

---

## 10. Tasks

1. Inventariar la superficie pública de integrations en specs, modelo, loader, adapters, docs y tests.
2. Confirmar y documentar la decisión de compatibilidad/schema conforme a R12.
3. Cambiar `IntegrationConfig.command` a representación estructurada equivalente a `tuple[str, ...] | None` o tipo inmutable equivalente.
4. Ajustar loader y validación para aceptar exclusivamente argv estructurado como contrato público.
5. Eliminar tokenización mediante `split()` del path de ejecución de integrations.
6. Normalizar defaults de Kiro/VS Code/Codex/Claude a argv estructurado.
7. Modelar/validar `pass_env` como allowlist opcional y default vacío.
8. Eliminar soporte de `inherit_env` en configuración pública.
9. Mantener `SafeProcessRunner` con environment controlado y overlay exclusivo de `pass_env`.
10. Reconciliar `doctor` con el executable principal del argv.
11. Actualizar documentación y ejemplos TOML.
12. Añadir tests que carguen literalmente los ejemplos documentados.
13. Añadir regresiones negativas para string command, invalid argv e `inherit_env`.
14. Ejecutar inventario post-auditoría R15 y registrar clasificación de cualquier otra superficie encontrada.
15. Ejecutar suite completa y conformance.
16. Actualizar tracking/CHANGELOG únicamente con el cambio contractual realmente realizado.

---

## 11. Verificación

E9-S3 termina únicamente cuando:

1. el contrato público de integrations tiene una sola representación y semántica;
2. specs, modelo, loader, adapters, docs y tests coinciden;
3. argv permanece estructurado y seguro;
4. `pass_env` es el único mecanismo adicional de herencia explícita soportado para integrations;
5. `inherit_env` dejó de ser contrato público;
6. cualquier impacto de schema/version quedó resuelto explícitamente;
7. no existe otra superficie pública introducida por auditorías sin clasificación;
8. la suite completa pasa sin regresiones;
9. no se amplió el scope hacia nuevas features o nueva arquitectura.

---

## 12. Resultado esperado

Después de E9-S3, `imass-worktree` recupera una única autoridad contractual sobre integrations y configuración post-auditoría. Las mejoras legítimas de seguridad permanecen, la ampliación accidental se elimina y el producto queda preparado para cierre sin seguir acumulando hardening no requerido.


---

## 13. Inventario post-auditoría (R15)

Inspección de la superficie pública actual (keys de `.imass-worktree.toml`,
opciones de integrations y flags de CLI) para clasificar cualquier elemento
introducido por auditorías. No se implementan features nuevas a partir de este
inventario.

### 13.1 Superficie de integrations

| Elemento | Clasificación | Nota |
|---|---|---|
| `integrations.<name>.command` | `COVERED_BY_E9_S3` | Convergido a argv estructurado (`tuple[str, ...]`). |
| `integrations.<name>.pass_env` | `COVERED_BY_E9_S3` | Allowlist explícita mínima; conservada. |
| `integrations.<name>.inherit_env` | `REMOVE_AS_ACCIDENTAL_PUBLIC_CONTRACT` | Retirada; ahora rechazada como clave no soportada. |
| `integrations.<name>.enabled` | `COVERED_BY_EXISTING_SPEC` | E5-S1/E5-S2. |
| `SafeProcessRunner(inherit_env=...)` / `controlled_base_env(inherit=...)` | `INTERNAL_IMPLEMENTATION_DETAIL` | Era el único consumidor del retiro anterior; eliminado por falta de consumidores. No era contrato TOML. |
| `redact_environment` / `redact_diagnostic` | `COVERED_BY_EXISTING_SPEC` | Hardening de diagnósticos de E7-S2 R14. |

### 13.2 Otros namespaces del TOML

| Namespace/clave | Clasificación | Owner |
|---|---|---|
| `meta.schema_version` | `COVERED_BY_EXISTING_SPEC` | E9-S1. |
| `project.*`, `target.*`, `target.normalization.*`, `worktree.*` | `COVERED_BY_EXISTING_SPEC` | E1-S0/E1-S2. |
| `branch.delete_on_destroy` | `COVERED_BY_EXISTING_SPEC` | E2-S3. |
| `ports.*` | `COVERED_BY_EXISTING_SPEC` | E6-S1. |
| `capabilities.*` | `COVERED_BY_EXISTING_SPEC` | E4-S0 y capabilities específicas. |

### 13.3 Flags de CLI

| Flag/subcomando | Clasificación | Owner |
|---|---|---|
| `--version` | `COVERED_BY_EXISTING_SPEC` | E9-S1. |
| `--open <tool>` | `COVERED_BY_EXISTING_SPEC` | E5-S1. |
| `init`/`adopt`/`destroy`/`list`/`status`/`doctor`/`start`/`stop` | `COVERED_BY_EXISTING_SPEC` | E2/E3/E4. |

Resultado: ninguna superficie pública queda sin clasificación. La única
ampliación accidental (`inherit_env`) se retiró; el resto tiene autoridad de
spec previa o quedó cubierto por E9-S3.

---

## 14. Decisión de compatibilidad de schema (R12) con evidencia

Decisión: **no se incrementa el schema de configuración; se mantiene `schema_version = 1`** y se corrige directamente al contrato canónico (design §7.4, opción 1).

### 14.1 Evidencia histórica de la precondición

La opción 1 es válida porque **antes de E9-S3 ninguna release oficial distribuyó el contrato divergente** (string `command` / `inherit_env`). Esto es un hecho *histórico*, verificado en el momento de escribir esta spec (rama `e9-s3-convergencia-contrato-post-auditoria`, sobre `main` en `c9bdea9`). Comprobaciones realizadas y su resultado en ese momento:

- **Sin tags git** locales ni remotos: `git tag --list` y `git ls-remote --tags origin` vacíos.
- **Sin GitHub releases**: `gh release list` vacío.
- **Sin commits** de release/publish del artefacto en toda la historia: `git log --all` sin entradas de publicación.
- **Sin artefacto en el canal interno de iMass**: la distribución oficial se realiza a través del canal interno autorizado (`docs/installation.md` §7). Se verificó que no existe un paquete `imass-worktree` publicado en ese canal correspondiente al contrato divergente; `docs/installation.md` documenta el *procedimiento* de instalación (`pipx install imass-worktree==0.1.0`), no una publicación efectuada. (Si el canal interno no fuese consultable en un futuro re-análisis, la ausencia debe re-confirmarse antes de reutilizar esta decisión, no asumirse.)
- El contrato divergente sólo existió en el árbol de trabajo posterior a la auditoría; nunca fue empaquetado en una versión etiquetada ni publicada.

Esta evidencia es **histórica y no se re-deriva dinámicamente**: una release *futura* del contrato ya correcto (por ejemplo, etiquetar `v0.1.0` tras esta convergencia) es legítima y no invalida la decisión. Por eso los tests **no** afirman que el repositorio deba permanecer sin tags para siempre.

### 14.2 Propiedad durable verificada por prueba

Lo que sí se fija por prueba es la propiedad perdurable de la decisión:

- `tests/unit/test_integrations_doc_contract.py::test_schema_decision_no_bump_required` fija `SUPPORTED_CONFIG_SCHEMA == 1` y falla si un cambio incrementa el schema sin revisar esta decisión.
- `test_schema_v1_config_without_meta_is_accepted` y `test_explicit_schema_v1_meta_is_accepted` demuestran, con el loader real, que el contrato final (argv `command` + `pass_env`) es expresable bajo schema v1 sin migración.

Si en el futuro se distribuyera una versión etiquetada con un contrato divergente respecto al schema v1, la decisión debería reevaluarse hacia la opción 2 (incrementar schema + migración documentada); esa reevaluación es un acto explícito, no una consecuencia automática de la existencia de tags.
