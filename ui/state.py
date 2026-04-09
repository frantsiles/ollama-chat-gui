"""Gestión centralizada del estado de la aplicación."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

from config import (
    ApprovalLevel,
    DEFAULT_WORKSPACE_ROOT,
    OLLAMA_BASE_URL,
    OLLAMA_DEFAULT_MODEL,
    OperationMode,
)
from core.models import Conversation, Plan


@dataclass
class AppState:
    """
    Estado centralizado de la aplicación.
    
    Wrapper sobre st.session_state que proporciona acceso tipado
    y valores por defecto.
    """
    
    # Keys para session_state
    MESSAGES_KEY = "messages"
    MODELS_KEY = "models"
    MODEL_CAPABILITIES_KEY = "model_capabilities"
    WORKSPACE_ROOT_KEY = "workspace_root"
    CURRENT_CWD_KEY = "current_cwd"
    MODE_KEY = "operation_mode"
    APPROVAL_LEVEL_KEY = "approval_level"
    UPLOADER_KEY = "uploader_key"
    PENDING_APPROVAL_KEY = "pending_approval"
    CURRENT_PLAN_KEY = "current_plan"
    AGENT_TRACE_KEY = "agent_trace"
    RAG_SOURCES_KEY = "rag_sources"
    BASE_URL_KEY = "base_url"
    MODEL_KEY = "selected_model"
    TEMPERATURE_KEY = "temperature"
    
    @classmethod
    def init(cls) -> None:
        """Inicializa el estado con valores por defecto."""
        defaults = {
            cls.MESSAGES_KEY: [],
            cls.MODELS_KEY: [],
            cls.MODEL_CAPABILITIES_KEY: {},
            cls.WORKSPACE_ROOT_KEY: DEFAULT_WORKSPACE_ROOT,
            cls.CURRENT_CWD_KEY: DEFAULT_WORKSPACE_ROOT,
            cls.MODE_KEY: OperationMode.AGENT,
            cls.APPROVAL_LEVEL_KEY: ApprovalLevel.WRITE_ONLY,
            cls.UPLOADER_KEY: 0,
            cls.PENDING_APPROVAL_KEY: None,
            cls.CURRENT_PLAN_KEY: None,
            cls.AGENT_TRACE_KEY: [],
            cls.RAG_SOURCES_KEY: [],
            cls.BASE_URL_KEY: OLLAMA_BASE_URL,
            cls.MODEL_KEY: OLLAMA_DEFAULT_MODEL,
            cls.TEMPERATURE_KEY: 0.7,
        }
        
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value
    
    # ==========================================================================
    # Mensajes
    # ==========================================================================
    
    @classmethod
    def get_messages(cls) -> List[Dict[str, Any]]:
        """Obtiene la lista de mensajes."""
        return st.session_state.get(cls.MESSAGES_KEY, [])
    
    @classmethod
    def add_message(cls, role: str, content: str, **kwargs) -> None:
        """Agrega un mensaje a la conversación."""
        msg = {"role": role, "content": content, **kwargs}
        st.session_state[cls.MESSAGES_KEY].append(msg)
    
    @classmethod
    def clear_messages(cls) -> None:
        """Limpia los mensajes."""
        st.session_state[cls.MESSAGES_KEY] = []
    
    # ==========================================================================
    # Modelos
    # ==========================================================================
    
    @classmethod
    def get_models(cls) -> List[str]:
        """Obtiene la lista de modelos."""
        return st.session_state.get(cls.MODELS_KEY, [])
    
    @classmethod
    def set_models(cls, models: List[str]) -> None:
        """Establece la lista de modelos."""
        st.session_state[cls.MODELS_KEY] = models
    
    @classmethod
    def get_model_capabilities(cls, model: str) -> set:
        """Obtiene las capacidades de un modelo."""
        caps = st.session_state.get(cls.MODEL_CAPABILITIES_KEY, {})
        return caps.get(model, set())
    
    @classmethod
    def set_model_capabilities(cls, model: str, capabilities: set) -> None:
        """Establece las capacidades de un modelo."""
        if cls.MODEL_CAPABILITIES_KEY not in st.session_state:
            st.session_state[cls.MODEL_CAPABILITIES_KEY] = {}
        st.session_state[cls.MODEL_CAPABILITIES_KEY][model] = capabilities
    
    @classmethod
    def get_selected_model(cls) -> str:
        """Obtiene el modelo seleccionado."""
        return st.session_state.get(cls.MODEL_KEY, "")
    
    @classmethod
    def set_selected_model(cls, model: str) -> None:
        """Establece el modelo seleccionado."""
        st.session_state[cls.MODEL_KEY] = model
    
    # ==========================================================================
    # Workspace
    # ==========================================================================
    
    @classmethod
    def get_workspace_root(cls) -> str:
        """Obtiene la raíz del workspace."""
        return st.session_state.get(cls.WORKSPACE_ROOT_KEY, DEFAULT_WORKSPACE_ROOT)
    
    @classmethod
    def set_workspace_root(cls, path: str) -> None:
        """Establece la raíz del workspace."""
        st.session_state[cls.WORKSPACE_ROOT_KEY] = path
    
    @classmethod
    def get_current_cwd(cls) -> str:
        """Obtiene el directorio de trabajo actual."""
        return st.session_state.get(cls.CURRENT_CWD_KEY, DEFAULT_WORKSPACE_ROOT)
    
    @classmethod
    def set_current_cwd(cls, path: str) -> None:
        """Establece el directorio de trabajo actual."""
        st.session_state[cls.CURRENT_CWD_KEY] = path
    
    # ==========================================================================
    # Modo de operación
    # ==========================================================================
    
    @classmethod
    def get_mode(cls) -> str:
        """Obtiene el modo de operación actual."""
        return st.session_state.get(cls.MODE_KEY, OperationMode.AGENT)
    
    @classmethod
    def set_mode(cls, mode: str) -> None:
        """Establece el modo de operación."""
        st.session_state[cls.MODE_KEY] = mode
    
    @classmethod
    def get_approval_level(cls) -> str:
        """Obtiene el nivel de aprobación."""
        return st.session_state.get(cls.APPROVAL_LEVEL_KEY, ApprovalLevel.WRITE_ONLY)
    
    @classmethod
    def set_approval_level(cls, level: str) -> None:
        """Establece el nivel de aprobación."""
        st.session_state[cls.APPROVAL_LEVEL_KEY] = level
    
    # ==========================================================================
    # Aprobaciones pendientes
    # ==========================================================================
    
    @classmethod
    def get_pending_approval(cls) -> Optional[Dict[str, Any]]:
        """Obtiene la aprobación pendiente."""
        return st.session_state.get(cls.PENDING_APPROVAL_KEY)
    
    @classmethod
    def set_pending_approval(cls, approval: Optional[Dict[str, Any]]) -> None:
        """Establece la aprobación pendiente."""
        st.session_state[cls.PENDING_APPROVAL_KEY] = approval
    
    @classmethod
    def clear_pending_approval(cls) -> None:
        """Limpia la aprobación pendiente."""
        st.session_state[cls.PENDING_APPROVAL_KEY] = None
    
    # ==========================================================================
    # Plan
    # ==========================================================================
    
    @classmethod
    def get_current_plan(cls) -> Optional[Dict[str, Any]]:
        """Obtiene el plan actual."""
        return st.session_state.get(cls.CURRENT_PLAN_KEY)
    
    @classmethod
    def set_current_plan(cls, plan: Optional[Dict[str, Any]]) -> None:
        """Establece el plan actual."""
        st.session_state[cls.CURRENT_PLAN_KEY] = plan
    
    @classmethod
    def clear_current_plan(cls) -> None:
        """Limpia el plan actual."""
        st.session_state[cls.CURRENT_PLAN_KEY] = None
    
    # ==========================================================================
    # Traza y fuentes
    # ==========================================================================
    
    @classmethod
    def get_agent_trace(cls) -> List[str]:
        """Obtiene la traza del agente."""
        return st.session_state.get(cls.AGENT_TRACE_KEY, [])
    
    @classmethod
    def set_agent_trace(cls, trace: List[str]) -> None:
        """Establece la traza del agente."""
        st.session_state[cls.AGENT_TRACE_KEY] = trace
    
    @classmethod
    def get_rag_sources(cls) -> List[str]:
        """Obtiene las fuentes RAG."""
        return st.session_state.get(cls.RAG_SOURCES_KEY, [])
    
    @classmethod
    def set_rag_sources(cls, sources: List[str]) -> None:
        """Establece las fuentes RAG."""
        st.session_state[cls.RAG_SOURCES_KEY] = sources
    
    # ==========================================================================
    # Configuración
    # ==========================================================================
    
    @classmethod
    def get_base_url(cls) -> str:
        """Obtiene la URL base de Ollama."""
        return st.session_state.get(cls.BASE_URL_KEY, OLLAMA_BASE_URL)
    
    @classmethod
    def set_base_url(cls, url: str) -> None:
        """Establece la URL base de Ollama."""
        st.session_state[cls.BASE_URL_KEY] = url
    
    @classmethod
    def get_temperature(cls) -> float:
        """Obtiene la temperatura."""
        return st.session_state.get(cls.TEMPERATURE_KEY, 0.7)
    
    @classmethod
    def set_temperature(cls, temp: float) -> None:
        """Establece la temperatura."""
        st.session_state[cls.TEMPERATURE_KEY] = temp
    
    # ==========================================================================
    # Uploader
    # ==========================================================================
    
    @classmethod
    def get_uploader_key(cls) -> int:
        """Obtiene la key del uploader."""
        return st.session_state.get(cls.UPLOADER_KEY, 0)
    
    @classmethod
    def increment_uploader_key(cls) -> None:
        """Incrementa la key del uploader para resetear."""
        st.session_state[cls.UPLOADER_KEY] = cls.get_uploader_key() + 1
    
    # ==========================================================================
    # Reset completo
    # ==========================================================================
    
    @classmethod
    def reset_conversation(cls) -> None:
        """Reinicia el estado de la conversación."""
        cls.clear_messages()
        cls.clear_pending_approval()
        cls.clear_current_plan()
        cls.set_agent_trace([])
        cls.set_rag_sources([])
        cls.increment_uploader_key()
