# E9-S1 — Instalación y distribución empresarial

## 1. Identificación

- **Proyecto:** imass-worktree
- **Etapa:** E9 — Estandarización y adopción en iMass
- **Spec:** E9-S1
- **Nombre:** Instalación y distribución empresarial
- **Dependencias:** E9-S0
- **Bloquea a:** E9-S2 y consolidación del producto
- **Estado inicial:** Planificada

---

## 2. Contexto

Después de validar el producto en más de un proyecto, `imass-worktree` necesita una forma oficial de instalarse, actualizarse y versionarse dentro de iMass.

La distribución no debe depender de copiar el repositorio manualmente, copiar scripts entre proyectos ni editar cada proyecto para instalar el motor.

El objetivo es que el comando:

```text
imass-wt
```

sea una herramienta del desarrollador y que cada repositorio sólo tenga que aportar su configuración compartida.

---

## 3. Objetivo

Definir e implementar un mecanismo oficial y reproducible para:

- instalar `imass-worktree`;
- exponer `imass-wt` en PATH;
- conocer la versión instalada;
- actualizar a una versión concreta o estable;
- conservar compatibilidad con configuración del proyecto;
- separar instalación del motor de configuración cliente;
- permitir diagnóstico de versión y entorno.

---

## 4. Alcance

### 4.1 Incluido

- Empaquetado Python instalable.
- Entry point `imass-wt`.
- Versionado semántico del producto.
- Fuente única de versión.
- Instalación por método oficial documentado.
- Upgrade.
- Reinstalación idempotente.
- Verificación de versión.
- Política inicial de compatibilidad de `.imass-worktree.toml`.
- Configuración global/personal del developer, si aplica.
- Estrategia de distribución interna.
- Rollback/downgrade documentado cuando sea razonable.
- CI/release checks necesarios para producir artefactos confiables.

### 4.2 Fuera de alcance

- Publicación pública obligatoria en PyPI.
- Auto-update silencioso.
- Instalación automática de Docker, tmux, zrok, Kiro u otras tools.
- Gestión de secretos.
- Gestión de permisos sudo.
- Provisionamiento completo del equipo del desarrollador.
- Onboarding de proyecto — E9-S2.

---

## 5. Principios e invariantes

### INV-01 — Motor separado del proyecto

El repositorio cliente no contiene una copia del motor.

### INV-02 — Instalación reproducible

Una misma versión del paquete debe producir el mismo CLI esperado.

### INV-03 — Sin auto-update oculto

La herramienta no cambia de versión durante un comando de lifecycle.

### INV-04 — Versiones observables

El usuario debe poder consultar la versión instalada.

### INV-05 — Compatibilidad explícita

Una versión incompatible con la configuración debe fallar de forma diagnosticable, no interpretar silenciosamente un contrato desconocido.

### INV-06 — Dependencias opcionales siguen opcionales

Instalar `imass-worktree` no debe instalar ni requerir todas las integrations/capabilities externas.

---

## 6. Requirements

### R1 — Paquete instalable

`pyproject.toml` debe declarar un paquete instalable coherente con la estructura `src/` del proyecto.

### R2 — Entry point

La instalación debe exponer:

```bash
imass-wt
```

sin wrappers específicos de cada repositorio.

### R3 — Versión

Debe existir:

```bash
imass-wt --version
```

o equivalente consistente con el contrato CLI.

### R4 — Fuente única de versión

La versión no debe mantenerse manualmente en múltiples archivos divergentes.

### R5 — SemVer

La política inicial utilizará Semantic Versioning para distinguir:

- patch: correcciones compatibles;
- minor: capacidades compatibles;
- major: cambios incompatibles de contrato.

### R6 — Método oficial de instalación

Debe definirse al menos un método oficial soportado para desarrolladores iMass.

La elección concreta puede ser, por ejemplo, una instalación Python aislada o gestor equivalente, pero debe evitar contaminar entornos de proyecto.

### R7 — Entorno aislado

La instalación del CLI no debe depender del virtualenv del proyecto cliente.

### R8 — Upgrade explícito

Debe existir procedimiento soportado para actualizar de versión.

### R9 — Pinning

Debe ser posible instalar una versión concreta para reproducibilidad y rollback.

### R10 — Idempotencia

Reinstalar la misma versión no debe generar configuraciones duplicadas ni romper el executable.

