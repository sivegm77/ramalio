# E4-S0 — Capability contract y registry

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E4 — Capacidades y procesos
- **Spec:** E4-S0
- **Nombre:** Capability contract y registry
- **Dependencias:** E3-S0, E3-S1, E3-S2, E3-S3
- **Bloquea a:** E4-S1, E4-S2, E5, E6
- **Estado inicial:** Planificada

---

## 2. Contexto

Al finalizar E3, `imass-worktree` ya dispone del lifecycle público:

```text
init
adopt
destroy
list
status
doctor
start
stop
```

El siguiente paso es permitir que un workspace coordine comportamientos adicionales sin acoplar el core a herramientas concretas.

Ejemplos futuros:

- procesos;
- tmux;
- runtime;
- túneles;
- Docker Compose;
- zrok.

Estas funciones no deben convertirse en dependencias universales ni introducir condicionales específicos por herramienta dentro del core.

---

## 3. Objetivo

Definir e implementar el contrato común de capability y un registry que permita:

1. declarar capabilities disponibles;
2. habilitarlas o deshabilitarlas por proyecto;
3. resolver su configuración;
4. consultar su estado;
5. exponer sus requisitos a `doctor`;
6. permitir que lifecycle y status trabajen con una interfaz común;
7. incorporar nuevas capabilities sin modificar la lógica central.

---

## 4. Alcance

### Incluido

- Interface/protocol base de capability.
- Identidad única de capability.
- Registry.
- Enable/disable por configuración.
- Configuración específica namespaced.
- Estados comunes.
- Resultado estructurado.
- Errores de capability.
- Integración base con `status`.
- Integración base con `doctor`.
- Tests con capabilities fake/simuladas.

### Fuera de alcance

- Hooks de lifecycle — E4-S1.
- Procesos reales — E4-S2.
- tmux — E5.
- Docker Compose/zrok — E6.
- Discovery dinámico por paquetes externos.
- Marketplace de plugins.
- Carga de código arbitrario desde TOML.

---

## 5. Principios e invariantes

### INV-01 — Capability opcional

Ninguna capability concreta es obligatoria para usar el core.

### INV-02 — Core agnóstico

El core conoce el contrato, no implementaciones concretas.

### INV-03 — Configuración por proyecto

El proyecto cliente decide qué capabilities están habilitadas.

### INV-04 — Identidad estable

Cada capability tiene un nombre único y determinista.

### INV-05 — Status observable

Toda capability habilitada debe poder reportar estado.

### INV-06 — Doctor extensible

Toda capability puede declarar checks de disponibilidad/configuración.

### INV-07 — TOML no ejecuta código

La configuración selecciona capacidades conocidas por la instalación; no referencia módulos arbitrarios.

---

# 6. Requirements

## R1 — Capability protocol

Debe existir un contrato equivalente a:

```text
Capability
├── name
├── is_enabled(config)
├── status(context)
└── doctor_checks(context)
```

Las operaciones de lifecycle se conectarán en E4-S1.

---

## R2 — Nombre único

Cada capability debe declarar un identificador estable, por ejemplo:

```text
processes
tmux
runtime
tunnel
```

No pueden coexistir dos registrations con el mismo nombre.

Error:

```text
CAPABILITY_DUPLICATE
```

---

## R3 — Registry

Debe existir un registry responsable de:

- registrar implementations conocidas;
- resolver una capability por nombre;
- enumerar capabilities;
- filtrar habilitadas según configuración.

---

## R4 — No auto-import arbitrario

El registry no debe cargar módulos desde paths o strings de configuración suministrados por el proyecto.

---

## R5 — Configuración namespaced

La configuración debe vivir bajo:

```toml
[capabilities.<name>]
enabled = true
```

Cada capability puede definir campos adicionales en specs posteriores.

---

## R6 — Default seguro

Una capability no declarada o sin `enabled=true` debe considerarse deshabilitada, salvo que una spec posterior justifique explícitamente otro comportamiento.

---

## R7 — Estados comunes

El contrato debe soportar como mínimo:

