## Purpose

提供与 CampusClaw 同仓构建运行的只读教学 MCP 演示服务，让验收能够独立检查协议与工具结果，并通过真实内部网络证明主机完成远端工具调用，而不是仅使用主机逻辑替身。

## ADDED Requirements

### Requirement: Demo server exposes authenticated JSON-RPC tools
The demo server SHALL expose public `GET /health` and Bearer-protected `POST /mcp` using JSON-RPC 2.0. It SHALL support `initialize`, `notifications/initialized`, `tools/list`, and `tools/call`, negotiate protocol version `2024-11-05`, and advertise only implemented tool capabilities. Every `/mcp` request, including notifications, SHALL require the runtime token.

#### Scenario: Initialization and discovery succeed
- **WHEN** a client sends valid authenticated initialize, initialized notification, and tools/list requests
- **THEN** initialize returns the negotiated version and tools capability, the notification returns HTTP 202 without a JSON-RPC response, and discovery returns names, descriptions, and input schemas

#### Scenario: Credentials are absent or incorrect
- **WHEN** a client sends any /mcp request without the correct Bearer token
- **THEN** the server returns HTTP 401 without executing a method or exposing the configured token

#### Scenario: Invalid request is submitted
- **WHEN** an authenticated client submits invalid JSON, an invalid JSON-RPC envelope, an unknown method, or invalid method parameters
- **THEN** it receives a readable JSON-RPC error using respectively -32700, -32600, -32601, or -32602, with the valid request ID echoed when available and no internal traceback

### Requirement: Demo tools return bounded deterministic text
The service SHALL discover and execute `formula_hint` and `unit_convert`, with names matching `^[a-z][a-z0-9_]*$`. Both SHALL accept a bounded `question` string and return MCP text content. Formula hints SHALL provide a known formula's applicability and checking hints rather than a final homework answer; unit conversion SHALL support a documented finite unit set without executing user expressions. Unsupported questions SHALL return an explicit safe text outcome, not invented results.

#### Scenario: Formula hint is requested
- **WHEN** tools/call invokes formula_hint with a supported formula question
- **THEN** the result contains at least one text content item with a deterministic formula hint

#### Scenario: Unit conversion is requested
- **WHEN** tools/call invokes unit_convert with the documented question “将 100 cm 转换为 m”
- **THEN** the text result identifies 1 m and the conversion relationship

#### Scenario: Invalid or unsupported arguments are supplied
- **WHEN** a call contains unknown fields, a missing or oversized question, or an unsupported conversion
- **THEN** invalid schemas receive -32602 and semantically unsupported conversions return a bounded tool result marked isError true

### Requirement: Demo is deployed with runtime-only credentials
The repository SHALL contain `mcp-server/` and build it as service `mcp-demo` from the main docker-compose.yml. CampusClaw API SHALL reach its Base URL `http://mcp-demo:8090` over a shared internal network. The MCP token SHALL come only from runtime environment injection, never from tracked configuration, build arguments, image layers, or frontend assets. Missing or blank token SHALL prevent the MCP service from starting securely.

#### Scenario: Compose starts the application
- **WHEN** the operator supplies MCP_AUTH_TOKEN in the local .env and builds and starts the main stack
- **THEN** the API can discover and call the actual MCP container, while MCP port 8090 is not published to the host by default

#### Scenario: Health is checked independently
- **WHEN** an operator checks /health and performs authenticated tools/list and tools/call from the internal network
- **THEN** health returns success without credentials and the two protocol calls return the actual implemented tools and text results

#### Scenario: Build and frontend artifacts are inspected
- **WHEN** tracked files, image build history/layers, logs, or frontend bundles are inspected
- **THEN** none contains the runtime MCP token
