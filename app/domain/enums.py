from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class ApiKeyScope(StrEnum):
    INGEST = "ingest"
    SEARCH = "search"
    ADMIN = "admin"


class StorageProvider(StrEnum):
    S3 = "s3"
    R2 = "r2"
    SPACES = "spaces"
    WASABI = "wasabi"
    S3_COMPATIBLE = "s3_compatible"


class StorageAuthType(StrEnum):
    ASSUME_ROLE = "assume_role"
    ACCESS_KEY = "access_key"


class StorageConnectionStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class SourceType(StrEnum):
    TEXT = "text"
    UPLOAD = "upload"
    URL = "url"


class MediaType(StrEnum):
    TEXT = "text"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    HTML = "html"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ChunkModality(StrEnum):
    TEXT = "text"
    OCR = "ocr"
    CAPTION = "caption"
    TRANSCRIPT = "transcript"


class SearchMode(StrEnum):
    HYBRID = "hybrid"
    VECTOR = "vector"
    KEYWORD = "keyword"


class JobKind(StrEnum):
    INGEST = "ingest"
    REPROCESS = "reprocess"


class JobQueue(StrEnum):
    LIGHT = "light"
    MEDIA = "media"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
