import base64
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from ollama_client import OllamaClient, OllamaClientError


DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "")
DEFAULT_WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.getcwd())
TEXT_FILE_EXTENSIONS = (".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml", ".py", ".log")
MAX_TEXT_CHARS_PER_FILE = 12000
MAX_FILE_SIZE_MB = 8
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_SCAN_RESULTS = 300
MAX_READ_CHARS = 30000
MAX_COMMAND_OUTPUT_CHARS = 30000
COMMAND_TIMEOUT_SECONDS = 30
CHAT_COMMAND_PREFIX = "/cmd"


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = []
    if "models" not in st.session_state:
        st.session_state.models = []
    if "model_capabilities" not in st.session_state:
        st.session_state.model_capabilities = {}
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0
    if "workspace_root" not in st.session_state:
        st.session_state.workspace_root = DEFAULT_WORKSPACE_ROOT


def _resolve_workspace_root(root_text: str) -> Path:
    return Path(root_text).expanduser().resolve()


def _safe_resolve_path(workspace_root: Path, target: str) -> Path:
    if not target.strip():
        target = "."

    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = workspace_root / target_path

    resolved = target_path.resolve()
    workspace = workspace_root.resolve()
    if os.path.commonpath([str(workspace), str(resolved)]) != str(workspace):
        raise ValueError("Ruta fuera del workspace permitido.")
    return resolved


def _scan_directory(workspace_root: Path, target: str, recursive: bool) -> str:
    root = _safe_resolve_path(workspace_root, target)
    if not root.exists():
        raise ValueError("La carpeta indicada no existe.")
    if not root.is_dir():
        raise ValueError("La ruta indicada no es una carpeta.")

    iterator = root.rglob("*") if recursive else root.glob("*")
    entries: List[str] = []
    for path in iterator:
        if len(entries) >= MAX_SCAN_RESULTS:
            break
        rel = path.relative_to(workspace_root)
        suffix = "/" if path.is_dir() else ""
        entries.append(f"{rel}{suffix}")

    if not entries:
        return f"Scan de `{root.relative_to(workspace_root)}`: no se encontraron entradas."

    return (
        f"Scan de `{root.relative_to(workspace_root)}` "
        f"(mostrando hasta {MAX_SCAN_RESULTS} resultados):\n"
        + "\n".join(f"- {entry}" for entry in entries)
    )


def _read_text_file(workspace_root: Path, target: str) -> str:
    file_path = _safe_resolve_path(workspace_root, target)
    if not file_path.exists():
        raise ValueError("El archivo indicado no existe.")
    if not file_path.is_file():
        raise ValueError("La ruta indicada no es un archivo.")

    raw = file_path.read_bytes()
    text = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("No se pudo decodificar el archivo como texto.")

    trimmed = text[:MAX_READ_CHARS]
    suffix = ""
    if len(text) > MAX_READ_CHARS:
        suffix = "\n...[contenido recortado]..."

    rel = file_path.relative_to(workspace_root)
    return f"Contenido de `{rel}`:\n\n{trimmed}{suffix}"


def _write_text_file(workspace_root: Path, target: str, content: str, append: bool) -> str:
    file_path = _safe_resolve_path(workspace_root, target)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with file_path.open("a", encoding="utf-8") as fh:
            fh.write(content)
    else:
        file_path.write_text(content, encoding="utf-8")

    rel = file_path.relative_to(workspace_root)
    mode = "append" if append else "overwrite"
    return f"Escritura exitosa en `{rel}` (modo: {mode}, chars: {len(content)})."


def _add_system_context(context: str) -> None:
    st.session_state.messages.append({"role": "system", "content": context})


def _run_workspace_command(workspace_root: Path, command: str) -> str:
    if not command.strip():
        raise ValueError("Debes indicar un comando.")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(
            f"El comando superó el timeout de {COMMAND_TIMEOUT_SECONDS}s."
        ) from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined = (
        f"Comando: {command}\n"
        f"Exit code: {result.returncode}\n\n"
        f"STDOUT:\n{stdout or '[vacío]'}\n\n"
        f"STDERR:\n{stderr or '[vacío]'}"
    )
    if len(combined) > MAX_COMMAND_OUTPUT_CHARS:
        combined = combined[:MAX_COMMAND_OUTPUT_CHARS] + "\n...[salida recortada]..."
    return combined


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


