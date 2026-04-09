"""Aplicación principal de UI que orquesta todos los componentes."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from config import (
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    MAX_TEXT_CHARS_PER_FILE,
    OperationMode,
    TEXT_FILE_EXTENSIONS,
)
from core.agent import Agent, AgentResponse
from core.models import Conversation, Plan, ToolCall
from core.planner import PlanManager
from llm.client import OllamaClient, OllamaClientError
from rag.local_rag import LocalRAG
from ui.components.approval import render_approval_dialog
from ui.components.chat import (
    render_chat_input,
    render_chat_messages,
    render_file_uploader,
    render_workspace_info,
)
from ui.components.mode_selector import render_mode_indicator
from ui.components.plan_view import render_plan_view
from ui.components.sidebar import render_sidebar
from ui.state import AppState


def process_attachments(
    files: List[Any],
    supports_vision: bool,
) -> Tuple[str, List[str], List[str]]:
    """
    Procesa archivos adjuntos.
    
    Args:
        files: Lista de archivos subidos
        supports_vision: Si el modelo soporta vision
        
    Returns:
        Tupla (contexto_texto, imágenes_base64, labels)
    """
    text_blocks: List[str] = []
    images: List[str] = []
    labels: List[str] = []
    
    for f in files:
        name = f.name
        mime = f.type or ""
        raw = f.getvalue()
        size = len(raw)
        
        # Verificar tamaño
        if size > MAX_FILE_SIZE_BYTES:
            continue
        
        # Imágenes
        if mime.startswith("image/"):
            if supports_vision:
                images.append(base64.b64encode(raw).decode("utf-8"))
                labels.append(f"🖼️ {name}")
            continue
        
        # Texto
        lower_name = name.lower()
        if mime.startswith("text/") or any(lower_name.endswith(ext) for ext in TEXT_FILE_EXTENSIONS):
            text = None
            for encoding in ("utf-8", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if text:
                if len(text) > MAX_TEXT_CHARS_PER_FILE:
                    text = text[:MAX_TEXT_CHARS_PER_FILE] + "\n...[recortado]..."
                
                text_blocks.append(f"[Archivo: {name}]\n{text}")
                labels.append(f"📄 {name}")
    
    context = ""
    if text_blocks:
        context = "\n\n---\n\n".join(text_blocks)
    
    return context, images, labels


def handle_chat_mode(
    client: OllamaClient,
    model: str,
    temperature: float,
    user_input: str,
    attachments_context: str,
    images: List[str],
    attachment_labels: List[str],
) -> None:
    """Maneja el modo Chat."""
    # Agregar mensaje del usuario
    content = user_input
    if attachments_context:
        content = f"{user_input}\n\n---\nArchivos adjuntos:\n{attachments_context}"
    
    AppState.add_message("user", content, attachments=attachment_labels)
    
    # Mostrar mensaje del usuario
    with st.chat_message("user"):
        st.markdown(user_input)
        if attachment_labels:
            st.caption(f"📎 {', '.join(attachment_labels)}")
    
    # Generar respuesta
    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("🤔 Pensando...")
        
        messages = [{"role": m["role"], "content": m["content"]} for m in AppState.get_messages()]
        
        try:
            response_chunks = []
            for chunk in client.chat_stream(
                model=model,
                messages=messages,
                options={"temperature": temperature},
            ):
                response_chunks.append(chunk)
                placeholder.markdown("".join(response_chunks) + "▌")
            
            response = "".join(response_chunks)
            placeholder.markdown(response)
            AppState.add_message("assistant", response)
            
        except OllamaClientError as e:
            placeholder.error(f"❌ Error: {e}")


def handle_agent_mode(
    client: OllamaClient,
    model: str,
    temperature: float,
    user_input: str,
    attachments_context: str,
    images: List[str],
    attachment_labels: List[str],
) -> None:
    """Maneja el modo Agent."""
    workspace_root = Path(AppState.get_workspace_root())
    current_cwd = Path(AppState.get_current_cwd())
    
    # Crear agente
    agent = Agent(
        client=client,
        model=model,
        workspace_root=workspace_root,
        current_cwd=current_cwd,
        temperature=temperature,
        mode=OperationMode.AGENT,
    )
    
    # Configurar nivel de aprobación
    agent.approval_manager.set_level(AppState.get_approval_level())
    
    # Crear conversación desde mensajes existentes
    conversation = Conversation(
        workspace_root=str(workspace_root),
        current_cwd=str(current_cwd),
    )
    
    # Copiar mensajes existentes
    for msg in AppState.get_messages():
        from core.models import Message, MessageRole
        role = MessageRole(msg["role"]) if msg["role"] in ["user", "assistant", "system"] else MessageRole.USER
        conversation.messages.append(Message(role=role, content=msg["content"]))
    
    # RAG si aplica
    rag = LocalRAG(workspace_root)
    if rag.should_activate(user_input):
        rag_context, sources = rag.retrieve(user_input)
        if rag_context:
            conversation.add_system_message(rag_context)
            AppState.set_rag_sources(sources)
    else:
        AppState.set_rag_sources([])
    
    # Preparar input
    full_input = user_input
    if attachments_context:
        full_input = f"{user_input}\n\n---\nArchivos adjuntos:\n{attachments_context}"
    
    # Agregar mensaje del usuario a UI
    AppState.add_message("user", user_input, attachments=attachment_labels)
    with st.chat_message("user"):
        st.markdown(user_input)
        if attachment_labels:
            st.caption(f"📎 {', '.join(attachment_labels)}")
    
    # Ejecutar agente
    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("🤖 Ejecutando agente...")
        
        try:
            response = agent.run(
                user_input=full_input,
                conversation=conversation,
                images=images,
            )
            
            AppState.set_agent_trace(response.trace)
            
            if response.new_cwd:
                AppState.set_current_cwd(response.new_cwd)
            
            if response.status == "awaiting_approval":
                # Guardar aprobación pendiente
                if agent.state.pending_approval:
                    AppState.set_pending_approval(agent.state.pending_approval.to_dict())
                placeholder.warning(response.content)
                AppState.add_message("assistant", response.content)
                st.rerun()
            
            elif response.status == "error":
                placeholder.error(f"❌ Error: {response.error}")
                AppState.add_message("assistant", f"Error: {response.error}")
            
            else:
                placeholder.markdown(response.content)
                AppState.add_message("assistant", response.content)
                
        except Exception as e:
            placeholder.error(f"❌ Error inesperado: {e}")


def handle_plan_mode(
    client: OllamaClient,
    model: str,
    temperature: float,
    user_input: str,
) -> None:
    """Maneja el modo Plan."""
    workspace_root = Path(AppState.get_workspace_root())
    
    # Agregar mensaje del usuario
    AppState.add_message("user", user_input)
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Crear plan manager
    plan_manager = PlanManager(
        client=client,
        model=model,
        temperature=temperature,
    )
    
    # Crear conversación
    conversation = Conversation(workspace_root=str(workspace_root))
    for msg in AppState.get_messages():
        from core.models import Message, MessageRole
        role = MessageRole(msg["role"]) if msg["role"] in ["user", "assistant", "system"] else MessageRole.USER
        conversation.messages.append(Message(role=role, content=msg["content"]))
    
    # Generar plan
    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("📋 Generando plan...")
        
        try:
            plan = plan_manager.create_plan(
                user_request=user_input,
                conversation=conversation,
            )
            
            if plan:
                AppState.set_current_plan(plan.to_dict())
                placeholder.markdown(f"Se ha creado un plan: **{plan.title}**\n\nRevisa el panel inferior para aprobarlo.")
                AppState.add_message("assistant", f"Plan creado: {plan.title}")
            else:
                placeholder.info("No se generó un plan. Respondiendo directamente...")
                # Fallback a chat simple
                messages = [{"role": m["role"], "content": m["content"]} for m in AppState.get_messages()]
                response = client.chat(model=model, messages=messages, options={"temperature": temperature})
                placeholder.markdown(response)
                AppState.add_message("assistant", response)
                
        except Exception as e:
            placeholder.error(f"❌ Error: {e}")


def main() -> None:
    """Función principal de la aplicación."""
    st.set_page_config(
        page_title="Ollama Agent",
        page_icon="🤖",
        layout="wide",
    )
    
    # Inicializar estado
    AppState.init()
    
    # Título
    st.title("🤖 Ollama Agent")
    
    # Sidebar
    client, model, temperature = render_sidebar()
    
    # Indicador de modo
    render_mode_indicator()
    render_workspace_info()
    
    st.divider()
    
    # Mostrar plan si existe (modo Plan)
    plan_data = AppState.get_current_plan()
    if plan_data:
        plan = Plan.from_dict(plan_data)
        
        def on_approve():
            from core.models import PlanStatus
            plan.status = PlanStatus.APPROVED
            AppState.set_current_plan(plan.to_dict())
            st.rerun()
        
        def on_cancel():
            AppState.clear_current_plan()
            st.rerun()
        
        def on_execute():
            # Ejecutar plan (simplificado)
            st.info("Ejecutando plan...")
            # TODO: Implementar ejecución completa
        
        render_plan_view(
            plan=plan,
            on_approve=on_approve,
            on_cancel=on_cancel,
            on_execute=on_execute,
        )
        st.divider()
    
    # Mostrar aprobación pendiente si existe
    pending = AppState.get_pending_approval()
    if pending:
        tool_call = ToolCall.from_dict(pending)
        
        def on_approve():
            AppState.clear_pending_approval()
            AppState.add_message("system", f"Acción aprobada: {tool_call}")
            st.rerun()
        
        def on_reject():
            AppState.clear_pending_approval()
            AppState.add_message("assistant", "Acción rechazada por el usuario.")
            st.rerun()
        
        def on_always():
            AppState.clear_pending_approval()
            AppState.add_message("system", f"Acción aprobada permanentemente: {tool_call.tool}")
            st.rerun()
        
        render_approval_dialog(
            tool_call=tool_call,
            on_approve=on_approve,
            on_reject=on_reject,
            on_approve_always=on_always,
        )
        st.divider()
    
    # Mensajes del chat
    render_chat_messages()
    
    # Uploader de archivos
    model_caps = AppState.get_model_capabilities(model)
    supports_vision = "vision" in model_caps
    uploaded_files = render_file_uploader(supports_vision=supports_vision)
    
    # Input del chat
    mode = AppState.get_mode()
    has_pending = pending is not None
    
    user_input = render_chat_input(
        placeholder=f"Escribe tu mensaje ({mode})...",
        disabled=has_pending,
    )
    
    if user_input:
        # Procesar adjuntos
        attachments_context, images, labels = process_attachments(
            uploaded_files,
            supports_vision,
        )
        
        # Manejar según modo
        if mode == OperationMode.CHAT:
            handle_chat_mode(
                client, model, temperature,
                user_input, attachments_context, images, labels,
            )
        
        elif mode == OperationMode.AGENT:
            handle_agent_mode(
                client, model, temperature,
                user_input, attachments_context, images, labels,
            )
        
        elif mode == OperationMode.PLAN:
            handle_plan_mode(
                client, model, temperature,
                user_input,
            )
        
        # Reset uploader
        AppState.increment_uploader_key()
        st.rerun()


if __name__ == "__main__":
    main()
