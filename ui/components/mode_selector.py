"""Selector de modo de operación."""

from __future__ import annotations

import streamlit as st

from config import OperationMode
from ui.state import AppState


def render_mode_selector() -> str:
    """
    Renderiza el selector de modo en la parte superior.
    
    Returns:
        Modo seleccionado
    """
    mode = AppState.get_mode()
    
    # Tabs para el modo
    tabs = st.tabs(["💬 Chat", "🤖 Agent", "📋 Plan"])
    
    with tabs[0]:
        if mode != OperationMode.CHAT:
            if st.button("Cambiar a Chat", key="mode_chat"):
                AppState.set_mode(OperationMode.CHAT)
                st.rerun()
        else:
            st.info("Modo Chat: Conversación directa sin herramientas")
    
    with tabs[1]:
        if mode != OperationMode.AGENT:
            if st.button("Cambiar a Agent", key="mode_agent"):
                AppState.set_mode(OperationMode.AGENT)
                st.rerun()
        else:
            st.info("Modo Agent: Ciclo ReAct automático con herramientas")
    
    with tabs[2]:
        if mode != OperationMode.PLAN:
            if st.button("Cambiar a Plan", key="mode_plan"):
                AppState.set_mode(OperationMode.PLAN)
                st.rerun()
        else:
            st.info("Modo Plan: Planifica, aprueba y ejecuta paso a paso")
    
    return mode


def render_mode_indicator() -> None:
    """Renderiza un indicador del modo actual."""
    mode = AppState.get_mode()
    
    mode_info = {
        OperationMode.CHAT: ("💬", "Chat", "Conversación simple"),
        OperationMode.AGENT: ("🤖", "Agent", "Herramientas automáticas"),
        OperationMode.PLAN: ("📋", "Plan", "Planificación primero"),
    }
    
    icon, name, desc = mode_info.get(mode, ("❓", "Unknown", ""))
    
    st.markdown(f"**{icon} Modo {name}** - {desc}")
