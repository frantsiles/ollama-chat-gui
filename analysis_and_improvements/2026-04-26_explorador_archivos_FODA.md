# Análisis FODA — Explorador de archivos

**Fecha:** 2026-04-26
**Alcance:** módulo de explorador de archivos del proyecto (frontend + backend).

## 1. Componentes auditados

**Frontend** ([web/static/js/explorer.js](../web/static/js/explorer.js), 1788 líneas; [web/static/css/explorer.css](../web/static/css/explorer.css), 1325 líneas):

- `Explorer` — barra de actividad estilo VS Code, árbol, menú contextual, drag & drop, redimensionado, keyboard nav.
- `ExplorerDialog` — prompt/confirm modal interno (sustituye `window.prompt/confirm`).
- `FileViewer` — visor de archivos con números de línea y resaltado vía `hljs`.
- `QuickOpen` — buscador de archivos por nombre (`Ctrl+P`).
- `SearchPanel` — grep en contenido (`Ctrl+Shift+F`).
- `Breadcrumbs` — ruta navegable con elipsis para rutas largas.
- `TreeSelection` — multiselección (Ctrl/Shift+click) y acciones masivas (adjuntar, copiar rutas, borrar).
- `GitStatus` — badges de estado git con polling cada 15 s.
- `FileWatcher` — refresco automático del árbol vía evento WS `file_changed`.

**Backend** ([web/api.py](../web/api.py)):

- `GET /api/files` — listado con filtros `show_hidden`, `use_gitignore`.
- `POST /api/files/{create,mkdir,rename,delete,duplicate,move,upload}` — CRUD de archivos/carpetas.
- `GET /api/files/search` — búsqueda por nombre (fuzzy substring), recursivo con `MAX_RESULTS=50`, profundidad 12.
- `GET /api/files/grep` — búsqueda en contenido (regex escapado), `MAX_FILES=30`, 30 matches/archivo, ≤512 KB.
- `GET /api/file-content` — lectura con límite de 2 MB.
- `GET /api/git/{status,info,changes,diff,log}` y `POST /api/git/{init,stage,unstage,discard,commit,remote/*,push,pull}` — integración Git completa.

---

## 2. Matriz FODA

### F — Fortalezas

