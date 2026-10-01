## 1. Retrieval and LLM Foundations

- [x] 1.1 Add pinned backend dependencies for PDF extraction, OpenAI-compatible embedding/generation calls, PostgreSQL keyword retrieval, and Qdrant; verify a clean backend environment installs and imports each dependency.
- [x] 1.2 Add validated server-only embedding settings for endpoint, key, data boundary, model, dimension, timeout, batch size, and retry bounds; verify tests reject insecure, unauthorized-egress, missing, or incompatible values without echoing secrets.
- [x] 1.3 Add independent server-only generation settings for endpoint, key, data boundary, model, temperature, timeout, output-token limit, evidence budget, structured-output capability, and prompt version; verify invalid production settings fail closed without exposing values.
- [x] 1.4 Add validated Qdrant, query, candidate, result, extraction, worker-lease, and rate-limit settings; verify vector dimension/distance compatibility and bounded limits.
- [x] 1.5 Extend `.env.example` and Compose wiring while excluding all provider and Qdrant credentials from frontend inputs; verify configuration inspection and production bundles contain no secret, authorization header, or hidden prompt.
- [x] 1.6 Define API schemas for single-turn questions, `keyword`/`vector`/`hybrid` retrieval, answered/refused/error states, inline citations, source records, safe degradation, exact refusal `根据本班资料无法回答该问题`, and retryable generation failures; verify omitted mode defaults to `hybrid` and no reasoning-trace field exists.

## 2. PostgreSQL Retrieval Schema and Keyword Index

- [x] 2.1 Add PostgreSQL SQLAlchemy models and Alembic migrations for composite material ownership, `material_search_states`, `material_index_versions`, `knowledge_chunks`, and `material_index_jobs`; verify keys, foreign keys, cascades, locator constraints, retry/lease fields, and existing material preservation.
- [x] 2.2 Define `knowledge_chunks.id` with a stable representation accepted unchanged as a Qdrant point ID; store bounded original text, keyword-search data, source/class/version identifiers, hash, ordinal, page or line locator, and optional section label; verify PostgreSQL has no vector column or point-ID translation table.
- [x] 2.3 Add normalized search text with a `pg_trgm` GIN index for Chinese/mixed-language substring matching and optional PostgreSQL full-text ranking for tokenizable terms; verify every keyword candidate contains matched text under documented normalization and semantic paraphrases alone do not match.
- [x] 2.4 Implement repository primitives for idempotent state creation, job enqueue/claim/lease/retry, inactive version writes, atomic active-version switching, stale-version cleanup, and aggregate counts; verify duplicate enqueue, expired leases, rollback, and all-or-nothing visibility.
- [x] 2.5 Enforce source/class integrity so malformed, orphaned, cross-class, inactive-version, or non-ready chunks cannot be retrieved or supplied to generation; verify fault-injection tests reject invalid writes and hydration omits invalid rows.

## 3. Qdrant Vector Collection and Reconciliation

- [x] 3.1 Add an internal Qdrant service and create a pinned collection whose dimension and distance match embedding configuration; verify persistent storage, health checks, optional server-only credentials, and no published host port.
- [x] 3.2 Implement vector upsert with point ID exactly equal to `knowledge_chunks.id` and payload limited to necessary class/material/version identifiers; verify tests reject or detect text, excerpts, titles, filenames, questions, answers, credentials, and provider bodies in payloads.
- [x] 3.3 Implement class-filtered Qdrant search followed by batched same-ID PostgreSQL hydration and active-version, ready-source, authorization checks; verify missing, stale, inactive, orphaned, and cross-class points never become evidence.
- [x] 3.4 Implement idempotent reconciliation for expected, missing, orphaned, stale, and incompatible points; verify it repairs derived vector state without changing authoritative chunk text or weakening authorization.

## 4. Text Extraction, Normalization, and Durable Indexing

- [x] 4.1 Implement parser selection using content type, sanitized extension, and bounded signature checks for PDF, UTF-8 text, and Markdown; verify valid, spoofed, invalid UTF-8/binary, and unsupported fixtures.
- [x] 4.2 Implement bounded PDF extraction with one-based page provenance and explicit `no_extractable_text` handling without OCR; verify multi-page and image-only fixtures preserve page boundaries and safe error codes.
- [x] 4.3 Implement UTF-8/BOM text and Markdown extraction with normalized line endings, one-based line provenance, and bounded section labels only when reliable; verify mixed Chinese/English fixtures retain original text and do not execute markup.
- [x] 4.4 Implement deterministic versioned chunking that never crosses page boundaries, honors line ranges, bounds overlap/labels/pages/characters/chunks, and persists authoritative text only in PostgreSQL; verify boundaries, hashes, excerpts, and limits.
- [x] 4.5 Enqueue or mark unsupported retrieval state when a material becomes ready without changing upload/list/detail/download behavior; verify supported, unsupported, and enqueue-recovery cases.
- [x] 4.6 Implement the worker claim loop with PostgreSQL row locking, leases, bounded retry, graceful shutdown, source path/hash verification, and safe terminal errors; verify concurrent workers process each desired source version once and reclaim expired work.
- [x] 4.7 Implement publication in this order: inactive PostgreSQL version/chunks, bounded embeddings, same-ID Qdrant upsert, expected-point verification, then atomic PostgreSQL activation; verify injected failures expose only the prior complete version or no replacement.
- [x] 4.8 Preserve keyword-searchable chunks during transient semantic failure and schedule idempotent vector completion; verify recovery creates same-ID points without duplicate active chunks.
- [x] 4.9 Implement idempotent backfill, targeted reindex, aggregate status, worker, reconciliation, and vector-rebuild commands; verify repeated runs and output redaction.

