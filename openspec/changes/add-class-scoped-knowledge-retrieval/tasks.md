## 1. Retrieval Foundations and Configuration

- [ ] 1.1 Add pinned backend dependencies for PDF extraction, HTTP embedding calls, and SQLAlchemy pgvector support; verify a clean API environment installs successfully and imports each dependency.
- [ ] 1.2 Add validated retrieval settings for enablement, HTTPS provider URL in production, API key, `private`/`approved_external` data-boundary mode, model, fixed vector dimension, timeouts, batch size, query/result limits, extraction limits, retry bounds, and worker lease duration; verify configuration tests reject missing, placeholder, insecure, unauthorized-egress, or schema-incompatible values without echoing secrets.
- [ ] 1.3 Extend `.env.example` and server-only Compose environment wiring for retrieval settings while excluding embedding values from Vite build inputs; verify config inspection and the production frontend bundle contain no endpoint credential or authorization header.
- [ ] 1.4 Define retrieval status/error enums and evidence-only API schemas for material status, search mode, returned source count, provenance locators, optional section labels, and safe degradation/no-match codes; verify schema tests accept every specified state, reject mixed PDF-page/text-line locators, and expose no generated-answer field.

## 2. PostgreSQL Retrieval Schema

- [ ] 2.1 Extend SQLAlchemy models with composite material ownership and versioned search state, index version, chunk, and durable job entities from design D2; verify metadata tests assert unique keys, composite foreign keys, cascades, status checks, locator checks, and retry/lease fields.
- [ ] 2.2 Create an Alembic migration that pins/enables `vector` and `pg_trgm`, creates fixed-dimension vector and trigram/HNSW indexes, and adds retrieval tables without changing existing material rows; verify upgrade from the current head preserves existing data and schema inspection matches the models.
- [ ] 2.3 Implement repository primitives for idempotent state creation, job enqueue/claim/lease/retry, inactive version writes, atomic active-version switching, stale-version cleanup, and aggregate status counts; verify PostgreSQL tests cover duplicate enqueue, expired leases, rollback, and all-or-nothing activation.
- [ ] 2.4 Enforce source/class integrity at the database and repository layers so malformed, orphaned, cross-class, inactive-version, or non-ready-source chunks cannot be returned; verify fault-injection tests fail invalid writes and omit manually corrupted candidates.

## 3. Text Extraction, Normalization, and Chunking

- [ ] 3.1 Implement parser selection using content type, sanitized extension, and bounded signature checks for PDF, UTF-8 plain text, and Markdown; verify fixtures cover valid formats, spoofed metadata, invalid UTF-8/binary input, and unsupported files.
- [ ] 3.2 Implement bounded PDF extraction with one-based page provenance and explicit `no_extractable_text` handling without OCR; verify multi-page and image-only PDF tests preserve page boundaries and safe failure codes.
- [ ] 3.3 Implement UTF-8/BOM text and Markdown extraction with normalized line endings, one-based line provenance, and bounded nearest-section labels only when headings are parsed reliably; verify mixed Chinese/English fixtures retain correct line ranges/sections without rendering or executing markup.
- [ ] 3.4 Implement versioned Unicode normalization and overlapping chunking that never crosses page boundaries, honors line ranges, bounds optional section labels, and enforces page/character/chunk limits; verify deterministic unit tests cover boundaries, overlap, absent/unreliable headings, adversarial sizes, stable hashes, and bounded excerpts.

## 4. External Embedding Adapter and Degradation

- [ ] 4.1 Implement the narrow OpenAI-compatible embedding adapter with institution-private and explicitly approved-external boundary modes, bounded batches, timeouts, expected-dimension validation, model metadata, and sanitized exceptions; verify fake-provider tests cover private success, blocked unauthorized egress, approved external success, timeout, rate limit, 4xx/5xx, malformed JSON, wrong count, and wrong dimension.
- [ ] 4.2 Ensure provider request bodies, boundary configuration, endpoints, and authorization data are excluded from client responses, logs, health output, and CLI diagnostics; verify log-capture tests use sentinel secrets/content and find none in emitted output.
- [ ] 4.3 Implement a bounded semantic-query circuit breaker and safe `keyword_only` degradation mapping; verify repeated transient failures open the circuit, later recovery closes it, and no degraded path attempts a browser-side or unscoped provider call.
- [ ] 4.4 Add deterministic fake embeddings and provider fixtures for all automated tests so CI never contacts or bills a live service; verify the full backend test suite passes with outbound network access to embedding hosts blocked.

## 5. Durable Indexing Lifecycle

- [ ] 5.1 Enqueue or mark unsupported retrieval state when a material becomes ready, without changing upload/list/detail/download success semantics; verify API workflow tests cover supported, unsupported, and enqueue-failure recovery cases.
- [ ] 5.2 Implement the worker claim loop with `SKIP LOCKED`, leases, bounded exponential retry, graceful shutdown, and terminal safe errors; verify concurrent-worker tests process each desired source version once and reclaim expired work after interruption.
- [ ] 5.3 Implement source path containment plus size/SHA-256 verification before extraction, then build an inactive lexical/vector version and atomically activate it; verify fault injection at extraction, batch embedding, row write, and activation leaves either the prior complete version or one complete replacement.
- [ ] 5.4 Preserve keyword-searchable chunks when semantic indexing is transiently unavailable and schedule idempotent semantic completion without duplicate active chunks; verify outage/recovery tests transition from keyword-only to hybrid for the same material.
- [ ] 5.5 Implement reconciliation and `campusclaw retrieval backfill`, `reindex --material`, `status`, and `worker` commands; verify existing ready materials are discovered, repeated commands are idempotent, aggregate output contains no extracted text/secrets, and unsupported files are not repeatedly queued.

