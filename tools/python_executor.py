"""Herramienta para ejecución de código Python en sandbox."""

from __future__ import annotations

import sys
import subprocess
import textwrap
from typing import List

from config import PYTHON_SANDBOX_TIMEOUT_SECONDS, MAX_COMMAND_OUTPUT_CHARS
from tools.base import BaseTool, ToolParameter, ToolResult


class ExecutePythonTool(BaseTool):
    """
    Ejecuta código Python en un subproceso aislado.

    Ideal para cálculos, transformaciones de datos y verificación
    de hipótesis directamente desde el agente, en lugar de solo
    describirlos.  El código corre con el CWD del workspace actual
    y hereda las variables de entorno del proceso padre.
    """

    name = "execute_python"
    description = (
        "Ejecuta código Python y retorna stdout, stderr y el código de salida. "
        "Úsalo para cálculos, transformaciones de datos o verificar resultados concretos."
    )
    # Puede escribir archivos → se trata como operación de escritura
    is_write_operation = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timeout: int = PYTHON_SANDBOX_TIMEOUT_SECONDS

    def get_parameters(self) -> List[ToolParameter]:
        return [
            ToolParameter(
                name="code",
                description="Código Python a ejecutar",
                type="string",
                required=True,
            ),
        ]

    def execute(self, code: str, **kwargs) -> ToolResult:  # type: ignore[override]
        if not code or not code.strip():
            return ToolResult(success=False, output="", error="El parámetro 'code' está vacío.")

        # Desidentar automáticamente para tolerar bloques con indentación extra
        code_clean = textwrap.dedent(code)

        try:
            result = subprocess.run(
                [sys.executable, "-c", code_clean],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.current_cwd,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"El código superó el límite de {self.timeout}s.",
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Error al lanzar el subproceso: {exc}",
            )

        stdout = (result.stdout or "").rstrip()
        stderr = (result.stderr or "").rstrip()

        combined = (
            f"Exit code: {result.returncode}\n\n"
            f"STDOUT:\n{stdout or '[vacío]'}\n\n"
            f"STDERR:\n{stderr or '[vacío]'}"
        )

        if len(combined) > MAX_COMMAND_OUTPUT_CHARS:
            combined = combined[:MAX_COMMAND_OUTPUT_CHARS] + "\n...[salida recortada]..."

        return ToolResult(
            success=result.returncode == 0,
            output=combined,
            error=stderr if result.returncode != 0 else None,
            metadata={
                "exit_code": result.returncode,
                "cwd": str(self.current_cwd),
            },
        )
