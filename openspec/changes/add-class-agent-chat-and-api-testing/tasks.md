## 1. Database Schema and Configuration

- [x] 1.1 Add agent, agent revision, skill, skill revision, and revision-to-skill binding models with class/creator foreign keys, lifecycle checks, uniqueness constraints, and timestamps; verify focused model tests cover valid rows and rejected cross-owner/duplicate bindings.
- [x] 1.2 Add conversation, ordered message, and message-citation models with student/class/agent links, soft deletion, processing/completed/failed states, applied revision provenance, and a partial uniqueness rule for one processing turn; verify focused model tests cover ordering and constraint violations.
- [x] 1.3 Create one additive Alembic migration for the new tables, constraints, indexes, and PostgreSQL partial index without changing existing auth/material/retrieval data; verify upgrade from the current head and migration-shape tests pass on PostgreSQL.
- [x] 1.4 Add bounded server configuration for agent fields, skill fields, message/history budgets, SSE heartbeat/task timeout, and conversation rate limits; verify settings tests reject unsafe zero, negative, oversized, or inconsistent values without exposing secret inputs.

## 2. Agent and Skill Domain Services

- [x] 2.1 Implement repositories that always query agents and skills by server-derived class and creator scope and provide existence-hiding identifier lookups; verify unit/integration tests compare nonexistent, same-class-other-creator, and other-class results.
- [x] 2.2 Implement immutable agent/skill revision creation and configuration revision selection, including propagation when a bound skill changes; verify tests prove prior revisions remain unchanged and the latest revision is selected deterministically.
- [x] 2.3 Implement skill create/list/read/update/retire rules and protect `solution_guidance` instructions under platform policy; verify teacher, student, other-creator, invalid-bound, and retirement tests pass.
- [x] 2.4 Implement agent create/list/read/update/retire and idempotent skill binding rules with forbidden client ownership fields; verify tests cover multiple agents, bounds, duplicate skills, rollback on invalid references, and server-derived class/creator values.
- [x] 2.5 Implement explicit publish/unpublish transitions requiring a valid prompt and active solution-guidance skill and invalidating publication when required configuration retires; verify publication success, HTTP 409 readiness, student catalog filtering, and existing-session blocking tests pass.

## 3. Agent and Skill HTTP APIs

- [x] 3.1 Add strict Pydantic request/response models and stable domain error models for agent and skill maintenance and student catalog views; verify schema tests enforce field bounds, `extra="forbid"`, and omission of private prompts/instructions from student responses.
- [x] 3.2 Add `GET|POST /api/agents` and `GET|PATCH|DELETE /api/agents/{agent_id}` with role-aware collection behavior and creator-only mutations; verify route tests cover teacher success, student 403, safe student catalog fields, and indistinguishable 404 responses.
- [x] 3.3 Add agent publish/unpublish routes and register all agent routes in the app factory; verify route tests cover valid transitions, repeated transitions, readiness conflicts, and no partial database mutation.
- [x] 3.4 Add `GET|POST /api/skills` and `GET|PATCH|DELETE /api/skills/{skill_id}` and register the router; verify route tests cover creator CRUD, student denial, same-class other-teacher 404, retirement effects, and response/database agreement.

## 4. Conversation Persistence and Authorization

- [x] 4.1 Implement student conversation create/list/read/soft-delete repository and service operations using current class and ownership in every query; verify tests cover deterministic ordering, hidden deleted rows, cross-student/class 404, and blocked post-delete messages.
- [x] 4.2 Implement agent-creator audit list/read operations that include active and student-deleted conversations with full bounded message history; verify the creator can read both states while every other teacher and class receives the ordinary 404 shape.
- [x] 4.3 Implement short transactional turn acceptance with conversation locking, ordinal allocation, one user row, one processing assistant row, and one-in-progress conflict handling; verify concurrent PostgreSQL tests produce one accepted turn and one HTTP 409 without duplicate rows.
- [x] 4.4 Implement terminal completion/failure persistence and current-turn citation snapshots; verify tests compare completed text/citations/revision metadata and prove failed rows contain only safe error codes and no raw provider output.
- [x] 4.5 Add strict conversation and current-message schemas that reject client-supplied history, class, prompt, assistant content, and citations; verify validation tests return documented errors before any rows are created.
- [x] 4.6 Add `GET|POST /api/conversations`, `GET|DELETE /api/conversations/{conversation_id}`, and creator-audit `GET /api/agents/{agent_id}/conversations`; verify student lifecycle, retention disclosure fields, creator audit, deleted state, and all ownership/class scenarios through API tests.

## 5. Grounded Multi-turn Generation and SSE

