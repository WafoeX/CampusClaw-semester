## Context

See `proposal.md` for motivation and scope. The current application is a single FastAPI process backed by PostgreSQL, with Qdrant used only for vectors, React behind Nginx, JWT Bearer authentication parsed by a custom dependency, and an OpenAI-compatible non-streaming generation adapter. `POST /api/knowledge/query` performs one bounded class-scoped retrieval and validates the complete structured generation before returning it. Nginx already disables proxy response buffering for `/api/`.

The existing implementation and completed-but-unarchived OpenSpec changes make PostgreSQL authoritative for identity, material text, provenance, lifecycle, and authorization. Qdrant candidates must be hydrated and reauthorized through PostgreSQL. The new conversation path must retain these boundaries while allowing server-loaded history to influence a response. Teacher-created prompt and skill text is untrusted configuration, not a source of authorization or evidence.

FastAPI currently exposes default documentation internally, but the custom Bearer parser does not produce a usable OpenAPI security scheme and the gateway does not intentionally expose a documented Swagger path. There is no repository-level `apitest/` suite. Existing `api/tests/` are white-box/unit/integration tests and remain necessary rather than being replaced.

The supplied prototype is a visual/reference aid, not a pixel-compatibility contract; its public page exposes only the application shell to a non-interactive fetch. Existing CampusClaw accessibility, Chinese UI, and security constraints take precedence.

## Goals / Non-Goals

**Goals:**

- Add creator-owned, class-scoped agent and skill configuration with explicit publication readiness.
- Add student-owned multi-turn conversations that always use the latest valid published agent configuration and freshly authorized current-turn evidence.
- Stream a validated response and citations over a stable SSE event contract without exposing raw model output.
- Preserve the legacy single-turn knowledge endpoint and its clients.
- Make authentication, success responses, expected errors, and SSE schemas discoverable in OpenAPI and usable from same-origin Swagger UI.
- Add an isolated black-box API acceptance harness that compares API results with PostgreSQL state and emits a safe HTML report.

**Non-Goals:**

- Autonomous planning, tool execution, MCP, web browsing, model-selected class scope, or student-authored agents/skills.
- Guaranteeing that arbitrary natural language can be semantically classified with mathematical certainty; enforcement uses constrained output, platform instructions, validation, and explicit acceptance fixtures.
- Provider-token passthrough before safety validation, replayable/resumable SSE, WebSockets, or concurrent turns in one conversation.
- Sharing conversations with students other than the owner, or allowing non-creator teachers to inspect them.
- Replacing `api/tests/`/frontend tests with `apitest/`, exposing production PostgreSQL to the host, or testing against real external models by default.
- Pixel-level reproduction of the reference prototype.

## Decisions

### 1. Keep agent resources class-scoped and creator-owned

Add REST resources under `/api/agents` and `/api/skills`. The server always derives `class_id` and `creator_id` from `Principal`; request schemas use `extra="forbid"`. Teacher collection reads return only the caller's own maintainable resources. Student `GET /api/agents` returns only safe catalog fields for currently valid published agents in the student's class. Identifier lookups apply ownership/class predicates in the database query so inaccessible and nonexistent IDs share one 404 shape.

Planned operations are:

- `GET|POST /api/agents`
- `GET|PATCH|DELETE /api/agents/{agent_id}`
- `POST /api/agents/{agent_id}/publish`
- `POST /api/agents/{agent_id}/unpublish`
- `GET|POST /api/skills`
- `GET|PATCH|DELETE /api/skills/{skill_id}`

`DELETE` is an API-level retirement operation, not destructive row deletion when history or bindings exist. Publication is an explicit transition rather than a writable arbitrary status field. It requires a valid prompt and at least one active `solution_guidance` skill. Retiring a bound skill invalidates affected agents and blocks their use until repaired and republished.

Alternatives considered:

