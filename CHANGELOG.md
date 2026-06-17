# Changelog

All notable changes to **Modular RAG MCP Server** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### PDF Text-Layer Quality Checker (`src/libs/loader/pdf_quality_checker.py`)

New pre-ingestion check that detects low-quality PDFs (scanned, noisy, or sparse)
before they waste compute on meaningless chunks. Runs between `PdfLoader` and
`DocumentChunker` in the ingestion pipeline.

- **`PdfQualityChecker`** — samples the first N pages (default 3) and evaluates:
  - **Valid character ratio**: `valid_chars / total_chars` where valid = printable
    ASCII + whitespace + CJK + most other Unicode (excludes C0/DEL controls,
    C1 controls 0x80-0x9F, Unicode private use area 0xE000-0xF8FF, variation
    selectors).
  - **Text density**: `valid_chars / (sampled_pages * 3000)` — estimated chars
    vs theoretical page capacity.
  - **Scanned detection** (3 signals): valid_ratio < 10%, ALL sampled pages
    garbage-dominant (≥ 30% noise chars), or ≥ 80% of pages individually
    suspicious.
  - **Quality level**: `excellent` / `good` / `fair` / `poor` / `scanned`.
  - `recommendation` field with actionable Chinese-language message
    (`PASS` / `FAIL_SCAN` / `FAIL_NOISE` / `FAIL_DENSITY`).

- **`QualityReport`** / **`PageReport`** — structured reports with per-page
  breakdown (`is_suspicious`, `suspicion_reasons`).
- **`DocumentQualityError`** — raised when `fail_on_scanned=True` and a scanned
  PDF is detected; carries the full report for inspection.
- Two check interfaces: `check(path)` (re-parses PDF via PyMuPDF) and
  `check_text(pages)` (uses pre-extracted page texts — preferred for pipeline
  integration to avoid double-parsing).

#### Ingestion Pipeline

- **`src/ingestion/pipeline.py`** — new **Stage 2b: Quality Check** between
  `load` and `split`. Records a `quality_check` stage in trace context with
  full `QualityReport.to_dict()` for observability. Logged warnings surface
  when `is_poor_quality` is true, but the pipeline continues by default
  (use `quality_check.fail_on_scanned: true` to hard-fail).

#### Configuration

- **`config/settings.yaml`** — new `ingestion.quality_check` section:
  ```yaml
  ingestion:
    quality_check:
      enabled: true
      min_valid_ratio: 0.80
      min_text_density: 0.20
      check_first_n_pages: 3
      fail_on_scanned: false
  ```

#### Tests

- **`tests/unit/test_pdf_quality_checker.py`** — 47 unit tests covering all
  quality tiers, scanned/noise/density detection, character classification
  (whitelist/blacklist Unicode blocks), `DocumentQualityError` semantics, and
  end-to-end integration with a real PDF fixture.

#### Redis Caching Layer (`src/libs/redis/`)

New optional caching layer backed by Redis. Provides three independent cache types
with graceful degradation — when Redis is unavailable all caches become no-ops
so the rest of the codebase stays unaffected.

- **`src/libs/redis/client.py`**
  - `get_redis_client()` — thread-safe lazy singleton. Returns a real `redis.Redis`
    instance when `settings.redis.enabled=True` and a `Redis` server is reachable,
    or a `_DummyRedis` no-op stand-in otherwise.
  - `close_redis_client()` — pool cleanup helper for application shutdown.
  - `BaseCache` — thin base class providing key-building utilities and
    uniform error handling (all Redis failures are caught and logged as warnings).

- **`src/libs/redis/embedding_cache.py`** — `EmbeddingCache`
  - Key: `rag:embedding:<sha256(text)[:32]>`
  - TTL: `settings.redis.ttl.embedding` (default: 7 days)
  - Methods: `get()`, `set()`, `get_many()` (batch), `set_many()` (batch), `clear()`
  - Caches raw embedding vectors for repeated text, avoiding redundant API calls.

- **`src/libs/redis/llm_response_cache.py`** — `LLMResponseCache`
  - Key: `rag:llm:<sha256(prompt_template + "|||" + input_text)[:32]>`
  - TTL: `settings.redis.ttl.llm_response` (default: 1 day)
  - Methods: `get()`, `set()`, `get_metadata()`, `set_metadata()`, `invalidate()`, `clear()`
  - Caches LLM-generated refinement and enrichment results.