## 5. Deterministic Class-Scoped Retrieval

- [x] 5.1 Implement bounded PostgreSQL keyword retrieval with mandatory session class, active-version, and ready-source predicates; verify deterministic mixed Chinese/English same-class ranking.
- [x] 5.2 Implement bounded vector retrieval by embedding the question, filtering Qdrant by session class, and hydrating IDs from PostgreSQL; verify semantic paraphrases may match and no unhydrated point is returned.
- [x] 5.3 Implement deterministic RRF for hybrid mode with independent lists, duplicate collapse, documented constant, stable tie-breakers, authorization hydration, and final cap; verify keyword-only, vector-only, overlap, tie, stale, and empty fixtures.
- [x] 5.4 Validate question length, result caps, and `keyword`/`vector`/`hybrid` mode; default omitted mode to `hybrid` and verify invalid requests invoke neither retrieval nor models.
- [x] 5.5 Read class scope only from the authenticated login session and reject or ignore every request class value as non-authoritative; verify query/header/path/body variants never alter PostgreSQL predicates, Qdrant filters, evidence, citations, response shape, or timing-visible authorization behavior.
- [x] 5.6 Add a bounded vector-dependency circuit breaker: hybrid may report `keyword_only`, while explicit vector mode must return vector-unavailable; verify no failure path performs global retrieval, trusts client class scope, or invokes providers from the browser.

## 6. Evidence Assembly and Prompt-Injection Boundary

- [x] 6.1 Build a deterministic evidence selector using retrieval rank, chunk-count cap, per-item limit, and total token/character budget; verify stable selection and that every chosen chunk is reauthorized immediately before use.
- [x] 6.2 Assign request-local opaque source IDs only after authorization and serialize bounded question/evidence as untrusted data separate from backend-owned system policy; verify model input excludes class IDs, storage paths, download URLs, credentials, and unrelated metadata.
- [x] 6.3 Implement a versioned system prompt requiring evidence-only answering, exact insufficient-evidence status, citation of factual claims, no hidden reasoning, and refusal to follow instructions inside questions or documents; verify snapshot tests cover the complete policy.
- [x] 6.4 Add adversarial fixtures containing “ignore prior rules”, role changes, secret requests, cross-class requests, fake tool calls, HTML/Markdown/scripts, and fabricated source IDs; verify none can alter class scope, policy, schema, tool availability, or citation rules.
- [x] 6.5 Ensure prompts, questions, evidence, answers, endpoint details, boundary settings, authorization data, and credentials are absent from routine logs, health output, CLI diagnostics, traces, and client errors; verify sentinel-content and sentinel-secret capture tests.

## 7. Grounded Generation and Citation Validation

- [x] 7.1 Implement the OpenAI-compatible generation adapter with private and explicitly approved-external modes, bounded request/output sizes, low-variance settings, timeouts, retry classification, structured-output support, and sanitized exceptions; verify fake-provider success, blocked egress, timeout, rate limit, 4xx/5xx, malformed, and oversized responses.
- [x] 7.2 Define and parse structured model output containing only `answered` or `insufficient_evidence`, bounded answer text, and source IDs; verify unknown fields, hidden reasoning fields, malformed status, executable markup, and overlong output are rejected or sanitized according to contract.
- [x] 7.3 Validate consistency between inline citations and the declared citation list, require at least one authorized citation for an answered result, and resolve citations only from the current request's evidence map; verify unknown, duplicate, stale, removed, cross-class, and uncited-answer cases never reach clients.
- [x] 7.4 Implement at most one bounded output-repair attempt using the same authorized evidence and no new retrieval; verify repair success is revalidated and repair failure returns `generation_invalid` without raw model text.
- [x] 7.5 Skip generation when no valid evidence remains and normalize retrieval-empty, topically insufficient, and model-declared insufficient cases to HTTP 200 with exact answer `根据本班资料无法回答该问题` and zero sources; verify other-class-only evidence is indistinguishable from ordinary insufficiency.
- [x] 7.6 Return a grounded answer only with validated source records containing material ID/title/original filename, bounded excerpt, page or line locator, optional reliable section, and authorized source action; verify every returned citation resolves and every source remains authorized at response completion.
- [x] 7.7 Return safe retryable `answer_generation_unavailable` or `generation_invalid` outcomes when generation fails; verify retrieval excerpts are not mislabeled as answers and provider details or invalid output are not exposed.
- [x] 7.8 Add deterministic groundedness contract fixtures for supported answers, model-memory bait, weak evidence, conflicting evidence, prompt injection, invalid citations, source removal during generation, timeout, and repair failure; verify CI uses no live or paid provider.

