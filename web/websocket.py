"""WebSocket handlers para chat en tiempo real."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import WebSocket, WebSocketDisconnect

from config import (
    AGENT_TASK_TIMEOUT,
    MAX_ATTACHMENT_CHARS_PER_FILE,
    MAX_ATTACHMENT_CHARS_TOTAL,
    MAX_INPUT_CHARS,
    MEMORY_ENABLED,
    OLLAMA_BASE_URL,
    OperationMode,
)
from core.agent import Agent, AgentResponse
from core.models import Plan, PlanStatus, ToolCall
from core.planner import PlanManager
from llm.client import OllamaClient, OllamaClientError, create_client
from web.state import Session, SessionManager
from web.metrics import MetricsCollector

# Setup logger
logger = logging.getLogger("websocket")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[%(asctime)s] [WS] %(message)s', '%H:%M:%S'))
    logger.addHandler(handler)


class ConnectionManager:
    """Gestor de conexiones WebSocket."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Acepta una conexión WebSocket."""
        await websocket.accept()
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        """Desconecta un cliente."""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
    
    async def send_json(self, session_id: str, data: Dict[str, Any]):
        """Envía JSON a un cliente específico."""
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_json(data)
    
    async def send_text(self, session_id: str, text: str):
        """Envía texto a un cliente específico."""
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_text(text)


manager = ConnectionManager()


async def _build_full_content(
    content: str,
    attachments_raw: list,
) -> str:
    """
    Inyecta el contenido de adjuntos en el mensaje del usuario.
    Respeta límites de tamaño para no saturar el contexto.
    """
    if not attachments_raw:
        return content

    blocks = []
    total_chars = 0
    for att in attachments_raw:
        if not isinstance(att, dict):
            continue
        att_content = att.get("content", "")
        if not att_content:
            continue
        name = att.get("name", "archivo")
        # Truncar por archivo
        if len(att_content) > MAX_ATTACHMENT_CHARS_PER_FILE:
            att_content = att_content[:MAX_ATTACHMENT_CHARS_PER_FILE] + "\n...[recortado]..."
        # Respetar límite total
        if total_chars + len(att_content) > MAX_ATTACHMENT_CHARS_TOTAL:
            remaining = MAX_ATTACHMENT_CHARS_TOTAL - total_chars
            if remaining <= 0:
                break
            att_content = att_content[:remaining] + "\n...[recortado]..."
        blocks.append(f"[Archivo: {name}]\n{att_content}")
        total_chars += len(att_content)

    if not blocks:
        return content

    attachment_ctx = "\n\n---\n\n".join(blocks)
    return f"{content}\n\n---\nArchivos adjuntos:\n{attachment_ctx}"


import re as _re
_AFFIRMATIVE_RE = _re.compile(
    r"^(s[íi]|yes|ok|okay|dale|claro|adelante|procede|hazlo|"
    r"ejecuta|confirmo?|confirmar|apruebo?|aprobar|approve|"
    r"proceed|go\s+ahead|do\s+it|continue|continuar|perfecto|"
    r"listo|va|venga|ándale|ándele)[!.,\s]*$",
    _re.IGNORECASE,
)


