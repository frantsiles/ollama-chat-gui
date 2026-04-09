#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Creando entorno virtual en .venv..."
  python -m venv "${VENV_DIR}"
fi

echo "Activando entorno virtual..."
source "${VENV_DIR}/bin/activate"

echo "Instalando/actualizando dependencias..."
pip install -r "${PROJECT_DIR}/requirements.txt"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Aviso: 'ollama' no está instalado o no está en PATH."
  echo "La app iniciará, pero no podrá chatear hasta que Ollama esté disponible."
else
  echo "Verificando estado de Ollama..."
  ollama ps >/dev/null 2>&1 || true
fi

echo "Iniciando aplicación..."
exec streamlit run "${PROJECT_DIR}/app.py"
