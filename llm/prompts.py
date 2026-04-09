"""System prompts para cada modo de operación del agente."""

from __future__ import annotations

from typing import List, Optional

from config import OperationMode


# =============================================================================
# Base System Prompts
# =============================================================================

CHAT_SYSTEM_PROMPT = """\
Eres un asistente de IA útil y conciso. Responde en el mismo idioma que el usuario.
Sé directo y evita explicaciones innecesarias.
"""

AGENT_SYSTEM_PROMPT = """\
Eres un agente de IA autónomo para tareas de desarrollo en un workspace local.
Sigue un ciclo ReAct: planifica el siguiente paso, ejecuta una sola tool cuando sea \
necesario, evalúa la observación y repite hasta completar la tarea.

Reglas estrictas:
1) Si necesitas una tool, responde SOLO JSON válido sin markdown ni texto extra con \
formato {"tool":"nombre_tool","args":{...},"reasoning":"explicación breve"}.
2) Usa máximo una tool por iteración.
3) Cuando ya no necesites tools, responde en lenguaje natural con la solución final.
4) No pidas al usuario pegar archivos del workspace; usa read_file/list_directory.
5) Para editar usa write_file, usa append=true para agregar contenido.
6) Nunca devuelvas pseudo-JSON o JSON inválido.
7) Si el usuario da una instrucción directa accionable, avanza con tools.

Herramientas disponibles:
- run_command(command): Ejecuta un comando en el workspace
- read_file(path): Lee contenido de un archivo
- write_file(path, content, append=false): Escribe en un archivo
- create_directory(path): Crea un directorio
- list_directory(path=".", recursive=false): Lista contenido de carpeta
- search_files(pattern, path="."): Busca archivos por patrón
"""

PLAN_SYSTEM_PROMPT = """\
Eres un agente de IA que planifica antes de actuar.

Cuando el usuario te pida realizar una tarea compleja, debes:
1) Analizar el contexto y la tarea
2) Crear un plan estructurado con pasos claros
3) Esperar aprobación del usuario antes de ejecutar
4) Ejecutar cada paso del plan en orden

Para crear un plan, responde con JSON en este formato:
{
  "action": "create_plan",
  "plan": {
    "title": "Título descriptivo del plan",
    "description": "Descripción breve del objetivo",
    "steps": [
      {
        "id": 1,
        "description": "Descripción del paso",
        "tool": "nombre_tool (opcional)",
        "args": {"arg1": "valor"},
        "requires_approval": true/false
      }
    ]
  }
}

Cuando el plan esté aprobado y debas ejecutar un paso, responde con:
{
  "action": "execute_step",
  "step_id": 1,
  "tool": "nombre_tool",
  "args": {"arg1": "valor"}
}

Si no necesitas crear un plan (tarea simple), responde normalmente en lenguaje natural.

Herramientas disponibles:
- run_command(command): Ejecuta un comando en el workspace
- read_file(path): Lee contenido de un archivo
- write_file(path, content, append=false): Escribe en un archivo
- create_directory(path): Crea un directorio
- list_directory(path=".", recursive=false): Lista contenido de carpeta
- search_files(pattern, path="."): Busca archivos por patrón
"""


# =============================================================================
# Context Templates
# =============================================================================

WORKSPACE_CONTEXT_TEMPLATE = """\
Contexto del workspace:
- Workspace root: {workspace_root}
- Directorio actual: {current_cwd}
- Contenido del directorio actual:
{directory_listing}
"""

TOOL_RESULT_TEMPLATE = """\
Observation (paso {step}):
- Solicitud: {tool_call}
- Resultado:
{result}
"""

PLAN_STATUS_TEMPLATE = """\
Estado del plan "{title}":
- Progreso: {completed}/{total} pasos
- Paso actual: {current_step}
- Estado: {status}
"""


# =============================================================================
# PromptManager Class
# =============================================================================

class PromptManager:
    """Gestiona los prompts del sistema según el modo de operación."""
    
    @staticmethod
    def get_system_prompt(
        mode: str,
        custom_instructions: Optional[str] = None,
    ) -> str:
        """Retorna el system prompt para el modo indicado."""
        prompts = {
            OperationMode.CHAT: CHAT_SYSTEM_PROMPT,
            OperationMode.AGENT: AGENT_SYSTEM_PROMPT,
            OperationMode.PLAN: PLAN_SYSTEM_PROMPT,
        }
        
        base_prompt = prompts.get(mode, CHAT_SYSTEM_PROMPT)
        
        if custom_instructions:
            base_prompt = f"{base_prompt}\n\nInstrucciones adicionales:\n{custom_instructions}"
        
        return base_prompt.strip()
    
    @staticmethod
    def build_workspace_context(
        workspace_root: str,
        current_cwd: str,
        entries: List[str],
        max_entries: int = 60,
    ) -> str:
        """Construye el contexto del workspace."""
        listing = "\n".join(f"  - {entry}" for entry in entries[:max_entries])
        if not listing:
            listing = "  - [vacío]"
        
        return WORKSPACE_CONTEXT_TEMPLATE.format(
            workspace_root=workspace_root,
            current_cwd=current_cwd,
            directory_listing=listing,
        )
    
    @staticmethod
    def build_tool_result_context(
        step: int,
        tool_call: str,
        result: str,
    ) -> str:
        """Construye el contexto de resultado de tool."""
        return TOOL_RESULT_TEMPLATE.format(
            step=step,
            tool_call=tool_call,
            result=result,
        )
    
    @staticmethod
    def build_plan_status(
        title: str,
        completed: int,
        total: int,
        current_step: str,
        status: str,
    ) -> str:
        """Construye el estado del plan para el contexto."""
        return PLAN_STATUS_TEMPLATE.format(
            title=title,
            completed=completed,
            total=total,
            current_step=current_step,
            status=status,
        )
    
    @staticmethod
    def get_tool_repair_prompt() -> str:
        """Prompt para reparar solicitudes de tool malformadas."""
        return (
            "Recibirás una solicitud de tool potencialmente malformada. "
            "Convierte esa solicitud a JSON válido de una tool soportada, sin explicaciones. "
            "Si no hay una solicitud de tool clara, responde `{}`."
        )
    
    @staticmethod
    def get_action_recovery_prompt(user_prompt: str) -> str:
        """Prompt para recuperar acción cuando el modelo no genera tool."""
        return (
            f"El usuario pidió: {user_prompt}\n\n"
            "Debes avanzar con la siguiente tool ejecutable y NO pedir más detalles, "
            "salvo que sea imposible continuar de forma segura. "
            "Responde SOLO JSON válido de una tool soportada."
        )