async def handle_chat_message(
    websocket: WebSocket,
    session: Session,
    data: Dict[str, Any],
) -> None:
    """Maneja un mensaje de chat."""
    raw_content = data.get("content", "").strip()
    if not raw_content:
        await websocket.send_json({"type": "error", "message": "Empty message"})
        return

    # --- Si hay una aprobación pendiente y el mensaje es una confirmación, redirigir ---
    if session.pending_approval and _AFFIRMATIVE_RE.match(raw_content):
        await handle_approval(websocket, session, {"approved": True})
        return

    # --- Validación de tamaño de input ---
    if len(raw_content) > MAX_INPUT_CHARS:
        await websocket.send_json({
            "type": "error",
            "message": (
                f"El mensaje es demasiado largo ({len(raw_content):,} caracteres). "
                f"Máximo permitido: {MAX_INPUT_CHARS:,} caracteres."
            ),
        })
        return

    attachments_raw = data.get("attachments", [])
    images = data.get("images", [])
    image_names = data.get("image_names", [])

    # --- Inyectar adjuntos en el contenido del mensaje ---
    content = await _build_full_content(raw_content, attachments_raw)

    # Etiquetas para persistir en Message.attachments y mostrarlas en el chat.
    attachment_labels: list = []
    for att in attachments_raw:
        if isinstance(att, dict) and att.get("name"):
            attachment_labels.append(f"📎 {att['name']}")
    for name in image_names:
        if name:
            attachment_labels.append(f"🖼️ {name}")

    # --- Cola por sesión: evitar ejecuciones concurrentes ---
    lock = SessionManager.get_lock(session.id)
    if lock.locked():
        await websocket.send_json({
            "type": "error",
            "message": "⏳ El agente ya está procesando. Espéra o canélalo primero.",
        })
        return

    # --- Métricas ---
    metric = MetricsCollector.start(session.id, session.mode)
    metric.prompt_chars = len(content)

    async with lock:
        # --- Flag de cancelación (thread-safe) ---
        cancel_flag = SessionManager.get_cancel_flag(session.id)
        cancel_flag.clear()

        def cancel_check() -> bool:
            return cancel_flag.is_set()

        # Crear cliente y agente
        from llm.base import LLMClientError as _LLMErr
        try:
            client = create_client(provider=session.llm_provider, base_url=session.llm_base_url or None)
        except _LLMErr as _e:
            await websocket.send_json({"type": "error", "message": str(_e)})
            return
        agent = Agent(
            client=client,
            model=session.model,
            workspace_root=Path(session.workspace_root),
            current_cwd=Path(session.current_cwd),
            temperature=session.temperature,
            mode=session.mode,
        )
        agent.approval_manager.set_level(session.approval_level)
        agent._context_summary = session.context_summary
        agent._max_agent_steps = session.max_agent_steps
        agent.tool_registry.set_python_timeout(session.python_sandbox_timeout)
        # Inyectar skill activo al comienzo de las instrucciones
        if session.active_skill:
            from tools.skills_manager import SkillsManager
            _skill_prompt = SkillsManager(Path(session.workspace_root)).get_skill_prompt(session.active_skill)
            if _skill_prompt:
                agent._custom_instructions = _skill_prompt + (
                    "\n\n" + session.system_prompt if session.system_prompt else ""
                )
            else:
                agent._custom_instructions = session.system_prompt
        else:
            agent._custom_instructions = session.system_prompt

        # --- Memoria a largo plazo ---
        memory_store = None
        if MEMORY_ENABLED and SessionManager._db:
            from core.memory import MemoryStore
            memory_store = MemoryStore(SessionManager._db)
            agent._memory_store = memory_store
            agent._memory_context = memory_store.build_memory_context(
                session.workspace_root
            )

        # --- RAG semántico (workspace + KB) ---
        # Activo en modos Agent y Plan; en Chat es opt-in por keywords.
        from rag.semantic_rag import get_semantic_rag
        srag = get_semantic_rag(session.workspace_root)
        # Asegurar indexación en background la primera vez
        srag.ensure_indexed()
        if srag.should_activate(raw_content):
            rag_context, _ = await asyncio.to_thread(
                srag.retrieve, raw_content
            )
            if rag_context:
                session.conversation.add_system_message(rag_context)

        # Notificar inicio
        await websocket.send_json({"type": "start", "mode": session.mode})

        try:
            if session.mode == OperationMode.CHAT:
                response = await asyncio.to_thread(
                    agent.chat,
                    content,
                    session.conversation,
                    attachment_labels,
                    images,
                )

            elif session.mode == OperationMode.AGENT:
                # --- Streaming de pasos + cancelación ---
                step_queue: asyncio.Queue = asyncio.Queue()
                loop = asyncio.get_running_loop()

                def step_callback(msg) -> None:
                    """Acepta str o dict con campos {kind, ...}."""
                    loop.call_soon_threadsafe(step_queue.put_nowait, msg)

                agent_task = asyncio.create_task(
                    asyncio.to_thread(
                        lambda: agent.run(
                            content,
                            session.conversation,
                            attachment_labels,
                            images,
                            step_callback,
                            cancel_check,
                        )
                    )
                )

                async def _drain_and_wait() -> AgentResponse:
                    """Drenar step_queue mientras el agente trabaja y retornar su resultado."""
                    while not agent_task.done():
                        try:
                            step_msg = step_queue.get_nowait()
                            if isinstance(step_msg, dict):
                                await websocket.send_json({
                                    "type": "agent_step",
                                    **step_msg,
                                })
                            else:
                                await websocket.send_json({
                                    "type": "agent_step",
                                    "kind": "status",
                                    "message": step_msg,
                                })
                        except asyncio.QueueEmpty:
                            await asyncio.sleep(0.1)
                    # Drenar lo que quedó al terminar
                    while not step_queue.empty():
                        step_msg = step_queue.get_nowait()
                        if isinstance(step_msg, dict):
                            await websocket.send_json({"type": "agent_step", **step_msg})
                        else:
                            await websocket.send_json({"type": "agent_step", "kind": "status", "message": step_msg})
                    exc = agent_task.exception()
                    if exc:
                        raise exc
                    return agent_task.result()

                try:
                    response = await asyncio.wait_for(
                        _drain_and_wait(), timeout=session.agent_task_timeout
                    )
                except asyncio.TimeoutError:
                    agent_task.cancel()
                    metric.finish("timeout")
                    await websocket.send_json({
                        "type": "error",
                        "message": (
                            f"El agente tardó más de {session.agent_task_timeout}s "
                            "y fue cancelado automáticamente."
                        ),
                    })
                    SessionManager.save(session)
                    return

                metric.steps = len(response.trace)

            elif session.mode == OperationMode.PLAN:
                planner = PlanManager(client=client, model=session.model)
                plan = await asyncio.to_thread(
                    planner.create_plan,
                    content,
                    session.conversation,
                )
                if plan:
                    session.current_plan = plan.to_dict()
                    await websocket.send_json({
                        "type": "plan_created",
                        "plan": plan.to_dict(),
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No se pudo crear el plan",
                    })
                metric.finish("completed")
                return
            else:
                response = AgentResponse(
                    content="Modo no soportado",
                    status="error",
                )

            # --- Persistir sumario de contexto actualizado ---
            if agent._context_summary:
                session.context_summary = agent._context_summary

            # Error interno del loop: enviarlo como type=error para que el
            # frontend lo muestre (content puede ser vacío en este caso).
            if response.status == "error":
                metric.finish("error")
                await websocket.send_json({
                    "type": "error",
                    "message": response.error or "El agente encontró un error inesperado. Inténtalo de nuevo.",
                    "trace": response.trace,
                })
                SessionManager.save(session)
                return

            # Enviar respuesta INMEDIATAMENTE — sin esperar memoria/sugerencias
            await websocket.send_json({
                "type": "response",
                "content": response.content,
                "status": response.status,
                "trace": response.trace,
                "tool_results": [tr.to_dict() for tr in response.tool_results],
                "token_usage": response.token_usage,
                "message_count": len(session.conversation.messages),
            })

            # Actualizar CWD si cambió
            if response.new_cwd:
                session.current_cwd = response.new_cwd

            # Manejar aprobación pendiente
            if response.status == "awaiting_approval":
                pending_tool = agent.state.pending_approval
                session.pending_approval = {
                    "tool_call": str(pending_tool) if pending_tool else "",
                    "tool_call_data": pending_tool.to_dict() if pending_tool else None,
                    "description": response.content,
                }
                await websocket.send_json({
                    "type": "approval_required",
                    "pending": session.pending_approval,
                })

            # Guardar trace y métricas
            session.agent_trace = response.trace
            metric.finish(response.status)

            # --- Extracción de memorias en BACKGROUND (no bloquea respuesta) ---
            if memory_store and response.status == "completed" and response.content:
                async def _extract_memories_bg() -> None:
                    try:
                        await asyncio.to_thread(
                            agent.extract_memories, raw_content, response.content
                        )
                        # Notificar al frontend si se extrajo algo nuevo
                        ws_memories = memory_store.get_workspace_memories(
                            session.workspace_root
                        )
                        profile_traits = memory_store.get_profile_traits()
                        if ws_memories or profile_traits:
                            await websocket.send_json({
                                "type": "memory_updated",
                                "workspace_memories": len(ws_memories),
                                "profile_traits": len(profile_traits),
                            })
                    except Exception as _mem_exc:
                        logger.debug("Error extrayendo memorias en background: %s", _mem_exc)

                asyncio.create_task(_extract_memories_bg())

            # --- Sugerencias proactivas (background, no bloquea) ---
            # Se generan después de enviar la respuesta para no añadir latencia.
            try:
                recent_texts = [
                    m.content for m in session.conversation.messages[-6:]
                    if m.content
                ]
                suggestions = await asyncio.to_thread(
                    srag.get_proactive_suggestions, recent_texts
                )
                if suggestions:
                    await websocket.send_json({
                        "type": "rag_suggestion",
                        "suggestions": [
                            {
                                "path": s.path,
                                "score": s.score,
                                "snippet": s.snippet,
                                "reason": s.reason,
                            }
                            for s in suggestions
                        ],
                    })
            except Exception as _sug_exc:
                logger.debug("Error calculando sugerencias proactivas: %s", _sug_exc)

        except OllamaClientError as e:
            metric.finish("error")
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception as e:
            metric.finish("error")
            await websocket.send_json({
                "type": "error",
                "message": f"Error interno: {str(e)}",
            })
        finally:
            # Generar título automático la primera vez que hay mensajes
            if not session.title:
                session.title = session.generate_title()
            # Persistir sesión tras cada request (incluso si hubo error)
            SessionManager.save(session)


