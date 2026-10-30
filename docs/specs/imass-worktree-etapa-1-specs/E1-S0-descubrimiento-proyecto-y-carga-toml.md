# E1-S0 — Descubrimiento del proyecto y carga de TOML

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E1 — Configuración y targets
- **Spec:** E1-S0
- **Nombre:** Descubrimiento del proyecto y carga de TOML
- **Dependencias:** E0-S0, E0-S1
- **Bloquea a:** E1-S1, E1-S2 y cualquier spec posterior que necesite configuración de proyecto
- **Estado inicial:** Planificada

---

## 2. Contexto

`imass-worktree` debe ser un producto genérico. Las particularidades de cada repositorio no deben quedar codificadas dentro del core, sino declararse mediante configuración versionable perteneciente al proyecto cliente.

La fuente compartida principal prevista es:

```text
.imass-worktree.toml
```

Esta spec establece cómo `imass-wt` descubre el proyecto desde el contexto de ejecución, localiza su configuración, la carga, aplica defaults y precedencia, y produce un modelo de configuración válido para el resto del producto.

La resolución del proyecto no debe depender de variables globales específicas de un repositorio como `KIRO_PROJECT_ROOT`.

---

## 3. Objetivo

Implementar el contrato base mediante el cual `imass-worktree`:

1. determina el repositorio/proyecto cliente desde el contexto de ejecución;
2. localiza `.imass-worktree.toml`;
3. carga y parsea la configuración;
4. aplica defaults definidos por el producto;
5. resuelve precedencia entre fuentes de configuración;
6. valida la estructura general de la configuración;
7. entrega un modelo normalizado y tipado al resto de la aplicación;
8. falla con mensajes claros cuando el contexto o la configuración son inválidos.

Al finalizar esta spec, dos proyectos distintos deben poder declarar reglas diferentes sin requerir modificaciones al core.

---

## 4. Alcance

### 4.1 Incluido

- Descubrimiento del repositorio Git desde el directorio actual o un subdirectorio.
- Resolución del root del proyecto.
- Localización de `.imass-worktree.toml` en el root descubierto.
- Carga y parseo de TOML.
- Modelo de configuración inicial.
- Defaults del producto.
- Precedencia de configuración.
- Validación estructural del TOML.
- Errores diagnósticos.
- Base para configuración global/personal sin mezclar secretos con configuración versionada.
- Pruebas unitarias e integración del descubrimiento y carga.
- Ejemplos de configuración representativos de al menos tres perfiles de proyecto.

### 4.2 Fuera de alcance

- Validación semántica completa del `target` — E1-S1.
- Normalización del `target` — E1-S2.
- Expansión de patrones de branch/worktree — E1-S2.
- Creación real de branches o worktrees — E2.
- Capabilities — E4+.
- tmux, Kiro, Codex, VS Code, Docker Compose o zrok.
- Administración de secretos.
- Bootstrap real de un proyecto.
- Puertos o locks.

---

## 5. Principios e invariantes

### INV-01 — El proyecto cliente es la fuente de sus reglas compartidas

Las reglas específicas del repositorio deben provenir del propio proyecto, principalmente de `.imass-worktree.toml`.

### INV-02 — El core no conoce proyectos concretos

No debe existir lógica especial para SiVale, Laravel, Docker, Kiro ni otra tecnología específica.

### INV-03 — El root se deriva del contexto

La herramienta debe poder invocarse desde el root o desde un subdirectorio del repositorio y resolver el mismo proyecto.

### INV-04 — Configuración versionada y personal son conceptos distintos

La configuración compartida puede vivir en el repositorio. Rutas personales, preferencias locales y secretos no deben requerir versionado.

### INV-05 — Los secretos no pertenecen al TOML compartido

El contrato no debe exigir tokens, contraseñas, claves privadas ni credenciales dentro de `.imass-worktree.toml`.

### INV-06 — Fallar temprano

Una configuración inválida debe rechazarse antes de ejecutar operaciones de lifecycle.

### INV-07 — La configuración resuelta debe ser determinista

Con las mismas fuentes de entrada, la configuración efectiva debe ser la misma.

---

# 6. Requirements

## R1 — Descubrimiento del repositorio

El sistema debe localizar el root del repositorio Git asociado al directorio de ejecución.

### Criterios