## 6. Class-Scoped Hybrid Search API

- [ ] 6.1 Implement lexical candidate retrieval using normalized trigram similarity plus the short-query fallback, with mandatory class, active-version, and ready-source predicates; verify mixed Chinese/English repository tests return only bounded same-class candidates in deterministic order.
- [ ] 6.2 Implement cosine semantic candidate retrieval with the same mandatory predicates and configurable bounded candidate pool; verify identical vectors/content placed in two classes never expose the other class in results or timing-visible error shapes.
- [ ] 6.3 Implement deterministic Reciprocal Rank Fusion, duplicate collapse, stable tie-breaking, bounded excerpts, and source hydration through `(material_id, class_id)`; verify unit/integration tests cover lexical-only, semantic-only, overlapping, tied, stale, and no-result candidates.
- [ ] 6.4 Add authenticated `GET /api/materials/search` with trimmed query validation, server result cap, supported-role access, `returned_count`, safe degraded/no-match metadata, PDF page/text line provenance, optional reliable section labels, no generated-answer fields, and no authoritative class parameter; verify question-shaped queries still return only sources plus 200/400/401 and forged-class cases against two-class fixtures.
- [ ] 6.5 Add retrieval status fields to material list/detail responses without changing existing field meaning or download behavior; verify old frontend/API assertions still pass and pending, processing, searchable, unsupported, and failed materials remain downloadable when otherwise authorized.

## 7. Materials Search Interface

- [ ] 7.1 Add a typed evidence-only frontend search client and state model that sends only query/limit, handles source counts plus hybrid/keyword-only responses, and treats excerpts as text; verify unit tests assert no class identifier, embedding endpoint, generated-answer/chat field, or raw HTML execution is introduced.
- [ ] 7.2 Add an accessible Chinese “讲义与检索” region with search form and live loading, validation, error, empty, and degraded notices to the existing materials page while preserving the ordinary material grid and teacher upload action; verify Testing Library keyboard and assistive-label scenarios for both teacher and student roles.
- [ ] 7.3 Render each source card with bounded excerpt, material title, original filename, one-based page or line locator, optional section label, retrieval mode, and existing authorized source/download action; verify component tests cover PDF/text provenance and omit unavailable/stale results.
- [ ] 7.4 Show an explicit current-class no-match message with query-refinement or teacher-upload guidance, without rendering an answer, assistant message, reasoning trace, model selector, or token statistics; verify zero-source component tests for teacher and student views.
- [ ] 7.5 Display pending, processing, searchable, unsupported, and failed status for each material without hiding its normal download action; verify visual/component tests cover every state on desktop and mobile layouts.

## 8. Compose, Health, Backup, and Documentation

- [ ] 8.1 Pin a pgvector-enabled PostgreSQL 16 image and add the internal `indexer` service with read-only material storage, retrieval settings, health/restart behavior, and no host port; verify `docker compose config` and published-port tests still expose only the web gateway.
- [ ] 8.2 Extend `/health` with extension/schema, worker freshness, queue, and recent semantic degradation signals without synchronously calling the provider; verify database/indexer incompatibility is operator-visible, provider outage is degraded rather than core-unhealthy, and no secrets/content appear.
- [ ] 8.3 Extend coordinated backup/restore and verification tooling for retrieval references, active-version completeness, model/dimension compatibility, and rebuild fallback; verify a restored fixture either retains valid hybrid retrieval or successfully rebuilds it from restored ready materials.
- [ ] 8.4 Update `README.md` and `docs/operations.md` to remove only the obsolete material/full-text/vector retrieval non-goals, while retaining explicit non-goals for question answering, intelligent chat, assignments, learning diagnosis, lesson/exercise generation, registration/password recovery, skill switches/MCP, multi-agent behavior, and knowledge graphs; document supported formats, no-OCR/evidence-only boundaries, selected endpoint data boundary, configuration, backfill/reindex/status commands, monitoring, rollback, and model-dimension migration, then verify documentation-consistency tests match current defaults and commands.
- [ ] 8.5 Update demo/production deployment examples and secret-handling guidance so semantic mode is explicit, institution-private endpoints are supported, approved external egress requires deliberate server-side configuration, and keyword fallback remains available; verify fresh demo and production configuration checks start without leaking or inventing provider credentials.

## 9. End-to-End Acceptance and Quality Gates

- [ ] 9.1 Add PostgreSQL-backed security scenarios with identical terms and vectors in two classes for teacher/student search, forged class input, no-class denial, stale-source omission, and indistinguishable empty results; verify both lexical and semantic branches enforce server-side class isolation.
- [ ] 9.2 Add Playwright scenarios through the published gateway for supported upload-to-search, source counts/cards, PDF page and text line provenance, optional section labels, explicit current-class no-match guidance, unsupported-file download, pending/failed states, keyboard operation, and source download; verify no generated-answer/chat UI appears and the suite observes no API/database/indexer host ports.
- [ ] 9.3 Add private-endpoint, blocked-unapproved-egress, approved-external, provider-outage, and recovery acceptance scenarios proving keyword-only search remains usable, the UI shows a safe degradation notice, queued semantic work recovers idempotently, and health/CLI output remains redacted.
- [ ] 9.4 Run backend format/lint/type/unit/integration coverage, frontend lint/type/unit/build, Alembic upgrade checks, Docker/Compose port checks, backup/restore verification, Playwright, and `openspec validate --changes --strict`; record exact passing commands and results before marking the change complete.
