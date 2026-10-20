from collections.abc import Sequence
from pathlib import Path

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

from app.db.models.vectors import TEXT_EMBEDDING_DIMENSIONS


class EmbeddingDimensionError(RuntimeError):
    pass


def ensure_registered(model_name: str, model_file: str) -> None:
    if any(model["model"] == model_name for model in TextEmbedding.list_supported_models()):
        return
    TextEmbedding.add_custom_model(
        model=model_name,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=model_name),
        dim=TEXT_EMBEDDING_DIMENSIONS,
        model_file=model_file,
    )


class FastEmbedTextEmbedder:
    def __init__(
        self,
        *,
        model_name: str,
        model_file: str,
        cache_dir: Path,
        query_prefix: str,
        passage_prefix: str,
        batch_size: int,
    ) -> None:
        self._model_name = model_name
        self._query_prefix = query_prefix
        self._passage_prefix = passage_prefix
        self._batch_size = batch_size
        ensure_registered(model_name, model_file)
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed([self._passage_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._query_prefix + text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [
            vector.tolist() for vector in self._model.embed(texts, batch_size=self._batch_size)
        ]
        if any(len(vector) != TEXT_EMBEDDING_DIMENSIONS for vector in vectors):
            raise EmbeddingDimensionError(
                f"{self._model_name} must produce {TEXT_EMBEDDING_DIMENSIONS}-dimension vectors",
            )
        return vectors
