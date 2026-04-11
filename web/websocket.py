"""WebSocket handlers para chat en tiempo real."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

# Setup logger
logger = logging.getLogger("websocket")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('[%(asctime)s] [WS] %(message)s', '%H:%M:%S'))
    logger.addHandler(handler)

from config import (
    MAX_ATTACHMENT_CHARS_PER_FILE,
    MAX_ATTACHMENT_CHARS_TOTAL,
    MAX_INPUT_CHARS,
    OLLAMA_BASE_URL,
    OperationMode,
)
from core.agent import Agent, AgentResponse
from core.models import Conversation, Plan, PlanStatus, ToolCall
from core.planner import PlanManager
from llm.client import OllamaClient, OllamaClientError
from web.state import Session, SessionManager
from pathlib import Path as _Path  # re-export para evitar shadowing


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

    # --- Inyectar adjuntos en el contenido del mensaje ---
    content = await _build_full_content(raw_content, attachments_raw)

    # Crear cliente y agente
    client = OllamaClient(base_url=OLLAMA_BASE_URL)
    agent = Agent(
        client=client,
        model=session.model,
        workspace_root=Path(session.workspace_root),
        current_cwd=Path(session.current_cwd),
        temperature=session.temperature,
        mode=session.mode,
    )
    agent.approval_manager.set_level(session.approval_level)
    # Restaurar el sumario de contexto de sesiones anteriores
    agent._context_summary = session.context_summary

    # Notificar inicio
    await websocket.send_json({"type": "start", "mode": session.mode})

    try:
        if session.mode == OperationMode.CHAT:
            response = await asyncio.to_thread(
                agent.chat,
                content,
                session.conversation,
                [],  # attachments ya inyectados en content
                images,
            )

        elif session.mode == OperationMode.AGENT:
            # --- Streaming de pasos del agente ---
            step_queue: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def step_callback(msg: str) -> None:
                loop.call_soon_threadsafe(step_queue.put_nowait, msg)

            agent_task = asyncio.create_task(
                asyncio.to_thread(
                    lambda: agent.run(
                        content,
                        session.conversation,
                        [],  # attachments ya inyectados
                        images,
                        step_callback,
                    )
                )
            )

            # Emitir pasos mientras el agente trabaja
            while not agent_task.done():
                try:
                    step_msg = step_queue.get_nowait()
                    await websocket.send_json({
                        "type": "agent_step",
                        "message": step_msg,
                    })
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.1)

            # Vaciar cola restante
            while not step_queue.empty():
                step_msg = step_queue.get_nowait()
                await websocket.send_json({
                    "type": "agent_step",
                    "message": step_msg,
                })

            # Propagar excepción si la tarea falló
            exc = agent_task.exception()
            if exc:
                raise exc
            response = agent_task.result()

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
            return
        else:
            response = AgentResponse(
                content="Modo no soportado",
                status="error",
            )

        # --- Persistir sumario de contexto actualizado ---
        if agent._context_summary:
            session.context_summary = agent._context_summary

        # Enviar respuesta
        await websocket.send_json({
            "type": "response",
            "content": response.content,
            "status": response.status,
            "trace": response.trace,
            "tool_results": [tr.to_dict() for tr in response.tool_results],
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

        # Guardar trace
        session.agent_trace = response.trace

    except OllamaClientError as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": f"Error interno: {str(e)}",
        })
    finally:
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
    
    # Crear agente y continuar
    client = OllamaClient(base_url=OLLAMA_BASE_URL)
    agent = Agent(
        client=client,
        model=session.model,
        workspace_root=Path(session.workspace_root),
        current_cwd=Path(session.current_cwd),
        temperature=session.temperature,
        mode=session.mode,
    )
    
    agent.approval_manager.set_level(session.approval_level)
    
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
    
    try:
        response = await asyncio.to_thread(
            agent.resume_after_approval,
            session.conversation,
            approved,
        )

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
        plan.status = PlanStatus.APPROVED
        session.current_plan = plan.to_dict()
        
        await websocket.send_json({
            "type": "plan_approved",
            "plan": plan.to_dict(),
        })
        
    elif action == "reject":
        plan.status = PlanStatus.CANCELLED
        session.current_plan = None
        
        await websocket.send_json({
            "type": "plan_rejected",
        })
        
    elif action == "execute":
        if plan.status != PlanStatus.APPROVED:
            await websocket.send_json({
                "type": "error",
                "message": "El plan debe ser aprobado primero",
            })
            return
        
        # Ejecutar plan paso a paso
        client = OllamaClient(base_url=OLLAMA_BASE_URL)
        agent = Agent(
            client=client,
            model=session.model,
            workspace_root=Path(session.workspace_root),
            current_cwd=Path(session.current_cwd),
            temperature=session.temperature,
            mode=OperationMode.PLAN,
        )
        agent.approval_manager.set_level(session.approval_level)
        
        try:
            response = await asyncio.to_thread(
                agent.execute_plan_step,
                plan,
                session.conversation,
            )
            
            session.current_plan = response.plan.to_dict() if response.plan else None
            
            await websocket.send_json({
                "type": "plan_step_complete",
                "plan": session.current_plan,
                "status": response.status,
                "content": response.content,
            })

            if response.status == "awaiting_approval":
                session.pending_approval = {
                    "tool_call": "plan_step",
                    "description": response.content,
                }
                await websocket.send_json({
                    "type": "approval_required",
                    "pending": session.pending_approval,
                })
            
        except Exception as e:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
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
    client = OllamaClient(base_url=OLLAMA_BASE_URL)
    
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


async def websocket_handler(websocket: WebSocket, session_id: str):
    """Handler principal de WebSocket."""
    logger.info(f"🔌 New WebSocket connection request: {session_id}")
    
    # Obtener o crear sesión
    session = SessionManager.get_or_create(session_id)
    logger.info(f"✅ Session created/retrieved: {session_id}")
    
    await manager.connect(websocket, session_id)
    logger.info(f"✅ WebSocket accepted: {session_id}")
    
    # Enviar estado inicial
    await websocket.send_json({
        "type": "connected",
        "session": session.to_dict(),
        "messages": session.get_messages_for_display(),
    })
    logger.info(f"📤 Sent initial state to: {session_id}")
    
    try:
        while True:
            raw_data = await websocket.receive_text()
            
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })
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
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })
    
    except WebSocketDisconnect:
        logger.info(f"🔴 WebSocket disconnected: {session_id}")
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error for {session_id}: {e}")
        manager.disconnect(session_id)
