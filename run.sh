#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"
PORT="${PORT:-8000}"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "🔧 Creando entorno virtual en .venv..."
  python -m venv "${VENV_DIR}"
fi

echo "🔄 Activando entorno virtual..."
source "${VENV_DIR}/bin/activate"

echo "📦 Instalando/actualizando dependencias..."
pip install -q -r "${PROJECT_DIR}/requirements.txt"

if ! command -v ollama >/dev/null 2>&1; then
  echo "⚠️  Aviso: 'ollama' no está instalado o no está en PATH."
  echo "   La app iniciará, pero no podrá chatear hasta que Ollama esté disponible."
else
  echo "✅ Verificando estado de Ollama..."
  ollama ps >/dev/null 2>&1 || true
fi

echo ""
echo "🦙 Iniciando Ollama Chat GUI..."
echo "📍 Abre http://localhost:${PORT} en tu navegador"
echo "📖 API docs: http://localhost:${PORT}/docs"
echo ""
# Si el puerto ya está en uso, intentar cerrar una instancia previa de esta app.
if command -v lsof >/dev/null 2>&1; then
  EXISTING_PID="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null | head -n1 || true)"
  if [[ -n "${EXISTING_PID}" ]]; then
    CMDLINE="$(ps -p "${EXISTING_PID}" -o args= 2>/dev/null || true)"
    if [[ "${CMDLINE}" == *"uvicorn"* && "${CMDLINE}" == *"web.server:app"* ]]; then
      echo "♻️  Puerto ${PORT} en uso por instancia previa (PID ${EXISTING_PID}). Cerrando..."
      kill "${EXISTING_PID}" || true
      sleep 1
    else
      echo "❌ El puerto ${PORT} ya está en uso por otro proceso (PID ${EXISTING_PID})."
      echo "   Libera el puerto o ejecuta con otro: PORT=8001 ./run.sh"
      exit 1
    fi
  fi
fi

exec uvicorn web.server:app --host 0.0.0.0 --port "${PORT}" --reload