async def handle_approval(
    websocket: WebSocket,
    session: Session,
    data: Dict[str, Any],
) -> None:
    """Maneja una respuesta de aprobación."""
    approved = data.get("approved", False)
    
    if not session.pending_approval:
        await websocket.send_json({
            "type": "error",
            "message": "No hay aprobación pendiente",
        })
        return
    
    # Crear agente y continuar (heredando contexto de la sesión)
    from llm.base import LLMClientError as _LLMErr
    try:
        client = create_client(provider=session.llm_provider, base_url=session.llm_base_url or None)
    except _LLMErr as _e:
        await websocket.send_json({"type": "error", "message": str(_e)})
        return
    agent = Agent(
        client=client,
        model=session.model,
        workspace_root=Path(session.workspace_root),
        current_cwd=Path(session.current_cwd),
        temperature=session.temperature,
        mode=session.mode,
    )
    agent.approval_manager.set_level(session.approval_level)
    agent._context_summary = session.context_summary
    agent._max_agent_steps = session.max_agent_steps
    agent.tool_registry.set_python_timeout(session.python_sandbox_timeout)

    pending_tool_data = session.pending_approval.get("tool_call_data")
    if not pending_tool_data:
        await websocket.send_json({
            "type": "error",
            "message": "Aprobación pendiente inválida",
        })
        return
    
    tool_call = ToolCall.from_dict(pending_tool_data)
    agent.state.pending_approval = tool_call
    agent.approval_manager.request_approval(tool_call)

    await websocket.send_json({"type": "start", "mode": session.mode})

    step_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def step_callback(msg: str) -> None:
        loop.call_soon_threadsafe(step_queue.put_nowait, msg)

    try:
        agent_task = asyncio.create_task(
            asyncio.to_thread(
                lambda: agent.resume_after_approval(
                    session.conversation,
                    approved,
                    step_callback=step_callback,
                )
            )
        )

        while not agent_task.done():
            try:
                step_msg = step_queue.get_nowait()
                await websocket.send_json({"type": "agent_step", "message": step_msg})
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
        while not step_queue.empty():
            step_msg = step_queue.get_nowait()
            await websocket.send_json({"type": "agent_step", "message": step_msg})

        if agent_task.exception():
            raise agent_task.exception()
        response = agent_task.result()

        session.pending_approval = None

        await websocket.send_json({
            "type": "response",
            "content": response.content,
            "status": response.status,
            "trace": response.trace,
            "tool_results": [tr.to_dict() for tr in response.tool_results],
        })

    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })
    finally:
        # Persistir sesión tras cada aprobación
        SessionManager.save(session)


