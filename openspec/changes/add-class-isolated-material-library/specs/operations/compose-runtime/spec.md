## Purpose

Define a repeatable Docker Compose runtime with persistent application data, validated server configuration, and observable health.

## ADDED Requirements

### Requirement: Application starts with Docker Compose
The system SHALL provide a Docker Compose configuration that starts the web client, API, one-shot migration and environment-aware seed services, and PostgreSQL with documented environment configuration and service dependencies.

#### Scenario: Valid configuration is started
- **WHEN** an operator supplies the required environment values and runs the documented Docker Compose startup command
- **THEN** the database becomes ready, the API becomes healthy, and the web application is reachable through its documented port

#### Scenario: Required configuration is absent
- **WHEN** a required database, JWT signing, or storage configuration value is missing
- **THEN** the affected service refuses to become ready and reports a configuration error without printing secret values

### Requirement: API and database ports remain internal
The Compose runtime SHALL publish only the web gateway port to the host. The FastAPI and PostgreSQL services SHALL be reachable by service name on an internal Compose network and SHALL NOT publish their service ports to host interfaces. The web gateway SHALL proxy same-origin API and health requests to FastAPI.

#### Scenario: Operator inspects published ports
- **WHEN** the Compose stack is running
- **THEN** only the documented web gateway port is published and neither the FastAPI port nor the PostgreSQL port is bound on the host

#### Scenario: Browser calls an API
- **WHEN** the browser requests a same-origin `/api/` path through the published web gateway
- **THEN** the gateway proxies the request to FastAPI over the internal Compose network

#### Scenario: Client calls health through the gateway
- **WHEN** a client requests `/health` through the published web gateway
- **THEN** the gateway proxies the request to the API health endpoint without requiring authentication

### Requirement: Demo environment provides idempotent sample data
The Compose runtime SHALL support an environment-controlled, idempotent seed step that runs after database migration. Demo configuration SHALL enable seeding by default, while production configuration SHALL disable it by default. When enabled, the seed step SHALL create at least two classes, one teacher and one student in each class, and at least one ready material owned by each class. Sample account passwords SHALL come from server-side environment variables and SHALL be persisted only as adaptive password hashes.

#### Scenario: Demo stack starts from empty volumes
- **WHEN** the demo Compose configuration starts from empty database and material volumes with required sample passwords supplied
- **THEN** both sample classes, their teacher and student accounts, and their class-owned ready materials are available after migration and seeding complete

#### Scenario: Sample users exercise class boundaries
- **WHEN** a sample user logs in and requests materials
- **THEN** the user can see their own class's sample material and cannot obtain the other class's material

#### Scenario: Seed step is repeated
- **WHEN** the seed step runs again against already seeded data
- **THEN** it succeeds without duplicating classes, accounts, materials, or files and without resetting existing passwords or user-created data

#### Scenario: Enabled seed lacks required passwords
- **WHEN** demo seeding is enabled but a required sample-account password environment variable is absent or empty
- **THEN** the seed step fails without creating partially usable sample accounts and does not print password values

#### Scenario: Production stack starts
- **WHEN** the production Compose configuration starts without explicitly enabling demo seeding
- **THEN** no sample class, account, material metadata, or sample material file is created

### Requirement: Database schema is applied before serving traffic
The system SHALL apply versioned database migrations before the API reports readiness or serves protected operations.

#### Scenario: Empty database starts
- **WHEN** the stack starts against an empty PostgreSQL volume
- **THEN** all required schema migrations complete before the API reports healthy

#### Scenario: Migration fails
- **WHEN** a required database migration cannot be applied
- **THEN** the API does not report healthy or serve protected application traffic

### Requirement: Database and material files persist
The Compose runtime SHALL store PostgreSQL data and uploaded material files in persistent volumes that survive ordinary service and container recreation.

#### Scenario: Services are recreated
- **WHEN** the operator recreates containers without deleting persistent volumes
- **THEN** existing accounts, material metadata, and uploaded files remain available, and previously issued JWTs remain valid only while their configured signing key and expiration remain valid

### Requirement: Health endpoint reports readiness
The API SHALL expose unauthenticated `GET /health` and SHALL return HTTP 200 only when the API process, database connection, required schema, and material-storage location are ready for normal requests.

#### Scenario: All dependencies are ready
- **WHEN** an unauthenticated client calls `GET /health` while all required dependencies are usable
- **THEN** the API returns HTTP 200 with a non-secret readiness response

#### Scenario: A required dependency is unavailable
- **WHEN** the database, required schema, or material-storage location is unavailable
- **THEN** `GET /health` returns a non-2xx status and discloses no credentials or secret values