- Debe funcionar desde el root.
- Debe funcionar desde cualquier subdirectorio rastreable hasta el mismo repositorio.
- Debe detectar cuando el directorio no pertenece a un repositorio Git.
- No debe asumir una ruta absoluta fija.

---

## R2 — Descubrimiento del archivo de proyecto

Una vez resuelto el root, el sistema debe buscar exactamente:

```text
<repository-root>/.imass-worktree.toml
```

La ausencia del archivo debe producir un error de configuración explícito para los comandos que requieran un proyecto administrado.

No se recorrerán directorios padre buscando múltiples TOML una vez identificado el root Git.

---

## R3 — Parseo TOML

El sistema debe parsear `.imass-worktree.toml` utilizando soporte TOML compatible con la versión de Python adoptada por el proyecto.

Los errores de sintaxis deben reportar:

- archivo;
- naturaleza del error;
- ubicación cuando el parser la proporcione;
- código de salida consistente con error de configuración.

---

## R4 — Modelo inicial de configuración

La carga debe producir un modelo interno con, como mínimo, estas áreas conceptuales:

```text
project
target
target.normalization
worktree
branch
capabilities
integrations
```

Las secciones futuras podrán ampliarse sin obligar a que todas estén presentes desde E1.

---

## R5 — Campos mínimos del proyecto

El modelo debe contemplar inicialmente:

```toml
[project]
name = "..."
base_branch = "main"
```

### Reglas

- `project.name` debe ser string no vacío.
- `project.base_branch` debe ser string no vacío.
- Ninguno puede contener valores `null` equivalentes o estructuras complejas.

---

## R6 — Configuración de target

El modelo debe poder cargar, aunque la semántica se valide en specs posteriores:

```toml
[target]
regex = "..."
example = "..."
case_sensitive = true

[target.normalization]
trim = true
lowercase_slug = true
replace_spaces = "-"
collapse_dashes = true
```

---

## R7 — Configuración de worktree y branch

El modelo debe aceptar:

```toml
[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "spec/{target}"
```

La expansión semántica y validación de patrones pertenecen a E1-S2.

---

## R8 — Secciones extensibles

El loader debe preservar y modelar configuración opcional para capacidades e integraciones sin requerir que existan implementaciones concretas en E1.

Ejemplo:

```toml
[capabilities.tmux]
enabled = true

[integrations.kiro]
enabled = true
command = "kiro-cli --v3"
```

E1 sólo debe cargar/configurar; no ejecutar estas herramientas.

---

## R9 — Defaults

El producto debe definir defaults únicamente para valores universales y seguros.

Los defaults:

- deben estar centralizados;
- deben ser observables en pruebas;
- no deben contener supuestos de SiVale ni de un stack concreto;
- no deben inventar secretos;
- no deben activar capabilities externas por defecto.

---

## R10 — Precedencia

La configuración efectiva debe respetar esta jerarquía conceptual, de menor a mayor prioridad:

```text
defaults del producto
        ↓
configuración global/personal del desarrollador
        ↓
.imass-worktree.toml del proyecto
        ↓
variables de entorno soportadas
        ↓
opciones CLI explícitas
```

### Reglas

- Una fuente de mayor prioridad puede sobrescribir únicamente campos que el contrato permita sobrescribir.
- La implementación de cada override debe ser explícita y testeable.
- No se debe permitir que una configuración personal cambie silenciosamente la identidad del proyecto de forma incompatible.
- Los secretos, si aparecen en fases futuras, deben resolverse fuera del TOML compartido.

---

## R11 — Configuración global/personal

La arquitectura debe reservar una fuente de configuración personal fuera del repositorio.

Esta spec debe definir el contrato de precedencia y una interfaz de carga, aunque no es obligatorio incorporar todavía un catálogo amplio de preferencias personales.

No debe existir dependencia obligatoria de un archivo global para usar `imass-worktree`.

---

## R12 — Validación estructural

El loader debe rechazar:

- tipos incorrectos;
- tablas donde se esperaba un escalar;
- valores requeridos vacíos;
- claves críticas con tipos incompatibles;
- configuraciones imposibles de interpretar de forma determinista.

Las claves desconocidas deben seguir una política explícita y estable.

### Decisión

En E1, las claves desconocidas dentro de namespaces conocidos deben producir error de configuración, evitando typos silenciosos.