def _parse_chat_command(prompt: str) -> str | None:
    stripped = prompt.strip()
    if not stripped.startswith(CHAT_COMMAND_PREFIX):
        return None

    command = stripped[len(CHAT_COMMAND_PREFIX) :].strip()
    if not command:
        raise ValueError("Debes indicar un comando luego de /cmd.")
    return command


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
        workspace_root_text = st.text_input(
            "Workspace root",
            value=st.session_state.workspace_root,
            help="Solo se permitirá leer/escribir dentro de esta carpeta.",
        )

        client = OllamaClient(base_url=base_url)
        st.session_state.workspace_root = workspace_root_text

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
        if msg["role"] not in {"user", "assistant"}:
            continue
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            attachments = msg.get("attachments", [])
            if attachments:
                st.caption(f"Adjuntos: {', '.join(attachments)}")

    st.subheader("Herramientas de archivos")
    workspace_root = _resolve_workspace_root(st.session_state.workspace_root)
    st.caption(f"Workspace activo: `{workspace_root}`")

    scan_col, read_col = st.columns(2)
    with scan_col:
        st.markdown("**Escanear carpeta**")
        scan_target = st.text_input("Ruta a escanear", value=".", key="scan_target")
        scan_recursive = st.checkbox("Recursivo", value=True, key="scan_recursive")
        if st.button("Escanear", key="scan_btn"):
            try:
                scan_result = _scan_directory(workspace_root, scan_target, scan_recursive)
                _add_system_context(scan_result)
                st.success("Resultado de escaneo agregado al contexto del chat.")
                st.code(scan_result, language="text")
            except ValueError as exc:
                st.error(str(exc))

    with read_col:
        st.markdown("**Leer archivo**")
        read_target = st.text_input("Ruta de archivo a leer", value="", key="read_target")
        if st.button("Leer", key="read_btn"):
            try:
                read_result = _read_text_file(workspace_root, read_target)
                _add_system_context(read_result)
                st.success("Contenido agregado al contexto del chat.")
                st.code(read_result, language="text")
            except ValueError as exc:
                st.error(str(exc))

    st.markdown("**Escribir archivo**")
    write_target = st.text_input("Ruta de archivo a escribir", value="", key="write_target")
    write_append = st.checkbox("Append (agregar al final)", value=False, key="write_append")
    write_content = st.text_area("Contenido a escribir", value="", height=150, key="write_content")
    if st.button("Escribir archivo", key="write_btn"):
        try:
            write_result = _write_text_file(workspace_root, write_target, write_content, write_append)
            _add_system_context(write_result)
            st.success("Escritura completada y registrada en el contexto del chat.")
        except ValueError as exc:
            st.error(str(exc))

    st.markdown("**Ejecutar comando en workspace**")
    command_text = st.text_input(
        "Comando",
        value="",
        key="command_text",
        help="Se ejecuta dentro del Workspace root y su salida se agrega al contexto del chat.",
    )
    if st.button("Ejecutar comando", key="run_command_btn"):
        try:
            command_result = _run_workspace_command(workspace_root, command_text)
            _add_system_context(command_result)
            st.success("Resultado del comando agregado al contexto del chat.")
            st.code(command_result, language="text")
        except ValueError as exc:
            st.error(str(exc))
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
    st.caption(f"También puedes ejecutar comandos desde el chat con `{CHAT_COMMAND_PREFIX} <comando>`.") 

    if uploaded_files:
        image_files = [f for f in uploaded_files if (f.type or "").startswith("image/")]
        if image_files:
            st.caption("Previsualización de imágenes:")
            for image_file in image_files:
                st.image(image_file, caption=image_file.name, width=220)

    user_prompt = st.chat_input(f"Escribe tu mensaje... (o {CHAT_COMMAND_PREFIX} <comando>)")
    if not user_prompt:
        return

    try:
        chat_command = _parse_chat_command(user_prompt)
    except ValueError as exc:
        st.error(str(exc))
        return

    if chat_command:
        command_user_content = f"🛠️ Ejecutar comando en workspace: `{chat_command}`"
        st.session_state.messages.append({"role": "user", "content": command_user_content})
        with st.chat_message("user"):
            st.markdown(command_user_content)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            try:
                command_result = _run_workspace_command(workspace_root, chat_command)
                _add_system_context(
                    f"Resultado de comando en workspace `{workspace_root}`:\n\n{command_result}"
                )
                assistant_content = f"```text\n{command_result}\n```"
                placeholder.markdown(assistant_content)
            except ValueError as exc:
                assistant_content = f"Error ejecutando comando: {exc}"
                placeholder.error(assistant_content)

        st.session_state.messages.append({"role": "assistant", "content": assistant_content})
        st.rerun()
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
