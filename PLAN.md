# iNterra RAG: Retrieval Service Plan

A multimodal ingest and retrieval API. Clients send data of any supported type, the service detects the type, processes it with the best-fit models, and stores it in Postgres with pgvector. Clients search with text or an image and get back ranked chunks. They feed those chunks into their own LLM.

Generation is out of scope. This service only stores and retrieves.

## Progress

| Phase | Scope | Status |
|---|---|---|
| 0 | Setup: Docker pgvector (PG18), project skeleton, settings, health checks, lint/type/test tooling | Done |
| 1 | Data model + migrations, including the multimodal fields | Done |
| 2 | Text ingestion: detect, clean, chunk, embed, store | Done |
| 3 | Search: vector, keyword, hybrid (RRF), filters | Done |
| 4 | Background worker + document files (PDF, DOCX, PPTX, XLSX, HTML) | Done. Two follow-ups: local S3 container (Docker Hub unreachable), and installing the `ocr` group |
| 5 | Images: OCR, captions, CLIP vectors, image-to-image search | Done |
| 6 | Audio and video: Whisper transcripts, keyframes | Done |
| 7 | Auth and tenancy: API keys, isolation tests, rate limits, platform admin API | Done |
| 8 | Evaluation: retrieval test sets across modalities | Pending |
| 9 | Hardening: observability, Docker images, AWS deployment | Pending |

## Decisions

