## 1. Project Foundations

- [x] 1.1 Scaffold the Python 3.12 FastAPI project with application, domain, persistence, API, CLI, migration, and test packages; lock dependencies and verify a clean environment can install them and import the application.
- [x] 1.2 Configure backend formatting, linting, type checking, and pytest with coverage; verify the empty baseline passes the documented quality command.
- [x] 1.3 Scaffold the React + TypeScript + Vite project with routing, test utilities, linting, and production build scripts; verify lint, unit-test, type-check, and build commands pass.
- [x] 1.4 Replace session/cookie settings with validated server-only JWT signing key and bounded access-token lifetime settings; verify startup rejects missing or empty signing values without printing them.
- [x] 1.5 Add `.env.example`, ignore rules, and developer documentation that distinguish public build configuration, server-only secrets, and demo-only seed credentials; verify no usable secret or sample password is committed or emitted into a production web bundle.

## 2. PostgreSQL Schema and Provisioning

- [x] 2.1 Remove the SQLAlchemy session model and its schema metadata while retaining classes, users, and materials with the UUID keys, foreign keys, uniqueness, role/state checks, non-null class membership, and class-list indexes from D3; verify model metadata tests assert that no sessions table is declared.
- [x] 2.2 Create an Alembic migration from the deployed session schema that drops the legacy sessions table and its indexes, with a documented destructive downgrade; verify upgrade reaches head and schema inspection matches the JWT-only models.
- [x] 2.3 Implement database session and transaction helpers with explicit commit/rollback ownership; verify integration tests leave no partial rows after forced exceptions.
- [x] 2.4 Implement the containerized class/user provisioning CLI with hidden password prompt, Argon2id hashing, validated role, and idempotent class selection/creation; verify CLI integration tests create teacher and student users without plaintext credentials in arguments, output, or storage.
- [x] 2.5 Implement an environment-aware `seed-demo` command with stable seed identities for two classes, one teacher and one student per class, and at least one ready material per class; verify required passwords come only from environment variables, repeated runs create no duplicates or password resets, conflicting ownership fails visibly, and fault injection leaves no partial rows or files.

## 3. Authentication and Session Security

- [x] 3.1 Implement Argon2id password hashing, verification, parameter calibration, and rehash-on-login support; verify unit tests cover valid, invalid, uniquely salted, and rehash-required cases.
- [x] 3.2 Implement bounded HS256 JWT access-token issue and validation with issuer, audience, `sub`, `iat`, and `exp` claims; verify unit tests reject expired, malformed, missing-claim, wrong-key, wrong-algorithm, wrong-issuer, and wrong-audience tokens.
- [x] 3.3 Implement the current-principal dependency that reads only an Authorization Bearer token, validates it, then resolves current active user ID, role, and class from the database; verify protected API tests reject cookie-only, missing, malformed, expired, inactive, and unsupported credentials with JSON 401 responses.
- [x] 3.4 Implement `POST /api/auth/login` with generic invalid-credential errors, a safe JWT access-token response, and credential/token-safe logging; verify teacher/student success and indistinguishable unknown-account/wrong-password 401 tests.
- [x] 3.5 Implement Bearer-authenticated `GET /api/auth/me` and idempotent `POST /api/auth/logout` without cookies or CSRF state; verify identity data contains no credential/token fields, logout returns 204, and a formerly used token remains valid until expiry as specified.
- [x] 3.6 Build the React authentication provider, login page, localStorage access-token handling, Bearer-header API/download client, protected-route guard, safe same-origin return target, and logout action; verify component tests cover reload restoration, successful and failed login, redirect, authenticated request headers, 401 token cleanup, download, and logout.

## 4. Authorization and Class Isolation

- [x] 4.1 Implement reusable supported-role and teacher-only FastAPI dependencies; verify a student receives 403 on a minimal teacher-only test route while a teacher proceeds.
- [x] 4.2 Implement class-scoped material repository methods whose signatures require `class_id` and whose list/detail/download predicates include it; verify repository tests cannot retrieve another class's rows even when their IDs are known.
- [x] 4.3 Make material creation derive `class_id` and `uploader_id` exclusively from the current principal and reject or ignore client class selectors; verify integration tests cannot create a material for another class.
- [x] 4.4 Normalize missing and cross-class material lookup failures to the same 404 status and response body; verify paired metadata and download tests compare both responses and confirm no file bytes are returned.
- [x] 4.5 Add regression tests proving server-side enforcement is independent of web controls by calling protected APIs directly as unauthenticated, student, same-class teacher, and other-class users.

## 5. Material Storage and APIs

