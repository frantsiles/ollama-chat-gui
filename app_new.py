#!/usr/bin/env python3
"""
Ollama Agent - Entry point.

Un agente de IA local con múltiples modos de operación:
- Chat: Conversación simple sin herramientas
- Agent: Ciclo ReAct automático con herramientas
- Plan: Planifica antes de ejecutar

Uso:
    streamlit run app_new.py
"""

from ui.app import main

if __name__ == "__main__":
    main()