- **Class-wide teacher administration:** rejected because the user selected creator-only management and it broadens prompt-edit authority.
- **Create-implies-publish:** rejected because invalid or partially configured agents could become student-visible.
- **Hard deletion:** rejected because it would break conversation audit and message provenance.

### 2. Use immutable configuration revisions while conversations follow the latest revision

Use these PostgreSQL concepts:

- `agents`: identity, class, creator, lifecycle, current revision, timestamps.
- `agent_revisions`: immutable prompt/name/description configuration and monotonically increasing revision number.
- `skills`: identity, class, creator, type, lifecycle, current revision, timestamps.
- `skill_revisions`: immutable instruction text and revision number.
- `agent_skill_bindings`: active relation from an agent revision to exact skill revisions.

Every prompt, skill, or binding change creates a new immutable revision and, where necessary, unpublishes the agent until publication rules pass. Publishing points `agents.published_revision_id` to a validated immutable revision. Each turn loads the then-current published revision and stores its ID on the assistant message. Existing conversations do not pin configuration; comparing the current revision with the preceding assistant message drives `configuration_updated`.

This combines the chosen “use latest configuration” behavior with reproducible audit: historical messages still identify exactly what they used. If an agent is unpublished, retired, or invalid, existing conversations become read-only until a valid revision is published.

Alternative considered: mutating prompt/skill rows in place. Rejected because teacher audit could not explain which configuration produced a historical answer.

### 3. Persist conversations, ordered messages, and current-turn citations in PostgreSQL

Add:

- `conversations`: student owner, class, agent, active/deleted lifecycle, timestamps.
- `conversation_messages`: conversation, strictly increasing ordinal, role (`user` or `assistant`), bounded text, state (`processing`, `completed`, `failed`), safe error code, retrieval mode, applied agent revision, timestamps.
- `message_citations`: assistant message, source order/ID, material/chunk identifiers, and the bounded source presentation snapshot needed to reproduce the emitted response.

Conversation operations are:

- `GET|POST /api/conversations`
- `GET|DELETE /api/conversations/{conversation_id}`
- `POST /api/conversations/{conversation_id}/messages`
- `GET /api/agents/{agent_id}/conversations` for creator audit, with explicit active/deleted filters.

Student deletion sets `deleted_at` and blocks student reads/messages. The creating teacher's audit query deliberately includes retained deleted conversations and full message content; the student UI must disclose this before confirmation. Other teachers receive 404. Retention duration follows the deployment's data-retention policy; this change does not add an automatic purge job.

A partial unique constraint permits at most one `processing` assistant row per conversation. The acceptance transaction locks the conversation, checks owner/class/agent readiness, assigns ordinals, and commits one user row plus one processing assistant row. Generation runs outside that short lock. A terminal transaction changes the assistant to `completed` or `failed` and saves citations. This avoids holding a database transaction during provider latency while preventing concurrent turns.

Alternative considered: storing messages in Qdrant or browser state. Rejected because PostgreSQL is the authorization/audit authority and conversations must survive reloads.

### 4. Treat history as bounded context, never as current evidence

For each turn, the server loads a deterministic suffix of completed messages from the same authorized conversation under configurable message-count and character budgets. A contextual retrieval query is built deterministically from the current message plus a bounded recent user-context suffix; no additional model call is needed before retrieval. Retrieval still executes under the student's current class and returns current authorized chunks.

Generation input is separated into typed sections:

1. immutable platform policy;
2. mandatory solution-guidance contract;
3. latest teacher prompt and skill instructions, explicitly labeled untrusted configuration;
4. server-loaded history, labeled untrusted conversation context;
5. current question;
6. current authorized evidence, labeled untrusted evidence with request-local source IDs.

The output schema uses `status`, structured guidance sections, rendered answer text, and `citation_ids`; it has no `final_answer` field. Every factual guidance claim still needs a current source marker. Previous assistant text and citations may resolve references but cannot satisfy citation validation.

Alternative considered: summarize history with a separate model call. Rejected for this change because it adds cost, another failure mode, and an additional ungrounded artifact. Deterministic truncation is easier to test.

