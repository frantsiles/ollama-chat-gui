# Warp Features Roadmap — Adaptaciones para Ollama Chat GUI

**Fecha:** 2026-04-29  
**Fuente:** Análisis del repositorio `/home/frantsiles/warpdotdev/`  
**Referencia Warp:** `.agents/`, `app/src/ai/`, `app/src/context_chips/`, `app/src/search/ai_context_menu/`

---

## Features ya implementados (de Warp)

| Feature | Implementado | Archivos |
|---|---|---|
| Skills system | ✅ | `tools/skills_manager.py`, `web/api_skills.py`, `web/static/js/skills.js` |
| Warp V2 input layout | ✅ | `web/static/index.html`, `web/static/css/chat.css` |
| GFM table rendering | ✅ | `web/static/js/utils.js` |

---

## Features pendientes por prioridad

### 🔴 Alta prioridad

#### 1. Conversation History — Retomar sesiones anteriores
**Referencia Warp:** `app/src/ai/agent_conversations_model.rs`  
**Descripción:** Lista lateral de conversaciones previas con búsqueda. Al hacer clic se carga la sesión completa (mensajes + config).  
**Estado:** ⏳ Pendiente — **PRÓXIMO A IMPLEMENTAR**

**Plan de implementación:**
- [ ] Backend: endpoint `GET /api/conversations` — lista sesiones con metadata (título, fecha, nº mensajes)
- [ ] Backend: endpoint `GET /api/conversations/{id}` — carga mensajes completos de una sesión
- [ ] Backend: auto-generar título de conversación a partir del primer mensaje del usuario
- [ ] Backend: endpoint `DELETE /api/conversations/{id}` — borrar sesión
- [ ] Frontend: panel "Historial" en el sidebar izquierdo (nueva pestaña en activity bar)
- [ ] Frontend: módulo `history.js` — lista con búsqueda + carga de sesión
- [ ] Frontend: al cargar una sesión antigua, restaurar mensajes en el chat y config (modelo, modo)
- [ ] DB: ya existe SQLite en `web/state.py`; añadir columna `title` a la tabla de sesiones

**Archivos a modificar:**
- `web/state.py` — añadir campo `title` y método `generate_title()`
- `web/api.py` — nuevos endpoints de historial
- `web/static/index.html` — nueva pestaña en activity bar
- `web/static/js/history.js` — módulo nuevo
- `web/static/js/app.js` — registrar módulo History
- `web/static/css/chat.css` — estilos del panel historial

---

#### 2. Context Chips — Adjuntar contexto como pills en el input
**Referencia Warp:** `app/src/context_chips/`, `app/src/search/ai_context_menu/files/`  
**Descripción:** Al escribir `@archivo` o arrastrar un archivo al input, aparece una "chip/pill" visual. El contenido se inyecta en el mensaje al enviar.  
**Estado:** ⏳ Pendiente

**Plan de implementación:**
- [ ] Frontend: trigger `@` en textarea abre un mini-picker de archivos del workspace
- [ ] Frontend: chips visuales encima del textarea (nombre + botón ×)
- [ ] Backend: al enviar mensaje, el servidor inyecta el contenido de los archivos referenciados como contexto
- [ ] Límite: 10MB por archivo, deduplicación automática
- [ ] Sanitización de paths (no exponer paths del servidor)

**Archivos a modificar:**
- `web/static/js/chat.js` — lógica de chips + payload modificado
- `web/static/css/chat.css` — estilos de chips
- `web/websocket.py` — inyección de contexto de archivos en el mensaje

---

### 🟡 Media prioridad

#### 3. Keyboard Shortcuts — Atajos de teclado
**Referencia Warp:** `app/src/keyboard.rs`  
**Descripción:** Atajos de teclado para las acciones más comunes.  
**Estado:** ⏳ Pendiente

| Atajo | Acción |
|---|---|
| `Ctrl+Enter` | Enviar mensaje (alternativa al botón) |
| `↑` (input vacío) | Recuperar último mensaje enviado |
| `Ctrl+K` | Abrir command palette |
| `Ctrl+Shift+S` | Abrir panel Skills |
| `Ctrl+Shift+H` | Abrir panel Historial |
| `Escape` | Cancelar generación en curso |

#### 4. File Attachment mejorado
**Referencia Warp:** `app/src/ai/attachment_utils.rs`  
**Descripción:** Mejorar el sistema de adjuntos actual (ya existe) con: progress bar de carga, 10MB limit con feedback, deduplicación, drag & drop al textarea.  
**Estado:** ⏳ Pendiente

#### 5. Command Palette
**Referencia Warp:** `app/src/command_palette.rs`  
**Descripción:** `Ctrl+Shift+P` abre un modal con todas las acciones del app filtrable por texto.  
**Estado:** ⏳ Pendiente

---

### 🟢 Baja prioridad

#### 6. Theme Creator
**Referencia Warp:** `app/src/themes/theme_creator_*.rs`  
**Descripción:** Editor visual de temas con preview en vivo. Actualmente solo hay toggle dark/light.  
**Estado:** ⏳ Pendiente

#### 7. Prompt Suggestions
**Referencia Warp:** `app/src/ai/predict/`  
**Descripción:** Sugerencias de continuación de prompt basadas en historial reciente de la sesión.  
**Estado:** ⏳ Pendiente

---

## Progreso general

```
[██░░░░░░░░] 20% — 3/10 features implementados
```
