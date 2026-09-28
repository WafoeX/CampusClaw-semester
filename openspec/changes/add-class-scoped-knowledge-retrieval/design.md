## Context

See `proposal.md` for motivation and `specs/materials/knowledge-retrieval/spec.md` for the behavioral contract.

The current system is a same-origin React + FastAPI application backed by PostgreSQL 16. Uploaded bytes live on the `materials-data` volume; relational metadata and sessions live in PostgreSQL. `MaterialRepository` already requires the caller's `class_id` for every read, and `/api/materials` derives that value from the authenticated principal. Files become visible only in the `ready` state, and downloads verify size and SHA-256 before serving bytes.

There is no content parser, search schema, queue, or vector dependency today. The API is the only long-running backend service, Compose publishes only the Nginx gateway, and coordinated database/material backups are an existing operational invariant. `README.md` and `docs/operations.md` currently identify parsing and search as explicit non-goals, so implementation must update those statements rather than silently contradicting them.

The selected scope is end-to-end search for PDF, plain text, and Markdown, with mixed keyword/vector retrieval, evidence-oriented source cards, and a server-configured OpenAI-compatible embedding API. The user experience adopts a dedicated “讲义与检索” region, explicit source counts, page/line provenance, optional reliable section labels, and a clear current-class no-match state. It does not introduce subject partitioning because the current domain model and this change are class-scoped. The implementation must preserve existing upload/list/download compatibility and must never make the embedding service or browser an authorization boundary.

## Goals / Non-Goals

**Goals:**

- Keep every extraction job, lexical candidate, vector candidate, hydrated result, and source link bound to the authenticated user's class.
- Add durable, retryable indexing without making material upload or download depend on external embedding latency.
- Support mixed Chinese and English course content and provide page/line provenance plus optional reliably extracted section labels.
- Return inspectable source evidence and a source count without generating answers or teaching content.
- Keep keyword search usable when semantic embedding is unavailable or external data egress is not approved.
- Allow the embedding endpoint to be institution-private while retaining an explicitly approved external mode.
- Reuse PostgreSQL as the authoritative retrieval store so class ownership, source integrity, backup, and restore remain coordinated.
- Make the rollout safe for existing ready materials and reversible without deleting original uploads.

**Non-Goals:**

- OCR for scanned/image-only PDFs, Office document parsing, image/audio/video transcription, or archive expansion.
- Answer generation, RAG synthesis, chat, direct question answering, solution generation, query rewriting, generative reranking, or citations not grounded in stored chunks.
- Assignment submission or grading, learning analytics/diagnosis, lesson-plan generation, exercise generation, classroom interaction, or teaching recommendations.
- Skill switches, custom skills, MCP integration, multi-agent orchestration, model-management UI, token accounting, or knowledge graphs.
- Subject/campus knowledge-base partitioning, cross-class search, teacher access to multiple classes, shared/global corpora, or client-selected class scope.
- Inline rendering of uploaded files; source access continues through the existing attachment download behavior.
- A general workflow platform or externally exposed queue/vector service.

## Decisions

### D1. Keep lexical and vector indexes in PostgreSQL with pgvector

Use PostgreSQL 16 with the `vector` and `pg_trgm` extensions. Replace the current `postgres:16-alpine` image with a pinned pgvector-enabled PostgreSQL 16 image, while retaining the same internal-only network and named volume. Store embeddings beside chunk provenance and relational ownership rather than introducing a separate vector database.

Lexical retrieval will use normalized chunk text plus a GIN trigram index. Trigrams work for mixed Chinese/English substring matching without requiring a language-specific tokenizer or a second search engine. Semantic retrieval will use a pgvector HNSW index with cosine distance. Both candidate queries include `class_id`, active index version, and ready-material predicates before ranking.