### 5. Buffer and validate provider output before emitting answer deltas

The provider adapter may remain non-streaming. `POST /api/conversations/{conversation_id}/messages` returns `StreamingResponse` with `text/event-stream` after pre-stream authorization and acceptance. The stream emits `message.started`, then performs retrieval/generation in a shielded bounded task. It buffers the complete provider response, applies the existing structured-output and citation checks plus guidance-shape validation, performs final source reauthorization, persists the terminal assistant state, and only then divides the validated rendered answer into bounded Unicode-safe `answer.delta` events followed by citation events and `message.completed`.

This produces browser-visible incremental delivery but intentionally does not forward raw provider tokens. Heartbeat comments may keep proxies from timing out but are not semantic events. Each semantic event uses a monotonic sequence and shared identifiers. On a post-start failure, the task persists `failed` and emits one redacted `message.error`. Client disconnect cancellation is shielded so the bounded task reaches a database terminal state; no unbounded retry is started. A refreshed conversation shows the authoritative result.

Alternatives considered:

- **Pass provider tokens directly:** rejected because malformed output, hidden prompts, direct final answers, and unauthorized citations could leak before validation.
- **WebSocket:** rejected because communication is one request followed by one server stream, and authenticated `fetch()` can send Bearer headers with SSE response handling.
- **Native `EventSource`:** rejected because it cannot set the required Authorization header.

### 6. Use explicit SSE event envelopes and pre-stream JSON errors

Every semantic event is `event: <name>` plus one JSON `data:` object. Names are `message.started`, `answer.delta`, `citation`, `message.completed`, and `message.error`. Common fields are `sequence`, `conversation_id`, `user_message_id`, and `assistant_message_id`. Completion includes status, assembled-answer digest/length, retrieval modes, and configuration revision. Citation data reuses the authorized source schema. No event contains prompt/history internals.

Validation, authentication, missing-resource, deleted-conversation, and agent-readiness failures are resolved before constructing `StreamingResponse`, allowing ordinary documented JSON 4xx/5xx responses. Failures after `message.started` are stream events because HTTP status can no longer change.

### 7. Express Bearer security through FastAPI's OpenAPI model

Replace the undocumented manual header extraction at the schema boundary with a shared FastAPI HTTP Bearer security dependency while preserving the existing token validation and 401 behavior. Configure `docs_url="/api/docs"` and `openapi_url="/api/openapi.json"` so both are already covered by the gateway's `/api/` proxy. Keep these documentation resources public and same-origin.

Define explicit request, success, domain-error, validation-error, and SSE envelope models and attach expected responses to each route. Override OpenAPI only where needed to describe SSE event variants, because OpenAPI does not natively model the temporal event sequence. Add contract tests that compare protected/public security metadata and representative actual responses.

Alternative considered: a hand-maintained YAML file. Rejected because it would drift from Pydantic route models and duplicate FastAPI's generated contract.

### 8. Keep the legacy knowledge endpoint isolated and compatible

`POST /api/knowledge/query` retains its path, request shape, response shape, single-turn prompt, refusal wording, and non-streaming behavior. Shared lower-level retrieval, evidence authorization, source serialization, and model-output validation may be refactored for reuse, but conversation history and teacher configuration are passed only through a new chat orchestration service.

This avoids a breaking migration and provides a regression oracle for existing class-isolation behavior.

### 9. Build `apitest/` as a black-box runner with test-only database observation

Use the requested layout, for example `apitest/cases/api/auth/login/POST.py`. `run_all.py` recursively discovers uppercase HTTP-method files in stable path order and loads a small case registration contract. Shared modules provide HTTP calls, login, SSE parsing, safe redaction, fixture IDs, PostgreSQL reads, and result records. The runner writes standalone HTML with escaped text using the Python standard library, avoiding a report dependency. Default output is `apitest/reports/<timestamp>.html`, and that directory is Git-ignored.