async def _run_plan_auto(
    websocket: WebSocket,
    session: Session,
    plan: Plan,
) -> None:
    """
    Ejecuta todos los pasos del plan de forma autónoma y hace streaming
    de cada paso completado via WebSocket.
    """
    from llm.base import LLMClientError as _LLMErr
    try:
        client = create_client(provider=session.llm_provider, base_url=session.llm_base_url or None)
    except _LLMErr as _e:
        await websocket.send_json({"type": "error", "message": str(_e)})
        return
    agent = Agent(
        client=client,
        model=session.model,
        workspace_root=Path(session.workspace_root),
        current_cwd=Path(session.current_cwd),
        temperature=session.temperature,
        mode=OperationMode.PLAN,
    )
    agent.approval_manager.set_level(session.approval_level)

    # Cola para que el step_callback (hilo) envíe actualizaciones al loop async
    step_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def step_callback(description: str, plan_dict: dict) -> None:
        loop.call_soon_threadsafe(step_queue.put_nowait, (description, plan_dict))

    agent_task = asyncio.create_task(
        asyncio.to_thread(
            lambda: agent.execute_plan_step(
                plan,
                session.conversation,
                auto_execute=True,
                step_callback=step_callback,
            )
        )
    )

    # Drenar la cola mientras el agente trabaja
    while not agent_task.done():
        try:
            description, plan_dict = step_queue.get_nowait()
            await websocket.send_json({
                "type": "plan_step_complete",
                "plan": plan_dict,
                "status": "in_progress",
                "content": description,
            })
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.1)

    # Drenar lo que quedó en la cola tras terminar
    while not step_queue.empty():
        description, plan_dict = step_queue.get_nowait()
        await websocket.send_json({
            "type": "plan_step_complete",
            "plan": plan_dict,
            "status": "in_progress",
            "content": description,
        })

    exc = agent_task.exception()
    if exc:
        raise exc

    response = agent_task.result()
    session.current_plan = response.plan.to_dict() if response.plan else None
    if response.new_cwd:
        session.current_cwd = response.new_cwd

    await websocket.send_json({
        "type": "plan_step_complete",
        "plan": session.current_plan,
        "status": response.status,
        "content": response.content,
    })
    SessionManager.save(session)


