# Contexto de referencia para la IA

Esta carpeta contiene material de **referencia** destinado a dar contexto a
agentes de IA y personas. **No es autoritativo** para `ramalio`.

## Alcance y advertencias

- El documento autoritativo del producto es
  [`../standard-operativo.md`](../standard-operativo.md). Ante cualquier
  conflicto, ese estándar y el `AGENTS.md` de la raíz mandan.
- El material aquí puede provenir de **otros proyectos** (por ejemplo scripts
  atados a un stack Docker/Laravel, variables como `KIRO_PROJECT_ROOT`,
  `zurich-$KIRO_DEVELOPER`, etc.). Esos patrones se incluyen sólo como
  referencia histórica/conceptual.
- **No** deben copiarse tal cual al core: violarían invariantes del proyecto,
  en particular INV-02 (el core no conoce proyectos concretos) e INV-03 (el
  root se deriva del contexto, sin depender de `KIRO_PROJECT_ROOT`).

## Contenido

- `snapshot-scripts.txt` — volcado de scripts de lifecycle de un proyecto
  cliente previo (adopt/compose/etc.), útil como referencia de comportamientos
  y errores diagnósticos ya explorados en otro entorno.