| # | Fortaleza | Evidencia |
|---|-----------|-----------|
| F1 | **Cobertura funcional alta**: replica gran parte de la UX de VS Code (árbol, breadcrumbs, Quick Open, búsqueda en contenido, git, drag & drop bidireccional con SO y chat). | [explorer.js:497](../web/static/js/explorer.js#L497) (DnD SO), [explorer.js:561](../web/static/js/explorer.js#L561) (DnD chat). |
| F2 | **Separación por sub-módulos**: cada responsabilidad es un objeto `const` con `init()` propio, lo que aísla estado dentro de un mismo archivo. | [explorer.js:964](../web/static/js/explorer.js#L964), [explorer.js:1042](../web/static/js/explorer.js#L1042), etc. |
| F3 | **Atajos de teclado consistentes**: `Ctrl+P`, `Ctrl+Shift+F`, navegación con flechas en el árbol, `Esc` para cerrar overlays. | [explorer.js:1189](../web/static/js/explorer.js#L1189), [explorer.js:206](../web/static/js/explorer.js#L206). |
| F4 | **Diálogos propios** (sin `window.prompt`): mejor UX y estilizables. | [explorer.js:964](../web/static/js/explorer.js#L964). |
| F5 | **Soporte `.gitignore`** y archivos ocultos con toggles persistidos. | [api.py:240-258](../web/api.py#L240). |
| F6 | **Refresco reactivo vía WebSocket** (`file_changed` con debounce de 800 ms). | [explorer.js:1736](../web/static/js/explorer.js#L1736). |
| F7 | **Acciones masivas** sobre selección (adjuntar, copiar rutas, borrar). | [explorer.js:1532](../web/static/js/explorer.js#L1532). |
| F8 | **Integración Git profunda** ya servida por la API (status/diff/log/commit/push/pull). | [api.py:770-1100](../web/api.py#L770). |
| F9 | **Persistencia de preferencias** (ancho del panel, secciones colapsadas) en localStorage. | [explorer.js:137](../web/static/js/explorer.js#L137). |

### O — Oportunidades

| # | Oportunidad | Beneficio esperado |
|---|-------------|-------------------|
| O1 | **Editor integrado** (Monaco / CodeMirror 6) reemplazando `FileViewer` de solo lectura. | Cierra el bucle "ver → editar → guardar" sin salir de la GUI; clave dado el target de "chat con LLM + workspace". |
| O2 | **Push WS de Git** en lugar de polling cada 15 s. | Elimina ~5760 requests/día por sesión inactiva; estado actualizado en tiempo real. |
| O3 | **Virtual scrolling** del árbol para directorios con miles de entradas. | Evita lag al expandir `node_modules`/repos grandes. |
| O4 | **Indexación incremental** para Quick Open (Trie/fzf en el cliente). | Búsqueda sub-100 ms sin volver al servidor por cada tecla. |
| O5 | **Streaming de grep** por SSE/WS con cancelación. | Resultados progresivos en lugar de un único `MAX_FILES=30`. |
| O6 | **Vista diff** integrada (ya hay `/git/diff`) con highlighting lado-a-lado. | Saca partido de un endpoint existente. |
| O7 | **Carga perezosa de `hljs`** y de los iconos SVG. | Reduce JS inicial; `hljs` solo se necesita al abrir el visor. |
| O8 | **Integración con RAG/MCP** del proyecto: "indexar selección", "añadir al contexto". | El explorador ya está en la misma página que `api_rag.py`/`api_mcp.py`; falta el puente UI. |
| O9 | **Pruebas automatizadas** del backend (pytest) y del frontend (Playwright/Vitest). | El módulo no tiene tests visibles en `tests/`. |
| O10 | **Accesibilidad ARIA** (`role="tree"`, `aria-expanded`, `aria-selected`). | Mejora soporte a lectores de pantalla y testing. |
| O11 | **Historial reciente / archivos fijados** y favoritos. | Reduce navegación repetitiva. |
| O12 | **Comando "abrir en…"** (terminal del sistema, VSCode externo). | Productividad para usuarios power. |

### D — Debilidades

| # | Debilidad | Evidencia / Riesgo |
|---|-----------|--------------------|
| D1 | **Archivo monolítico**: `explorer.js` con 1788 líneas y 9 objetos globales (`window.Explorer`, `window.QuickOpen`, …) acoplados entre sí. | [explorer.js:6-1734](../web/static/js/explorer.js#L6). Difícil de mantener y testear. |
| D2 | **Sin pruebas** para los endpoints `/api/files/*`, `/api/file-content`, ni para los módulos JS. | Carpeta `tests/` no contiene cobertura visible para este módulo. Cambios pueden romper sin que se detecte. |
| D3 | **Polling de Git cada 15 s** independientemente de si hay cambios. | [explorer.js:1652](../web/static/js/explorer.js#L1652). Costo CPU/IO innecesario. |
| D4 | **Sin virtual scroll**: cada carpeta abierta inserta DOM completo. | [explorer.js:_loadTree](../web/static/js/explorer.js). En `/usr` o `node_modules` se nota. |
| D5 | **Búsquedas síncronas y bloqueantes** en el backend: `_walk_grep` lee archivos secuencialmente sin async ni cancelación. | [api.py:626](../web/api.py#L626). Una consulta lenta bloquea otras del mismo worker. |
| D6 | **Lectura de archivo por API responde JSON con todo el contenido** (hasta 2 MB). | [api.py:683](../web/api.py#L683). No hay paginado/streaming; copia memoria innecesariamente. |
| D7 | **`.gitignore` simplificado**: sólo glob por nombre, no respeta sub-rutas, negaciones (`!`) ni `.gitignore` anidados. | [api.py:240-258](../web/api.py#L240). Resultados de listado pueden divergir de `git ls-files`. |
| D8 | **SVG inline duplicados** (chevron, folder, file) en cada render. | [explorer.js:_svgChevron/_svgFolder/_svgFile](../web/static/js/explorer.js#L934). Inflado de bytes y de DOM. |
| D9 | **CSS muy grande** (1325 líneas) sin separación clara por sub-módulo. | [explorer.css](../web/static/css/explorer.css). Difícil eliminar reglas muertas. |
| D10 | **Acoplamiento global**: `Explorer.setWorkspace` toca `Sidebar`, `Chat`, `FileWatcher`, `GitStatus`, `GitPanel` por nombre. | [explorer.js:182](../web/static/js/explorer.js#L182). |
| D11 | **Visor sin búsqueda interna**, sin saltar a línea, sin word wrap conmutable. | [explorer.js:1042](../web/static/js/explorer.js#L1042). |
| D12 | **Quick Open ignora `.gitignore`** (sólo respeta `_IGNORE_DIRS`); aparece ruido de `__pycache__/`, `dist/`, etc. (mitigado parcialmente, ver [api.py:_IGNORE_DIRS]). | [api.py:524](../web/api.py#L524). |
| D13 | **Sin papelera/undo** en borrados. | [api.py:391](../web/api.py#L391). Pérdida accidental. |
| D14 | **No-op silencioso ante errores de red** (`catch {}` en polling y búsquedas). | [explorer.js:1681](../web/static/js/explorer.js#L1681). Diagnóstico difícil. |

### A — Amenazas

| # | Amenaza | Evidencia / Riesgo |
|---|---------|--------------------|
| A1 | **Path traversal / acceso a todo el FS**: los endpoints aceptan rutas absolutas arbitrarias y sólo hacen `Path.resolve()` sin "encarcelar" en un workspace. | [api.py:272](../web/api.py#L272), [api.py:683](../web/api.py#L683). Si el servidor se expone fuera de localhost, cualquiera puede leer/borrar `/etc/*`, `~/.ssh/*`. |
| A2 | **Borrado/move sin confirmación de ámbito**: `POST /api/files/delete` acepta cualquier ruta tras `Path.resolve()`. | [api.py:391](../web/api.py#L391). |
| A3 | **Subida de archivos** (`POST /api/files/upload`) sin sanitizado fuerte de nombre ni límite global de tamaño visible. | [api.py:481](../web/api.py#L481). DoS o sobreescritura. |
| A4 | **Grep/Search puede consumir CPU/IO** en árboles grandes pese a límites; ejecutado en el event loop sin `run_in_executor`. | [api.py:626](../web/api.py#L626). Bloquea el resto de peticiones del worker uvicorn. |
| A5 | **Highlighting con `hljs.highlightElement` sobre contenido del archivo**: aunque escapado, hay riesgo si se cambia el flujo y se re-inyecta HTML. | [explorer.js:1106](../web/static/js/explorer.js#L1106). |
| A6 | **Dependencia de `window.*` globals**: cualquier extensión/skin que machaque `window.Chat` rompe el explorador. | múltiples puntos. |
| A7 | **`.gitignore` propio divergente del real**: confunde al usuario que ve un fichero como "ignorado" en la UI pero `git status` lo lista (o viceversa). | [api.py:240](../web/api.py#L240). |

---

## 3. Plan de trabajo (D → mitigar / O → capitalizar)

Priorización: **P0 = seguridad/datos**, **P1 = correctness/UX bloqueante**, **P2 = mejora**, **P3 = nice-to-have**.

### Fase 1 — Seguridad y robustez (P0)

| ID | Acción | Aborda | Esfuerzo |
|----|--------|--------|----------|
| T1 | **Encarcelar todas las rutas en el workspace activo**: middleware `_resolve_safe(path, workspace)` que rechace rutas fuera y symlinks que salten la jaula. Aplicar en `files`, `file-content`, `files/*`, `git/*`. | A1, A2 | M |
| T2 | **Endurecer upload**: límite global, sanitizar nombres (`werkzeug.secure_filename` o equivalente), rechazar paths con `..`. | A3 | S |
| T3 | **Mover grep/search a `run_in_executor`** con `asyncio.wait_for` y cancelación cuando el cliente desconecta. | A4, D5 | M |
| T4 | **Reemplazar el matcher de `.gitignore`** por `pathspec` (mismo algoritmo que git) y respetar `.gitignore` anidados. | D7, A7 | M |
| T5 | **Tests** mínimos pytest para los endpoints CRUD, listado, search, grep y para los casos de path-traversal (deben fallar con 400/403). | D2 | M |

### Fase 2 — Correctness y UX (P1)

| ID | Acción | Aborda | Esfuerzo |
|----|--------|--------|----------|
| T6 | **Sustituir polling Git por push WS**: emitir `git_status_changed` desde el watcher (mismo canal que `file_changed`) y cliente actualiza badges al recibirlo. Mantener un único `GET /git/status` inicial. | D3, O2 | M |
| T7 | **Confirmación de borrado con previsualización** y opcional "papelera" (mover a `~/.local/share/Trash` o a `.trash/` del workspace). | D13 | M |
| T8 | **Errores de red visibles** (toast): convertir los `catch {}` silenciosos en notificaciones discretas. | D14 | S |
| T9 | **Streaming/progressive grep** vía SSE o WS, con botón cancelar y resultados que aparecen archivo a archivo. | D5, O5 | L |
| T10 | **Tests Playwright** mínimos: abrir Quick Open, ejecutar búsqueda, ver archivo, crear/renombrar/borrar. | D2 | M |

### Fase 3 — Arquitectura y rendimiento (P2)

| ID | Acción | Aborda | Esfuerzo |
|----|--------|--------|----------|
| T11 | **Trocear `explorer.js`** en módulos ES (`explorer/index.js`, `tree.js`, `quickOpen.js`, `search.js`, `viewer.js`, `gitStatus.js`, `selection.js`). Bundling vía esbuild o import maps. | D1 | L |
| T12 | **Virtual scroll** del árbol cuando una carpeta supere ~500 entradas. | D4, O3 | M |
| T13 | **Index local fuzzy** (fzf en JS) para Quick Open con caché del árbol y diff al recibir `file_changed`. | O4 | L |
| T14 | **Sprite SVG / iconos por clase CSS** en lugar de inline. | D8 | S |
| T15 | **CSS troceado** alineado al troceo JS y eliminación de reglas muertas (audit con `purgecss`). | D9 | S |
| T16 | **Bus de eventos** (`EventTarget` propio o `wsManager.emit`) para desacoplar `Explorer ↔ Chat ↔ Git ↔ Sidebar`. | D10, A6 | M |

### Fase 4 — Capacidades nuevas (P3)

| ID | Acción | Aborda | Esfuerzo |
|----|--------|--------|----------|
| T17 | **Editor integrado** (CodeMirror 6 o Monaco) con guardado vía nuevo `PUT /api/file-content`. | O1 | L |
| T18 | **Vista diff** lado-a-lado consumiendo `/git/diff` con `diff2html` o equivalente. | O6 | M |
| T19 | **Carga perezosa de `hljs`** (dynamic `import()` al primer `FileViewer.open`). | O7 | S |
| T20 | **Pestaña "Workspace → RAG/MCP"**: acción "Indexar selección" desde la barra de selección masiva, llamando al endpoint del módulo RAG existente. | O8 | M |
| T21 | **Recientes y favoritos** persistidos en localStorage, sección colapsable en el panel. | O11 | S |
| T22 | **ARIA tree** (`role`, `aria-level`, `aria-expanded`, `aria-selected`) y testing con axe. | O10 | S |
| T23 | **Buscar/saltar a línea** dentro del visor (Ctrl+F, Ctrl+G). | D11 | M |

### Resumen de orden recomendado

```
T1 → T2 → T4 → T5 → T3       (fase 1: seguridad y tests)
T6 → T8 → T7 → T9 → T10      (fase 2: correctness)
T11 → T16 → T12 → T14 → T15 → T13   (fase 3: arquitectura)
T19 → T20 → T22 → T21 → T17 → T18 → T23  (fase 4: nuevas capacidades)
```

---

## 4. Indicadores de éxito

- **Seguridad**: 0 endpoints aceptan rutas fuera del workspace; suite de tests de path-traversal pasando.
- **Cobertura tests**: ≥70 % en `web/api.py` para funciones de archivos; ≥1 test E2E por flujo crítico (abrir, crear, renombrar, borrar, buscar, grep, abrir visor).
- **Rendimiento**: árbol con 5 000 entradas se renderiza en <100 ms; Quick Open responde en <100 ms para query con índice cacheado.
- **Mantenibilidad**: ningún archivo JS del explorador supera 400 líneas tras T11.
- **UX**: 0 polls de `/git/status` en estado idle (push WS) tras T6.
