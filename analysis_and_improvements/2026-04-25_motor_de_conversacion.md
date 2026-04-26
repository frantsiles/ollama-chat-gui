# Análisis del motor de conversación

**Fecha:** 2026-04-25
**Contexto:** El chat se corta, responde mal o pierde contexto cuando se le pide ejecutar tareas. Funciona aceptablemente para conversación simple pero falla al pasar a trabajo real con tools.

---

## 1. Flujo actual (modo AGENT)

```
Usuario envía "lee config.py"
         │
         ▼
[web/websocket.py] → crea Agent NUEVO (pierde estado de aprobaciones previas)
         │
         ▼
[core/agent.py: run()] → _maybe_summarize → add_user_message → _run_natural
         │
         ▼
[_run_natural] (loop hasta MAX_AGENT_STEPS=12)
         │
         ├─ LLM call #1 (modelo principal, texto libre)
         ├─ LLM call #2 (parser, fmt=json)
         ├─ ¿necesita tool? → ejecuta
         │   └─ extra_messages += [assistant, observation]   ⚠️ NO se persiste
         └─ ¿no necesita? → respuesta final
                  │
                  ▼
[_reflect_on_response] → LLM call #3 (revisor crítico)        ⚠️ puede modificar respuesta
                  │
                  ▼
[_maybe_extract_memories] → LLM call #4 (extractor de memorias) ⚠️ síncrono y bloqueante
                  │
                  ▼
[websocket] → envía response al frontend
```

---

## 2. Problemas identificados

### 🔴 Críticos (causan los cortes y respuestas malas)

#### 2.1. Hasta 4 llamadas al LLM por cada respuesta simple

Para un mensaje trivial como "Hola":
1. Modelo principal → "¡Hola!"
2. Parser → `{"needs_tool": false}`
3. Reflexión crítica → revisar la respuesta
4. Extracción de memorias → analizar si guardar algo

Con `OLLAMA_TIMEOUT=60s` por llamada, en peor caso son **240s solo para un saludo**. Cuando hay tools, multiplica por número de pasos del ciclo.

**Archivos:**
- [core/agent.py](../core/agent.py) — `_run_natural`, `_parse_natural_response`, `_reflect_on_response`, `_maybe_extract_memories`

---

#### 2.2. La reflexión crítica puede empeorar respuestas correctas

`REFLECTION_ENABLED=True` por defecto. El revisor:
- Solo ve los últimos 4 mensajes truncados a 500 chars (contexto pobre)
- Puede "corregir" respuestas que ya estaban bien
- Si su propio JSON falla al parsear, devuelve la original silenciosamente

