"""Cliente de embeddings via Ollama con caché LRU en memoria."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import List, Optional

import requests

from config import EMBEDDING_MODEL, OLLAMA_BASE_URL, OLLAMA_TIMEOUT

logger = logging.getLogger(__name__)

# Tamaño máximo del caché LRU (número de textos únicos cacheados)
_LRU_MAX_SIZE = 512


class EmbeddingError(Exception):
    """Error al generar embeddings."""


class _LRUCache:
    """Caché LRU simple para vectores de embeddings."""

    def __init__(self, max_size: int = _LRU_MAX_SIZE) -> None:
        self._cache: OrderedDict[str, List[float]] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[List[float]]:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: str, value: List[float]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


def _text_key(text: str) -> str:
    """Hash SHA-256 del texto para usar como clave de caché."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


class EmbeddingClient:
    """
    Cliente para el endpoint /api/embeddings de Ollama.

    Uso:
        client = EmbeddingClient()
        if client.available:
            vec = client.embed("texto de ejemplo")
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = EMBEDDING_MODEL,
        timeout: int = OLLAMA_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._cache = _LRUCache()
        self._available: Optional[bool] = None  # None = no comprobado todavía
        self._dim: Optional[int] = None

    # ------------------------------------------------------------------
    # Disponibilidad
    # ------------------------------------------------------------------

    def _probe(self) -> bool:
        """Comprueba si el modelo de embeddings está disponible en Ollama."""
        try:
            vec = self._call_api("test")
            self._dim = len(vec)
            return True
        except Exception as exc:
            logger.warning(
                "EmbeddingClient: modelo '%s' no disponible: %s", self.model, exc
            )
            return False

    @property
    def available(self) -> bool:
        """True si el modelo de embeddings responde correctamente."""
        if self._available is None:
            self._available = self._probe()
        return self._available

    @property
    def dim(self) -> Optional[int]:
        """Dimensionalidad del vector (disponible tras primera llamada exitosa)."""
        return self._dim

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def _call_api(self, text: str) -> List[float]:
        """Llama directamente al endpoint de Ollama (sin caché)."""
        url = f"{self.base_url}/api/embeddings"
        payload = {"model": self.model, "prompt": text}
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise EmbeddingError(f"Error HTTP al embeddar: {exc}") from exc

        data = resp.json()
        if "error" in data:
            raise EmbeddingError(str(data["error"]))

        embedding = data.get("embedding")
        if not embedding or not isinstance(embedding, list):
            raise EmbeddingError("Respuesta de embeddings vacía o inválida")

        return embedding

    def embed(self, text: str) -> List[float]:
        """
        Genera el embedding de un texto con caché LRU.

        Args:
            text: Texto a embeddar (se trunca a 8000 chars para no saturar el modelo)

        Returns:
            Vector de embeddings como lista de floats

        Raises:
            EmbeddingError: Si el modelo no está disponible o falla la petición
        """
        if not self.available:
            raise EmbeddingError(
                f"Modelo de embeddings '{self.model}' no disponible en Ollama"
            )

        text = text[:8000]  # Límite seguro para la mayoría de modelos
        key = _text_key(text)

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        vec = self._call_api(text)
        if self._dim is None:
            self._dim = len(vec)
        self._cache.put(key, vec)
        return vec

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Genera embeddings para una lista de textos.
        Ollama no tiene endpoint batch nativo, se itera secuencialmente.
        """
        return [self.embed(t) for t in texts]

    def cache_info(self) -> dict:
        """Información del estado de la caché."""
        return {"size": len(self._cache), "max_size": _LRU_MAX_SIZE}

    def clear_cache(self) -> None:
        """Vacía la caché LRU."""
        self._cache.clear()


# ---------------------------------------------------------------------------
# Singleton global por (base_url, model)
# ---------------------------------------------------------------------------
_CLIENT_REGISTRY: dict[tuple[str, str], EmbeddingClient] = {}


def get_embedding_client(
    base_url: str = OLLAMA_BASE_URL,
    model: str = EMBEDDING_MODEL,
) -> EmbeddingClient:
    """Retorna (o crea) el cliente singleton para la combinación base_url + model."""
    key = (base_url, model)
    if key not in _CLIENT_REGISTRY:
        _CLIENT_REGISTRY[key] = EmbeddingClient(base_url=base_url, model=model)
    return _CLIENT_REGISTRY[key]
