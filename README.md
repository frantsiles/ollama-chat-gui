# Ollama Chat GUI
Aplicación gráfica local para chatear con modelos de Ollama usando Streamlit.

## Objetivo
- Que cualquier persona pueda clonar el repositorio y levantar la app rápidamente.
- Mantener el proyecto simple, local-first y fácil de extender.

## Requisitos
- Python 3.11+
- Ollama instalado y ejecutándose
- Al menos un modelo descargado (ejemplo: `gemma3:latest`)

## Instalación
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecución
1. Verifica que Ollama esté activo:
```bash
ollama ps
```
2. Ejecuta la app:
```bash
streamlit run app.py
```
3. Abre el navegador en la URL que Streamlit muestre (normalmente `http://localhost:8501`).

## Variables de entorno (opcional)
Puedes crear tu `.env` basado en `.env.example`:
- `OLLAMA_BASE_URL` (default: `http://localhost:11434`)
- `OLLAMA_DEFAULT_MODEL` (default vacío)

## Publicar en GitHub (repo público)
```bash
git init
git add .
git commit -m "feat: initial Ollama chat GUI scaffold"
git branch -M main
git remote add origin <URL_DEL_REPO>
git push -u origin main
```

## Próximas mejoras sugeridas
- Historial persistente (SQLite)
- Múltiples conversaciones
- Perfiles de parámetros por modelo
- Exportar/importar chats
