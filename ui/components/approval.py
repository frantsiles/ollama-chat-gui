"""Diálogo de aprobación de acciones."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import streamlit as st

from core.models import ToolCall


def render_approval_dialog(
    tool_call: ToolCall,
    on_approve: Optional[Callable[[], None]] = None,
    on_reject: Optional[Callable[[], None]] = None,
    on_approve_always: Optional[Callable[[], None]] = None,
) -> Optional[str]:
    """
    Renderiza el diálogo de aprobación para una acción.
    
    Args:
        tool_call: Llamada a aprobar
        on_approve: Callback para aprobar
        on_reject: Callback para rechazar
        on_approve_always: Callback para aprobar siempre
        
    Returns:
        "approved", "rejected", "always" o None si no se tomó acción
    """
    st.warning("⚠️ Se requiere aprobación para continuar")
    
    # Mostrar detalles de la acción
    with st.container():
        st.markdown("### Acción solicitada")
        st.code(str(tool_call), language="text")
        
        if tool_call.reasoning:
            st.markdown(f"**Razón:** {tool_call.reasoning}")
        
        # Detalles de la herramienta
        st.markdown(f"**Herramienta:** `{tool_call.tool}`")
        
        if tool_call.args:
            with st.expander("Ver argumentos"):
                import json
                st.json(tool_call.args)
    
    st.divider()
    
    # Botones de acción
    col1, col2, col3 = st.columns(3)
    
    result = None
    
    with col1:
        if st.button("✅ Aprobar", type="primary", use_container_width=True, key="approve_btn"):
            if on_approve:
                on_approve()
            result = "approved"
    
    with col2:
        if st.button("❌ Rechazar", use_container_width=True, key="reject_btn"):
            if on_reject:
                on_reject()
            result = "rejected"
    
    with col3:
        if st.button("✅✅ Aprobar siempre", use_container_width=True, key="approve_always_btn"):
            if on_approve_always:
                on_approve_always()
            result = "always"
    
    return result


def render_approval_from_dict(
    approval_data: Dict[str, Any],
    on_approve: Optional[Callable[[], None]] = None,
    on_reject: Optional[Callable[[], None]] = None,
    on_approve_always: Optional[Callable[[], None]] = None,
) -> Optional[str]:
    """
    Renderiza el diálogo de aprobación desde un diccionario.
    
    Args:
        approval_data: Datos de la aprobación
        on_approve: Callback para aprobar
        on_reject: Callback para rechazar
        on_approve_always: Callback para aprobar siempre
        
    Returns:
        "approved", "rejected", "always" o None
    """
    tool_call = ToolCall.from_dict(approval_data)
    return render_approval_dialog(
        tool_call=tool_call,
        on_approve=on_approve,
        on_reject=on_reject,
        on_approve_always=on_approve_always,
    )


def render_simple_approval(
    description: str,
    on_approve: Optional[Callable[[], None]] = None,
    on_reject: Optional[Callable[[], None]] = None,
) -> Optional[bool]:
    """
    Renderiza un diálogo de aprobación simple.
    
    Args:
        description: Descripción de la acción
        on_approve: Callback para aprobar
        on_reject: Callback para rechazar
        
    Returns:
        True si se aprobó, False si se rechazó, None si no se tomó acción
    """
    st.warning("⚠️ Se requiere confirmación")
    st.markdown(description)
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("✅ Confirmar", type="primary", use_container_width=True):
            if on_approve:
                on_approve()
            return True
    
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            if on_reject:
                on_reject()
            return False
    
    return None
