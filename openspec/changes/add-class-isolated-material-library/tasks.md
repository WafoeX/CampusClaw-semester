## 1. Project Foundations

- [ ] 1.1 Scaffold the Python 3.12 FastAPI project with application, domain, persistence, API, CLI, migration, and test packages; lock dependencies and verify a clean environment can install them and import the application.
- [ ] 1.2 Configure backend formatting, linting, type checking, and pytest with coverage; verify the empty baseline passes the documented quality command.
- [ ] 1.3 Scaffold the React + TypeScript + Vite project with routing, test utilities, linting, and production build scripts; verify lint, unit-test, type-check, and build commands pass.
- [ ] 1.4 Add validated backend settings for application environment, database URL, session HMAC key, cookie options, session lifetime, upload root, upload-size limit, demo-seed mode, and seed-only sample passwords; verify startup/seed tests reject missing or empty required values without printing them.
- [ ] 1.5 Add `.env.example`, ignore rules, and developer documentation that distinguish public build configuration, server-only secrets, and demo-only seed credentials; verify no usable secret or sample password is committed or emitted into a production web bundle.

## 2. PostgreSQL Schema and Provisioning

- [ ] 2.1 Define SQLAlchemy models for classes, users, sessions, and materials with the UUID keys, foreign keys, uniqueness, role/state checks, non-null class membership, expiry fields, and class-list indexes from D3; verify model metadata tests assert every required constraint and index.
- [ ] 2.2 Create the initial Alembic migration and downgrade policy for the complete schema; verify upgrade from an empty PostgreSQL database reaches head and schema inspection matches the models.
- [ ] 2.3 Implement database session and transaction helpers with explicit commit/rollback ownership; verify integration tests leave no partial rows after forced exceptions.
- [ ] 2.4 Implement the containerized class/user provisioning CLI with hidden password prompt, Argon2id hashing, validated role, and idempotent class selection/creation; verify CLI integration tests create teacher and student users without plaintext credentials in arguments, output, or storage.
- [ ] 2.5 Implement an environment-aware `seed-demo` command with stable seed identities for two classes, one teacher and one student per class, and at least one ready material per class; verify required passwords come only from environment variables, repeated runs create no duplicates or password resets, conflicting ownership fails visibly, and fault injection leaves no partial rows or files.

## 3. Authentication and Session Security

- [ ] 3.1 Implement Argon2id password hashing, verification, parameter calibration, and rehash-on-login support; verify unit tests cover valid, invalid, uniquely salted, and rehash-required cases.
- [ ] 3.2 Implement 256-bit opaque session tokens, HMAC token digests, session-bound CSRF tokens, bounded expiry, revocation, and expired-session cleanup; verify unit and PostgreSQL tests cover lookup, expiry, revocation, and digest-only persistence.
- [ ] 3.3 Implement the current-principal dependency that resolves active user ID, role, and class from the session cookie and rejects unknown, expired, inactive, or unsupported accounts; verify protected API tests return 401 without an HTML redirect.
- [ ] 3.4 Implement `POST /api/auth/login` with generic invalid-credential errors, secure cookie attributes, and credential-safe logging; verify teacher/student success and indistinguishable unknown-account/wrong-password 401 tests.
- [ ] 3.5 Implement `GET /api/auth/me` and `POST /api/auth/logout` with CSRF and Origin enforcement for state changes; verify identity data contains no credential fields and logout revokes reuse of the cookie.
- [ ] 3.6 Build the React authentication provider, login page, in-memory CSRF handling, protected-route guard, safe same-origin return target, and logout action; verify component tests cover successful login, failed login, redirect to `/login`, return navigation, and logout.

## 4. Authorization and Class Isolation

- [ ] 4.1 Implement reusable supported-role and teacher-only FastAPI dependencies; verify a student receives 403 on a minimal teacher-only test route while a teacher proceeds.
- [ ] 4.2 Implement class-scoped material repository methods whose signatures require `class_id` and whose list/detail/download predicates include it; verify repository tests cannot retrieve another class's rows even when their IDs are known.
- [ ] 4.3 Make material creation derive `class_id` and `uploader_id` exclusively from the current principal and reject or ignore client class selectors; verify integration tests cannot create a material for another class.
- [ ] 4.4 Normalize missing and cross-class material lookup failures to the same 404 status and response body; verify paired metadata and download tests compare both responses and confirm no file bytes are returned.
- [ ] 4.5 Add regression tests proving server-side enforcement is independent of web controls by calling protected APIs directly as unauthenticated, student, same-class teacher, and other-class users.

## 5. Material Storage and APIs

