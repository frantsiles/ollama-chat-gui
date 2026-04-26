"""Tests del motor de conversación.

Cubre tres niveles:
  1. Unitarios  — sin LLM, sin filesystem real (mocks)
  2. Filesystem — tools reales sobre directorios de prueba
  3. Integración — Agent completo con Ollama real (requiere servidor activo)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# Asegurar que el raíz del proyecto esté en sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

WORKSPACE = Path("/home/frantsiles/EjemploDeGrafosPython")
MODEL = "qwen2.5-coder:14b"


# =============================================================================
# 1. Router — sin LLM
# =============================================================================

class TestConversationRouter:
    """Verifica que el fast-path conversacional clasifica correctamente."""

    from core.conversation.router import ConversationRouter as _CR

    @pytest.mark.parametrize("msg", [
        "hola", "Hola!", "hi", "buenos días",
        "gracias", "ok", "vale", "perfecto",
        "adiós", "chao", "nos vemos",
        "sí", "no", "claro",
    ])
    def test_clasifica_conversacional(self, msg):
        from core.conversation.router import ConversationRouter
        assert ConversationRouter.is_conversational(msg), f"Debería ser conversacional: {msg!r}"

    @pytest.mark.parametrize("msg", [
        "lista los archivos",
        "Listame los archivos de este repo",
        "lee el archivo config.py",
        "busca funciones con 'def main'",
        "crea un directorio llamado src",
        "¿puedes leer el README?",
        "muéstrame el contenido del workspace",
        "ejecuta pytest",
        "analiza el proyecto",
    ])
    def test_clasifica_trabajo(self, msg):
        from core.conversation.router import ConversationRouter
        assert not ConversationRouter.is_conversational(msg), f"Debería ser trabajo: {msg!r}"


# =============================================================================
# 2. Tools de filesystem — acceso real al disco
# =============================================================================

class TestListDirectoryTool:
    """list_directory ejecuta en el filesystem real."""

    def _make_tool(self, workspace: Path):
        from tools.filesystem import ListDirectoryTool
        return ListDirectoryTool(workspace_root=workspace, current_cwd=workspace)

    def test_lista_workspace_grafos(self):
        """Debe listar los archivos del repo EjemploDeGrafosPython."""
        tool = self._make_tool(WORKSPACE)
        result = tool.execute(path=".")
        assert result.success, f"Falló: {result.error}"
        assert "README.md" in result.output or ".gitignore" in result.output, (
            f"No encontró archivos esperados. Output: {result.output}"
        )

    def test_lista_directorio_inexistente(self):
        """Debe retornar error (no lanzar excepción) si el dir no existe."""
        tool = self._make_tool(WORKSPACE)
        result = tool.execute(path="./no_existe_este_dir")
        assert not result.success
        assert result.error is not None

    def test_path_traversal_bloqueado(self):
        """No debe permitir salir del workspace."""
        tool = self._make_tool(WORKSPACE)
        result = tool.execute(path="../../etc")
        assert not result.success


class TestReadFileTool:
    """read_file lee contenido real de archivos."""

    def _make_tool(self, workspace: Path):
        from tools.filesystem import ReadFileTool
        return ReadFileTool(workspace_root=workspace, current_cwd=workspace)

    def test_lee_readme(self):
        tool = self._make_tool(WORKSPACE)
        result = tool.execute(path="README.md")
        assert result.success, f"Falló: {result.error}"
        assert len(result.output) > 0

    def test_archivo_inexistente(self):
        tool = self._make_tool(WORKSPACE)
        result = tool.execute(path="no_existe.py")
        assert not result.success


class TestToolRegistry:
    """ToolRegistry orquesta tools correctamente."""

    def _make_registry(self, workspace: Path):
        from tools.registry import ToolRegistry
        return ToolRegistry(workspace_root=workspace, current_cwd=workspace)

    def test_list_directory_via_registry(self):
        from core.models import ToolCall
        registry = self._make_registry(WORKSPACE)
        tc = ToolCall(tool="list_directory", args={"path": "."})
        result = registry.execute(tc)
        assert result.success, f"Falló: {result.error}"
        assert result.output

    def test_herramienta_invalida(self):
        from core.models import ToolCall
        registry = self._make_registry(WORKSPACE)
        error = registry.validate_tool_call(ToolCall(tool="tool_inexistente", args={}))
        assert error is not None

    def test_tools_disponibles(self):
        registry = self._make_registry(WORKSPACE)
        tools = registry.list_tools()
        assert "list_directory" in tools
        assert "read_file" in tools
        assert "search_files" in tools


# =============================================================================
# 3. NaturalConversationLoop — con LLM simulado
# =============================================================================

class TestNaturalConversationLoop:
    """Prueba el bucle interno con LLM y tool mockeados."""

    def _make_loop(self, llm_responses: List[str], tool_output: str = "OK"):
        """Construye un NaturalConversationLoop con dobles de prueba."""
        from core.conversation.natural_loop import NaturalConversationLoop
        from core.models import AgentState, ToolCall, ToolResult

        call_iter = iter(llm_responses)

        def fake_llm(messages, fmt=None):
            try:
                return next(call_iter)
            except StopIteration:
                return "No tengo más respuestas."

        def fake_parse(response: str) -> Dict[str, Any]:
            if "list_directory" in response:
                return {"needs_tool": True, "tool": "list_directory", "args": {"path": "."}}
            return {"needs_tool": False}

        def fake_build_messages(conv, system_prompt):
            return [{"role": "system", "content": system_prompt or ""}]

        def fake_validate(tc: ToolCall) -> Optional[str]:
            return None  # siempre válida

        def fake_is_write(tc: ToolCall) -> bool:
            return False

        def fake_requires_approval(tc: ToolCall, is_write: bool) -> bool:
            return False

        def fake_execute(tc: ToolCall):
            return ToolResult(tool_call=tc, success=True, output=tool_output)

        def fake_cwd_change(p: Path):
            pass

        state = AgentState(mode="agent")
        return NaturalConversationLoop(
            llm_call=fake_llm,
            build_messages=fake_build_messages,
            parse_response=fake_parse,
            validate_tool_call=fake_validate,
            is_write_operation=fake_is_write,
            requires_approval=fake_requires_approval,
            execute_tool=fake_execute,
            on_cwd_change=fake_cwd_change,
            state=state,
        )

    def _make_conversation(self, user_message: str):
        from core.models import Conversation
        conv = Conversation()
        conv.add_user_message(user_message)
        return conv

    def test_respuesta_directa_sin_tool(self):
        """Si el modelo responde sin necesitar tool, retorna completed."""
        loop = self._make_loop(["Aquí está mi respuesta directa."])
        conv = self._make_conversation("hola")
        result = loop.run(conv, system_prompt="eres un asistente")
        assert result.status == "completed"
        assert "respuesta directa" in result.final_response

    def test_usa_tool_y_responde(self):
        """Detecta tool → la ejecuta → el modelo da respuesta final."""
        loop = self._make_loop(
            llm_responses=[
                "Voy a list_directory para ver los archivos.",  # paso 1: necesita tool
                "Los archivos encontrados son: README.md",       # paso 2: respuesta final
            ],
            tool_output="README.md\n.gitignore",
        )
        conv = self._make_conversation("lista los archivos")
        result = loop.run(conv, system_prompt="eres un asistente")
        assert result.status == "completed"
        assert len(result.tool_results) == 1
        assert result.tool_results[0].output == "README.md\n.gitignore"

    def test_tool_result_se_persiste_en_conversation(self):
        """El resultado de la tool debe quedar en conversation.messages."""
        loop = self._make_loop(
            llm_responses=[
                "list_directory a continuación.",
                "Listo, encontré los archivos.",
            ],
            tool_output="archivo1.py\narchivo2.py",
        )
        conv = self._make_conversation("muéstrame los archivos")
        result = loop.run(conv, system_prompt="eres un asistente")
        assert result.status == "completed"
        # El tool result debe estar en los mensajes system de la conversación
        system_msgs = [m for m in conv.messages if m.role.value == "system"]
        assert any("archivo1.py" in m.content for m in system_msgs), (
            "El tool result no se persistió en la conversación"
        )

    def test_respuesta_vacia_reintenta(self):
        """Una respuesta vacía del modelo no debe causar crash — reintenta."""
        loop = self._make_loop(["", "", "Respuesta válida al tercer intento."])
        conv = self._make_conversation("hola")
        result = loop.run(conv, system_prompt="eres un asistente")
        assert result.status == "completed"


# =============================================================================
# 4. Integración real — Agent + Ollama + Filesystem
# =============================================================================

@pytest.mark.integration
class TestAgentIntegration:
    """Pruebas end-to-end con Ollama real. Ejecutar con:
       pytest tests/test_conversation_engine.py -m integration -v -s
    """

    def _make_agent(self):
        from core.agent import Agent
        from llm.client import OllamaClient
        client = OllamaClient()
        return Agent(
            client=client,
            model=MODEL,
            workspace_root=WORKSPACE,
            current_cwd=WORKSPACE,
        )

    def _make_conversation(self):
        from core.models import Conversation
        conv = Conversation()
        conv.workspace_root = str(WORKSPACE)
        conv.current_cwd = str(WORKSPACE)
        return conv

    def test_lista_archivos_workspace(self):
        """El agente debe listar los archivos del repo EjemploDeGrafosPython."""
        agent = self._make_agent()
        conv = self._make_conversation()

        t0 = time.time()
        response = agent.run(
            user_input="Listame los archivos que hay en este repo",
            conversation=conv,
        )
        elapsed = time.time() - t0

        print(f"\n--- Respuesta del agente ({elapsed:.1f}s) ---")
        print(response.content)
        print(f"--- Tool results: {len(response.tool_results)} ---")
        for tr in response.tool_results:
            print(f"  [{tr.tool_name if hasattr(tr, 'tool_name') else 'tool'}] success={tr.success}")
            print(f"  {tr.output[:200]}")

        assert response.content, "El agente no retornó ninguna respuesta"
        # La respuesta debe mencionar alguno de los archivos conocidos
        content_lower = response.content.lower()
        assert any(f in content_lower for f in ["readme", ".gitignore", "archivos", "encontré", "hay"]), (
            f"La respuesta no parece mencionar los archivos: {response.content[:300]}"
        )

    def test_respuesta_contiene_archivos_del_workspace(self):
        """El agente debe responder con los archivos reales del workspace.

        Nota: el modelo puede responder desde el workspace snapshot del system
        prompt (sin llamar a list_directory) o invocando la tool — ambos son
        comportamientos válidos. Lo que importa es que la respuesta sea correcta.
        """
        agent = self._make_agent()
        conv = self._make_conversation()

        response = agent.run(
            user_input="Lista todos los archivos que hay en el directorio actual",
            conversation=conv,
        )

        tool_names = [getattr(tr, "tool_name", "") for tr in response.tool_results]
        print(f"\nTools usadas: {tool_names}")
        print(f"Respuesta: {response.content[:300]}")

        # El modelo puede listar desde el workspace context O llamar a list_directory
        content_lower = response.content.lower()
        archivos_conocidos = ["readme", ".gitignore", "git"]
        encontrados = [f for f in archivos_conocidos if f in content_lower]
        assert encontrados, (
            f"La respuesta no menciona ningún archivo del workspace. "
            f"Respuesta: {response.content[:300]}"
        )

    def test_fast_path_hola(self):
        """'hola' debe ir por fast-path (sin tools, respuesta rápida)."""
        agent = self._make_agent()
        conv = self._make_conversation()

        t0 = time.time()
        response = agent.run(user_input="hola", conversation=conv)
        elapsed = time.time() - t0

        print(f"\nRespuesta 'hola' en {elapsed:.1f}s: {response.content[:100]}")
        assert response.content
        assert len(response.tool_results) == 0, "Fast-path no debería usar tools"
        # Fast-path debería ser notablemente más rápido que el ciclo completo
        assert elapsed < 60, f"Fast-path tardó demasiado: {elapsed:.1f}s"