A separate Qdrant service was considered. It offers mature vector filtering, but would add another persistent service, another backup/restore unit, duplicated class/material metadata, and a cross-store consistency protocol. Elasticsearch/OpenSearch was rejected for the same operational reasons and is excessive for the expected course-scale corpus. PostgreSQL full-text search alone was rejected because it does not provide semantic recall and its default tokenization is weak for unsegmented Chinese. Application-only in-memory vectors were rejected because they are not durable or suitable for multi-process reads.

### D2. Add versioned retrieval rows with database-enforced source ownership

Add the following relational structures through Alembic:

- `material_search_states`: one row per material with `material_id`, `class_id`, lifecycle status, active version, attempt count, safe error code, timestamps, and next retry time.
- `material_index_versions`: immutable build records containing source SHA-256, extraction format/version, embedding model, vector dimension, chunking version, build status, and completion time.
- `material_chunks`: versioned chunks containing `material_id`, `class_id`, ordinal, bounded text, text SHA-256, page number or line range, an optional reliably parsed section label, lexical search text, and nullable fixed-dimension embedding.
- `material_index_jobs`: a durable unique job per material/desired source version with state, lease owner/expiry, attempts, and next retry time.

Add a unique `(id, class_id)` key on `materials` and use composite foreign keys from retrieval state/version/chunk rows to prevent a material/class mismatch. Jobs cascade with their source. Database constraints enforce one locator family per chunk: PDF chunks have a one-based page and no line range; text/Markdown chunks have a valid one-based line range and no page.

The embedding column uses a fixed dimension selected for the deployed model (default 1536 for the initial OpenAI-compatible model contract). The configured dimension must match the migration/schema value. Changing dimensions is an explicit migration and full reindex, not a runtime toggle. Every version stores model and extraction/chunking identifiers so stale versions can be detected.

An unversioned chunk table was rejected because reindexing could expose a partial mixture of old and new chunks. Storing only a page number on all formats was rejected because line ranges provide more actionable text provenance.

### D3. Use a durable internal index worker rather than indexing inside upload requests

Add an `indexer` Compose service using the API image and a `campusclaw retrieval worker` command. It has internal database access, a read-only mount of `materials-data`, embedding configuration, and no published or exposed port. The API enqueues a durable job after a supported material becomes ready. A periodic reconciliation query also discovers ready supported materials with no state or a stale source hash, closing the crash window between material readiness and enqueue.

Workers claim jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, write a lease, and use bounded retries with exponential backoff and a terminal failed state. Even though the initial deployment runs one worker, leases and idempotency prevent duplicate publication after restarts. The worker verifies the source path containment, byte size, and SHA-256 before extraction.

For each job it builds a new inactive version, extracts and chunks text, writes lexical chunks, requests embeddings in bounded batches, and activates the version in one transaction only after all required rows are consistent. The previous active version remains searchable until the replacement activates, then is deleted asynchronously. If embedding fails transiently, the worker publishes the lexical version with nullable vectors, records semantic work as retrying, and later fills a replacement semantic-complete version. It never mutates an active version in place.

FastAPI `BackgroundTasks` was rejected because work would be lost on process restart and could run more than once across workers. Synchronous upload-time indexing was rejected because PDF parsing and an external network call would increase upload latency and make successful material storage depend on provider availability. Introducing Redis/Celery was rejected because PostgreSQL already provides the durability and locking needed at this scale.

### D4. Extract bounded text while preserving provenance

Use `pypdf` for page-oriented PDF text extraction. OCR is not attempted; an image-only or otherwise textless PDF receives the safe `no_extractable_text` failure code. Decode plain text and Markdown as UTF-8 with BOM handling, normalize line endings, and reject binary/invalid text with a safe extraction error. Content-type, sanitized filename extension, and a lightweight signature check must agree sufficiently to select a parser; client media type alone is not authoritative.

Normalize Unicode and whitespace for retrieval without changing the original file. Split within provenance boundaries into approximately 800 Unicode characters with approximately 120 characters of overlap and a hard maximum chunk size. PDF chunks never span pages. Text/Markdown chunks preserve one-based start/end lines. Markdown headings and parser-provided document outlines may populate an optional bounded `section_label` only when their association with the chunk is reliable; page or line locators remain authoritative when no reliable label exists. Excerpts are generated from stored bounded chunk text, not by reopening arbitrary client paths.

