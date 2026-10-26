from __future__ import annotations

import threading
from collections.abc import Iterable

import numpy as np


class Embedder:
    """FastEmbed 本地中文向量模型，向量归一化后可用 L2 距离近似余弦相似度。"""

    def __init__(self, model_name: str, cache_dir: str | None = None, dim: int = 512) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.dim = dim
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
        return self._model

    @staticmethod
    def _normalize(vector: Iterable[float]) -> list[float]:
        array = np.asarray(list(vector), dtype=np.float32)
        norm = float(np.linalg.norm(array))
        if norm > 0:
            array = array / norm
        return array.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            model = self._ensure_model()
            vectors = list(model.embed(texts))
        return [self._normalize(vector) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            model = self._ensure_model()
            vectors = list(model.query_embed(text))
        return self._normalize(vectors[0])


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
