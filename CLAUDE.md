# CLAUDE.md

Agente de IA con interfaz web sobre múltiples providers LLM. El objetivo del proyecto es
que **cualquiera pueda usar IAs locales**: todo debe funcionar con Ollama o LM Studio en
la máquina del usuario, sin API key ni cuenta. Los providers de pago (OpenAI, Anthropic,
Groq, Copilot) son opcionales y nunca requisito.

Esa misión decide diseño: si una funcionalidad solo funciona bien con un modelo grande de
pago, necesita camino de degradación para un modelo local de 3B–8B.

## Arranque

```bash
./run.sh                      # puerto 9901, hot reload  ← preferido
PORT=8001 ./run.sh
python app_web.py             # puerto 8000, hardcodeado
```

Requiere `.venv` (Python 3.11+) y, para chatear, Ollama corriendo en `:11434`.
No hay `.env` en el repo; ver [.env.example](.env.example). Toda la config es
env-overridable desde [config.py](config.py).

## Comprobar cambios

```bash
.venv/bin/python -m pytest tests/ -q -m "not integration" --ignore=tests/test_e2e.py
```

Gate por defecto: ~60 tests, menos de 2 s, sin Ollama ni navegador. **Un fallo aquí es
real.** Los otros dos suites tienen requisitos propios y fallan por motivos ajenos al
cambio — ver la skill `verifying-changes-locally` antes de interpretarlos.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) solo ejecuta `ruff check .` y un
`py_compile`. Ruff está instalado en `.venv` pero **no en `requirements.txt`**, así que un
entorno recién creado no lo tendrá: `.venv/bin/pip install -q ruff`.

```bash
.venv/bin/ruff check .
```

Las reglas están **fijadas explícitamente** en [pyproject.toml](pyproject.toml)
(`E4`, `E7`, `E9`, `F`, `I`, `UP`). No las quites: sin selección explícita se aplica el set
por defecto de la versión de ruff que CI instale sin pin, que crece entre releases y rompe
el build sin que nadie haya tocado el código. Eso tuvo CI en rojo durante meses.

`UP042` está en `ignore` a propósito — convertir los enums `(str, Enum)` a `StrEnum`
cambiaría lo que devuelve `str(miembro)`, y esos valores están persistidos en SQLite.

## Mapa

| Módulo | Responsabilidad |
| --- | --- |
| [core/](core/) | Agente, modos, planner, memoria, construcción de contexto |
| [llm/](llm/) | Providers, factory, prompts, JSON schemas de structured output |
| [tools/](tools/) | Herramientas del agente, registro, MCP, skills del usuario final |
| [rag/](rag/) | Indexado semántico (ChromaDB) y knowledge base, con fallback por keywords |
| [security/](security/) | Aprobación de operaciones de escritura y sandbox de Python |
| [web/](web/) | FastAPI, WebSocket, persistencia SQLite, frontend estático |

Tres modos de operación: **Chat** (sin herramientas), **Agent** (ciclo ReAct con tools),
**Plan** (planifica → aprueba → ejecuta).

[AGENTS.md](AGENTS.md) tiene el detalle largo: tipos de mensaje WebSocket, endpoints REST
de RAG/memoria y flujo semántico.

## Código legacy — no tocar

Estos archivos son la versión Streamlit anterior. Siguen en el repo pero **no** son la
aplicación actual; no los edites ni los uses como referencia de patrones:

- `app.py` (monolito Streamlit) y `ollama_client.py`, que solo usa `app.py`
- `app_new.py` y todo `ui/`

La app viva es `web/` + `core/` + `llm/` + `tools/`. Si algo parece duplicado entre la
raíz y esos módulos, la versión buena es la de los módulos.

## Convenciones

- **Comentarios y docstrings en español.** Es la lengua del código; mantenla.
- **Mensajes de commit en inglés**, `feat:` / `fix:` / `chore:` y cuerpo con bullets.
- **Textos de UI en español**, incluidos los errores que ve el usuario.
- Ruff: línea máxima 100, target `py311` ([pyproject.toml](pyproject.toml)).
- No añadas dependencias sin necesidad real: cada una es fricción para quien quiere
  ejecutar esto en local.

## Invariantes

Romper cualquiera de estas produce fallos silenciosos, no excepciones:

1. **`workspace_root` es un límite de seguridad**, no una sugerencia. Ninguna herramienta
   opera fuera de él.
2. **`is_write_operation` alimenta la capa de aprobación.** Una tool que muta el sistema y
   no lo declara se ejecuta sin pedir permiso. Ante la duda, marca `True`.
3. **El `id` de un tool call se preserva** al normalizar la respuesta del provider. Es lo
   que empareja cada resultado con su llamada.
4. **`fmt` acepta `None`, `"json"` o un dict con JSON schema**, y los providers degradan a
   `"json"` cuando el servidor no soporta schema. Los prompts siguen describiendo el
   formato esperado: no los recortes porque exista un schema.
5. **El frontend es JavaScript plano sin build step.** Nada de `import`/`export`, npm,
   bundler ni framework — los archivos se sirven tal cual.

## Skills

Los rituales multi-archivo están documentados en [.claude/skills/](.claude/skills/) y se
cargan solos cuando hacen falta:

| Skill | Cuándo |
| --- | --- |
| `adding-llm-providers` | Añadir provider o depurar tool calling/structured output específico de uno |
| `adding-agent-tools` | Dar al agente una capacidad nueva |
| `adding-frontend-modules` | Cualquier cosa bajo `web/static/` |
| `debugging-local-model-behavior` | El agente falla solo con modelos pequeños |
| `verifying-changes-locally` | Antes de commit/push, o al triar un test rojo |

Hay además un sistema de skills **del usuario final** en `.agents/skills/`, gestionado por
[tools/skills_manager.py](tools/skills_manager.py). No lo confundas con `.claude/skills/`:
aquellas las ve quien usa la app, estas las uso yo al desarrollarla.

## Problemas conocidos

- Cuatro tests e2e de `TestFileViewer`/explorer fallan: `.file-viewer-content` se queda en
  `fv-hidden`. Es anterior a los commits actuales, no una regresión. Sin arreglar.
- Los tests de integración fijan el modelo en
  [tests/test_conversation_engine.py:24](tests/test_conversation_engine.py#L24). Si no
  está descargado fallan con aserciones engañosas, no con un error de modelo ausente.
- `run.sh` usa el puerto 9901 y `app_web.py` el 8000; el README documenta el 8000.