async def handle_plan_action(
    websocket: WebSocket,
    session: Session,
    data: Dict[str, Any],
) -> None:
    """Maneja acciones sobre planes."""
    action = data.get("action")

    if not session.current_plan:
        await websocket.send_json({
            "type": "error",
            "message": "No hay plan activo",
        })
        return

    plan = Plan.from_dict(session.current_plan)

    if action == "approve":
        # Marcar como aprobado y ejecutar automáticamente todos los pasos
        plan.status = PlanStatus.APPROVED
        session.current_plan = plan.to_dict()

        await websocket.send_json({
            "type": "plan_approved",
            "plan": plan.to_dict(),
        })

        try:
            await _run_plan_auto(websocket, session, plan)
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Error ejecutando el plan: {e}",
            })

    elif action == "reject":
        plan.status = PlanStatus.CANCELLED
        session.current_plan = None

        await websocket.send_json({
            "type": "plan_rejected",
        })

    elif action == "execute":
        # Compatibilidad: si el cliente envía 'execute' explícitamente,
        # ejecutar igual que en approve (auto_execute=True).
        if plan.status != PlanStatus.APPROVED:
            await websocket.send_json({
                "type": "error",
                "message": "El plan debe ser aprobado primero",
            })
            return

        try:
            await _run_plan_auto(websocket, session, plan)
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": f"Error ejecutando el plan: {e}",
            })