### R11 — Config schema version

La configuración del proyecto debe contar con un mecanismo explícito de compatibilidad/versionado de schema cuando el contrato lo requiera.

No se debe asumir que todo TOML futuro es eternamente compatible.

### R12 — Incompatibilidad

Si una configuración requiere una versión/schema no soportada:

```text
CONFIG_VERSION_UNSUPPORTED
```

o código equivalente.

### R13 — Doctor de versión

`doctor` debe poder comprobar al menos:

- versión del CLI;
- compatibilidad de config;
- availability de dependencies configuradas mediante sus checks existentes.

### R14 — Distribución interna

Debe documentarse la fuente autorizada de releases/artefactos internos.

### R15 — Integridad

La estrategia de release debe minimizar riesgo de instalar artefactos ambiguos o no versionados.

Cuando el canal elegido soporte hashes/signatures/checksums, deberán incorporarse de forma razonable.

### R16 — Release notes

Cada release distribuible debe tener notas suficientes para conocer cambios de comportamiento y compatibilidad.

### R17 — Downgrade

Debe documentarse qué ocurre al instalar una versión anterior frente a una configuración más nueva.

Debe fallar cerrado cuando no pueda garantizar compatibilidad.

### R18 — Sin secret material

El empaquetado no incluye tokens, credenciales ni configuraciones personales de desarrolladores.

### R19 — Platform scope

Deben declararse plataformas soportadas inicialmente por el producto y probarse en CI cuando sea viable.

No se debe prometer soporte no validado.

### R20 — Uninstall

Debe existir procedimiento para retirar el CLI sin tocar `.imass-worktree.toml` ni worktrees de los proyectos.

---

## 7. Diseño

### 7.1 Separación

```text
Developer machine
└── installed imass-worktree package
    └── imass-wt

Project repository
└── .imass-worktree.toml
```

### 7.2 Version compatibility

Flujo conceptual:

```text
CLI version
   +
config schema/version
      ↓
compatibility check
   ├─ compatible → continue
   └─ incompatible → fail closed
```

### 7.3 Releases

Cada release oficial debe producir artefactos identificables por versión y ejecutar previamente la suite de conformidad del producto.

---

## 8. Criterios de aceptación

- **AC-01:** El paquete se instala en un entorno limpio soportado.
- **AC-02:** `imass-wt --version` reporta versión correcta.
- **AC-03:** El CLI funciona fuera de un virtualenv del proyecto.
- **AC-04:** Puede instalarse una versión concreta.
- **AC-05:** Upgrade explícito funciona.
- **AC-06:** Reinstalación de misma versión es segura.
- **AC-07:** Config compatible funciona tras upgrade soportado.
- **AC-08:** Config incompatible falla de forma explícita.
- **AC-09:** `doctor` reporta compatibilidad de versión.
- **AC-10:** Uninstall no elimina datos/worktrees del proyecto.
- **AC-11:** La instalación no introduce Docker/tmux/zrok/Kiro como dependencias universales.
- **AC-12:** Un release ejecuta gates de conformidad antes de distribuirse.

---

## 9. Tasks

1. Consolidar metadata de paquete en `pyproject.toml`.
2. Definir entry point `imass-wt`.
3. Definir fuente única de versión.
4. Implementar `--version`.
5. Adoptar política SemVer.
6. Elegir y documentar canal/método oficial de instalación interna.
7. Implementar procedimiento de instalación limpia.
8. Implementar/prescribir pinning de versión.
9. Implementar procedimiento de upgrade.
10. Definir compatibilidad/versionado de config schema.
11. Integrar compatibilidad en loader/doctor.
12. Definir comportamiento fail-closed en downgrade/incompatibilidad.
13. Integrar release checks con suite de conformidad.
14. Definir artefactos oficiales y notas de release.
15. Documentar uninstall.
16. Probar instalación/upgrade/uninstall en plataformas soportadas.

---

## 10. Verificación

La spec termina cuando un desarrollador puede instalar una release oficial de `imass-worktree`, usar `imass-wt` en proyectos compatibles, actualizarla de forma explícita y diagnosticar incompatibilidades sin copiar código del motor dentro de cada repositorio.

---

## 11. Resultado esperado

Después de E9-S1, `imass-worktree` deja de depender de instalación artesanal y dispone de una distribución interna versionada y mantenible.