- [x] 5.1 Refactor shared retrieval/evidence/source validation so the legacy knowledge endpoint remains byte-for-contract compatible while a chat orchestrator can reuse it; verify existing knowledge, grounding, provider-boundary, and class-isolation tests remain green.
- [x] 5.2 Implement deterministic bounded history loading and contextual retrieval-query construction from only the current authorized conversation; verify tests cover follow-up reference resolution, deterministic suffix truncation, fabricated-history rejection, and exclusion of other conversations.
- [x] 5.3 Build the chat prompt envelope with fixed platform policy, mandatory solution guidance, untrusted latest teacher configuration, untrusted persisted history, current question, and current authorized evidence in explicit priority order; verify prompt tests prove no history or teacher text can alter class scope, tools, secrets, grounding, or citation rules.
- [x] 5.4 Extend structured generation parsing for guidance sections, refusal normalization, current-turn citation equality, size/markup bounds, and one bounded repair while retaining full-output buffering; verify tests cover direct-final-answer requests, malformed output, stale/unknown citations, prompt injection, and no invalid text release.
- [x] 5.5 Implement loading the latest published immutable agent revision per turn and recording it on the assistant message; verify changing a prompt or bound skill affects the next message, sets `configuration_updated`, preserves prior revision audit, and unpublished/invalid agents return pre-stream HTTP 409.
- [x] 5.6 Implement typed SSE serialization for `message.started`, `answer.delta`, `citation`, `message.completed`, and `message.error` with common identifiers and monotonic sequence values; verify parser tests cover framing, Unicode-safe delta assembly, event ordering, terminal uniqueness, and sensitive-field absence.
- [x] 5.7 Add `POST /api/conversations/{conversation_id}/messages` using authenticated `StreamingResponse`, shielded bounded generation, heartbeat comments, final source reauthorization, and terminal persistence; verify success, insufficient evidence, provider failure, invalid output, concurrent message, and client-disconnect integration tests reach the specified stream/database states.
- [x] 5.8 Add request-level rate/size/time limits and safe logging for conversation generation; verify tests show bounded rejection or failure without logging tokens, prompts, history, questions, evidence, answers, credentials, or provider bodies.

## 6. OpenAPI and Swagger

- [x] 6.1 Replace schema-invisible Bearer parsing with a shared FastAPI HTTP Bearer security dependency while preserving current token validation and exact 401 behavior; verify all existing auth/principal tests and new OpenAPI security assertions pass.
- [x] 6.2 Configure public same-origin Swagger UI at `/api/docs` and OpenAPI JSON at `/api/openapi.json`; verify both load through the Nginx gateway while the API container remains unexposed on the host.
- [x] 6.3 Add operation IDs, tags, summaries, request/response models, reusable safe errors, expected status codes, public/protected security metadata, and content types to all existing and new main routes; verify an OpenAPI contract test finds no undocumented requested operation or expected error status.
- [x] 6.4 Add explicit OpenAPI schema/description for SSE event variants, ordering, pre-stream JSON errors, and post-start `message.error`; verify the generated document declares `text/event-stream` and every event payload schema used by serializer tests.
- [x] 6.5 Add documentation secrecy tests that scan generated OpenAPI/Swagger assets for runtime secrets, tokens, database URLs, private prompts, skill instructions, messages, and material text; verify only synthetic examples are present.

## 7. Frontend Agent and Conversation Experience

- [x] 7.1 Add typed frontend API helpers for agent/skill CRUD, publication, conversations, audit reads, and authenticated fetch-based SSE parsing with ordered-event validation; verify Vitest covers 401 handling, split SSE frames, sequence gaps, terminal events, and interrupted streams.
- [x] 7.2 Add creator-only teacher pages for multiple agents, prompt editing, skill maintenance/binding, readiness errors, publish/unpublish, and retirement; verify component tests cover validation, private data display only for creator routes, and keyboard operation.
- [x] 7.3 Add student agent catalog and conversation create/list/read/soft-delete pages, including explicit notice that the creating teacher retains deleted conversation audit access; verify component tests cover class catalog filtering, deletion confirmation, hidden deleted conversations, and unavailable-agent states.
- [x] 7.4 Add the accessible chat view with one in-flight message, live streamed status, configuration-updated notice, safe interruption state, validated inline citations, source cards, and authenticated downloads; verify component tests assemble deltas once, preserve plain-text rendering, move focus correctly, and expose live-region updates.
- [x] 7.5 Add creator audit UI for active and student-deleted conversations while preventing navigation for non-creators; verify teacher audit component/e2e tests show full authorized history and no same-class-other-teacher access.
- [x] 7.6 Integrate new routes/navigation without removing materials, upload, or the legacy single-turn knowledge interface; verify frontend route tests and Playwright smoke tests can use both old and new flows after login.
- [x] 7.7 Run frontend lint, typecheck, unit tests, production build, and accessibility-oriented e2e checks; verify every configured frontend quality command exits zero.

## 8. Isolated API Test Harness

