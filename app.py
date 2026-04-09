import os
from typing import Dict, List

import streamlit as st

from ollama_client import OllamaClient, OllamaClientError


DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "")


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, str]] = []
    if "models" not in st.session_state:
        st.session_state.models = []


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

        if st.button("Limpiar chat"):
            st.session_state.messages = []
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_prompt = st.chat_input("Escribe tu mensaje...")
    if not user_prompt:
        return

    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

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


if __name__ == "__main__":
    main()