| Topic | Decision |
|---|---|
| Language | Python 3.12, managed with uv |
| API | FastAPI (async) |
| Database | PostgreSQL 16+ with pgvector. Local: `pgvector/pgvector:pg18` in Docker on port 5434 |
| DB access | SQLAlchemy 2 (async) + asyncpg + Alembic |
| Text embeddings | `intfloat/multilingual-e5-base` (768 dimensions, about 100 languages), run with fastembed as a custom ONNX model (`onnx/model.onnx`). `query: ` and `passage: ` prefixes are applied automatically |
| Chunking | Token-aware with the model's own tokenizer. Up to 400 tokens with 60 tokens of overlap. Splits on paragraphs, then sentences, then words. Overlap carries whole sentences |
| Language detection | lingua (low-accuracy mode), per chunk. The document language is the most common chunk language |
| Authentication | `Authorization: Bearer rag_<prefix>_<secret>`. Only the prefix and an HMAC-SHA256 hash (keyed by `RAG_API_KEY_PEPPER`) are stored. Keys are shown once. Verified keys are cached for 60 s, `last_used_at` is written at most once a minute, and revocation and suspension clear the local cache immediately |
| Scopes | `search` (search and read), `ingest` (plus write), `admin` (plus storage connections and key management). Missing scope gives 403 |
| Rate limits | Redis fixed one-minute windows per key and bucket (`search` 60, `ingest` 30, `api` 120), overridable per tenant in `settings.rate_limits`. `X-RateLimit-*` headers, and 429 with `Retry-After`. Allows requests if Redis is down. Local Redis: WSL `redis://localhost:6379/5`, keys prefixed `rag:ratelimit:` |
| Platform admin | `/admin/tenants` with `RAG_PLATFORM_ADMIN_KEY`: create a tenant (returns its first admin key), list, get, suspend or reactivate, change rate limits, issue recovery keys. Disabled (503) when the key isn't set |
| Image embeddings | CLIP ViT-B/32 through fastembed ONNX (`Qdrant/clip-ViT-B-32-vision`, 512 dimensions). Text-to-image queries use `sentence-transformers/clip-ViT-B-32-multilingual-v1` (about 50 languages) |
| OCR | RapidOCR (ONNX) |
| Captions | Florence-2-base, native in transformers (`florence-community/Florence-2-base`), `<MORE_DETAILED_CAPTION>` |
| Transcription | faster-whisper (`small`, CPU int8 by default; `large-v3-turbo` with `RAG_WHISPER_DEVICE=cuda`). Lines are grouped into transcript chunks up to the chunk budget, keeping `start_ms` and `end_ms`. PyAV decodes audio and video, so no ffmpeg install is needed |
| Video | The audio track is transcribed. Keyframes are taken at most one per 10 s (max 60), decoding key frames only. Each keyframe gets a caption and OCR chunk at its timestamp, plus a CLIP vector in `media_vectors` |
| Media dependencies | Optional groups: `media` (torch, transformers, sentence-transformers, faster-whisper, av) and `ocr` (rapidocr). `./run.sh setup` installs all of them. Without them, media jobs retry with a clear 503-style error |
| Keyword search | Postgres full-text, with the text-search language chosen per chunk from the detected language |
| Ranking | Hybrid search fused with Reciprocal Rank Fusion (k = 60), in one SQL round trip. The hybrid score is normalized so 1.0 means ranked first by both vector and keyword. Each ranking pulls `max(top_k × 4, 40)` candidates, capped at 400 |
| Keyword matching | The query is parsed with every supported text-search language and OR-combined. Each chunk matches through its own language's stemming. Any term can match, and ranking uses `ts_rank_cd` |
| Vector scan | `hnsw.iterative_scan = relaxed_order` and `hnsw.ef_search` = candidates per query, so filtered searches still return enough results. On a 20k-chunk load test, the vector ranking used the HNSW index and took 1.3 ms |
| Queue | An interface. Postgres (`SKIP LOCKED`) locally, SQS on AWS |
| File storage | An interface. Local disk locally, S3 on AWS |
| Tenancy | Every row carries `tenant_id`, which comes from the API key. Internal data is its own tenant |
| Upload limits | 50 MB for documents and images, 1 GB for audio and video |
| File storage ownership | Bring your own bucket. Bucket chosen in order: collection's bucket → tenant default → platform bucket. Originals are always kept |
| Duplicates | Identical content in the same collection returns the existing document |
| Deletes | Hard delete, cascading to chunks, vectors, jobs and the stored file |
| API key scopes | `ingest`, `search`, `admin` |
| Code style | No comments, small typed functions, interfaces and registries, dependency injection. Enforced with ruff and mypy (strict) |
| Ingest flow | `/v1/ingest` takes JSON text or a multipart file. Type comes from magic bytes, then the declared type or extension, then a UTF-8 check. The original is stored first, then a job is queued in the same transaction as the document. Returns `queued` |
| Worker | `python -m app.workers --queue light\|media`. Jobs are claimed with `FOR UPDATE SKIP LOCKED`. Transient errors retry with exponential backoff (5 attempts, capped at 1 hour). Unreadable content fails at once. Stale running jobs are released or failed every minute |
| Extractors | PDF: pypdfium2, with OCR for pages under 20 characters. DOCX: headings as `##`, tables row by row. PPTX: slides plus speaker notes. XLSX: `Header: value` rows. HTML: trafilatura main content. OCR is RapidOCR in the optional `ocr` group (`uv sync --group ocr`) |
| Local development storage | `RAG_STORAGE_BACKEND=local` writes platform originals to `./storage` as `local://platform/<key>`, and downloads are streamed by the API. Client buckets (BYOB) are always S3 |
| Storage | `s3://bucket/key` URIs. Key = `tenant/collection/document/hash16/filename`. Downloads are 307 redirects to presigned URLs. Replacing a document deletes the old object. Credentials: AWS role assumption with an external ID, or Fernet-encrypted access keys (KMS later) |

## Data model

| Table | Holds | Key points |
|---|---|---|
| `tenants` | Clients and internal data owners | Every other table is scoped by `tenant_id` |
| `api_keys` | Hashed keys + scopes | Only the hash is stored. A key needs at least one known scope |
| `storage_connections` | Client buckets | `assume_role` needs a role ARN, `access_key` needs encrypted credentials. One default per tenant. Can't be deleted while in use |
| `collections` | Groups within a tenant | Optional bucket override |
| `documents` | One row per ingested item | Unique per collection by `external_id` and by `content_hash` |
| `chunks` | Searchable text | 768-dimension vector (HNSW, cosine). Generated `tsvector` (GIN). Metadata (GIN). Copies of tenant/collection for join-free search |
| `media_vectors` | CLIP vectors for images and keyframes | 512 dimensions (HNSW, cosine). Bucket inherited from its document |
| `jobs` | Processing queue | Partial index on pending jobs by queue, priority, run_after |

IDs are UUIDv7 generated in the app. `chunks` and `media_vectors` use bigint identity. Enum-like columns are `varchar(32)` with CHECK constraints, not Postgres ENUMs.