- [x] 5.1 Implement bounded-chunk upload streaming to a same-volume temporary directory with byte counting, SHA-256, generated IDs, generated storage keys, display-filename sanitization, and path-containment checks; verify unit tests cover empty/malformed input, traversal names, hash accuracy, and boundary sizes.
- [x] 5.2 Implement the `pending` row → atomic rename → `ready` row workflow with cleanup on every error branch; verify fault-injection tests at each step expose no partial material and leave no unintended temporary/final file.
- [x] 5.3 Implement startup reconciliation for stale temporary files and stale pending rows/files without touching ready materials; verify recovery tests reproduce interrupted states and converge to a clean store.
- [x] 5.4 Implement `POST /api/materials` for teachers with exactly one file, non-empty title, configured size enforcement, 201 metadata response, and 400/413 failures; verify API tests assert students create neither metadata nor files.
- [x] 5.5 Implement class-scoped `GET /api/materials` and `GET /api/materials/{id}` with deterministic newest-first ordering and the specified metadata fields; verify empty, populated, tie-break, and cross-class integration tests.
- [x] 5.6 Implement `GET /api/materials/{id}/download` as an attachment stream with safe content disposition, stored media type, content length, and pre-stream file checks; verify downloaded bytes match stored size and SHA-256 and missing files never return a partial 200 response.
- [x] 5.7 Build React material list, metadata display, download action, teacher-only upload route/form, progress/error states, and post-upload refresh; verify component tests show no upload control for students and include the new record after teacher upload.

## 6. Gateway, Compose, and Readiness

- [x] 6.1 Create production multi-stage Dockerfiles for the FastAPI image and React/Nginx web image using locked dependencies and non-root runtime users where compatible; verify both images build reproducibly and start without source bind mounts.
- [x] 6.2 Configure Nginx SPA fallback, `/api/*` and `/health` reverse proxies, forwarded headers, body-size ceiling, attachment-safe headers, CSP, frame restrictions, and `nosniff`; verify proxy tests serve routes and reject bodies above the gateway ceiling.
- [x] 6.3 Implement unauthenticated `GET /health` checks for database connectivity, Alembic head, and writable material storage with non-secret responses; verify healthy and each dependency-failure case return the expected 200/non-2xx status.
- [x] 6.4 Create Docker Compose services for `web`, `api`, one-shot `migrate`, one-shot `seed`, and `db`, with migrate→seed→API dependency ordering, demo-enabled and production-disabled seed defaults, health checks, internal gateway/data networks, PostgreSQL/material named volumes, and only the web gateway in `ports`; verify `docker compose config` and published-port inspection show no host binding for FastAPI or PostgreSQL.
- [x] 6.5 Start the demo stack from empty volumes and verify migration and seeding complete before API readiness, both sample classes/accounts/materials are available, `/health` succeeds through the web port, protected APIs work through Nginx, and direct host connections to API/database ports fail.
- [x] 6.6 Recreate all demo service containers without deleting volumes and verify sample data is not duplicated, changed sample-account passwords are not reset, and provisioned accounts, material metadata, and uploaded file bytes remain available.

## 7. End-to-End Security and Behavior Verification

- [x] 7.1 Update PostgreSQL-backed API integration fixtures for the stable demo manifest, teacher/student JWT Bearer tokens, and temporary material storage; verify tests cleanly repeat without persisting plaintext passwords or tokens.
- [x] 7.2 Add Playwright scenarios using environment-supplied sample credentials for unauthenticated protected-page redirect, preloaded class-specific materials, teacher login/upload/list/download/logout, student login/read/no-upload control, and invalid credentials; verify the suite passes only through the published web gateway.
- [x] 7.3 Update adversarial Playwright/API scenarios for direct student upload, forged class fields, known cross-class IDs, filename traversal, oversize upload, missing files, and missing/malformed/expired/tampered Bearer tokens; verify expected 400/401/403/404/413 outcomes and absence of leaked data or partial storage.
- [x] 7.4 Add an acceptance assertion that inspects the running Compose stack and fails if any host port other than the documented web port is published; verify it detects deliberately added API or database mappings.
- [x] 7.5 Start the production Compose configuration from empty volumes without explicitly enabling seeding and verify no sample class, account, material row, or sample file exists; then explicitly enable seeding with required environment passwords and verify the documented override works.
- [x] 7.6 Run backend formatting/lint/type/unit/integration coverage, frontend lint/type/unit/build, Docker image builds, demo and production Compose acceptance, Playwright, and non-interactive `openspec validate --changes --strict`; record a passing verification summary with exact commands and results.

## 8. Operations Documentation

- [x] 8.1 Update documentation for demo and production startup, secure JWT signing-key generation, bounded token lifetimes, localStorage/XSS risk, migration logout effect, seed behavior, health checks, real-account provisioning, volume lifecycle, and the internal-only API/database topology; verify a fresh operator can start and inspect both configurations using only the documentation.
- [x] 8.2 Document coordinated PostgreSQL and material-volume backup/restore with an upload-quiescing maintenance window and rollback precautions; verify a test backup restores accounts, metadata, and matching file SHA-256 values.
- [x] 8.3 Document current limits and semester non-goals, including single API writer, local volume storage, no content execution/inline rendering, material search/question answering, intelligent conversation, assignment submission, registration/password recovery, and skill toggles; verify the documentation agrees with README, AGENTS, the proposal, specs, and design.
