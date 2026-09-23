## Context

This is a greenfield repository: there is no application source or existing main specification to preserve. See `proposal.md` for motivation and the five delta specs for behavior. The selected stack is FastAPI + React + PostgreSQL, deployed with Docker Compose. The user further requires that neither the FastAPI port nor the PostgreSQL port be published to the host.

The material library stores files rather than parsed, indexed, or vectorized content. Every account belongs to exactly one class. `README.md` also establishes that the demo system provides preloaded sample data, so initialization must create useful examples without weakening production defaults or bypassing the same password, class, and storage rules used by normal data. The implementation therefore needs one security boundary spanning sessions, role checks, database queries, file paths, reverse-proxy routing, initialization, and tests.

## Goals / Non-Goals

**Goals:**

- Keep browser traffic same-origin through one published web gateway.
- Make server-side identity, role, and class scope mandatory for every protected operation.
- Keep uploaded-file visibility consistent with durable metadata and complete file storage.
- Provide deterministic schema migration, account provisioning, environment-aware demo seeding, readiness, and container startup.
- Make the critical security behavior directly testable at API and browser levels.

**Non-Goals:**

- Self-registration, password reset, account administration UI, or external identity providers.
- Multi-class membership, teacher access across classes, or user-selectable active classes.
- Content parsing, malware scanning, material search, full-text search, vector search, RAG question answering, or intelligent conversation.
- Assignment submission, skill/feature toggles, material editing, deletion, versioning, sharing links, or object-storage integration.
- Horizontal API scaling or shared network file storage in the initial deployment.

## Decisions

### D1. Use a same-origin web gateway and keep backend ports internal

Docker Compose will run `web`, `api`, `migrate`, `seed`, and `db` services. `web` will contain the React production build and Nginx; it is the only service with a host `ports` mapping. Nginx will serve browser assets and reverse-proxy `/api/*` and `/health` to `api:8000`. `api` and `db` will have no host port mappings and will communicate over internal Compose networks. PostgreSQL will only be reachable by `api`, `migrate`, and the one-shot `seed` service on the data network.

This gives the browser one origin, avoids CORS and cross-site cookie configuration, and satisfies the no-backend-port requirement. No supported Compose configuration publishes the FastAPI or PostgreSQL service port to the host; development access also goes through the published web gateway.

Alternatives considered:

- Publishing FastAPI directly is simpler for debugging but violates the required deployment boundary.
- Hosting the React development server in production adds an unnecessary runtime and does not provide the reverse-proxy boundary.
- Serving React from FastAPI would reduce the service count, but the selected separated frontend benefits from an explicit gateway and independently built static assets.

### D2. Use FastAPI, SQLAlchemy 2, Alembic, React TypeScript, and PostgreSQL

The API will use Python 3.12, FastAPI, Pydantic settings, SQLAlchemy 2, psycopg 3, Alembic, `argon2-cffi`, and multipart upload support. The web client will use React, TypeScript, Vite, React Router, and a small typed API client. PostgreSQL will own relational metadata and session state; uploaded bytes will live on a named volume mounted read-write into `api` and the one-shot `seed` service. The seed mount exists only for initialization and does not expose a new network endpoint.

Synchronous SQLAlchemy sessions are sufficient for the expected workload and keep transaction behavior straightforward. File copies and hashes will be processed in bounded chunks rather than loading whole files into memory.

Alternatives considered:

- SQLite reduces service count but has a less explicit concurrency and lifecycle boundary and was rejected in favor of the selected PostgreSQL container.
- A Node/Fastify API would align languages across the stack, but the user selected FastAPI.
- Storing file bytes in PostgreSQL would make backup atomicity easier but would inflate the database and make streaming/storage operations less flexible.

### D3. Model class ownership and sessions explicitly

The initial schema will contain:

- `classes(id UUID, name UNIQUE, created_at)`.
- `users(id UUID, account UNIQUE, password_hash, role, class_id NOT NULL, is_active, created_at, updated_at)` with role constrained to `teacher` or `student` and a foreign key to `classes`.
- `sessions(id UUID, token_digest UNIQUE, user_id, csrf_digest, expires_at, created_at, last_seen_at)` with cascading removal when a user is removed and indexes for lookup and expiry cleanup.
- `materials(id UUID, class_id, uploader_id, title, original_filename, content_type, byte_size, sha256, storage_key UNIQUE, state, created_at)` with foreign keys and indexes on `(class_id, created_at, id)`; `state` is constrained to `pending` or `ready`.

UUID identifiers avoid guessable sequential resource IDs but do not replace authorization. Database constraints prevent missing class membership and unsupported roles. Material queries still include `class_id` in their predicates; loading by material ID and checking later is not the normal access path.