```text
DISABLED
READY
ACTIVE
STOPPED
DEGRADED
ERROR
UNKNOWN
```

No todas las capabilities necesitan usar todos los estados.

---

## R8 — Capability status result

Debe existir una representación equivalente a:

```text
CapabilityStatus
├── name
├── state
├── summary
└── details?
```

---

## R9 — Integración con workspace status

`imass-wt status <target>` debe incorporar:

```text
capabilities:
  - ...
```

para capabilities habilitadas.

Una capability deshabilitada puede omitirse o mostrarse como `DISABLED` según el formato final, pero la decisión debe ser consistente.

---

## R10 — Aislamiento de fallos

Si una capability falla al consultar status:

- `status` del workspace no debe colapsar sin explicación;
- debe reportar la capability como `ERROR`;
- debe conservar el resto de la información disponible.

---

## R11 — Doctor registration

Una capability debe poder aportar uno o más checks a `doctor`.

El core de doctor no debe conocer nombres concretos como tmux o Docker.

---

## R12 — Capability config validation

Cada capability debe poder validar su propia configuración namespaced.

Errores deben mapearse a:

```text
CAPABILITY_CONFIG_INVALID
```

con nombre de capability y detalle.

---

## R13 — Capabilities desconocidas

Si el TOML habilita una capability no registrada:

```text
CAPABILITY_UNKNOWN
```

Debe ser FAIL en `doctor` y error al ejecutar lifecycle que dependa de la configuración válida.

---

## R14 — Orden determinista

El registry y las ejecuciones deben mantener un orden estable.

Decisión inicial:

```text
orden de registro explícito
```

No depender del hash/dict order como contrato implícito.

---

## R15 — Tests con fakes

La suite debe incluir al menos:

- capability deshabilitada;
- habilitada READY;
- ACTIVE;
- error en status;
- config inválida;
- duplicate registration;
- unknown capability.

---

# 7. Diseño

## 7.1 Estructura conceptual

```text
capabilities/
├── base.py
└── registry.py
```

---

## 7.2 CapabilityContext

Las capabilities deben recibir contexto suficiente sin acoplarse al CLI.

Conceptualmente:

```text
CapabilityContext
├── project
├── workspace_identity?
├── workspace_status?
└── config
```

---

## 7.3 Registry explícito

En E4 el registry puede construirse explícitamente por código.

No se necesita plugin discovery dinámico todavía.

---

## 7.4 Error boundaries

Cada llamada a capability debe estar envuelta por una frontera que convierta excepciones no controladas en resultados diagnósticos estables.

---

# 8. Criterios de aceptación

## AC-01

Una fake capability puede registrarse sin modificar core lifecycle.

## AC-02

Duplicate registration falla.

## AC-03

Capability deshabilitada no participa.

## AC-04

Capability habilitada aparece en status.

## AC-05

Fallo de status de una capability no destruye el status completo.

## AC-06

Doctor recibe checks desde registry.

## AC-07

Capability desconocida en configuración falla explícitamente.

## AC-08

No existe carga de código arbitrario desde TOML.

---

# 9. Tasks

## T1 — Definir contrato base de capability
Protocol/interface y modelos.

## T2 — Definir estados y resultados
`CapabilityStatus`.

## T3 — Implementar registry
Registration, lookup, enabled list.

## T4 — Integrar config namespaced
Validación base.

## T5 — Implementar unknown/duplicate errors
Contratos estables.

## T6 — Integrar status
Colección de capabilities.

## T7 — Integrar doctor
Checks aportados por capability.

## T8 — Implementar error boundary
Status/checks.

## T9 — Crear fake capabilities
Fixtures de test.

## T10 — Tests unitarios e integración
Todos los casos mínimos.

---

# 10. Verificación

La spec está completa cuando una capability simulada puede:

- registrarse;
- habilitarse por TOML;
- validar configuración;
- aparecer en status;
- aportar doctor checks;

sin que el core conozca su implementación concreta.

---

# 11. Resultado esperado

Después de E4-S0, `imass-worktree` dispone de una frontera estable para capacidades opcionales y puede crecer sin convertir el lifecycle en una colección de casos especiales.