- [x] 8.1 Create `apitest/` support modules and deterministic discovery in `run_all.py` for uppercase method scripts beneath mirrored URL directories; verify a harness self-test discovers fixtures in stable order and rejects malformed/duplicate operation registrations.
- [x] 8.2 Implement escaped standalone HTML reporting, bounded safe diagnostics, redaction, pass/fail summary, duration, and nonzero exit behavior; verify harness tests cover passing, failing, crashing, secret-bearing, and empty-suite runs.
- [x] 8.3 Add `apitest/reports/` and generated artifacts to `.gitignore`; verify a generated report does not appear in `git status --short` while committed harness sources do.
- [x] 8.4 Add a deterministic internal OpenAI-compatible embedding/generation stub with health checks and synthetic class-specific facts; verify contract tests exercise embeddings, grounded guidance JSON, refusal, malformed/failure fixtures, and prove no external endpoint is contacted.
- [x] 8.5 Add `docker-compose.apitest.yml` with an isolated project name, volumes, test PostgreSQL, migration/seed/fixture setup, Qdrant, indexer, provider stub, API, gateway, and runner plus a test-only least-privileged database role; verify Compose config exposes only the documented gateway port and no production/development volume.
- [x] 8.6 Add shared black-box clients for login, JSON APIs, SSE parsing, run-scoped fixture data, and read-only PostgreSQL assertions with complete redaction; verify support tests reject non-test database targets and never print tokens, passwords, prompts, or connection strings.

## 9. Black-box API Cases

- [x] 9.1 Add `apitest/cases/api/auth/login/POST.py` for valid teacher/student login, unknown account, wrong password, response fields, generic 401 equality, and database non-mutation; verify the operation script passes in the isolated stack.
- [x] 9.2 Add operation scripts for the existing knowledge query path covering same-class citation, other-class-only indistinguishable refusal, invalid input, missing Bearer token, and response/database expectations; verify each script passes against deterministic indexed fixtures.
- [x] 9.3 Add one method script per skill endpoint covering create/list/read/update/retire, content bounds, student denial, other-creator/class 404, and direct database consistency; verify all discovered skill cases pass.
- [x] 9.4 Add one method script per agent endpoint covering multiple drafts, prompt revisions, skill binding, publication readiness, student safe catalog, unpublish/retire, ownership isolation, and database revision/binding state; verify all discovered agent cases pass.
- [x] 9.5 Add one method script per conversation lifecycle/audit endpoint covering student create/list/read/delete, agent creator audit after deletion, non-creator 404, class mismatch, and database retention; verify all discovered conversation cases pass.
- [x] 9.6 Add the message `POST.py` case for SSE success, current-turn citation, direct-answer guidance, latest configuration update notice, insufficient evidence, event order/sequence, terminal persistence, concurrent conflict, and safe errors; verify stream assembly exactly matches PostgreSQL messages/citations.
- [x] 9.7 Add OpenAPI/Swagger black-box cases for gateway access, security scheme, public/protected markers, requested paths/methods/errors, SSE media/schema, and authorized try-out equivalence; verify the generated report shows every documentation assertion passing.
- [x] 9.8 Run `apitest/run_all.py` through the Compose runner and verify exit zero, all minimum workflows listed in the HTML report, response and database assertions present, no secrets/content leakage, and no generated report tracked by Git.

## 10. Operations, Regression, and Final Verification

- [x] 10.1 Update `.env.example`, Compose/runtime documentation, and Nginx timeout/buffering guidance for chat budgets, provider behavior, Swagger paths, audit privacy, soft deletion, and isolated API-test commands; verify documented Compose/config commands parse with placeholder test values.
- [x] 10.2 Update README and operations scope to describe agents, skills, multi-turn grounded chat, SSE, and current non-goals without weakening Bearer auth, model egress, class isolation, or legacy query guarantees; verify documentation links and referenced commands/paths exist.
- [x] 10.3 Add backend regression tests for migration, legacy `POST /api/knowledge/query`, login/material APIs, retrieval isolation, health secrecy, and provider boundaries; verify the full backend test suite meets the existing coverage threshold.
- [x] 10.4 Run backend Ruff, formatting check, mypy, pytest/coverage, frontend quality commands, Compose configuration checks, and browser end-to-end tests; verify every command exits zero and no suppression weakens existing quality rules.
- [x] 10.5 Run every Scenario in the five delta specs, including cross-class indistinguishability, latest configuration, creator-only deleted-conversation audit, SSE failures, Swagger authentication, and database-consistent API reports; record a concise verification matrix with no untested Scenario.
- [x] 10.6 Run `openspec validate --strict`, inspect `git diff --check` and `git status --short`, and verify only intended implementation/docs/tests plus this change's artifacts are modified and no report, secret, runtime data, or unrelated file is present.
- [x] 10.7 Before archiving this change, sync or archive the completed `add-class-scoped-knowledge-retrieval` change so `materials/knowledge-retrieval` exists in the main spec set; verify `openspec list --specs` shows that exact path and strict validation no longer reports the archive-order informational warning.
