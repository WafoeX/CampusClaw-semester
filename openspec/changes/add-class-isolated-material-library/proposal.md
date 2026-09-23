## Why

The project needs a secure, containerized foundation for class-scoped teaching-material sharing. Authentication, server-enforced authorization, and class isolation must be defined together so that uploaded materials cannot be exposed across roles or class boundaries.

## What Changes

- Add account/password login for teachers and students, with server-managed sessions and login redirection for unauthenticated page access.
- Store passwords only as adaptive password hashes and load application secrets only from server-side environment variables.
- Add server-side role authorization so only teachers can upload materials and student upload attempts are rejected.
- Make each user belong to exactly one class and enforce that class as the data boundary for every material read, list, and upload operation.
- Add a class-scoped material library that stores uploaded files and metadata, lists materials for the authenticated user's class, and supports authorized download.
- Provide idempotent demo seed data with two isolated classes, teacher/student accounts, and class-owned materials; enable it by default for the demo environment and disable it by default for production.
- Add a Docker Compose runtime with persistent data volumes, an unauthenticated `GET /health` readiness endpoint, and no host-published API or database port.
- Keep material search and question answering, intelligent conversation, assignment submission, registration, password recovery, and skill toggles out of scope for this semester.

## Capabilities

### New Capabilities
- `identity/user-authentication`: Account/password login, protected-resource behavior, sessions, password hashing, logout, and server-side secret handling.
- `identity/role-authorization`: Teacher/student role permissions, including teacher-only material upload enforced by the server.
- `identity/class-isolation`: Single-class membership and uniform server-side class filtering for material operations.
- `materials/material-library`: Upload, persist, list, inspect, and download class-scoped teaching materials and their metadata.
- `operations/compose-runtime`: Docker Compose startup, environment-aware demo seeding, persistent storage, configuration validation, and health reporting.

### Modified Capabilities

None. The project has no existing capability specifications.

## Impact

- Introduces the initial application, API, web UI, persistence schema, file-storage layout, authentication/session layer, and authorization middleware.
- Adds password-hashing, database, upload-processing, and test dependencies.
- Adds container images, Docker Compose configuration, an internal-only API/database network boundary, an idempotent demo-seed lifecycle, persistent volumes, environment configuration, and operational documentation.
- Establishes externally visible login, logout, health, and material APIs plus protected browser pages.