## API surface (v1)

```
POST   /v1/ingest                  one endpoint: JSON text or multipart file. Detects the type, then routes it
POST   /v1/storage-connections     connect a client bucket; it is verified straight away
GET    /v1/storage-connections     list (credentials are never returned)
POST   /v1/storage-connections/{id}/verify
DELETE /v1/storage-connections/{id}   refused while it is in use
PATCH  /v1/collections/{slug}      rename, or assign a storage connection
GET    /v1/documents/{id}          status: queued | processing | ready | failed
PUT    /v1/documents/{id}          replace content and re-process it
DELETE /v1/documents/{id}          remove the document and its chunks
GET    /v1/documents/{id}/file     original file
POST   /v1/collections             create a collection
GET    /v1/collections             list collections
POST   /v1/search                  text query. Modes: hybrid | vector | keyword. Takes filters
POST   /v1/search/images           JSON text description, or multipart image upload → similar images (with captions)
POST   /v1/api-keys                create a key (token shown once)
GET    /v1/api-keys                list keys
DELETE /v1/api-keys/{id}           revoke
POST   /admin/tenants              platform admin: create a tenant and its first admin key
GET    /admin/tenants[/{slug}]     platform admin: list or get tenants
PATCH  /admin/tenants/{slug}       platform admin: suspend, reactivate, rename, rate limits
POST   /admin/tenants/{slug}/api-keys  platform admin: recovery key
GET    /health/live
GET    /health/ready
```

## Routing by detected type

| Type | Pipeline |
|---|---|
| Text, Markdown, JSON, CSV | clean → chunk → embed |
| PDF with a text layer | extract per page → chunk → embed |
| Scanned PDF | render pages → OCR → chunk → embed |
| DOCX, PPTX, XLSX, HTML | extract → chunk → embed |
| Image | OCR + caption → embed text. CLIP vector for image similarity |
| Audio | Whisper transcript with timestamps → chunk by segment → embed |
| Video | ffmpeg: audio → audio pipeline, keyframes → image pipeline |

## Scaling

- A stateless API that scales out horizontally. Heavy work never runs inside a request.
- Separate worker pools: light (CPU: text and documents) and media (GPU: image, audio, video). They scale on queue depth, and the media pool can drop to zero.
- Models load once per worker, and embedding runs in batches.
- Content hashes mean the same content is never processed twice. Idempotency keys make client retries safe.
- Pooled connections (PgBouncer or RDS Proxy), HNSW indexes, and `chunks` ready to be partitioned by tenant.
- Uploads stream to storage. Production uses presigned S3 uploads.

## Hardware

Local minimum: 8 cores, 16 GB RAM (32 GB recommended), 30 GB disk. A GPU is optional.

AWS minimum:

| Component | Service | Size |
|---|---|---|
| API | ECS Fargate | 2 × 1 vCPU / 2 GB |
| Light worker | ECS | c7i.xlarge |
| Media worker | EC2 GPU | g4dn.xlarge (T4). Move to g5.xlarge under load |
| Database | RDS PostgreSQL 16+ | db.r7g.large |
| Files / queue | S3 / SQS | |

## Running locally

Swagger UI is at http://127.0.0.1:8000/docs and ReDoc at `/redoc`. Create a tenant with `./run.sh tenant acme "Acme Ltd"`, then click **Authorize** and paste the printed key into **ApiKey**. Uploads only become `ready` while a worker is running. Locally, originals are written to `./storage` (`RAG_STORAGE_BACKEND=local`). Set `RAG_STORAGE_BACKEND=s3` for S3.

Use `./run.sh` from Git Bash (`./run.sh help` lists every command):

```
./run.sh setup                     first run: dependencies, .env, database, migrations
./run.sh tenant acme "Acme Ltd"    create a tenant
./run.sh start                     database + migrations + API + worker; Ctrl+C stops all
./run.sh check                     lint, format, types and tests
```

The individual commands, if you need them:

```
docker compose up -d
uv sync
uv run alembic upgrade head
uv run python -m app.cli create-tenant acme "Acme Ltd"
uv run uvicorn app.main:app --reload
uv run python -m app.workers --queue light
uv run pytest
uv run pytest -m model
uv run ruff check .
uv run mypy app
```