async def handle_cancel(
    websocket: WebSocket,
    session: Session,
    data: Dict[str, Any],
) -> None:
    """Cancela la ejecución del agente en curso."""
    SessionManager.request_cancel(session.id)
    await websocket.send_json({
        "type": "cancelled",
        "message": "Cancelación solicitada. El agente se detendrá en el próximo paso.",
    })


async def handle_stream_chat(
    websocket: WebSocket,
    session: Session,
    data: Dict[str, Any],
) -> None:
    """Maneja chat con streaming de respuesta."""
    content = data.get("content", "").strip()
    if not content:
        await websocket.send_json({"type": "error", "message": "Empty message"})
        return
    
    # Agregar mensaje del usuario
    session.add_message("user", content)
    
    # Crear cliente
    from llm.base import LLMClientError as _LLMErr
    try:
        client = create_client(provider=session.llm_provider, base_url=session.llm_base_url or None)
    except _LLMErr as _e:
        await websocket.send_json({"type": "error", "message": str(_e)})
        return

    # Preparar mensajes
    messages = [{"role": "user", "content": content}]
    for msg in session.conversation.messages[:-1]:  # Excluir el último que acabamos de agregar
        messages.insert(0, msg.to_ollama_format())
    
    try:
        await websocket.send_json({"type": "stream_start"})
        
        full_response = []
        for chunk in client.chat_stream(
            model=session.model,
            messages=messages,
            options={"temperature": session.temperature},
        ):
            full_response.append(chunk)
            await websocket.send_json({
                "type": "stream_chunk",
                "content": chunk,
            })
            await asyncio.sleep(0)  # Yield control
        
        response_text = "".join(full_response)
        session.add_message("assistant", response_text)
        
        await websocket.send_json({
            "type": "stream_end",
            "content": response_text,
        })
        
    except OllamaClientError as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })


# =============================================================================
# File Watcher (watchfiles-based, one task per WS session)
# =============================================================================

_WATCH_IGNORE = frozenset({
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    '.mypy_cache', '.pytest_cache', 'dist', 'build', '.next',
})

