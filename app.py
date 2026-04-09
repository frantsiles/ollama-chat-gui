import base64
import os
from typing import Any, Dict, List

import streamlit as st

from ollama_client import OllamaClient, OllamaClientError


DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "")
TEXT_FILE_EXTENSIONS = (".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml", ".py", ".log")
MAX_TEXT_CHARS_PER_FILE = 12000
MAX_FILE_SIZE_MB = 8
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = []
    if "models" not in st.session_state:
        st.session_state.models = []
    if "model_capabilities" not in st.session_state:
        st.session_state.model_capabilities = {}
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0


def _extract_text(uploaded_file: Any) -> str | None:
    raw = uploaded_file.getvalue()
    if not raw:
        return None

    for encoding in ("utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    if len(text) > MAX_TEXT_CHARS_PER_FILE:
        return text[:MAX_TEXT_CHARS_PER_FILE] + "\n...[contenido recortado]..."
    return text


def build_user_message(
    prompt: str,
    uploaded_files: List[Any],
    supports_vision: bool,
    max_file_size_bytes: int,
) -> tuple[Dict[str, Any], List[str]]:
    message: Dict[str, Any] = {"role": "user", "content": prompt}
    attachment_labels: List[str] = []
    ignored_files: List[str] = []
    text_context_blocks: List[str] = []
    image_blobs: List[str] = []

    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        mime = uploaded_file.type or ""
        lower_name = filename.lower()
        raw = uploaded_file.getvalue()
        size_bytes = len(raw)

        if size_bytes > max_file_size_bytes:
            ignored_files.append(
                f"{filename} (excede tamaño máximo de {MAX_FILE_SIZE_MB} MB)"
            )
            continue

        if mime.startswith("image/"):
            if not supports_vision:
                ignored_files.append(f"{filename} (imagen no soportada por el modelo seleccionado)")
                continue
            image_blobs.append(base64.b64encode(raw).decode("utf-8"))
            attachment_labels.append(f"🖼️ {filename}")
            continue

        if mime.startswith("text/") or lower_name.endswith(TEXT_FILE_EXTENSIONS):
            extracted_text = _extract_text(uploaded_file)
            if not extracted_text:
                ignored_files.append(f"{filename} (no se pudo leer como texto)")
                continue
            text_context_blocks.append(f"[Archivo: {filename}]\n{extracted_text}")
            attachment_labels.append(f"📄 {filename}")
            continue

        ignored_files.append(f"{filename} (tipo no soportado)")

    if text_context_blocks:
        message["content"] = (
            f"{prompt}\n\n---\nContexto de archivos adjuntos:\n\n" + "\n\n".join(text_context_blocks)
        )
    if image_blobs:
        message["images"] = image_blobs
    if attachment_labels:
        message["attachments"] = attachment_labels

    return message, ignored_files


def main() -> None:
    st.set_page_config(page_title="Ollama Chat GUI", page_icon="💬", layout="wide")
    init_state()

    st.title("Ollama Chat GUI")
    st.caption("Cliente gráfico local para chatear con modelos de Ollama.")

    with st.sidebar:
        st.header("Configuración")
        base_url = st.text_input("Ollama URL", value=DEFAULT_BASE_URL)
        temperature = st.slider("Temperature", min_value=0.0, max_value=1.5, value=0.7, step=0.1)

        client = OllamaClient(base_url=base_url)

        if st.button("Recargar modelos"):
            try:
                st.session_state.models = client.list_models()
                st.success("Modelos actualizados.")
            except OllamaClientError as exc:
                st.error(str(exc))

        if not st.session_state.models:
            try:
                st.session_state.models = client.list_models()
            except OllamaClientError:
                st.session_state.models = []

        if st.session_state.models:
            default_index = 0
            if DEFAULT_MODEL and DEFAULT_MODEL in st.session_state.models:
                default_index = st.session_state.models.index(DEFAULT_MODEL)
            model = st.selectbox("Modelo", st.session_state.models, index=default_index)
        else:
            st.warning("No se detectaron modelos. Ejecuta `ollama list` para verificar.")
            model = st.text_input("Modelo manual", value=DEFAULT_MODEL or "gemma3:latest")

        capabilities = st.session_state.model_capabilities.get(model, set())
        if model and not capabilities:
            try:
                capabilities = client.get_model_capabilities(model)
                st.session_state.model_capabilities[model] = capabilities
            except OllamaClientError:
                capabilities = set()

        if capabilities:
            st.caption(f"Capacidades: {', '.join(sorted(capabilities))}")

        supports_vision = "vision" in capabilities

        if st.button("Limpiar chat"):
            st.session_state.messages = []
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            attachments = msg.get("attachments", [])
            if attachments:
                st.caption(f"Adjuntos: {', '.join(attachments)}")
    st.subheader("Adjuntar archivos")
    uploaded_files = st.file_uploader(
        "Adjuntar archivos al próximo mensaje",
        type=[
            "png",
            "jpg",
            "jpeg",
            "webp",
            "gif",
            "txt",
            "md",
            "json",
            "csv",
            "xml",
            "yaml",
            "yml",
            "py",
            "log",
        ],
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
        help="Imágenes se envían al modelo si soporta vision. Archivos de texto se inyectan como contexto.",
    )
    st.caption(f"Tamaño máximo por archivo: {MAX_FILE_SIZE_MB} MB")

    if uploaded_files:
        image_files = [f for f in uploaded_files if (f.type or "").startswith("image/")]
        if image_files:
            st.caption("Previsualización de imágenes:")
            for image_file in image_files:
                st.image(image_file, caption=image_file.name, width=220)

    user_prompt = st.chat_input("Escribe tu mensaje...")
    if not user_prompt:
        return

    user_message, ignored_files = build_user_message(
        prompt=user_prompt,
        uploaded_files=uploaded_files or [],
        supports_vision=supports_vision,
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    )

    st.session_state.messages.append(user_message)
    with st.chat_message("user"):
        st.markdown(user_prompt)
        attachments = user_message.get("attachments", [])
        if attachments:
            st.caption(f"Adjuntos: {', '.join(attachments)}")
        if ignored_files:
            st.warning("No se enviaron algunos archivos:\n- " + "\n- ".join(ignored_files))

    assistant_chunks: List[str] = []
    with st.chat_message("assistant"):
        placeholder = st.empty()
        try:
            for chunk in client.chat_stream(
                model=model,
                messages=st.session_state.messages,
                options={"temperature": temperature},
            ):
                assistant_chunks.append(chunk)
                placeholder.markdown("".join(assistant_chunks))
        except OllamaClientError as exc:
            placeholder.error(str(exc))
            return

    st.session_state.messages.append({"role": "assistant", "content": "".join(assistant_chunks)})
    st.session_state.uploader_key += 1
    st.rerun()


if __name__ == "__main__":
    main()