- **`src/libs/redis/session_memory.py`** — `SessionMemory`
  - Key: `rag:session:<session_id>` (Redis Hash)
  - TTL: `settings.redis.ttl.session` (default: 1 hour, sliding window)
  - Fields per session: `history`, `last_query`, `last_results`, `created_at`, `updated_at`
  - Methods: `get_or_create()`, `add_message()`, `get_history()`, `get_last_query()`,
    `set_last_query()`, `get_last_results()`, `set_last_results()`, `delete()`,
    `list_sessions()`

- **`src/libs/redis/factory.py`** — `CacheBundle`
  - `from_settings(Settings)` — creates all three cache instances wired to
    `settings.redis.ttl.*`, suitable for passing to `IngestionPipeline` or tools.

#### Configuration

- **`pyproject.toml`**
  - Added `redis>=5.0` to dependencies.

- **`config/settings.yaml`**
  - New `redis:` top-level section:

    ```yaml
    redis:
      enabled: true
      host: "localhost"
      port: 6379
      db: 0
      password: null
      ttl:
        embedding: 604800    # 7 days
        llm_response: 86400  # 1 day
        session: 3600        # 1 hour
    ```

- **`src/core/settings.py`**
  - New `RedisTTLSettings` and `RedisSettings` frozen dataclasses.
  - `Settings.redis: Optional[RedisSettings]` field.
  - `Settings.from_dict()` parses the `redis` section (all fields optional).
  - `validate_settings()` checks `redis.host` and `redis.port` range when enabled.

#### Ingestion Pipeline

- **`src/ingestion/embedding/dense_encoder.py`**
  - New constructor argument: `embedding_cache: Optional[EmbeddingCache]`
  - `set_embedding_cache()` setter for post-construction injection.
  - `encode()` now checks the cache before calling `embedding.embed()`.
    Misses are batched, encoded, then written back to the cache.
    Hit rate is transparent to callers — same return type and order.

- **`src/ingestion/transform/chunk_refiner.py`**
  - New constructor argument: `llm_cache: Optional[LLMResponseCache]`
  - `set_llm_cache()` setter.
  - `_llm_refine()` checks cache before calling the LLM API.
    Cache key = SHA256(prompt_template + `|||` + text).
    Result is stored on successful LLM response.

- **`src/ingestion/transform/metadata_enricher.py`**
  - New constructor argument: `llm_cache: Optional[LLMResponseCache]`
  - `set_llm_cache()` setter.
  - `_llm_enrich()` checks cache before calling the LLM API.
    Supports both raw string and structured dict (`get_metadata`/`set_metadata`) caching.

- **`src/ingestion/pipeline.py`**
  - `IngestionPipeline.__init__()` now creates a `CacheBundle` from settings
    and injects `EmbeddingCache` into `DenseEncoder`,
    `LLMResponseCache` into both `ChunkRefiner` and `MetadataEnricher`.

#### Query Path

- **`src/core/query_engine/dense_retriever.py`**
  - New constructor argument: `embedding_cache: Optional[EmbeddingCache]`
  - `set_embedding_cache()` setter.
  - `retrieve()` now checks cache before calling `embedding_client.embed()`.
    On miss, the query vector is cached for future identical queries.

- **`src/mcp_server/tools/query_knowledge_hub.py`**
  - New MCP tool parameter: `session_id: Optional[str]`
  - New constructor arguments: `session_memory`, `embedding_cache`
  - `execute()` accepts `session_id` and persists conversation turns to Redis:
    user query, assistant response, and retrieval results are stored per session.
  - Session history is returned via `SessionMemory` and can be used by downstream
    LLM calls to build context-aware answers (future enhancement).
  - `EmbeddingCache` is injected into `DenseRetriever` via `create_dense_retriever()`
    so repeated query strings bypass the embedding API.

### Changed

- `EmbeddingCache.get_many()`: fixed duplicate stat-counting bug in the hit/miss loop.
- `_DummyPipeline` (fallback when Redis is unavailable): corrected `execute()` to return
  one boolean per queued command instead of an empty list, ensuring batch operations
  degrade gracefully without errors.
- `QueryKnowledgeHubTool.execute()`: `session_id` is now recorded in the trace metadata.
