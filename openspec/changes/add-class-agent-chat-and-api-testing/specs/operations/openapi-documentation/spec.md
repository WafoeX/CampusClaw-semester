## Purpose

定义可由浏览器访问和试调的 OpenAPI/Swagger 契约，使调用方能够准确识别各主要接口的路径、参数、响应、错误与 Bearer 认证要求，并避免文档泄露服务端秘密。

## ADDED Requirements

### Requirement: The service publishes a valid OpenAPI description
The system SHALL expose a machine-readable OpenAPI document that includes every supported public and protected HTTP API path, operation identifier, HTTP method, tag, summary, request parameters or body schema, success response schema, documented error responses, and content type.

#### Scenario: Client loads the OpenAPI document
- **WHEN** a client requests the documented OpenAPI JSON path
- **THEN** the system returns a valid OpenAPI document describing the currently deployed API version

#### Scenario: Major interface is inspected
- **WHEN** a caller inspects login, identity, material, knowledge query, agent, skill, conversation, or streaming message operations
- **THEN** each operation documents its input, output, error codes, media types, and authentication requirement

#### Scenario: Streaming operation is inspected
- **WHEN** a caller inspects the conversation message operation
- **THEN** the document identifies `text/event-stream`, describes every SSE event name and payload schema, and distinguishes pre-stream HTTP errors from terminal stream error events

### Requirement: Bearer authentication is explicit and usable in Swagger
The OpenAPI document SHALL define one HTTP Bearer JWT security scheme. Every protected operation SHALL reference it, and public login, logout, health, OpenAPI, and Swagger resources SHALL explicitly omit a login requirement. Swagger UI SHALL provide an authorization control whose token is sent in the `Authorization: Bearer <token>` header when protected operations are tried.

#### Scenario: User authorizes Swagger
- **WHEN** a user enters a valid access token through Swagger UI and tries a protected operation
- **THEN** the request carries exactly one Bearer authorization header and can be handled as the same principal as a non-Swagger client

#### Scenario: Protected operation has no token
- **WHEN** a caller tries a protected operation without authorization
- **THEN** the documented and actual response is HTTP 401 with the standard unauthenticated error shape

#### Scenario: Public operation is inspected
- **WHEN** a caller views login, logout, health, OpenAPI, or Swagger resources
- **THEN** the documentation does not claim that Bearer authentication is required

### Requirement: Responses and errors use reusable documented schemas
The system SHALL document reusable schemas for validation errors and domain errors, including a stable machine-readable code and safe message. Each operation SHALL list all behaviorally expected status codes, including applicable 400, 401, 403, 404, 409, 413, and 503 responses, without exposing raw framework or provider internals.

#### Scenario: Agent publication conflict is inspected
- **WHEN** a caller views the publish operation
- **THEN** HTTP 409 and its publication-readiness error schema are documented alongside the success response

#### Scenario: Cross-class resource is requested
- **WHEN** a protected identifier refers to an inaccessible other-class resource
- **THEN** the actual HTTP 404 body conforms to the same documented schema used for a nonexistent resource

#### Scenario: Request validation fails
- **WHEN** an input violates a documented bound or includes a forbidden field
- **THEN** the actual error status and body conform to the documented validation schema

### Requirement: Swagger UI is browser-accessible through the deployed gateway
The system SHALL serve Swagger UI at a documented same-origin browser path through the Web gateway, and that UI SHALL load its OpenAPI document and try supported API operations without requiring direct host access to the internal API port.

#### Scenario: User opens Swagger through the gateway
- **WHEN** the local Compose stack is healthy and a browser opens the documented Swagger path on the Web origin
- **THEN** the page loads successfully and resolves the OpenAPI description from the same origin

#### Scenario: User tries a main workflow
- **WHEN** a user logs in through Swagger, authorizes with the returned token, and invokes a documented main protected endpoint
- **THEN** the request reaches the API through the gateway and its response is shown against the declared schema

### Requirement: API documentation contains no secrets or private prompt content
The OpenAPI document and Swagger assets SHALL NOT contain credentials, example access tokens, database URLs, model endpoint secrets, hidden platform prompts, teacher prompt contents, skill instruction contents, student messages, or material text. Example identifiers and payloads SHALL be synthetic and non-sensitive.

#### Scenario: Documentation is downloaded
- **WHEN** a caller reads the OpenAPI JSON or Swagger assets
- **THEN** no runtime secret, private configuration value, prompt content, conversation content, or class data is present
