from typing import Any

from fastapi import status
from pydantic import BaseModel

INGEST_DESCRIPTION = """
One endpoint for every kind of content. Pick the request body type:

- **`application/json`**: send `text` directly.
- **`multipart/form-data`**: upload a `file`. Its type is detected from the content itself
  (PDF, DOCX, PPTX, XLSX, HTML, Markdown, CSV, JSON or plain text).

The response is immediate with `status: queued`; a worker processes it in the background.
Sending identical content to the same collection returns the existing document with
`duplicate: true`. Reusing an `external_id` replaces that document's content.
"""

SEARCH_DESCRIPTION = """
Returns the best matching chunk (or the top `top_k`), ready to pass to an LLM. Each chunk is
one section of a document and starts with its heading path.

| Mode | Ranking |
|---|---|
| `vector` (default) | Meaning only, across languages. `score` is cosine similarity |
| `hybrid` | Meaning and keywords fused by rank (1.0 = first in both); see `vector_score` |
| `keyword` | Words only, stemmed per chunk language. `score` is `ts_rank_cd` |

`min_score` drops weak matches by meaning similarity (`score` in vector mode, `vector_score` in
hybrid mode). Omit `collections` to search all of the tenant's collections. `filters` match the
`metadata` sent at ingest exactly.
"""

IMAGE_SEARCH_DESCRIPTION = """
Finds images (uploaded images and video keyframes) by meaning, using CLIP vectors.

- **`application/json`**: describe the image in `query`, in any of about 50 languages.
- **`multipart/form-data`**: upload an `image` to find visually similar ones.

`score` is cosine similarity. Each result includes the image's generated `caption`.
Text inside images and captions is also searchable through `POST /v1/search`.
"""

TAGS = [
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "collections", "description": "Groups of documents within a tenant."},
    {"name": "ingest", "description": "Send text or files to be indexed."},
    {"name": "documents", "description": "Status, download and deletion of ingested content."},
    {"name": "search", "description": "Hybrid, vector and keyword retrieval."},
    {"name": "storage", "description": "Bring-your-own-bucket storage connections."},
    {"name": "api keys", "description": "Create, list and revoke your API keys."},
    {
        "name": "platform admin",
        "description": "Tenant management, authorized with the platform admin key.",
    },
]

SWAGGER_UI_PARAMETERS = {
    "persistAuthorization": True,
    "displayRequestDuration": True,
    "tryItOutEnabled": True,
    "docExpansion": "list",
    "defaultModelsExpandDepth": 0,
}


class ErrorResponse(BaseModel):
    detail: str


ERROR_DESCRIPTIONS = {
    status.HTTP_401_UNAUTHORIZED: "Missing, invalid, expired or revoked key",
    status.HTTP_403_FORBIDDEN: "The API key lacks the required scope",
    status.HTTP_404_NOT_FOUND: "Resource not found",
    status.HTTP_409_CONFLICT: "Conflicts with the current state",
    status.HTTP_413_CONTENT_TOO_LARGE: "Content exceeds the size limit",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Content type is not supported",
    status.HTTP_429_TOO_MANY_REQUESTS: "Rate limit exceeded; see Retry-After",
    status.HTTP_503_SERVICE_UNAVAILABLE: "A required service is not configured",
}


AUTHENTICATED_ERRORS = (
    status.HTTP_401_UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN,
    status.HTTP_429_TOO_MANY_REQUESTS,
)


def described(codes: tuple[int, ...]) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code]} for code in codes
    }


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return described((*AUTHENTICATED_ERRORS, *codes))


ADMIN_ERRORS = described(
    (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ),
)