async def _git_status_data(watch_path: str) -> dict:
    """Run git status --porcelain and return badge map (reuses api._git logic inline)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain", "-u",
            cwd=watch_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except Exception:
        return {"files": {}, "is_git": False}

    if proc.returncode == 128:
        return {"files": {}, "is_git": False}

    files: dict[str, str] = {}
    for line in stdout.decode(errors="replace").splitlines():
        if len(line) < 4:
            continue
        xy, rel = line[:2], line[3:]
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip().strip('"')
        badge = xy[0] if xy[0] != " " else xy[1]
        files[rel] = "U" if badge == "?" else badge
    return {"files": files, "is_git": True}


async def _file_watcher_task(websocket: WebSocket, watch_path: str, stop_event: asyncio.Event) -> None:
    """Watch *watch_path* and push file_changed + git_status_changed events over *websocket*."""
    try:
        from watchfiles import awatch, Change
    except ImportError:
        logger.warning("watchfiles not installed — file watcher disabled")
        return

    root = Path(watch_path)
    logger.info(f"👁  Starting file watcher on: {root}")

    def _ignore(raw_path: str) -> bool:
        p = Path(raw_path)
        return any(part in _WATCH_IGNORE for part in p.parts)

    git_debounce_task: asyncio.Task | None = None

    async def _push_git_status_debounced() -> None:
        """Wait 600 ms then push git_status_changed (debounces rapid file saves)."""
        await asyncio.sleep(0.6)
        data = await _git_status_data(str(root))
        try:
            await websocket.send_json({"type": "git_status_changed", **data})
        except Exception:
            pass

    try:
        async for changes in awatch(str(root), stop_event=stop_event):
            batch: list[dict] = []
            for change, raw_path in changes:
                if _ignore(raw_path):
                    continue
                try:
                    rel = str(Path(raw_path).relative_to(root))
                except ValueError:
                    rel = raw_path
                batch.append({
                    "change": change.name.lower(),   # created | modified | deleted
                    "path": raw_path,
                    "rel_path": rel,
                })
            if batch:
                try:
                    await websocket.send_json({"type": "file_changed", "changes": batch})
                except Exception:
                    break  # socket closed
                # Debounce git status push: cancel previous, schedule new
                if git_debounce_task and not git_debounce_task.done():
                    git_debounce_task.cancel()
                git_debounce_task = asyncio.create_task(_push_git_status_debounced())
    except Exception as e:
        logger.debug(f"File watcher stopped: {e}")
    finally:
        if git_debounce_task and not git_debounce_task.done():
            git_debounce_task.cancel()

    logger.info(f"👁  File watcher stopped for: {root}")


async def websocket_handler(websocket: WebSocket, session_id: str):
    """Handler principal de WebSocket."""
    logger.info(f"🔌 New WebSocket connection request: {session_id}")

    session = SessionManager.get_or_create(session_id)
    logger.info(f"✅ Session created/retrieved: {session_id}")

    await manager.connect(websocket, session_id)
    logger.info(f"✅ WebSocket accepted: {session_id}")

    await websocket.send_json({
        "type": "connected",
        "session": session.to_dict(),
        "messages": session.get_messages_for_display(),
    })
    logger.info(f"📤 Sent initial state to: {session_id}")

    # File watcher state
    watcher_task: asyncio.Task | None = None
    watcher_stop = asyncio.Event()
    current_watch_path: str | None = None

    def _restart_watcher(path: str | None) -> None:
        nonlocal watcher_task, watcher_stop, current_watch_path
        if watcher_task and not watcher_task.done():
            watcher_stop.set()
            watcher_task.cancel()
        watcher_task = None
        watcher_stop = asyncio.Event()
        current_watch_path = path
        if path and Path(path).is_dir():
            watcher_task = asyncio.create_task(
                _file_watcher_task(websocket, path, watcher_stop)
            )

    # Start watcher immediately if session already has a workspace
    if session.workspace_root:
        _restart_watcher(session.workspace_root)

    try:
        while True:
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = data.get("type", "")

            if msg_type == "chat":
                await handle_chat_message(websocket, session, data)
            elif msg_type == "stream_chat":
                await handle_stream_chat(websocket, session, data)
            elif msg_type == "approval":
                await handle_approval(websocket, session, data)
            elif msg_type == "plan":
                await handle_plan_action(websocket, session, data)
            elif msg_type == "cancel":
                await handle_cancel(websocket, session, data)
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "watch":
                # Client sends {"type":"watch","path":"..."} to (re)start the watcher
                new_path = data.get("path") or session.workspace_root
                if new_path != current_watch_path:
                    _restart_watcher(new_path)
                await websocket.send_json({"type": "watch_ack", "path": new_path})
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info(f"🔴 WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"❌ WebSocket error for {session_id}: {e}")
    finally:
        watcher_stop.set()
        if watcher_task and not watcher_task.done():
            watcher_task.cancel()
        manager.disconnect(session_id)
