from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="RAG_", extra="ignore")

    app_name: str = "iNterra RAG"
    app_version: str = "0.1.0"
    environment: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://rag:rag@localhost:5434/rag"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    model_cache_dir: Path = Path("models")
    preload_models: bool = False
    text_embedding_model: str = "intfloat/multilingual-e5-base"
    text_embedding_model_file: str = "onnx/model.onnx"
    text_embedding_query_prefix: str = "query: "
    text_embedding_passage_prefix: str = "passage: "
    embedding_batch_size: int = 32

    chunk_max_tokens: int = 256
    chunk_overlap_tokens: int = 40
    max_text_bytes: int = 5_000_000
    max_document_bytes: int = 50 * 1024 * 1024
    max_media_bytes: int = 1024 * 1024 * 1024

    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: Path = Path("storage")
    storage_bucket: str = "rag-platform"
    storage_region: str = "us-east-1"
    storage_endpoint_url: str | None = None
    storage_access_key_id: str | None = None
    storage_secret_access_key: str | None = None
    storage_encryption_key: str = ""
    storage_presigned_url_seconds: int = 900

    image_embedding_model: str = "Qdrant/clip-ViT-B-32-vision"
    image_text_embedding_model: str = "sentence-transformers/clip-ViT-B-32-multilingual-v1"
    image_caption_model: str = "florence-community/Florence-2-base"
    image_caption_max_tokens: int = 96

    whisper_model: str = "small"
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 5
    video_keyframe_seconds: float = 10.0
    video_max_keyframes: int = 60
    video_keyframe_ocr: bool = True

    ocr_min_page_characters: int = 20
    ocr_render_scale: float = 2.0

    api_key_pepper: str = ""
    api_key_cache_seconds: int = 60
    api_key_touch_seconds: int = 60
    platform_admin_key: str = ""

    redis_url: str = "redis://localhost:6379/5"
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_search: int = 60
    rate_limit_ingest: int = 30
    rate_limit_api: int = 120

    worker_concurrency: int = 2
    worker_idle_seconds: float = 1.0
    worker_stale_after_seconds: int = 900
    job_retry_base_seconds: int = 10

    search_max_top_k: int = 50
    search_candidate_factor: int = 4
    search_min_candidates: int = 40
    search_max_candidates: int = 400

    def search_candidates(self, top_k: int) -> int:
        wanted = max(top_k * self.search_candidate_factor, self.search_min_candidates)
        return min(wanted, self.search_max_candidates)


@lru_cache
def get_settings() -> Settings:
    return Settings()
