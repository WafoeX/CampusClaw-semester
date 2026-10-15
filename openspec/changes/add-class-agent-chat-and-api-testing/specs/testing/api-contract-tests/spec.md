## Purpose

定义可在隔离本地 Docker Compose 环境中一键执行的黑盒接口验收套件，使每个接口由按 URL 和方法组织的独立脚本验证响应契约、权限边界及 PostgreSQL 持久化一致性，并生成不入库的 HTML 报告。

## ADDED Requirements

### Requirement: API test cases are organized one operation per script
The repository SHALL contain an `apitest/` suite whose case directories mirror URL path segments beneath `apitest/cases/` and whose script filename is the uppercase HTTP method plus `.py`. Each script SHALL target exactly one documented path-and-method operation, although it MAY contain multiple scenarios for that operation.

#### Scenario: Login case is located
- **WHEN** a maintainer looks for the `POST /api/auth/login` test
- **THEN** the operation's scenarios are in `apitest/cases/api/auth/login/POST.py`

#### Scenario: One path supports multiple methods
- **WHEN** a documented path supports more than one HTTP method
- **THEN** each method has a separate uppercase method script in the same mirrored path directory

#### Scenario: Shared setup is required
- **WHEN** cases need HTTP, authentication, database, fixture, SSE, or reporting helpers
- **THEN** reusable support code lives outside operation scripts and does not combine multiple operations into one case script

### Requirement: A single runner executes all cases and writes an HTML report
The suite SHALL provide `apitest/run_all.py` that deterministically discovers operation scripts, executes all cases, returns a nonzero process status when any case fails or cannot run, and writes a timestamped HTML report containing per-case status, duration, safe assertion details, and a summary.

#### Scenario: All cases pass
- **WHEN** the isolated environment is ready and every discovered case passes
- **THEN** `run_all.py` exits zero and writes an HTML report showing all cases passed

#### Scenario: One case fails
- **WHEN** any response, database, isolation, or stream assertion fails
- **THEN** the runner continues collecting bounded results, exits nonzero, and identifies the failed operation and safe assertion in the report

#### Scenario: Report output is considered for commit
- **WHEN** Git status is inspected after a test run
- **THEN** generated HTML reports and other generated test artifacts are ignored and are not tracked

### Requirement: Tests run against an isolated local Compose environment
The suite SHALL use a dedicated local Docker Compose test configuration with isolated project resources, a test database, controlled seed data, and deterministic OpenAI-compatible embedding and generation substitutes. Test configuration SHALL use non-production credentials, SHALL NOT call an unapproved external model endpoint, and SHALL expose database access only to the local test runner or internal test network.

#### Scenario: Test environment starts
- **WHEN** the documented API test startup command is run on a machine with Docker Compose
- **THEN** migration, seed, model substitute, indexer, API, gateway, and test database become ready without using production volumes or credentials

#### Scenario: Existing development stack is running
- **WHEN** the API test stack starts with its documented isolated project name and ports
- **THEN** it does not reuse, migrate, truncate, or overwrite the development or production database and volumes

#### Scenario: External model configuration is absent
- **WHEN** tests exercise retrieval and chat generation
- **THEN** requests use the deterministic local substitutes and no question, history, prompt, or material content leaves the test environment

### Requirement: Cases assert response semantics, not only status codes
Every operation script SHALL validate the documented response media type and schema plus operation-specific values, error codes, authorization behavior, and cross-class or ownership behavior where applicable. Streaming cases SHALL parse SSE framing, event order, sequence numbers, terminal state, assembled answer, and citations.

#### Scenario: Login succeeds
- **WHEN** the login case uses the controlled valid account
- **THEN** it verifies the Bearer token metadata and safe identity fields rather than checking HTTP 200 alone

#### Scenario: Login fails
- **WHEN** the login case uses an unknown account and a wrong password
- **THEN** both responses conform to the same generic HTTP 401 error contract and expose no account existence detail

#### Scenario: Streamed message completes
- **WHEN** the message case sends one question in a created conversation
- **THEN** it verifies the documented SSE content type, event order, stable identifiers, assembled guidance response, current-turn citation, and terminal completion data

#### Scenario: Cross-class identifier is used
- **WHEN** a case uses an identifier belonging to another seeded class
- **THEN** the response is indistinguishable in status and body shape from the corresponding nonexistent identifier

### Requirement: Mutation cases verify PostgreSQL consistency
For every tested operation that creates, updates, publishes, retires, soft-deletes, or appends persistent data, the suite SHALL query the isolated PostgreSQL database using a least-privileged test-only connection and compare the authoritative rows and relationships with the API response. Database checks SHALL include server-derived class and owner fields and SHALL fail on unexpected duplicate or partial rows.

#### Scenario: Agent and skill are persisted
- **WHEN** the prompt/skill workflow creates a skill, creates an agent, binds the skill, and publishes the agent
- **THEN** database assertions confirm the returned identifiers, creating teacher, class, sanitized configuration, one binding, and published state

#### Scenario: Conversation and one message are persisted
- **WHEN** the chat workflow creates a conversation and completes one streamed message
- **THEN** database assertions confirm the student and class scope, selected agent, one user message, one completed assistant message, applied configuration version, and citations matching the stream

#### Scenario: Unauthorized mutation is attempted
- **WHEN** a student, other creator, or other-class principal attempts a forbidden mutation
- **THEN** database assertions confirm that no target row, binding, message, status, or ownership value changed

### Requirement: Minimum acceptance coverage spans the requested workflows
The committed suite SHALL at minimum cover login, class-scoped retrieval, teacher prompt and solution-guidance skill management, agent publication, student conversation creation, and sending one streamed message. It SHALL include positive, validation, unauthenticated, unauthorized, nonexistent, and cross-class cases required by the corresponding API contracts.

#### Scenario: Required coverage is discovered
- **WHEN** `run_all.py` lists discovered cases
- **THEN** at least one operation script covers each required workflow and the report groups results by URL and HTTP method

#### Scenario: Knowledge retrieval is checked
- **WHEN** retrieval cases query controlled same-class and other-class material facts
- **THEN** same-class evidence produces the expected cited result while other-class-only evidence produces the exact ordinary insufficient-evidence response

#### Scenario: Guidance behavior is checked
- **WHEN** the controlled student asks the published solution-guidance agent for a direct final answer
- **THEN** the deterministic response and persisted assistant message satisfy the guidance contract and do not directly present the configured final answer

### Requirement: Test outputs and diagnostics protect secrets and content
The runner, console output, and HTML report SHALL redact Authorization headers, passwords, database credentials, model keys, hidden prompts, and raw provider payloads. Failure evidence SHALL be bounded and SHALL avoid including full student messages, material bodies, or private skill instructions unless an explicit local debugging mode is enabled outside generated reports.

#### Scenario: Authentication assertion fails
- **WHEN** a case fails after obtaining a token
- **THEN** neither console output nor the HTML report includes the token or password

#### Scenario: Generation assertion fails
- **WHEN** a streamed answer or model substitute response violates expectations
- **THEN** the report contains a safe bounded diagnostic rather than hidden prompts or raw provider bodies
