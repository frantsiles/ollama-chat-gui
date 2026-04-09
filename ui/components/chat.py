"""Componentes de chat: mensajes e input."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from ui.state import AppState


def render_chat_messages() -> None:
    """Renderiza los mensajes del chat."""
    messages = AppState.get_messages()
    
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        # Solo mostrar user y assistant
        if role not in {"user", "assistant"}:
            continue
        
        # Saltar respuestas vacías
        if role == "assistant" and not content.strip():
            continue
        
        with st.chat_message(role):
            st.markdown(content)
            
            # Mostrar adjuntos
            attachments = msg.get("attachments", [])
            if attachments:
                st.caption(f"📎 Adjuntos: {', '.join(attachments)}")


def render_chat_input(
    placeholder: str = "Escribe tu mensaje...",
    disabled: bool = False,
) -> Optional[str]:
    """
    Renderiza el input de chat.
    
    Args:
        placeholder: Texto placeholder
        disabled: Si está deshabilitado
        
    Returns:
        Mensaje del usuario o None
    """
    return st.chat_input(placeholder, disabled=disabled)


def render_file_uploader(
    supports_vision: bool = False,
) -> List[Any]:
    """
    Renderiza el uploader de archivos.
    
    Args:
        supports_vision: Si el modelo soporta imágenes
        
    Returns:
        Lista de archivos subidos
    """
    # Tipos permitidos
    allowed_types = [
        "txt", "md", "json", "csv", "xml", "yaml", "yml",
        "py", "log", "toml", "ini", "cfg",
        "js", "ts", "jsx", "tsx", "html", "css",
        "sh", "bash",
        "go", "rs", "java", "c", "cpp", "h",
    ]
    
    if supports_vision:
        allowed_types.extend(["png", "jpg", "jpeg", "webp", "gif"])
    
    uploader_key = f"uploader_{AppState.get_uploader_key()}"
    
    with st.expander("📎 Adjuntar archivos", expanded=False):
        files = st.file_uploader(
            "Selecciona archivos",
            type=allowed_types,
            accept_multiple_files=True,
            key=uploader_key,
            help="Archivos de texto se inyectan como contexto. Imágenes requieren modelo con vision.",
        )
        
        if files:
            st.caption(f"{len(files)} archivo(s) seleccionado(s)")
            
            # Preview de imágenes
            image_files = [f for f in files if f.type and f.type.startswith("image/")]
            if image_files:
                cols = st.columns(min(len(image_files), 3))
                for i, img in enumerate(image_files[:3]):
                    with cols[i]:
                        st.image(img, caption=img.name, width=100)
        
        return files or []


def render_workspace_info() -> None:
    """Renderiza información del workspace."""
    workspace = AppState.get_workspace_root()
    cwd = AppState.get_current_cwd()
    
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"📁 Workspace: `{workspace}`")
    with col2:
        st.caption(f"📂 CWD: `{cwd}`")