- [ ] 5.1 Implement bounded-chunk upload streaming to a same-volume temporary directory with byte counting, SHA-256, generated IDs, generated storage keys, display-filename sanitization, and path-containment checks; verify unit tests cover empty/malformed input, traversal names, hash accuracy, and boundary sizes.
- [ ] 5.2 Implement the `pending` row → atomic rename → `ready` row workflow with cleanup on every error branch; verify fault-injection tests at each step expose no partial material and leave no unintended temporary/final file.
- [ ] 5.3 Implement startup reconciliation for stale temporary files and stale pending rows/files without touching ready materials; verify recovery tests reproduce interrupted states and converge to a clean store.
- [ ] 5.4 Implement `POST /api/materials` for teachers with exactly one file, non-empty title, configured size enforcement, 201 metadata response, and 400/413 failures; verify API tests assert students create neither metadata nor files.
- [ ] 5.5 Implement class-scoped `GET /api/materials` and `GET /api/materials/{id}` with deterministic newest-first ordering and the specified metadata fields; verify empty, populated, tie-break, and cross-class integration tests.
- [ ] 5.6 Implement `GET /api/materials/{id}/download` as an attachment stream with safe content disposition, stored media type, content length, and pre-stream file checks; verify downloaded bytes match stored size and SHA-256 and missing files never return a partial 200 response.
- [ ] 5.7 Build React material list, metadata display, download action, teacher-only upload route/form, progress/error states, and post-upload refresh; verify component tests show no upload control for students and include the new record after teacher upload.

## 6. Gateway, Compose, and Readiness

- [ ] 6.1 Create production multi-stage Dockerfiles for the FastAPI image and React/Nginx web image using locked dependencies and non-root runtime users where compatible; verify both images build reproducibly and start without source bind mounts.
- [ ] 6.2 Configure Nginx SPA fallback, `/api/*` and `/health` reverse proxies, forwarded headers, body-size ceiling, attachment-safe headers, CSP, frame restrictions, and `nosniff`; verify proxy tests serve routes and reject bodies above the gateway ceiling.
- [ ] 6.3 Implement unauthenticated `GET /health` checks for database connectivity, Alembic head, and writable material storage with non-secret responses; verify healthy and each dependency-failure case return the expected 200/non-2xx status.
- [ ] 6.4 Create Docker Compose services for `web`, `api`, one-shot `migrate`, one-shot `seed`, and `db`, with migrate→seed→API dependency ordering, demo-enabled and production-disabled seed defaults, health checks, internal gateway/data networks, PostgreSQL/material named volumes, and only the web gateway in `ports`; verify `docker compose config` and published-port inspection show no host binding for FastAPI or PostgreSQL.
- [ ] 6.5 Start the demo stack from empty volumes and verify migration and seeding complete before API readiness, both sample classes/accounts/materials are available, `/health` succeeds through the web port, protected APIs work through Nginx, and direct host connections to API/database ports fail.
- [ ] 6.6 Recreate all demo service containers without deleting volumes and verify sample data is not duplicated, changed sample-account passwords are not reset, and provisioned accounts, material metadata, and uploaded file bytes remain available.

## 7. End-to-End Security and Behavior Verification

- [ ] 7.1 Add PostgreSQL-backed API integration fixtures aligned with the stable demo manifest for two classes, teacher/student accounts, isolated session cookies, and temporary material storage; verify tests cleanly repeat without sharing state or plaintext passwords.
- [ ] 7.2 Add Playwright scenarios using environment-supplied sample credentials for unauthenticated protected-page redirect, preloaded class-specific materials, teacher login/upload/list/download/logout, student login/read/no-upload control, and invalid credentials; verify the suite passes only through the published web gateway.
- [ ] 7.3 Add adversarial Playwright/API scenarios for direct student upload, forged class fields, known cross-class IDs, filename traversal, oversize upload, expired sessions, missing files, and CSRF failure; verify expected 400/401/403/404/413 outcomes and absence of leaked data or partial storage.
- [ ] 7.4 Add an acceptance assertion that inspects the running Compose stack and fails if any host port other than the documented web port is published; verify it detects deliberately added API or database mappings.
- [ ] 7.5 Start the production Compose configuration from empty volumes without explicitly enabling seeding and verify no sample class, account, material row, or sample file exists; then explicitly enable seeding with required environment passwords and verify the documented override works.
- [ ] 7.6 Run backend formatting/lint/type/unit/integration coverage, frontend lint/type/unit/build, Docker image builds, demo and production Compose acceptance, Playwright, and non-interactive `openspec validate --changes --strict`; record a passing verification summary with exact commands and results.

## 8. Operations Documentation

- [ ] 8.1 Document demo and production startup, secure environment generation, sample-account password setup, seed idempotency and production-disable behavior, HTTPS/Secure-cookie expectations, migrations, health checks, real-account provisioning, volume lifecycle, and the internal-only API/database topology; verify a fresh operator can start and inspect both configurations using only the documentation.
- [ ] 8.2 Document coordinated PostgreSQL and material-volume backup/restore with an upload-quiescing maintenance window and rollback precautions; verify a test backup restores accounts, metadata, and matching file SHA-256 values.
- [ ] 8.3 Document current limits and semester non-goals, including single API writer, local volume storage, no content execution/inline rendering, material search/question answering, intelligent conversation, assignment submission, registration/password recovery, and skill toggles; verify the documentation agrees with README, AGENTS, the proposal, specs, and design.
