"""Agente principal: orquesta los componentes de conversación, plan y memoria.

Esta clase es deliberadamente delgada — la lógica de bajo nivel vive en:
- core.conversation.context_builder   ← construcción de mensajes
- core.conversation.parser            ← parser de respuestas naturales
- core.conversation.reflector         ← revisión crítica opcional
- core.conversation.natural_loop      ← bucle modelo → parser → tool
- core.plan_executor                  ← ejecución autónoma de planes
- core.memory_hook                    ← extracción de memorias post-respuesta
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import MAX_AGENT_STEPS, OperationMode
from llm.prompts import PromptManager
from core.models import (
    AgentState,
    Conversation,
    Plan,
    ToolCall,
    ToolResult,
)
from llm.base import LLMClientError, LLMProvider
OllamaClientError = LLMClientError  # alias de compatibilidad
from security.approval import ApprovalManager
from tools.registry import ToolRegistry


@dataclass
class AgentResponse:
    """Respuesta del agente."""
    content: str
    status: str  # completed, awaiting_approval, max_steps, error
    tool_results: List[ToolResult] = field(default_factory=list)
    plan: Optional[Plan] = None
    error: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    new_cwd: Optional[str] = None
    token_usage: Optional[Dict[str, int]] = None


class Agent:
    """
    Agente de IA con soporte para múltiples modos de operación.
    
    Modos:
    - CHAT: Conversación simple sin herramientas
    - AGENT: Ciclo ReAct automático con herramientas
    - PLAN: Planifica antes de ejecutar
    """
    
    def __init__(
        self,
        client: LLMProvider,
        model: str,
        workspace_root: Path,
        current_cwd: Optional[Path] = None,
        temperature: float = 0.7,
        mode: str = OperationMode.AGENT,
    ):
        """
        Inicializa el agente.
        
        Args:
            client: Cliente de Ollama
            model: Nombre del modelo a usar
            workspace_root: Raíz del workspace
            current_cwd: Directorio de trabajo actual
            temperature: Temperatura para generación
            mode: Modo de operación
        """
        self.client = client
        self.model = model
        self.workspace_root = workspace_root.resolve()
        self.current_cwd = (current_cwd or workspace_root).resolve()
        self.temperature = temperature
        self.mode = mode
        
        # Componentes
        self.tool_registry = ToolRegistry(
            workspace_root=self.workspace_root,
            current_cwd=self.current_cwd,
        )
        self.approval_manager = ApprovalManager()
        self.state = AgentState(mode=mode)
        # Running lightweight summary of old conversation turns
        self._context_summary: str = ""
        # Memory context string injected into system prompt
        self._memory_context: str = ""
        # Optional MemoryStore for auto-extraction
        self._memory_store: Optional[Any] = None
        # Límite de pasos por sesión (sobreescribe MAX_AGENT_STEPS del config)
        self._max_agent_steps: Optional[int] = None
        # Instrucciones personalizadas del usuario (añadidas al system prompt)
        self._custom_instructions: str = ""
        # Acumulador de tokens para la sesión actual
        self._token_usage: Dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }

        # Registrar herramientas MCP en el registry para el modo JSON-ReAct
        self._register_mcp_tools()

        # Componentes de conversación (responsabilidad única por módulo)
        from core.conversation.context_builder import ContextBuilder
        from core.conversation.parser import NaturalResponseParser
        from core.conversation.reflector import ResponseReflector

        self._context_builder = ContextBuilder(
            mode=self.mode,
            workspace_root=self.workspace_root,
            current_cwd=self.current_cwd,
        )
        from config import DECISION_TEMPERATURE

        self._response_parser = NaturalResponseParser(
            llm_call=lambda msgs, fmt: self._call_model(
                msgs, fmt=fmt, temperature=DECISION_TEMPERATURE
            ),
            dynamic_tool_names=list(self.tool_registry._dynamic_executors.keys()),
        )
        self._reflector = ResponseReflector(
            llm_call=lambda msgs, temp, fmt: self.client.chat(
                model=self.model,
                messages=msgs,
                options={"temperature": temp},
                fmt=fmt,
            ),
        )
    
    def _register_mcp_tools(self) -> None:
        """Registra herramientas MCP en el ToolRegistry para el modo JSON-ReAct."""
        try:
            from tools.mcp_manager import MCPManager
            mcp = MCPManager.get_instance()
            for tool_def in mcp.get_all_tools():
                ollama_fmt = tool_def.to_ollama_tool()

                def make_executor(full_name: str):
                    def executor(args: dict) -> str:
                        return MCPManager.get_instance().execute_tool_sync(full_name, args)
                    return executor

                self.tool_registry.register_dynamic_tool(
                    name=tool_def.full_name,
                    ollama_tool=ollama_fmt,
                    executor=make_executor(tool_def.full_name),
                )
        except Exception:
            pass  # MCP no disponible o sin herramientas registradas

    def set_mode(self, mode: str) -> None:
        """Cambia el modo de operación."""
        self.mode = mode
        self.state.mode = mode
    
    def set_cwd(self, cwd: Path) -> None:
        """Actualiza el directorio de trabajo."""
        self.current_cwd = cwd.resolve()
        self.tool_registry.update_cwd(self.current_cwd)
    
    def _call_model(
        self,
        messages: List[Dict[str, Any]],
        stream: bool = False,
        fmt: Optional[Any] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Llama al modelo y retorna la respuesta.

        Args:
            fmt: "json" para forzar JSON válido, o un dict con JSON schema
                 para structured outputs (llamadas de decisión).
            temperature: override puntual (p.ej. DECISION_TEMPERATURE para
                 llamadas de decisión); si es None usa la de la sesión.
        """
        temp = self.temperature if temperature is None else temperature
        if stream:
            chunks = []
            for chunk in self.client.chat_stream(
                model=self.model,
                messages=messages,
                options={"temperature": temp},
                fmt=fmt,
            ):
                chunks.append(chunk)
            return "".join(chunks)
        else:
            result = self.client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": temp},
                fmt=fmt,
            )
            usage = self.client.last_usage
            if usage:
                self._token_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                self._token_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                self._token_usage["total_tokens"] += usage.get("total_tokens", 0)
                self._token_usage["calls"] += 1
                self._token_usage["last_prompt"] = usage.get("prompt_tokens", 0)
                self._token_usage["last_completion"] = usage.get("completion_tokens", 0)
            return result
    
    # ------------------------------------------------------------------
    # Construcción de mensajes (delegada a ContextBuilder)
    # ------------------------------------------------------------------

    def _maybe_summarize(self, conversation: Conversation) -> None:
        """Delega al ContextBuilder."""
        self._context_builder.maybe_summarize(conversation)
        # Mantener compatibilidad con código que lee self._context_summary
        self._context_summary = self._context_builder.context_summary

    def _build_messages(
        self,
        conversation: Conversation,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Delega al ContextBuilder."""
        # Mantener sincronizadas las propiedades mutables
        self._context_builder.set_mode(self.mode)
        self._context_builder.set_cwd(self.current_cwd)
        self._context_builder.memory_context = self._memory_context
        self._context_builder.context_summary = self._context_summary
        return self._context_builder.build(conversation, system_prompt=system_prompt)

    def _add_workspace_context(self, conversation: Conversation) -> None:
        """Añade contexto del workspace como mensaje system de la conversación.

        NOTA: el flujo natural ya no usa este método — embebe el snapshot en el
        system prompt directamente. Se mantiene por compatibilidad con paths
        legacy (function calling nativo).
        """
        self._context_builder.set_cwd(self.current_cwd)
        snapshot = self._context_builder.build_workspace_snapshot()
        conversation.add_system_message(snapshot)
    
    def _repair_tool_call(self, raw_response: str) -> Optional[ToolCall]:
        """Intenta reparar una respuesta de tool call malformada."""
        repair_messages = [
            {"role": "system", "content": PromptManager.get_tool_repair_prompt()},
            {"role": "user", "content": raw_response},
        ]
        
        try:
            repaired = self._call_model(repair_messages, fmt="json")
        except OllamaClientError:
            return None
        
        return ToolRegistry.extract_tool_call(repaired)
    
    # ------------------------------------------------------------------
    # Pre-exploración automática del workspace
    # ------------------------------------------------------------------

    def _pre_explore_workspace(self, user_input: str) -> str:
        """Lee automáticamente archivos clave del workspace antes del primer LLM call.

        Busca y lee:
        - README.md (si existe)
        - Archivos .py que importan módulos mencionados en el input del usuario
        - Los propios archivos .py mencionados en el input

        Retorna un bloque de texto formateado listo para inyectar como contexto,
        o "" si no encontró nada relevante.
        """
        import re

        sections: list[str] = []

        # 1. README
        for readme_name in ("README.md", "README.rst", "README.txt", "readme.md"):
            readme_path = self.workspace_root / readme_name
            if readme_path.exists():
                try:
                    text = readme_path.read_text(encoding="utf-8", errors="replace")[:2000]
                    if text.strip():
                        sections.append(f"[{readme_name}]\n{text}")
                except OSError:
                    pass
                break

        # 2. Detectar archivos/módulos mencionados en el input
        mentioned_py = re.findall(r'\b[\w\-/]+\.py\b', user_input)
        module_stems: set[str] = {Path(f).stem for f in mentioned_py}

        # 3. Leer los archivos .py mencionados directamente
        for stem in set(module_stems):
            for candidate in self.workspace_root.rglob(f"{stem}.py"):
                if any(skip in candidate.parts for skip in (".git", ".venv", "venv", "__pycache__")):
                    continue
                try:
                    text = candidate.read_text(encoding="utf-8", errors="replace")
                    rel = candidate.relative_to(self.workspace_root)
                    if text.strip():
                        sections.append(f"[{rel}]\n{text[:3000]}")
                except OSError:
                    pass

        # 4. Buscar archivos .py que importan esos módulos (dependientes directos)
        found_importers: set[Path] = set()
        try:
            for py_file in self.workspace_root.rglob("*.py"):
                if any(skip in py_file.parts for skip in (".git", ".venv", "venv", "__pycache__")):
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8", errors="replace")
                    if any(
                        f"import {stem}" in content or f"from {stem}" in content
                        for stem in module_stems
                    ):
                        found_importers.add(py_file)
                except OSError:
                    pass
        except OSError:
            pass

        for fp in sorted(found_importers)[:4]:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                rel = fp.relative_to(self.workspace_root)
                label = str(rel)
                # No duplicar si ya está en sections (comparar cabecera exacta)
                if any(s.startswith(f"[{label}]") for s in sections):
                    continue
                if text.strip():
                    sections.append(f"[{rel}]\n{text[:3000]}")
            except OSError:
                pass

        if not sections:
            return ""

        return (
            "=== CONTEXTO AUTOMÁTICO DEL REPOSITORIO ===\n"
            "Archivos leídos automáticamente del workspace antes de responder:\n\n"
            + "\n\n---\n\n".join(sections)
            + "\n\n=== FIN DEL CONTEXTO AUTOMÁTICO ==="
        )

    # ------------------------------------------------------------------
    # Parser de respuestas naturales (delegado a NaturalResponseParser)
    # ------------------------------------------------------------------

    def _parse_natural_response(self, response: str) -> Dict[str, Any]:
        """Delega al NaturalResponseParser inyectado en el constructor."""
        return self._response_parser.parse(response)

    # ------------------------------------------------------------------
    # Reflexión crítica (delegada a ResponseReflector)
    # ------------------------------------------------------------------

    def _reflect_on_response(
        self,
        response: str,
        conversation: Conversation,
    ) -> str:
        """Delega al ResponseReflector inyectado en el constructor."""
        return self._reflector.review(
            response=response,
            conversation=conversation,
            on_correction=self.state.add_trace,
        )

    # ------------------------------------------------------------------
    # Extracción de memorias (delegada a MemoryExtractionHook)
    # ------------------------------------------------------------------

    def extract_memories(self, user_input: str, response_content: str) -> None:
        """Extrae memorias de una interacción. PÚBLICO — pensado para que el
        caller (e.g. websocket) lo invoque como background task después de
        haber enviado la respuesta al usuario."""
        self._get_memory_hook().maybe_extract(user_input, response_content)

    def _maybe_extract_memories(
        self,
        user_input: str,
        response_content: str,
    ) -> None:
        """Alias privado conservado por compatibilidad. Prefiere extract_memories."""
        self.extract_memories(user_input, response_content)

    def _get_memory_hook(self):
        """Construye (o retorna cacheado) el MemoryExtractionHook."""
        from core.memory_hook import MemoryExtractionHook

        if not self._memory_store:
            return MemoryExtractionHook.disabled()

        # Reconstruir si cambió el store o el workspace_root
        cached = getattr(self, "_memory_hook_cache", None)
        if cached and cached[0] is self._memory_store and cached[1] == str(self.workspace_root):
            return cached[2]

        def llm_call(messages: List[Dict[str, Any]]) -> str:
            from llm.schemas import MEMORY_SCHEMA

            return self.client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": 0.2},
                fmt=MEMORY_SCHEMA,
            )

        hook = MemoryExtractionHook(
            memory_store=self._memory_store,
            llm_call=llm_call,
            workspace_root=str(self.workspace_root),
        )
        self._memory_hook_cache = (self._memory_store, str(self.workspace_root), hook)
        return hook

    # ------------------------------------------------------------------
    # Modos de operación
    # ------------------------------------------------------------------

    def chat(
        self,
        user_input: str,
        conversation: Conversation,
        attachments: Optional[List[str]] = None,
        images: Optional[List[str]] = None,
    ) -> AgentResponse:
        """
        Modo CHAT: Conversación simple sin herramientas.
        
        Args:
            user_input: Mensaje del usuario
            conversation: Conversación actual
            attachments: Archivos adjuntos (texto)
            images: Imágenes en base64
            
        Returns:
            Respuesta del agente
        """
        self.state.reset()
        self.state.mode = OperationMode.CHAT
        
        # Agregar mensaje del usuario
        conversation.add_user_message(
            content=user_input,
            attachments=attachments or [],
            images=images or [],
        )
        
        # Llamar al modelo (con instrucciones personalizadas si las hay)
        if self._custom_instructions:
            from llm.prompts import PromptManager as _PM
            _sp = _PM.get_system_prompt_with_memory(
                self.mode, self._memory_context, self._custom_instructions
            )
            messages = self._build_messages(conversation, system_prompt=_sp)
        else:
            messages = self._build_messages(conversation)

        try:
            response = self._call_model(messages)
        except OllamaClientError as e:
            return AgentResponse(
                content="",
                status="error",
                error=str(e),
            )
        
        # Reflexión crítica
        response = self._reflect_on_response(response, conversation)

        # Agregar respuesta
        conversation.add_assistant_message(response)

        # NOTA: extracción de memorias se delega al caller (websocket) como
        # background task tras enviar la respuesta — ya no es síncrona aquí.

        return AgentResponse(
            content=response,
            status="completed",
            token_usage=dict(self._token_usage),
        )

    def run(
        self,
        user_input: str,
        conversation: Conversation,
        attachments: Optional[List[str]] = None,
        images: Optional[List[str]] = None,
        step_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgentResponse:
        """Modo AGENT: enruta entre fast-path conversacional o ciclo natural."""
        from core.conversation.router import ConversationRouter

        self.state.reset()
        self.state.mode = OperationMode.AGENT
        self.state.is_running = True

        # Comprimir contexto si la conversación es larga
        self._maybe_summarize(conversation)

        # Agregar mensaje del usuario
        conversation.add_user_message(
            content=user_input,
            attachments=attachments or [],
            images=images or [],
        )

        # Fast-path: mensajes claramente conversacionales (saludos, ack, etc.)
        # → una sola llamada al modelo, sin parser, sin reflexión, sin memoria.
        if not attachments and not images and ConversationRouter.is_conversational(user_input):
            self.state.add_trace("Fast-path conversacional (sin parser/reflexión)")
            return self._run_fast_path(user_input, conversation)

        if self._model_supports_tools():
            self.state.add_trace("Modo: native tool calling")
            return self._run_native_tools(
                user_input=user_input,
                conversation=conversation,
                step_callback=step_callback,
                cancel_check=cancel_check,
            )

        return self._run_natural(
            user_input=user_input,
            conversation=conversation,
            step_callback=step_callback,
            cancel_check=cancel_check,
        )

    def _run_fast_path(
        self,
        user_input: str,
        conversation: Conversation,
    ) -> AgentResponse:
        """Camino rápido para mensajes conversacionales: una sola llamada al modelo."""
        from llm.prompts import NATURAL_CONVERSATIONAL_PROMPT

        messages = self._build_messages(
            conversation, system_prompt=NATURAL_CONVERSATIONAL_PROMPT
        )

        try:
            response = self._call_model(messages)
        except OllamaClientError as exc:
            self.state.is_running = False
            return AgentResponse(
                content="",
                status="error",
                error=str(exc),
                trace=self.state.trace,
            )

        if not response.strip():
            response = "..."

        conversation.add_assistant_message(response)
        self.state.is_running = False
        return AgentResponse(
            content=response,
            status="completed",
            trace=self.state.trace,
            new_cwd=str(self.current_cwd),
            token_usage=dict(self._token_usage),
        )

    def _model_supports_tools(self) -> bool:
        """Verifica si el modelo activo soporta native tool calling (resultado cacheado)."""
        if not hasattr(self, "_tools_cap_cache"):
            self._tools_cap_cache: Dict[str, bool] = {}
        if self.model not in self._tools_cap_cache:
            try:
                self._tools_cap_cache[self.model] = self.client.model_supports_tools(self.model)
            except Exception:
                self._tools_cap_cache[self.model] = False
        return self._tools_cap_cache.get(self.model, False)

    # ------------------------------------------------------------------
    # Modo native tool calling: JSON estructurado (modelos con soporte)
    # ------------------------------------------------------------------

    def _run_native_tools(
        self,
        user_input: str,
        conversation: Conversation,
        step_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgentResponse:
        """Ciclo agente usando native function calling del provider.

        El modelo devuelve tool_calls en JSON estructurado — no se necesita
        parser ni heurísticas regex.

        Durante el run, los tool calls y sus resultados viven SOLO en
        `extra_messages` (con el formato nativo del provider, cronología
        correcta). Al terminar —por cualquier vía— se persisten como texto en
        `conversation` para que el modelo los recuerde en turnos futuros.
        Así se evita que cada resultado aparezca duplicado en el prompt.
        """
        import json as _json
        from llm.prompts import NATURAL_AGENT_SYSTEM_PROMPT

        self._context_builder.set_cwd(self.current_cwd)
        workspace_ctx = self._context_builder.build_workspace_snapshot()
        full_system_prompt = f"{NATURAL_AGENT_SYSTEM_PROMPT}\n{workspace_ctx}"
        if self._custom_instructions:
            full_system_prompt += f"\n\nInstrucciones del usuario:\n{self._custom_instructions}"

        pre_ctx = self._pre_explore_workspace(user_input)
        if pre_ctx:
            self.state.add_trace("Pre-exploración automática del workspace")
            conversation.add_system_message(pre_ctx)

        tools = self.tool_registry.get_ollama_tools()
        limit = self._max_agent_steps or MAX_AGENT_STEPS
        tool_results: List[ToolResult] = []
        # Historial de tool calling de ESTE run, en formato nativo del provider.
        extra_messages: List[Dict[str, Any]] = []
        # Resúmenes en texto pendientes de persistir en conversation al terminar.
        pending_persist: List[str] = []
        # Detección de bucles: cuántas veces se ejecutó cada (tool, args) y
        # cuántas correcciones anti-repetición se han inyectado ya.
        executed_signatures: Dict[str, int] = {}
        repeat_corrections = 0

        def _flush_history() -> None:
            """Persiste los tool results en la conversación (memoria entre turnos)."""
            for text in pending_persist:
                conversation.add_system_message(text)
            pending_persist.clear()

        def _finish(content_: str, status_: str, error_: Optional[str] = None) -> AgentResponse:
            _flush_history()
            self.state.is_running = False
            return AgentResponse(
                content=content_,
                status=status_,
                error=error_,
                trace=self.state.trace,
                tool_results=tool_results,
                new_cwd=str(self.current_cwd),
                token_usage=dict(self._token_usage),
            )

        for step in range(1, limit + 1):
            self.state.step_count = step

            if cancel_check and cancel_check():
                return _finish("Ejecución cancelada por el usuario.", "cancelled")

            self.state.add_trace(f"Paso {step}: native tool call")
            if step_callback:
                step_callback(f"Paso {step}: consultando al modelo")

            messages = self._build_messages(conversation, system_prompt=full_system_prompt)
            messages.extend(extra_messages)

            try:
                raw = self.client.chat_with_tools(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options={"temperature": self.temperature},
                )
            except OllamaClientError as exc:
                return _finish("", "error", error_=str(exc))

            content = raw.get("content", "") or ""
            tool_calls_raw = raw.get("tool_calls", []) or []

            if not tool_calls_raw:
                # Sin tool_calls nativos — el modelo puede haber expresado la intención
                # como texto libre (ej. "Voy a ejecutar el comando: `git...`").
                # Intentar el parser heurístico antes de devolver como respuesta final.
                if content:
                    parsed = self._parse_natural_response(content)
                    if parsed.get("needs_tool"):
                        tool_name = parsed.get("tool", "")
                        tool_args = parsed.get("args", {})
                        # Reinyectar como si fuera un tool_call nativo y continuar
                        tool_calls_raw = [{
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args if isinstance(tool_args, dict) else {},
                            }
                        }]
                        self.state.add_trace(
                            f"Paso {step}: fallback heurístico → {tool_name}"
                        )
                        # No hacer return — caer al bloque de ejecución más abajo

                if not tool_calls_raw:
                    # Realmente no hay tool → respuesta final
                    final = self._reflect_on_response(content or "Listo.", conversation)
                    _flush_history()
                    conversation.add_assistant_message(final)
                    self.state.is_running = False
                    return AgentResponse(
                        content=final,
                        status="completed",
                        trace=self.state.trace,
                        tool_results=tool_results,
                        new_cwd=str(self.current_cwd),
                        token_usage=dict(self._token_usage),
                    )

            # Normalizar TODOS los tool calls del turno (id + arguments dict).
            # El id debe ser estable: se reutiliza al emparejar cada resultado.
            for i, tc in enumerate(tool_calls_raw):
                if not tc.get("id"):
                    tc["id"] = f"call_s{step}_{i}"
                func = tc.get("function", {})
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except Exception:
                        args = {}
                func["arguments"] = args if isinstance(args, dict) else {}
                tc["function"] = func

            # El assistant message referencia exactamente los calls del turno;
            # cada uno recibirá su mensaje de resultado (o error de validación).
            extra_messages.append(
                self.client.format_assistant_tool_message(content, tool_calls_raw)
            )

            for tc in tool_calls_raw:
                tool_name = tc["function"].get("name", "")
                tool_args = tc["function"].get("arguments", {})
                tool_call = ToolCall(tool=tool_name, args=tool_args)

                # Anti-bucle: el mismo tool con los mismos args repetido.
                # Un repeat legítimo se permite (p.ej. git status tras cambios);
                # a partir del tercero se devuelve una corrección en lugar de
                # ejecutar, y si el modelo insiste se fuerza el cierre.
                signature = f"{tool_name}:{_json.dumps(tool_args, sort_keys=True, default=str)}"
                if executed_signatures.get(signature, 0) >= 2:
                    repeat_corrections += 1
                    self.state.add_trace(
                        f"Paso {step}: repetición de {tool_name} bloqueada "
                        f"({repeat_corrections}/3)"
                    )
                    if repeat_corrections >= 3:
                        summary = self._summarize_tool_activity(tool_results)
                        _flush_history()
                        conversation.add_assistant_message(summary)
                        self.state.is_running = False
                        return AgentResponse(
                            content=summary,
                            status="completed",
                            trace=self.state.trace,
                            tool_results=tool_results,
                            new_cwd=str(self.current_cwd),
                            token_usage=dict(self._token_usage),
                        )
                    extra_messages.append(
                        self.client.format_tool_result_message(
                            tc,
                            "Ya ejecutaste esta misma herramienta con estos mismos "
                            "argumentos y el resultado no va a cambiar. NO la repitas. "
                            "Si la tarea del usuario ya está completa, responde ahora "
                            "en texto normal (sin tool calls) resumiendo lo que hiciste.",
                        )
                    )
                    continue

                # Validación — el error se devuelve al modelo como resultado
                validation_error = self.tool_registry.validate_tool_call(tool_call)
                if validation_error:
                    self.state.add_trace(f"Paso {step}: tool inválida — {validation_error}")
                    extra_messages.append(
                        self.client.format_tool_result_message(
                            tc, f"Error: {validation_error}"
                        )
                    )
                    continue

                # Aprobación — pausar el run; lo ya ejecutado se persiste
                is_write = self.tool_registry.is_tool_write_operation(tool_call)
                if self.approval_manager.requires_approval(tool_call, is_write):
                    if content:
                        conversation.add_assistant_message(content)
                    self.state.pending_approval = tool_call
                    self.approval_manager.request_approval(tool_call)
                    return _finish(
                        f"Se requiere aprobación para: `{tool_call}`",
                        "awaiting_approval",
                    )

                # Ejecución
                cmd_preview = tool_args.get("command", "") if tool_name == "run_command" else ""
                if step_callback:
                    if cmd_preview:
                        step_callback({
                            "kind": "exec",
                            "message": f"Ejecutando: {tool_name}",
                            "command": cmd_preview,
                        })
                    else:
                        step_callback(f"Paso {step}: ejecutando {tool_name}")
                result = self.tool_registry.execute(tool_call)
                tool_results.append(result)
                executed_signatures[signature] = executed_signatures.get(signature, 0) + 1

                if result.new_cwd:
                    self.set_cwd(Path(result.new_cwd))

                tool_output = result.output if result.success else f"Error: {result.error}"

                # Notificar resultado al frontend
                if step_callback:
                    step_callback({
                        "kind": "tool_result",
                        "tool": tool_name,
                        "success": result.success,
                        "output": (tool_output or "")[:2000],
                    })

                # Nudge embebido en el último resultado del turno: canal seguro
                # para todos los providers (un system message intercalado no
                # lo es). Ayuda a modelos locales pequeños a cerrar el ciclo.
                is_last_of_turn = tc is tool_calls_raw[-1]
                feedback = tool_output
                if is_last_of_turn:
                    feedback = (
                        f"{tool_output}\n\n"
                        "[Si la tarea del usuario ya está completa, responde ahora "
                        "en texto normal sin más tool calls. Si falta algo, continúa "
                        "con la siguiente herramienta.]"
                    )

                # Resultado en formato nativo (solo para este run)
                extra_messages.append(
                    self.client.format_tool_result_message(tc, feedback)
                )
                # Resumen textual para persistir al terminar el run (sin nudge)
                pending_persist.append(
                    PromptManager.build_tool_result_context(
                        step=step,
                        tool_call=str(tool_call),
                        result=tool_output,
                    )
                )

        return _finish(f"Se alcanzó el límite de {limit} pasos.", "max_steps")

    @staticmethod
    def _summarize_tool_activity(tool_results: List[ToolResult]) -> str:
        """Resumen de cierre cuando se fuerza el fin del ciclo (anti-bucle)."""
        if not tool_results:
            return "Listo."
        lines = ["He completado las siguientes acciones:"]
        seen = set()
        for tr in tool_results:
            desc = str(tr.tool_call)
            if desc in seen:
                continue
            seen.add(desc)
            estado = "✓" if tr.success else "✗"
            lines.append(f"- {estado} {desc}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Modo natural: texto libre → parser → tool (sin JSON forzado)
    # ------------------------------------------------------------------

    def _run_natural(
        self,
        user_input: str,
        conversation: Conversation,
        step_callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AgentResponse:
        """Ciclo agente delegado a NaturalConversationLoop.

        El bucle ejecuta el flujo modelo → parser → tool. Aquí solo se
        ensambla el system prompt, se invoca el bucle, y se aplican los
        post-procesos (reflexión, memoria, persistencia) al resultado.
        """
        from core.conversation.natural_loop import NaturalConversationLoop
        from llm.prompts import NATURAL_AGENT_SYSTEM_PROMPT

        # Pre-exploración automática: inyecta archivos clave en el contexto
        # antes de que el LLM empiece a razonar sobre la tarea.
        pre_ctx = self._pre_explore_workspace(user_input)
        if pre_ctx:
            self.state.add_trace("Pre-exploración automática del workspace")
            conversation.add_system_message(pre_ctx)

        # System prompt con snapshot del workspace embebido (fresco en cada run)
        self._context_builder.set_cwd(self.current_cwd)
        workspace_ctx = self._context_builder.build_workspace_snapshot()
        full_system_prompt = f"{NATURAL_AGENT_SYSTEM_PROMPT}\n{workspace_ctx}"
        if self._custom_instructions:
            full_system_prompt += f"\n\nInstrucciones del usuario:\n{self._custom_instructions}"

        loop = NaturalConversationLoop(
            llm_call=lambda msgs, fmt: self._call_model(msgs, fmt=fmt),
            build_messages=lambda conv, sp: self._build_messages(conv, system_prompt=sp),
            parse_response=self._parse_natural_response,
            validate_tool_call=self.tool_registry.validate_tool_call,
            is_write_operation=self.tool_registry.is_tool_write_operation,
            requires_approval=self.approval_manager.requires_approval,
            execute_tool=self.tool_registry.execute,
            on_cwd_change=self.set_cwd,
            state=self.state,
        )

        result = loop.run(
            conversation=conversation,
            system_prompt=full_system_prompt,
            step_callback=step_callback,
            cancel_check=cancel_check,
            max_steps=self._max_agent_steps,
        )

        # Post-procesos según el status del bucle
        if result.status == "completed":
            final = self._reflect_on_response(result.final_response, conversation)
            conversation.add_assistant_message(final)
            self.state.is_running = False
            # NOTA: extracción de memorias se delega al caller (websocket) como
            # background task tras enviar la respuesta — ya no es síncrona aquí.
            return AgentResponse(
                content=final,
                status="completed",
                trace=self.state.trace,
                tool_results=result.tool_results,
                new_cwd=str(self.current_cwd),
                token_usage=dict(self._token_usage),
            )

        if result.status == "awaiting_approval":
            # El bucle ya persistió la respuesta del modelo en la conversación
            self.state.pending_approval = result.pending_tool_call
            self.approval_manager.request_approval(result.pending_tool_call)
            self.state.is_running = False
            return AgentResponse(
                content=result.final_response,
                status="awaiting_approval",
                trace=self.state.trace,
                tool_results=result.tool_results,
                new_cwd=str(self.current_cwd),
                token_usage=dict(self._token_usage),
            )

        if result.status == "cancelled":
            self.state.is_running = False
            return AgentResponse(
                content=result.final_response,
                status="cancelled",
                trace=self.state.trace,
                tool_results=result.tool_results,
                new_cwd=str(self.current_cwd),
                token_usage=dict(self._token_usage),
            )

        if result.status == "error":
            self.state.is_running = False
            return AgentResponse(
                content="",
                status="error",
                error=result.error,
                trace=self.state.trace,
                tool_results=result.tool_results,
                token_usage=dict(self._token_usage),
            )

        # max_steps
        self.state.add_trace(f"Límite de {MAX_AGENT_STEPS} pasos alcanzado")
        self.state.is_running = False
        return AgentResponse(
            content=result.final_response,
            status="max_steps",
            trace=self.state.trace,
            tool_results=result.tool_results,
            new_cwd=str(self.current_cwd),
            token_usage=dict(self._token_usage),
        )

    def resume_after_approval(
        self,
        conversation: Conversation,
        approved: bool,
        step_callback: Optional[Callable[[str], None]] = None,
    ) -> AgentResponse:
        """
        Continúa la ejecución después de una aprobación.
        
        Args:
            conversation: Conversación actual
            approved: Si fue aprobado
            
        Returns:
            Respuesta del agente
        """
        if not self.approval_manager.has_pending:
            return AgentResponse(
                content="No hay acción pendiente de aprobación.",
                status="error",
                error="No pending approval",
            )
        
        pending = self.approval_manager.pending_request
        tool_call = pending.tool_call
        
        if not approved:
            self.approval_manager.reject_pending()
            self.state.add_trace("Acción rechazada por el usuario")
            conversation.add_system_message("El usuario rechazó la acción.")
            
            return AgentResponse(
                content="Acción rechazada.",
                status="completed",
                trace=self.state.trace,
            )
        
        # Aprobar y ejecutar
        self.approval_manager.approve_pending()
        self.state.add_trace(f"Acción aprobada, ejecutando {tool_call}")
        
        result = self.tool_registry.execute(tool_call)
        
        if result.new_cwd:
            self.set_cwd(Path(result.new_cwd))
        
        # Agregar resultado
        observation = PromptManager.build_tool_result_context(
            step=self.state.step_count,
            tool_call=str(tool_call),
            result=result.output if result.success else f"Error: {result.error}",
        )
        conversation.add_system_message(observation)
        
        # Continuar el ciclo
        return self.run(
            user_input="",
            conversation=conversation,
            step_callback=step_callback,
        )
    
    # ------------------------------------------------------------------
    # Ejecución de planes (delegada a PlanExecutor)
    # ------------------------------------------------------------------

    def execute_plan_step(
        self,
        plan: Plan,
        conversation: Conversation,
        auto_execute: bool = False,
        step_callback: Optional[Callable[[str, dict], None]] = None,
    ) -> AgentResponse:
        """Delega al PlanExecutor (creado lazily)."""
        executor = self._get_plan_executor()
        result = executor.execute(
            plan=plan,
            conversation=conversation,
            auto_execute=auto_execute,
            step_callback=step_callback,
        )
        return AgentResponse(
            content=result.content,
            status=result.status,
            plan=result.plan,
            trace=self.state.trace,
        )

    def _get_plan_executor(self):
        """Construye (o retorna cacheado) el PlanExecutor."""
        from core.plan_executor import PlanExecutor

        cached = getattr(self, "_plan_executor_cache", None)
        if cached:
            return cached

        executor = PlanExecutor(
            llm_call=lambda msgs, fmt: self._call_model(msgs, fmt=fmt),
            tool_registry=self.tool_registry,
            approval_manager=self.approval_manager,
            state=self.state,
            on_cwd_change=self.set_cwd,
        )
        self._plan_executor_cache = executor
        return executor