Parser and chunker versions are persisted. Limits cover maximum pages, maximum extracted characters, per-chunk size, section-label length, and total chunks per material so a small compressed or adversarial file cannot create unbounded CPU, database, or embedding cost.

A single whole-file chunk was rejected because relevance and provenance would be poor and provider limits could be exceeded. Parsing in the browser was rejected because it would expose raw material handling to an untrusted client and duplicate the authorization boundary.

### D5. Use a server-configured OpenAI-compatible embedding adapter with explicit data-boundary controls

Implement one narrow adapter for an OpenAI-compatible embeddings endpoint. Configuration includes:

- `EMBEDDING_ENABLED`
- `EMBEDDING_BASE_URL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_DATA_BOUNDARY` (`private` or `approved_external`)
- `EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `EMBEDDING_TIMEOUT_SECONDS`
- `EMBEDDING_BATCH_SIZE`

Only the API/indexer environment receives these values; none are Vite build variables. The endpoint may be an institution-controlled private service or an approved external service. Production requires an HTTPS base URL and non-placeholder credentials when semantic mode is enabled; internal TLS may use an explicitly configured institutional CA. `approved_external` must be selected explicitly before content may leave the approved private boundary. Startup validates endpoint mode, model, and dimension configuration but does not require a successful provider call, allowing keyword-only degraded startup during an outage or when external egress is not approved. Provider calls have connection/read timeouts, bounded batches, sanitized logs, and no automatic logging of request bodies or authorization headers.

Indexing sends only bounded extracted chunks and query-time search sends only the user's bounded query. Operations documentation must distinguish private-network processing from approved external processing, state what text crosses the selected boundary, and require an institution-approved provider/data-processing policy for external mode. The UI reports semantic availability but never provider identity, raw errors, endpoints, credentials, or boundary configuration.

A provider-specific SDK was rejected to keep the integration replaceable and configuration small. Supporting multiple adapters in this change was rejected as unnecessary scope; a second provider can implement the same internal interface later. Local model inference was rejected because the user selected a configurable external service and because it would materially increase image size and runtime memory.

### D6. Expose one additive class-scoped search API and additive material status fields

Add:

- `GET /api/materials/search?q=<query>&limit=<n>` for authenticated teachers and students.

The route trims and validates `q`, enforces a conservative maximum query length and maximum result count, and ignores/rejects any class selector. It derives `class_id` from the existing principal. A response contains `retrieval_mode` (`hybrid` or `keyword_only`), `returned_count`, an optional safe degradation/no-match code, and source records with material identifier/title/original filename, excerpt, page or line locator, optional reliable section label, source URL fields, and rank-derived relevance information. It has no generated `answer`, explanation, solution, summary, recommendation, or chat trace field. Exact raw vector distances are not an API compatibility promise.

The lexical branch retrieves a bounded candidate pool by trigram similarity (with a short-query substring fallback). If query embedding succeeds and vectors exist, the semantic branch retrieves a bounded cosine candidate pool. Merge candidates with Reciprocal Rank Fusion using a fixed documented constant, then sort by fused score followed by stable material/chunk identifiers. Hydration re-joins `materials` using both `material_id` and `class_id` and requires `materials.state = ready`; stale candidates are dropped.

Existing material list/detail response models gain additive retrieval status fields so the current materials page can show pending, processing, searchable, unsupported, or failed. Existing clients that ignore unknown JSON fields remain compatible. Search uses GET because it is read-only and the bounded query is not sensitive enough to require request-body semantics; server access logs must still avoid logging full query strings in production.

A single global search endpoint accepting `class_id` was rejected because it invites scope confusion. Returning chunk IDs as source authority was rejected; source authorization always resolves through the material and class relation.

### D7. Degrade semantic retrieval without weakening authorization or provenance

Wrap query embedding calls in a small circuit breaker. On timeout, rate limit, provider 5xx, malformed response, or open circuit, skip the semantic branch and return lexical results with `retrieval_mode = keyword_only` and a safe reason such as `semantic_temporarily_unavailable`. Authentication, class predicates, result limits, source hydration, and provenance rules are identical in degraded mode.

Do not fall back to unscoped cached results, a global vector query, or browser-side provider calls. Provider 4xx caused by invalid deployment configuration are operator-visible and keep semantic mode degraded until corrected. A missing vector on some chunks does not remove those chunks from lexical retrieval.

Returning HTTP 503 for every provider outage was rejected because an independently durable keyword index can still satisfy the core search request. Silently degrading was rejected because users and operators need to understand why semantic matches may be absent.

### D8. Integrate search into the existing materials page

Extend the current authenticated materials page rather than creating a separate navigation subsystem. Add a dedicated “讲义与检索” region with a labeled Chinese query field and submit button, preserve the ordinary material grid and teacher upload action, and render a source-card region with live loading/status announcements. Each result shows a bounded excerpt, title, filename, page or line locator, optional section label, retrieval-mode notice, and the existing authorized metadata/download action. A zero-source response states that the current class has no related material and suggests refining the query or having a teacher upload relevant material.

The frontend sends only query and limit, never class scope or embedding credentials. It renders server-provided excerpts as text, not HTML, and it does not render an assistant message, generated answer, chat composer, reasoning trace, or model/token controls. Search state is URL-query synchronized only if the query is encoded safely; full excerpts are never placed in the URL. Tests use role-aware mocked APIs and Playwright against the gateway.

Replacing the material list with search results was rejected because unsupported or not-yet-indexed files must remain discoverable for ordinary download. Inline PDF rendering and page deep links were rejected because the existing security posture forces attachment download; the UI displays the page number for manual source navigation.

### D9. Treat retrieval data as rebuildable but operationally coordinated

Alembic enables extensions and creates retrieval tables/indexes. Backups continue to capture PostgreSQL plus the material volume; vector and lexical indexes are included in the database dump, while source files remain the rebuild authority. Add CLI commands:

- `campusclaw retrieval backfill` to idempotently enqueue missing/stale supported materials.
- `campusclaw retrieval reindex --material <id>` for targeted rebuild.
- `campusclaw retrieval status` for aggregate safe counts and configuration compatibility.
- `campusclaw retrieval worker` for the long-running indexer.

`/health` checks database extension/schema readiness and reports recent retrieval/worker state. It does not call the external provider on every health request; it reports provider degradation from recent bounded adapter outcomes. Provider outage does not make the core application unhealthy, while missing extensions, incompatible vector dimensions, or a stale worker beyond a documented threshold are operator-visible.

Backup verification checks composite references, source readiness, active-version completeness, and source hashes without printing chunk text. Restore may discard/rebuild retrieval tables if vector/index compatibility is uncertain, because original ready materials remain authoritative.

### D10. Test security boundaries before ranking quality

Backend unit tests cover parser selection, PDF page/text line provenance, optional section-label reliability, chunk limits, provider boundary validation/redaction, dimension validation, retries, circuit breaking, evidence-only response schemas, and deterministic fusion. PostgreSQL integration tests cover migrations/extensions, composite ownership constraints, job leasing/idempotency, atomic version activation, class predicates in both retrieval branches, stale-source omission, degraded keyword fallback, and backfill.

API tests use two classes with deliberately identical terms and vectors to prove that neither lexical nor semantic search leaks cross-class results. They also cover invalid queries, result caps, both roles, no-class denial, safe errors, and existing API compatibility. Frontend tests cover form accessibility, source cards/counts/locators, optional section labels, explicit current-class no-match guidance, absence of generated-answer/chat controls, state badges, degraded/error states, and preserved downloads. Compose/Playwright tests verify that the indexer and database remain internal, that an uploaded supported document becomes searchable, that unsupported files remain downloadable, and that provider outage yields keyword-only results.

Ranking quality tests use a small deterministic fixture corpus and a fake embedding adapter; CI never calls a paid or live provider. A separately documented opt-in smoke test may exercise a real configured provider without logging content or credentials.

## Risks / Trade-offs

- **[Approved external mode sends course text and search queries outside the private boundary]** → Prefer institution-private endpoints, require explicit `approved_external` configuration and approved data handling for external mode, use HTTPS, bound payloads, redact logs, and document the selected boundary.
- **[pgvector image adoption changes the database runtime image]** → Pin PostgreSQL major and image digest/tag, back up before rollout, test `pg_dump`/`pg_restore`, and verify extensions before starting the indexer.
- **[Approximate vector search with a class filter can under-return candidates]** → Keep bounded lexical recall, tune HNSW search parameters, test per-class fixtures, and permit exact vector scan below a documented corpus threshold if measurements justify it.
- **[Trigram lexical ranking is less linguistically precise than a dedicated analyzer]** → Fuse it with semantic recall, normalize Unicode, retain excerpts, and record evaluation fixtures before considering a dedicated search engine.
- **[External rate limits or costs can delay indexing]** → Batch requests, cap material/query sizes, deduplicate by hashes, apply retries/circuit breaking, and expose queue counts without blocking keyword search.
- **[PDF extraction quality varies]** → Preserve page provenance, fail explicitly when no text is extractable, do not claim OCR support, and keep original downloads available.
- **[Chunk text duplicates sensitive material inside PostgreSQL]** → Apply the same database access controls and backups as material metadata, never expose chunk-management endpoints, return bounded excerpts only, and document retention/rebuild behavior.
- **[Schema-fixed vector dimensions make model changes operational]** → Treat model/dimension as versioned deployment configuration and require migration plus full reindex for dimension changes.
- **[Worker lag makes new uploads temporarily unsearchable]** → Show explicit states, monitor queue age, use durable jobs and reconciliation, and preserve normal material access.
- **[Database and source volume can be restored from mismatched points]** → Keep coordinated backup procedures, validate source hashes and active versions after restore, and rebuild retrieval data when consistency is uncertain.

## Migration Plan

1. Take and verify a coordinated PostgreSQL/material-volume backup. Record current PostgreSQL major version and Alembic head.
2. Build the API image with extraction, provider, pgvector client, CLI, and worker dependencies. Switch the database service to the pinned pgvector-enabled PostgreSQL 16 image without changing the data volume or publishing a port.
3. Run migration in staging to enable `vector`/`pg_trgm`, add composite material ownership constraints, retrieval tables, and indexes. Verify existing login, material list, upload, metadata, and download paths before enabling indexing.
4. Deploy the API/web changes with semantic mode disabled or with a fake/staging provider. Start one internal indexer and verify health, queue leases, class isolation, unsupported formats, keyword retrieval, and provenance.
5. Configure an institution-private endpoint where available; otherwise explicitly select the approved-external boundary mode and configure its endpoint, key, model, and schema-compatible dimension only in API/indexer server environments. Verify boundary validation, redaction, and semantic health, then enable semantic indexing.
6. Run `campusclaw retrieval backfill` for existing supported ready materials. Monitor aggregate pending/retrying/failed counts and sample source locators without printing extracted content.
7. Run backend, frontend, migration, Compose, backup/restore, and Playwright acceptance suites, including provider-outage and cross-class collision scenarios. Update README and operations scope/privacy guidance before release.

Rollback stops the indexer first, disables semantic mode, and returns API/web to the previous images. Additive retrieval tables can remain unused while existing material behavior continues. If the database runtime image must also roll back, restore the pre-change coordinated backup to a compatible PostgreSQL 16 image; do not reuse a data directory across unverified image variants. Original material files are never deleted by retrieval rollback.