**Archivo:** [core/agent.py:312-364](../core/agent.py#L312)

---

#### 2.3. Los tool results NO se guardan en la conversación

En `_run_natural`, las `extra_messages` (assistant + observation de tools ejecutadas) viven solo durante el run. Cuando termina:
- Solo se guarda la respuesta final del asistente
- En el siguiente turno, si el usuario pregunta "¿qué viste en el archivo?", el modelo NO recuerda haber leído nada
- Pierde toda la trazabilidad del trabajo realizado

**Archivo:** [core/agent.py:825-951](../core/agent.py#L825) — variable `extra_messages` local

---

#### 2.4. El parser es un punto de fallo silencioso

Si `_parse_natural_response` falla por cualquier razón (timeout, JSON inválido, modelo confuso):
- Retorna `needs_tool: false` por defecto
- El modelo dice "voy a leer config.py"
- Parser falla
- Se devuelve "voy a leer config.py" al usuario como si fuera la respuesta final
- El usuario espera el resultado pero nada pasa

**Archivo:** [core/agent.py:273-306](../core/agent.py#L273)

---

#### 2.5. El parser no tiene contexto de la conversación

El parser solo recibe la última respuesta del modelo principal, sin historial. Si el modelo dice "ahora voy a leerlo" (refiriéndose a un archivo mencionado antes en la conversación), el parser:
- No sabe a qué archivo se refiere
- Puede inventar argumentos o decidir `needs_tool: false` por incertidumbre

**Archivo:** [core/agent.py:290-293](../core/agent.py#L290)

---

#### 2.6. Estado del agente se pierde en cada mensaje

Cada mensaje crea un `Agent` completamente nuevo en el WebSocket handler:
- `_always_approved_tools` se reinicia
- `_history` de aprobaciones se reinicia
- El usuario tiene que volver a aprobar las mismas acciones

**Archivo:** [web/websocket.py:157](../web/websocket.py#L157)

---

#### 2.7. `resume_after_approval` rompe el flujo

Después de una aprobación, se llama `self.run(user_input="", conversation=...)`:
- Crea un mensaje de usuario VACÍO en la conversación
- Reinicia el estado completo
- Pierde los `extra_messages` del run anterior (las tools que ya se ejecutaron)

**Archivo:** [core/agent.py:1006-1020](../core/agent.py#L1006)

---

### 🟡 Moderados

#### 2.8. Modo AGENT no tiene streaming

El usuario solo ve "Pensando..." durante todas las llamadas. No hay sensación de progreso real más allá del trace en el sidebar. Mientras el modo CHAT sí streamea, el AGENT no.

**Archivo:** [web/websocket.py](../web/websocket.py) — `handle_chat_message` para modo AGENT

---

#### 2.9. Truncamiento agresivo de contexto

`MAX_CONTEXT_MESSAGES=20`, `MAX_CONTEXT_MESSAGES_KEEP=8`. Cuando llegas a 20 mensajes, se truncan a los últimos 8 + un sumario. El sumario es muy pobre — solo extrae la primera línea de cada mensaje.

**Archivo:** [config.py:55-57](../config.py#L55), [core/agent.py:191-211](../core/agent.py#L191)

---

#### 2.10. La extracción de memoria es síncrona

`_maybe_extract_memories` es bloqueante: una llamada extra al modelo antes de retornar la respuesta. Debería ser asíncrona o ejecutarse en background después de enviar la respuesta al usuario.

**Archivo:** [core/agent.py:452-477](../core/agent.py#L452)

---

#### 2.11. No hay validación cruzada parser ↔ contexto

Si el modelo dice "voy a leer ./src/config.py" pero ese archivo no existe en el listado del workspace, el parser no lo detecta. Se ejecuta la tool, falla, se reintenta sin pista clara del por qué.

---

#### 2.12. Mensajes intermedios del modelo se pierden

Cuando el modelo razona ("Voy a leer X, luego Y") y ejecuta varias tools en un run, el usuario solo ve el mensaje final. No hay registro de las decisiones intermedias en el chat.

---

### 🟢 Menores

#### 2.13. Mensajes residuales de runs anteriores

Las sesiones existentes tienen mensajes `system` con el workspace context viejo (que ahora ya no se agrega al historial). Estos viejos mensajes ensucian el contexto.

---

#### 2.14. El system prompt cambia entre llamadas

`_run_natural` usa `NATURAL_AGENT_SYSTEM_PROMPT` + workspace, pero `_reflect_on_response` y `_parse_natural_response` usan prompts diferentes. El modelo no tiene una "personalidad" coherente entre las distintas llamadas internas.

---

#### 2.15. No hay diferenciación entre conversación y trabajo

Cualquier mensaje pasa por todo el pipeline. "Gracias", "ok", "perfecto" hacen el ciclo completo: principal + parser + reflexión + memoria. No hay un fast-path para mensajes obviamente conversacionales.

---

## 3. Recomendaciones (orden por impacto/esfuerzo)

### 3.1. Fast-path para mensajes triviales 🎯
**Impacto: alto · Esfuerzo: bajo**

Detectar saludos / conversación pura ANTES de llamar al modelo. Si el mensaje es corto o coincide con patrones conversacionales, ir directo a CHAT mode con streaming. Sin parser, sin reflexión, sin memoria.

### 3.2. Persistir los tool results en la conversación 🎯
**Impacto: alto · Esfuerzo: medio**

Cuando el agente ejecuta tools, los resultados deben guardarse como mensajes `system` en la `Conversation` (no solo en `extra_messages` local). Así el modelo recuerda qué hizo en turnos previos.

### 3.3. Reflexión y memoria opcionales/asíncronas 🎯
**Impacto: medio · Esfuerzo: bajo**

- Reflexión: desactivar por defecto (`REFLECTION_ENABLED=False`), dejarla como opt-in
- Memoria: ejecutar en background DESPUÉS de retornar la respuesta al usuario

### 3.4. Streaming en modo AGENT
**Impacto: medio · Esfuerzo: medio**

Stream del modelo principal directamente al frontend. El parser puede correr al final del stream, no antes. Si no hay tool detectada, el usuario ya vio la respuesta completa fluyendo en tiempo real.

### 3.5. Persistir estado del agente entre mensajes
**Impacto: medio · Esfuerzo: bajo**

Mover `_always_approved_tools` y similares a la `Session` de `web/state.py`, no al `Agent` (que se recrea en cada turno).

### 3.6. Parser con contexto
**Impacto: medio · Esfuerzo: medio**

El parser debería recibir, además de la respuesta del modelo, los últimos N mensajes y el listado del workspace. Así puede resolver referencias como "ese archivo" o "el directorio que mencionaste".

### 3.7. Handling explícito del fallo del parser
**Impacto: medio · Esfuerzo: bajo**

En vez de retornar `needs_tool: false` silenciosamente cuando el parser falla, registrarlo en el trace y mostrar al usuario que algo no funcionó como se esperaba.

---

## 4. Próximos pasos sugeridos

Empezar por las recomendaciones de **alto impacto y bajo esfuerzo**:

1. **Fast-path conversacional** (3.1) — soluciona el problema de saludos lentos
2. **Desactivar reflexión por defecto** (3.3 parte 1) — quita una llamada del crítico path
3. **Memoria asíncrona** (3.3 parte 2) — quita otra llamada
4. **Persistir tool results** (3.2) — fundamental para coherencia entre turnos

Con esos 4 cambios, el motor debería ser sustancialmente más rápido y coherente sin reescritura mayor.

---

## 5. Cambios aplicados (2026-04-25)

### 5.1. Refactor estructural — responsabilidad única

`core/agent.py` se redujo de **1300 líneas → 636 líneas** (51% menos) extrayendo:

| Módulo nuevo | Líneas | Responsabilidad |
|---|---|---|
| [core/conversation/context_builder.py](../core/conversation/context_builder.py) | 145 | Mensajes para LLM (system, ventana, workspace) |
| [core/conversation/natural_loop.py](../core/conversation/natural_loop.py) | 202 | Bucle modelo → parser → tool |
| [core/conversation/parser.py](../core/conversation/parser.py) | 75 | Detecta tool calls en texto libre |
| [core/conversation/reflector.py](../core/conversation/reflector.py) | 94 | Revisión crítica (opcional) |
| [core/conversation/router.py](../core/conversation/router.py) | 97 | Fast-path conversacional |
| [core/plan_executor.py](../core/plan_executor.py) | 447 | Ejecución de planes con retry |
| [core/memory_hook.py](../core/memory_hook.py) | 67 | Extracción de memorias |

**Beneficios:** cada componente con dependencias inyectadas, testeable en aislamiento, código muerto del path nativo eliminado.

### 5.2. Fast-path conversacional ✅

[core/conversation/router.py](../core/conversation/router.py) — `ConversationRouter.is_conversational()` clasifica el mensaje. Si es saludo / acknowledgment / mensaje muy corto sin keywords de acción, va al `_run_fast_path` del agente: **una sola llamada al modelo, sin parser, sin reflexión, sin memoria síncrona**.

Verificado con 29 casos de test (saludos en es/en, agradecimientos, sí/no, tareas con keywords). 100% acierto.

### 5.3. Reflexión desactivada por defecto ✅

[config.py](../config.py) — `REFLECTION_ENABLED` ahora default `false`. Para activarla se necesita setear explícitamente `REFLECTION_ENABLED=true`. Quita una llamada del critical path.

### 5.4. Extracción de memorias asíncrona ✅

[web/websocket.py](../web/websocket.py) — la extracción de memorias ya NO bloquea la respuesta:
1. Se envía la respuesta al usuario inmediatamente
2. `asyncio.create_task(_extract_memories_bg())` dispara la extracción en background
3. Si extrae algo nuevo, se notifica al frontend con `memory_updated`

El `Agent.extract_memories()` se hizo público para que el WebSocket lo invoque externamente.

### 5.5. Tool results persistidos en Conversation ✅

[core/conversation/natural_loop.py](../core/conversation/natural_loop.py) — los resultados de tool ejecutadas ahora se guardan como mensajes `system` en la `Conversation` (no solo en `extra_messages` local). Las respuestas intermedias del modelo siguen siendo del run (no se persisten para no contaminar el chat).

**Resultado:** si el usuario pregunta en el siguiente turno "¿qué viste en el archivo?", el modelo tiene el contenido real en su contexto y puede responder sin volver a leer.

---

## 6. Estado del motor tras los cambios

**Antes:**
- "Hola" → 4 llamadas al LLM (principal + parser + reflexión + memoria síncrona)
- Tool results perdidos entre turnos
- `agent.py` con 1300 líneas mezclando responsabilidades

**Ahora:**
- "Hola" → **1 llamada al LLM** (fast-path directo, sin parser ni reflexión)
- Tool results persistidos → modelo recuerda turnos previos
- `agent.py` con 636 líneas, solo orquestando
- Componentes separados, testeables, con dependencias claras