Namespaces futuros no pueden inventarse sin contrato.

---

## R13 — Mensajes de error

Los errores deben distinguir al menos:

```text
NOT_IN_GIT_REPOSITORY
PROJECT_CONFIG_NOT_FOUND
PROJECT_CONFIG_PARSE_ERROR
PROJECT_CONFIG_INVALID
```

Cada error debe contener una explicación para humanos y un identificador estable para pruebas.

---

## R14 — Modelo reusable

El resto del producto no debe leer `.imass-worktree.toml` directamente.

Debe consumir el modelo de configuración resuelto por esta capa.

---

## R15 — Tres perfiles de ejemplo

La documentación/pruebas de fixtures deben incluir al menos tres configuraciones conceptualmente distintas:

1. proyecto simple, sólo Git worktrees;
2. proyecto web con runtime/capabilities declaradas;
3. proyecto CLI/Python sin Docker ni puertos.

Los ejemplos no necesitan implementar las capabilities todavía.

---

# 7. Diseño

## 7.1 Componentes propuestos

La estructura inicial podrá materializarse gradualmente alrededor de responsabilidades equivalentes a:

```text
src/imass_worktree/
├── core/
│   └── project.py
└── config/
    ├── loader.py
    ├── models.py
    ├── defaults.py
    └── validation.py
```

Los nombres son orientativos; la separación de responsabilidades es obligatoria.

---

## 7.2 Flujo de resolución

```text
directorio actual
      ↓
descubrir root Git
      ↓
resolver proyecto
      ↓
cargar defaults
      ↓
cargar configuración personal disponible
      ↓
cargar .imass-worktree.toml
      ↓
aplicar overrides de entorno permitidos
      ↓
aplicar overrides CLI explícitos
      ↓
validar estructura
      ↓
crear ResolvedProjectConfig
```

---

## 7.3 Modelo conceptual

Se propone un objeto inmutable equivalente a:

```text
ResolvedProjectConfig
├── repository_root
├── project
├── target
├── worktree
├── branch
├── capabilities
└── integrations
```

El modelo debe representar la configuración efectiva, no una mezcla de fuentes sin resolver.

---

## 7.4 Autoridad del repositorio

Git es autoridad para determinar el root real del repositorio.

`.imass-worktree.toml` es autoridad para las reglas compartidas del proyecto.

El loader no debe duplicar estado Git persistente.

---

## 7.5 Paths

Los paths relativos declarados por el proyecto deben interpretarse respecto al root del repositorio salvo que un contrato posterior defina otra base explícita.

No se debe normalizar todavía el path final de worktrees más allá de lo necesario para cargar la configuración.

---

## 7.6 Claves desconocidas

La política fail-closed evita que:

```toml
[worktree]
direcotry = ".local-wt"
```

sea aceptado silenciosamente.

El error debe apuntar a la clave desconocida.

---

## 7.7 Configuración personal

La implementación debe permitir incorporar una fuente personal futura sin mezclarla con la configuración versionada.

No debe exigirse un path global específico de SiVale ni una variable global específica de Kiro.

---

## 7.8 Seguridad

El loader no debe:

- ejecutar comandos arbitrarios contenidos en TOML;
- interpolar shell durante el parseo;
- leer secretos implícitamente;
- seguir includes arbitrarios en E1;
- evaluar expresiones.

TOML es datos, no código.

---

# 8. Criterios de aceptación

## AC-01

Dado un repositorio con `.imass-worktree.toml` válido, ejecutar la resolución desde el root devuelve el modelo esperado.

## AC-02

Ejecutar la resolución desde un subdirectorio del mismo repositorio produce el mismo root y la misma configuración efectiva.

## AC-03

Ejecutar fuera de un repositorio Git falla con `NOT_IN_GIT_REPOSITORY`.

## AC-04

Un repositorio sin `.imass-worktree.toml` falla con `PROJECT_CONFIG_NOT_FOUND`.

## AC-05

TOML sintácticamente inválido falla con `PROJECT_CONFIG_PARSE_ERROR`.

## AC-06

Campos críticos con tipos inválidos fallan con `PROJECT_CONFIG_INVALID`.

## AC-07

Una clave desconocida dentro de una sección conocida es rechazada.

## AC-08