Accounts will be provisioned with a containerized CLI that creates the class if requested, prompts for the password without placing it in command history, hashes it, and inserts the user. Self-registration is intentionally absent.

### D4. Use opaque, server-side sessions with Argon2id password hashes

Passwords will be hashed with Argon2id using parameters calibrated for the deployment and encoded with a per-password salt. The API will verify hashes through `argon2-cffi`, support rehash-on-login when parameters change, and exclude credential fields from request logging and validation errors.

Successful login will generate a 256-bit random session token. Only an HMAC digest of that token will be stored in PostgreSQL; the HMAC key is a required server-side environment secret. The raw token is sent in an HttpOnly, SameSite=Lax cookie with a bounded lifetime and `Secure` enabled for HTTPS deployments. Logout deletes the session and expires the cookie. Expired sessions are rejected and periodically removed.

State-changing requests will require a session-bound CSRF token sent in a custom header. The React client obtains it with the authenticated identity response and does not persist it outside memory. Same-origin routing and an Origin check provide additional defense. Login errors remain generic.

Alternatives considered:

- JWTs put authorization state in the browser and complicate immediate revocation; opaque sessions better match the requirements.
- Signed client-side session cookies reduce database reads but make logout and role/class changes harder to enforce immediately.
- bcrypt is acceptable, but Argon2id provides the selected memory-hard password hashing baseline.

### D5. Centralize authentication, role authorization, and class-scoped queries

FastAPI dependencies will resolve the session to a current principal containing immutable request-time `user_id`, `role`, and `class_id`. Separate dependencies will require a supported role and teacher role. Material repository methods will require `class_id` as an argument and include it in list/detail/download queries.

The upload API will ignore or reject client class selectors and assign `principal.class_id`. Detail and download lookups use both material ID and class ID; both a missing ID and a cross-class ID return the same 404 payload. Student upload is rejected before multipart content is persisted. The React UI hides teacher-only controls for usability, but API checks remain authoritative.

A narrow endpoint surface will be used:

- `POST /api/auth/login`, `POST /api/auth/logout`, and `GET /api/auth/me`.
- `GET /api/materials`, `POST /api/materials`, `GET /api/materials/{id}`, and `GET /api/materials/{id}/download`.
- `GET /health` outside `/api` for readiness.
- Browser routes `/login`, `/materials`, and `/materials/upload`.

React route guards call `/api/auth/me`; unauthenticated protected routes navigate to `/login` with a validated same-origin return path. This is navigation behavior only—the API remains the security boundary.

### D6. Stream uploads into a recoverable two-phase file workflow

The API will stream an upload in bounded chunks to `<upload-root>/tmp/<random-id>` while counting bytes and computing SHA-256. It will stop at `UPLOAD_MAX_BYTES`, delete the temporary file on every rejection, sanitize display metadata, and generate the final storage key as `<class-id>/<material-id>` independently of the original filename.

After validation:

1. Insert and commit a `pending` material row.
2. Atomically rename the temporary file to its final path on the same mounted filesystem.
3. Mark the row `ready` in a second transaction.

Lists, metadata reads, and downloads select only `ready` rows. Exceptions attempt to remove temporary/final files and pending rows. Startup reconciliation removes stale temporary files and stale `pending` rows/files older than a conservative threshold, covering process termination between steps. The final path is opened only after the class-scoped database lookup succeeds.

This protocol avoids exposing partial uploads despite the lack of a transaction spanning PostgreSQL and the filesystem. Direct-to-final writes were rejected because readers could observe incomplete data; keeping bytes in PostgreSQL was rejected as described in D2.

### D7. Apply migrations as a one-shot prerequisite and make readiness meaningful

The `migrate` service will use the API image, wait for PostgreSQL health, run `alembic upgrade head`, and exit. The one-shot `seed` service runs only after migration succeeds; it either performs enabled demo initialization or exits successfully without changes. `api` starts only after both one-shot services complete successfully. `web` may start independently but will not report the application ready while the proxied API is unavailable.

FastAPI's unauthenticated `/health` handler will verify a database round trip, confirm the Alembic revision is at the expected head, and verify that the upload root exists and is writable. It returns only a small status payload and no configuration values. Nginx proxies public `/health` to this internal endpoint. Container health checks use the internal service URLs, while acceptance tests call `/health` through the single published web port.

### D8. Keep secrets and environment-specific configuration out of browser builds

Pydantic settings will validate `APP_ENV`, `DATABASE_URL`, `SESSION_HMAC_KEY`, session lifetime, cookie security mode, upload root, upload size, and demo-seed mode. Compose will pass server values only to the backend services that need them; sample-account passwords are passed only to `seed`, while Vite build arguments are limited to non-secret public values and normally need no API base URL because requests are same-origin. A committed `.env.example` will contain placeholders, never usable secrets.

