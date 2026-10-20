import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastembed import ImageEmbedding

from app.db.models.vectors import IMAGE_EMBEDDING_DIMENSIONS
from app.ml.optional import optional_module

if TYPE_CHECKING:
    from PIL.Image import Image

MEDIA_GROUP = "media"
CAPTION_TASK = "<MORE_DETAILED_CAPTION>"


class EmbeddingDimensionError(RuntimeError):
    pass


def checked(vectors: list[list[float]], model_name: str) -> list[list[float]]:
    if any(len(vector) != IMAGE_EMBEDDING_DIMENSIONS for vector in vectors):
        raise EmbeddingDimensionError(
            f"{model_name} must produce {IMAGE_EMBEDDING_DIMENSIONS}-dimension vectors",
        )
    return vectors


class ClipImageEmbedder:
    def __init__(self, *, image_model: str, text_model: str, cache_dir: Path) -> None:
        self._image_model_name = image_model
        self._text_model_name = text_model
        self._cache_dir = cache_dir
        self._images = ImageEmbedding(model_name=image_model, cache_dir=str(cache_dir))
        self._text: Any = None
        self._text_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._image_model_name

    def embed_images(self, images: Sequence["Image"]) -> list[list[float]]:
        vectors = [vector.tolist() for vector in self._images.embed(list(images))]
        return checked(vectors, self._image_model_name)

    def embed_text(self, text: str) -> list[float]:
        vector: list[float] = self._text_encoder().encode(text, normalize_embeddings=True).tolist()
        return checked([vector], self._text_model_name)[0]

    def _text_encoder(self) -> Any:
        with self._text_lock:
            if self._text is None:
                sentence_transformers = optional_module("sentence_transformers", MEDIA_GROUP)
                self._text = sentence_transformers.SentenceTransformer(
                    self._text_model_name,
                    cache_folder=str(self._cache_dir),
                    device="cpu",
                )
            return self._text


class Florence2Captioner:
    def __init__(self, *, model_name: str, cache_dir: Path, max_new_tokens: int) -> None:
        transformers = optional_module("transformers", MEDIA_GROUP)
        self._torch = optional_module("torch", MEDIA_GROUP)
        self._max_new_tokens = max_new_tokens
        self._generating = threading.Lock()
        self._processor = transformers.AutoProcessor.from_pretrained(
            model_name,
            cache_dir=str(cache_dir),
        )
        self._model = transformers.Florence2ForConditionalGeneration.from_pretrained(
            model_name,
            cache_dir=str(cache_dir),
        ).eval()

    def caption(self, image: "Image") -> str:
        inputs = self._processor(text=CAPTION_TASK, images=image, return_tensors="pt")
        with self._generating, self._torch.inference_mode():
            generated = self._model.generate(
                **inputs,
                max_new_tokens=self._max_new_tokens,
                num_beams=3,
                do_sample=False,
            )
        decoded = self._processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = self._processor.post_process_generation(
            decoded,
            task=CAPTION_TASK,
            image_size=image.size,
        )
        return str(parsed[CAPTION_TASK])