Add `docker-compose.apitest.yml` with a distinct documented project name, isolated volumes/network, deterministic credentials, test seed/fixture preparation, an internal OpenAI-compatible stub, Qdrant, API, gateway, and an `apitest` runner service. The runner reaches PostgreSQL over the internal network with a dedicated read-only/limited test role after fixture setup; an optional loopback-only database port may be used for local debugging but is disabled by default. No production setting or volume is reused.

The stub returns deterministic embeddings and schema-valid guidance responses keyed by synthetic fixture facts. It enables stable assertions for same-class retrieval, cross-class refusal, direct-answer guidance, citations, and SSE persistence without external egress. Cases create unique run-scoped records and verify returned IDs, class/owner fields, bindings, states, messages, and citations directly in PostgreSQL. Cleanup operates only in the isolated test database.

Alternatives considered:

- **Reuse white-box pytest clients:** rejected because the requested suite must validate the deployed gateway, OpenAPI, streaming proxy, migrations, and real persistence boundary.
- **Test a shared development instance:** rejected because data mutation and model nondeterminism would make database assertions unsafe.
- **Commit reports:** rejected by the request and because reports may contain local diagnostics.

## Risks / Trade-offs

- **[Guidance semantics can be imperfect with generative text]** → Use mandatory platform instructions, constrained structured fields, full-output validation before release, deterministic adversarial fixtures, and safe failure after bounded repair; do not claim a formal semantic proof.
- **[Buffer-before-delta increases time to first answer text]** → Emit a start event and heartbeat comments, enforce provider timeout, show retrieval/generation status, and prefer safety over raw token latency.
- **[Shielded work continues after client disconnect]** → Apply strict time/input/output limits, one in-progress turn per conversation, terminal-state persistence, and no automatic retry.
- **[Latest configuration can change an ongoing conversation's behavior]** → Store immutable applied revision per answer and display `configuration_updated` before the changed response.
- **[Teacher audit of deleted student content has privacy impact]** → Restrict access to the agent creator, log safe access metadata, disclose retention before student deletion, and document the policy operationally.
- **[Soft-deleted content grows indefinitely]** → Keep retention/purge policy explicit as a deployment concern; automatic purge is outside this change and must not be implied.
- **[OpenAPI cannot fully encode SSE ordering]** → Document event variants in the schema and sequence rules in operation descriptions, then verify ordering in black-box tests.
- **[Existing capability specs are completed but unarchived]** → Preserve their exact capability path and validate the combined delta; archive/sync ordering must avoid losing the modified requirement.
- **[Test-only direct database checks could expose credentials]** → Keep credentials synthetic, network-internal, least-privileged, redacted, and isolated from all non-test volumes.

## Migration Plan

1. Add schema migration for immutable agent/skill revisions, bindings, conversations, messages, citations, lifecycle constraints, indexes, and the one-processing-turn constraint. Migration is additive and does not modify existing material/retrieval rows.
2. Deploy backend models, repositories, authorization queries, OpenAPI security scheme, agent/skill routes, conversation reads, then the message SSE route. Keep the old knowledge route and response contract active throughout.
3. Configure `/api/docs` and `/api/openapi.json`, verify public/protected security metadata, and verify gateway buffering/timeout behavior for SSE.
4. Add frontend teacher management and student conversation routes behind existing Bearer auth. Keep the materials/single-turn interface reachable during rollout.
5. Add isolated Compose API-test services and fixtures; run unit/integration/frontend tests, strict OpenSpec validation, and the full black-box suite before enabling the UI links.
6. Update operations, privacy/retention disclosure, environment examples, and remove only the superseded non-goal statements.

Rollback deploys the prior frontend/backend while leaving additive tables unused and keeps the legacy knowledge endpoint operational. Do not downgrade/drop the new tables until conversation and audit data has been explicitly exported or approved for destruction. If chat is unhealthy after deployment, hide/disable new UI entry points and stop new conversation writes without altering existing material, auth, or legacy query behavior.