Nginx will set a request-body limit slightly above the API's configured upload limit so the API remains the authoritative byte-count check while the gateway rejects extreme bodies. Security headers will include `X-Content-Type-Options: nosniff`, a restrictive content security policy suitable for the React build, and frame restrictions.

### D9. Seed representative demo data without production side effects

The API image will expose a one-shot `seed-demo` CLI used by the Compose `seed` service. Demo configuration sets `SEED_DEMO_DATA=true` by default; production configuration sets it to `false` and creates no sample rows or files unless an operator deliberately overrides that setting. When seeding is enabled, all required per-account demo passwords must be supplied through server-side environment variables. Missing values fail the seed before any account is created, and password values are never logged.

The seed manifest will define two predictably named but non-secret classes, one teacher and one student account per class, and at least one small non-executable teaching-material asset per class. Stable seed identifiers make repeated runs detectable. The command uses the normal Argon2id hashing, class assignment, material metadata, hashing, and storage workflow rather than inserting weaker special-case records. Existing seed records are verified and skipped; changed passwords, user-created data, and existing ready materials are never overwritten. A conflicting record with the same seed identity but incompatible ownership fails visibly instead of being mutated.

Sample material assets may be committed as non-sensitive fixtures, but sample passwords and server secrets may not. Seeding must be idempotent across container recreation and must clean up partial metadata/files on failure.

Alternatives considered:

- Always seeding every environment is convenient but risks production sample accounts and was rejected.
- Requiring a manual seed command weakens the README's demo-startup promise; an environment-aware one-shot service preserves convenience and safety.
- Direct SQL seed scripts are shorter but could bypass password hashing and material-storage invariants.

### D10. Verify boundaries at unit, integration, and browser levels

Backend unit tests will cover password hashing, session expiry, role dependencies, filename handling, size accounting, and seed idempotency. PostgreSQL integration tests will exercise migrations, demo seeding, login/logout, student upload rejection, class-scoped list/detail/download behavior, indistinguishable 404 responses, file/metadata cleanup, and health dependency failures.

Frontend tests will cover route guards, role-based controls, errors, and upload flow. Playwright tests against the demo Compose stack will cover sample teacher and student login, unauthenticated redirect, preloaded class-scoped materials, teacher upload appearing in the class list, student upload denial at the API, cross-class denial, download integrity, and `/health` through the gateway. A deployment assertion will inspect Compose-published ports and fail if API or database ports are host-bound. A production-profile assertion will prove that sample rows and files are absent by default.

## Risks / Trade-offs

- **[Local volume limits horizontal scaling]** → Keep one API writer in the initial Compose deployment and preserve the storage abstraction so object storage can replace the volume later.
- **[Database and file backups can be inconsistent]** → Document coordinated backup/restore that quiesces uploads or snapshots both stores in one maintenance window; test restore procedures before production use.
- **[A crash can leave pending metadata or orphaned files]** → Use `pending`/`ready` visibility, same-filesystem atomic rename, cleanup on failure, and startup reconciliation.
- **[Uploaded content can be malicious even when access-controlled]** → Force attachment download, apply `nosniff`, never execute or render uploads inline, and document malware scanning as a future hardening option.
- **[Argon2 settings can exhaust small containers]** → Benchmark and document memory/time parameters, cap concurrent login work, and retain rehash-on-login support.
- **[Cookie security differs between local HTTP and production HTTPS]** → Default production documentation to HTTPS with `Secure` cookies and require an explicit local-development override.
- **[Nginx and API upload limits can diverge]** → Define both values in deployment documentation, keep the gateway ceiling above the API limit, and test both rejection paths.
- **[Server-side sessions add database traffic and cleanup work]** → Index token digests and expiry, use bounded session lifetimes, and add scheduled expiry cleanup.
- **[Demo credentials or sample data could leak into production]** → Disable seeding by default in production, require explicit environment passwords only in the seed service, reject missing/placeholder production values, and test that the production profile creates no sample records or files.

## Migration Plan

1. Create the API and web projects, locked dependencies, container images, internal networks, named volumes, and environment templates.
2. Add the initial Alembic schema, the environment-aware demo seed command, and one-shot `migrate` then `seed` prerequisites for API startup.
3. Start the demo stack from empty volumes, verify idempotent sample classes/accounts/materials, verify `/health` through the web gateway, and assert that only the web port is published.
4. Start the production configuration from empty volumes and verify it creates no sample rows or files; provision real classes and teacher/student accounts only through the containerized CLI.
5. Run backend, frontend, integration, Compose, and Playwright acceptance suites before promoting the images.

This is a greenfield deployment, so no existing data migration is required. Rollback uses the previous API/web images while retaining named volumes. A database migration is downgraded only when its documented downgrade is data-safe; otherwise restore the coordinated database/material backup taken before deployment.
