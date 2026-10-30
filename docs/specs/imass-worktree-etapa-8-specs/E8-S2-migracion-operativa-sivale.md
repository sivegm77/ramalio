# E8-S2 — Migración operativa de SiVale a `imass-wt`

## 1. Identificación
- **Proyecto:** imass-worktree
- **Etapa:** E8 — Piloto real sobre SiVale
- **Spec:** E8-S2
- **Nombre:** Migración operativa de SiVale
- **Dependencias:** E8-S0, E8-S1
- **Bloquea a:** cierre E8 / E9

## 2. Contexto
Después de configurar SiVale y demostrar paridad, el paso final del piloto es adoptar `imass-wt` como mecanismo principal del lifecycle de worktrees.

Esta migración debe hacerse de forma controlada. El objetivo no es borrar scripts por limpieza estética, sino retirar únicamente wrappers o mecanismos cuyo comportamiento ya esté cubierto por el producto estándar.

## 3. Objetivo
Migrar el flujo cotidiano de SiVale para que la operación estándar sea:

```bash
imass-wt init <target>
imass-wt adopt <target>
imass-wt status <target>
imass-wt stop <target>
imass-wt start <target>
imass-wt destroy <target>
```

con las capabilities/integrations configuradas por el proyecto.

## 4. Alcance
Incluye:
- selección de `imass-wt` como mecanismo principal;
- transición desde wrappers/scripts reemplazables;
- compatibilidad temporal cuando sea necesaria;
- documentación operativa;
- validación con usuarios/workflows reales;
- retiro controlado de código legado reemplazado;
- rollback del cambio operativo si aparece un blocker.

Fuera de alcance:
- retirar scripts que aún tengan responsabilidades no cubiertas;
- cambiar el workflow de negocio de Kiro/specs;
- modificar funcionalidades de la aplicación SiVale;
- convertir configuraciones personales en configuración versionada.

## 5. Invariantes
1. El equipo conserva capacidad de trabajar durante la transición.
2. No se elimina un mecanismo legado antes de demostrar que está reemplazado.
3. El nuevo flujo no requiere conocimiento interno de scripts SiVale.
4. La documentación enseña el CLI estándar, no wrappers nuevos específicos.
5. Un rollback operativo debe ser posible mientras dure la transición.

## 6. Requirements
### R1 — Flujo canónico nuevo
La documentación de SiVale debe presentar `imass-wt` como mecanismo principal para lifecycle de worktrees.

### R2 — Wrappers existentes
Cada wrapper/script actual debe clasificarse:
- reemplazado por `imass-wt`;
- aún necesario por responsabilidad ajena;
- temporal durante transición;
- obsoleto.

### R3 — No doble autoridad
Una vez migrada una operación, no deben coexistir dos mecanismos “canónicos” que puedan administrar el mismo workspace de forma contradictoria.

### R4 — Compatibilidad temporal
Si se conservan wrappers durante transición, deben delegar o quedar claramente marcados como legacy; no mantener lógica divergente.

### R5 — Init real
El equipo debe poder iniciar un target real de SiVale mediante `imass-wt init` y entrar al worktree correcto.

### R6 — Reanudación
Debe validarse stop/start en un caso real cuando las capabilities configuradas lo hagan relevante.

### R7 — Destrucción
Debe validarse destroy seguro sobre un target real terminado y bloqueo sobre uno dirty.

### R8 — Kiro
Si se usa `--open kiro`, debe abrir Kiro en el worktree correcto; la ausencia de Kiro no invalida el core.

### R9 — Paralelismo
El flujo migrado debe soportar múltiples targets simultáneos como el workflow actual.

### R10 — Documentación
Actualizar documentación de desarrollo con:
- instalación/prerrequisitos;
- comandos canónicos;
- ejemplos de target;
- doctor;
- troubleshooting;
- transición desde comandos anteriores.

### R11 — Retiro controlado
Sólo se eliminan scripts/wrappers cuando:
- E8-S1 tiene paridad suficiente;
- no contienen responsabilidad exclusiva pendiente;
- existe alternativa documentada;
- tests ya no dependen de ellos.

### R12 — Evidencia final
Debe quedar una evidencia de operación real con:
- init;
- status;
- start/stop si aplica;
- destroy;
- paralelismo;
- ausencia de regresiones de lifecycle.

## 7. Diseño de transición
Fases recomendadas:

```text
1. imass-wt disponible + config SiVale
2. coexistencia controlada
3. pruebas reales
4. documentación cambia a imass-wt
5. wrappers antiguos dejan de ser canónicos
6. retiro de piezas reemplazadas
```

No saltar directamente de coexistencia a borrado.

## 8. Criterios de aceptación
- AC-01: un desarrollador puede operar SiVale con `imass-wt` sin conocer scripts internos.
- AC-02: lifecycle cotidiano funciona con múltiples worktrees.
- AC-03: doctor identifica prerequisitos faltantes.
- AC-04: no hay doble autoridad operacional.
- AC-05: wrappers retirados estaban completamente reemplazados.
- AC-06: wrappers conservados tienen razón explícita.
- AC-07: documentación oficial refleja el nuevo flujo.
- AC-08: existe evidencia real de init/adopt/start/stop/status/destroy según aplique.

## 9. Tasks
1. Inventariar comandos/wrappers actuales de SiVale.
2. Mapear cada uno a `imass-wt` o responsabilidad residual.
3. Instalar/distribuir versión del CLI usada por el piloto.
4. Activar `.imass-worktree.toml` validado.
5. Ejecutar flujo real de punta a punta.
6. Ejecutar dos o más workspaces simultáneos.
7. Actualizar documentación operativa.
8. Marcar/delegar wrappers transitorios.
9. Retirar sólo piezas reemplazadas.
10. Ejecutar regresión final y `doctor`.
11. Documentar gaps residuales que correspondan a E9 o backlog futuro.

## 10. Verificación
E8 termina cuando SiVale puede operar su lifecycle cotidiano mediante `imass-wt` y el conocimiento específico queda en su configuración/capabilities, no en el core.

## 11. Resultado esperado
SiVale queda como implementación de referencia real de `imass-worktree`, preparada para demostrar en E9 que el estándar también funciona fuera de SiVale.


## 12. Estado de migración post-auditoría

La implementación histórica de E8-S2 fue mergeada, pero **no se considera cerrado el reemplazo operacional del harness legacy** mientras E10-S4 no demuestre paridad completa de provisioning/cleanup.

Esto es coherente con R11: un script sólo puede retirarse cuando no conserva una responsabilidad exclusiva pendiente. Hasta entonces, la documentación debe clasificar los wrappers afectados como `PARTIAL` y preservar un camino operativo seguro.
