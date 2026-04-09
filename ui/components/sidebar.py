"""Componente de sidebar con configuración."""

from __future__ import annotations

from typing import Optional, Tuple

import streamlit as st

from config import ApprovalLevel, OLLAMA_BASE_URL, OLLAMA_DEFAULT_MODEL, OperationMode
from llm.client import OllamaClient, OllamaClientError
from ui.state import AppState


def render_sidebar() -> Tuple[OllamaClient, str, float]:
    """
    Renderiza el sidebar con configuración.
    
    Returns:
        Tupla (cliente, modelo, temperatura)
    """
    with st.sidebar:
        st.header("⚙️ Configuración")
        
        # URL de Ollama
        base_url = st.text_input(
            "Ollama URL",
            value=AppState.get_base_url(),
            help="URL del servidor Ollama",
        )
        AppState.set_base_url(base_url)
        
        # Crear cliente
        client = OllamaClient(base_url=base_url)
        
        # Botón recargar modelos
        if st.button("🔄 Recargar modelos"):
            try:
                models = client.list_models()
                AppState.set_models(models)
                st.success(f"✅ {len(models)} modelos encontrados")
            except OllamaClientError as e:
                st.error(f"❌ {e}")
        
        # Cargar modelos si no hay
        if not AppState.get_models():
            try:
                models = client.list_models()
                AppState.set_models(models)
            except OllamaClientError:
                pass
        
        # Selector de modelo
        models = AppState.get_models()
        if models:
            default_idx = 0
            if OLLAMA_DEFAULT_MODEL and OLLAMA_DEFAULT_MODEL in models:
                default_idx = models.index(OLLAMA_DEFAULT_MODEL)
            
            model = st.selectbox(
                "Modelo",
                models,
                index=default_idx,
                help="Modelo de Ollama a usar",
            )
            AppState.set_selected_model(model)
        else:
            st.warning("⚠️ No se detectaron modelos")
            model = st.text_input(
                "Modelo manual",
                value=OLLAMA_DEFAULT_MODEL or "llama3:latest",
            )
            AppState.set_selected_model(model)
        
        # Obtener capacidades
        model = AppState.get_selected_model()
        if model:
            caps = AppState.get_model_capabilities(model)
            if not caps:
                try:
                    caps = client.get_model_capabilities(model)
                    AppState.set_model_capabilities(model, caps)
                except OllamaClientError:
                    caps = set()
            
            if caps:
                st.caption(f"Capacidades: {', '.join(sorted(caps))}")
        
        # Temperatura
        temperature = st.slider(
            "Temperatura",
            min_value=0.0,
            max_value=1.5,
            value=AppState.get_temperature(),
            step=0.1,
            help="Controla la creatividad del modelo",
        )
        AppState.set_temperature(temperature)
        
        st.divider()
        
        # Modo de operación
        st.subheader("🎯 Modo de Operación")
        
        mode_options = {
            OperationMode.CHAT: "💬 Chat - Conversación simple",
            OperationMode.AGENT: "🤖 Agent - Herramientas automáticas",
            OperationMode.PLAN: "📋 Plan - Planifica antes de actuar",
        }
        
        current_mode = AppState.get_mode()
        mode = st.radio(
            "Selecciona el modo",
            options=list(mode_options.keys()),
            format_func=lambda x: mode_options[x],
            index=list(mode_options.keys()).index(current_mode),
            label_visibility="collapsed",
        )
        AppState.set_mode(mode)
        
        # Nivel de aprobación (solo si no es modo chat)
        if mode != OperationMode.CHAT:
            st.caption("Aprobación de acciones:")
            approval_options = {
                ApprovalLevel.NONE: "🟢 Ninguna",
                ApprovalLevel.WRITE_ONLY: "🟡 Solo escritura",
                ApprovalLevel.ALL: "🔴 Todas",
            }
            
            current_approval = AppState.get_approval_level()
            approval = st.radio(
                "Nivel de aprobación",
                options=list(approval_options.keys()),
                format_func=lambda x: approval_options[x],
                index=list(approval_options.keys()).index(current_approval),
                label_visibility="collapsed",
                horizontal=True,
            )
            AppState.set_approval_level(approval)
        
        st.divider()
        
        # Workspace
        st.subheader("📁 Workspace")
        workspace = st.text_input(
            "Workspace root",
            value=AppState.get_workspace_root(),
            help="Directorio raíz para operaciones",
        )
        AppState.set_workspace_root(workspace)
        
        cwd = AppState.get_current_cwd()
        st.caption(f"CWD: `{cwd}`")
        
        st.divider()
        
        # Acciones
        if st.button("🗑️ Limpiar chat", use_container_width=True):
            AppState.reset_conversation()
            st.rerun()
        
        # Info de RAG
        rag_sources = AppState.get_rag_sources()
        if rag_sources:
            with st.expander("📚 Fuentes RAG"):
                for source in rag_sources:
                    st.caption(f"- {source}")
        
        # Trace del agente
        trace = AppState.get_agent_trace()
        if trace:
            with st.expander("🔍 Traza del agente"):
                for line in trace:
                    st.caption(line)
    
    return client, model, temperature