## 8. Single-Turn Knowledge-Base Q&A Interface

- [x] 8.1 Add a typed frontend client/state model that sends only question, result limit, and optional retrieval mode; default to `hybrid`; verify no class ID, provider/Qdrant endpoint, prior-turn history, credential, or reasoning field is sent or stored.
- [x] 8.2 Add an accessible Chinese “知识库问答” region with question form, optional retrieval-mode selector, loading, validation, refusal, retrieval-degraded, generation-error, and answered states while preserving the material grid and teacher upload action; verify keyboard and assistive labels for both roles.
- [x] 8.3 Render answers as plain text with focusable inline source references and PostgreSQL-hydrated source cards containing excerpt, title, filename, one-based page or line locator, optional section, effective mode, and authorized source action; verify no raw HTML or model markup executes.
- [x] 8.4 Display exactly `根据本班资料无法回答该问题` with zero sources for insufficient evidence; verify no model-knowledge completion, assistant reasoning, model selector, token statistics, or fabricated citation appears.
- [x] 8.5 Make every new submission independent: replace or clearly separate the prior result and send no earlier question/answer automatically; verify network-level tests prove the request is single-turn.
- [x] 8.6 Display pending, processing, searchable, unsupported, and failed material states without hiding authorized downloads; verify desktop/mobile coverage.

## 9. Compose, Health, Backup, Restore, and Documentation

- [x] 9.1 Add internal `indexer` and Qdrant services with persistent storage, retrieval/model settings, health/restart behavior, and no host ports; verify Compose exposes only the web gateway and not PostgreSQL, Qdrant, or the indexer.
- [x] 9.2 Extend health output with PostgreSQL retrieval schema, worker freshness/queue, Qdrant compatibility, and recent embedding/generation degradation without sending real questions or evidence to providers; verify model/Qdrant outages do not make ordinary material access unhealthy and no content or secrets appear.
- [x] 9.3 Extend coordinated backup/restore verification to PostgreSQL chunks, material files, and Qdrant snapshots; document and test rebuilding an absent/incompatible Qdrant collection with exact IDs and orphan cleanup.
- [x] 9.4 Update `README.md` and `docs/operations.md` to describe supported formats, no-OCR boundary, three retrieval modes/default hybrid, RRF, single-turn evidence-only generation, exact refusal, citations, prompt-injection boundary, PostgreSQL/Qdrant ownership, private/approved-external data paths, commands, monitoring, rollback, and model/dimension migration.
- [x] 9.5 Remove only obsolete non-goals for retrieval, question answering, and bounded generation while retaining non-goals for multi-turn chat, autonomous Agent/tool use, assignments, learning diagnosis, lesson/exercise generation, registration/password recovery, skill switches/MCP, multi-agent behavior, and knowledge graphs; verify documentation consistency tests.
- [x] 9.6 Update demo/production secret and egress guidance so embedding and generation are independently explicit, private endpoints are supported, approved external use is deliberate, and fresh deployments invent no credentials; verify configuration tests and deployment review.

## 10. End-to-End Acceptance and Quality Gates

- [x] 10.1 Add two-class PostgreSQL/Qdrant fixtures with identical terms and vectors for teacher/student questions, forged class inputs, no-class denial, stale/orphan omission, and indistinguishable insufficient-evidence responses; verify every stage uses only login-session class scope.
- [x] 10.2 Add retrieval fixtures proving keyword mode requires original text, vector mode finds paraphrases, hybrid mode independently ranks before RRF, omitted mode selects hybrid, and bounded evidence selection is deterministic.
- [x] 10.3 Add generation fixtures proving supported claims cite current evidence, unsupported/model-memory questions use the exact refusal, prompt injection cannot alter policy, unknown citations are blocked, and malformed output never reaches the client.
- [x] 10.4 Add Playwright scenarios through the gateway for a grounded answer, citation/source navigation, PDF/text provenance, exact refusal, single-turn independence, all retrieval modes, hybrid degradation, generation failure, unsupported download, indexing states, keyboard operation, and absence of chat/Agent/reasoning/model-control UI.
- [x] 10.5 Add private-endpoint, blocked-unapproved-egress, approved-external, embedding/Qdrant/generation outage, reconciliation, and rebuild acceptance scenarios proving safe degradation, same-ID restoration, no fabricated fallback answer, and redacted health/CLI output.
- [x] 10.6 Run backend format/lint/type/unit/integration coverage, frontend lint/type/unit/build, PostgreSQL/Alembic migration checks, Qdrant reconciliation, Docker/Compose port checks, backup/restore/rebuild verification, Playwright, and `openspec validate --changes --strict`; record exact passing commands and results before marking the change complete.