Una capability declarada se carga como configuración, pero no se ejecuta.

## AC-09

Una integración declarada se carga como configuración, pero no se ejecuta.

## AC-10

La precedencia de una propiedad soportada es determinista y está cubierta por tests.

## AC-11

Los ejemplos de tres perfiles distintos pueden cargarse con el mismo core.

## AC-12

Ninguna prueba o implementación requiere Laravel, Docker, Kiro, tmux o zrok para pasar E1-S0.

---

# 9. Casos de prueba mínimos

### CT-01 — Root directo
Repositorio válido, cwd = root.

### CT-02 — Subdirectorio
Repositorio válido, cwd = `src/foo/bar`.

### CT-03 — Fuera de Git
Directorio temporal sin `.git`.

### CT-04 — TOML ausente
Repositorio Git válido sin config.

### CT-05 — TOML roto
Sintaxis inválida.

### CT-06 — Campo obligatorio vacío
`project.name = ""`.

### CT-07 — Tipo incorrecto
`project.base_branch = []`.

### CT-08 — Clave desconocida
`worktree.direcotry`.

### CT-09 — Defaults
Omisión de un campo opcional con default universal.

### CT-10 — Precedencia
Proyecto + override permitido.

### CT-11 — Capability declarada
`capabilities.tmux.enabled = true`.

### CT-12 — Integración declarada
`integrations.kiro.command`.

### CT-13 — Tres proyectos
Fixtures con convenciones diferentes.

---

# 10. Tasks

## T1 — Definir errores de configuración
Crear errores de dominio para los códigos de E1-S0.

## T2 — Implementar descubrimiento de repository root
Encapsular la operación Git necesaria y cubrir root/subdirectorios/no-repo.

## T3 — Implementar modelo de proyecto
Representar repository root e identidad del proyecto.

## T4 — Implementar modelos de configuración
Definir estructuras tipadas/inmutables para las secciones de E1.

## T5 — Implementar defaults
Centralizar únicamente defaults universales.

## T6 — Implementar loader TOML
Leer `.imass-worktree.toml` desde el root resuelto.

## T7 — Implementar validación estructural
Tipos, campos obligatorios, claves desconocidas y errores diagnósticos.

## T8 — Implementar precedencia
Resolver fuentes soportadas en orden determinista.

## T9 — Crear interfaz para configuración personal
Separar el concepto del TOML versionado, sin hacerla obligatoria.

## T10 — Crear fixtures de tres perfiles
Simple Git, web con capabilities declaradas y CLI/Python.

## T11 — Crear tests unitarios
Parser, modelos, defaults, validación y precedencia.

## T12 — Crear tests de integración
Descubrimiento real sobre repositorios Git temporales.

## T13 — Documentar contrato inicial
Actualizar documentación de configuración cuando corresponda.

---

# 11. Verificación

La spec se considera implementada sólo si:

- todos los tests nuevos pasan;
- los tests existentes permanecen verdes;
- la resolución funciona desde root y subdirectorios;
- no hay dependencia de tecnologías opcionales;
- los errores definidos son reproducibles;
- la configuración de tres perfiles distintos se carga con el mismo core.

Comandos exactos de test/lint se definirán conforme quede establecido el toolchain Python del repositorio; esta spec no debe inventar una herramienta que aún no haya sido adoptada formalmente.

---

# 12. Trazabilidad

| Requirement | Diseño | Tasks | Aceptación |
|---|---|---|---|
| R1-R3 | 7.2, 7.4 | T2, T6 | AC-01..05 |
| R4-R8 | 7.1, 7.3 | T4, T6 | AC-06,08,09 |
| R9-R11 | 7.2, 7.7 | T5, T8, T9 | AC-10 |
| R12-R13 | 7.6 | T1, T7 | AC-05..07 |
| R14 | 7.3 | T4, T6 | AC-01 |
| R15 | 7.3 | T10 | AC-11,12 |

---

# 13. Resultado esperado

Después de E1-S0, `imass-worktree` debe contar con una frontera clara entre:

```text
contexto de ejecución
+
Git repository root
+
configuración compartida del proyecto
+
configuración personal opcional
+
overrides explícitos
        ↓
ResolvedProjectConfig
```

Las specs siguientes podrán validar targets y derivar nombres sin volver a decidir cómo se descubre o configura un proyecto.
