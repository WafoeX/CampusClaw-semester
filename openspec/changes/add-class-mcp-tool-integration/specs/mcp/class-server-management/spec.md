## Purpose

定义教师在会话班级内管理 MCP 服务器、握手发现、撤销连接及查看最小调用审计的行为边界，确保学生只能经服务端执行已授权工具，错误不会阻断既有检索和流式聊天。

## ADDED Requirements

### Requirement: Teachers register servers within the authenticated class
The system SHALL let teachers register and list class-shared MCP servers using a unique class-local immutable name and Base URL. Class scope SHALL come only from the authenticated principal. Names SHALL match `^[a-z][a-z0-9-]{0,62}$`. All teachers in the same class SHALL be allowed to manage these server registrations; this SHALL NOT broaden existing creator-only agent, skill, or conversation-content access. Only deployment-approved Base URLs SHALL be accepted. Raw MCP credentials SHALL neither be accepted from browsers nor returned in responses.

#### Scenario: Teacher registers the demo
- **WHEN** a teacher registers campus-tools at approved Base URL http://mcp-demo:8090
- **THEN** the server is stored as disconnected in the teacher's class and the response contains no token or authorization header

#### Scenario: Other roles and classes access management
- **WHEN** a student requests server management or a teacher addresses another class's server ID
- **THEN** the student receives HTTP 403 and the teacher receives the ordinary missing-resource HTTP 404 without contacting the remote server

#### Scenario: Registration is invalid
- **WHEN** a teacher supplies a duplicate class-local name, an invalid name, client scope fields, URL credentials, or a non-approved URL
- **THEN** the system rejects the request with a documented 409 for duplicates or 400 for invalid input and creates no registration

### Requirement: Connecting atomically caches discovered tools
The system SHALL connect using the server-side runtime credential, completing initialize, initialized notification, and tools/list before marking a server connected. It SHALL cache only validated bounded tool metadata from that connection generation. Failed handshakes, missing credentials, invalid discovery, or authentication failures SHALL leave no usable cached tools and SHALL return a safe actionable error. Tool names SHALL obey `^[a-z][a-z0-9_]*$`.

#### Scenario: Connection succeeds
- **WHEN** a teacher connects a registered demo server
- **THEN** the UI and tools endpoint show connected status and discovered formula_hint and unit_convert without exposing secrets

#### Scenario: Connection fails
- **WHEN** initialization, remote authorization, protocol negotiation, discovery validation, or network timeout fails
- **THEN** connect returns HTTP 503 with a safe failure code, the UI explains the failure, and existing knowledge query and chat endpoints remain usable

### Requirement: Disconnect invalidates discovery and future dispatch
The system SHALL permit teachers to disconnect a class server idempotently, clear its discovery cache, and invalidate prior connection generations. A tool dispatch SHALL recheck current class, connection generation, cached tool membership, and credential availability before sending any request. Calls already dispatched before disconnect MAY complete remotely, but their stale results SHALL NOT be used in a later answer and SHALL be recorded as denied locally.

#### Scenario: Teacher disconnects a server
- **WHEN** disconnect completes
- **THEN** its tool listing is empty and subsequent dispatches using any previously saved skill are denied without a remote call

#### Scenario: Discovery and disconnect race
- **WHEN** disconnect occurs while a connect operation is fetching tools
- **THEN** the old connect operation cannot repopulate tools or restore connected status

#### Scenario: A previously dispatched call returns late
- **WHEN** a result arrives for an invalidated connection generation
- **THEN** the host discards the text and records a denied outcome rather than treating it as an authorized successful result

### Requirement: Teachers view minimal class-scoped tool audits
The system SHALL durably record each MCP tool dispatch or policy denial with tool@server, server identifier when authorized, status `ok`, `denied`, or `error`, initiating user, class, UTC time, conversation/assistant-turn identifier, and a safe reason code. An ok status SHALL require a valid current-generation successful remote text result. Audits SHALL NOT contain tokens, arguments, question text, raw results, or private conversation content. Teachers SHALL have a bounded paginated view of their own class's audits only.

#### Scenario: Call succeeds
- **WHEN** an authorized student turn completes a successful formula_hint call
- **THEN** a same-class teacher can see an ok audit identifying formula_hint@campus-tools, the student, and time

#### Scenario: Call is denied or fails
- **WHEN** a reference is disconnected, unauthorized, no longer discovered, times out, or returns a protocol/tool error
- **THEN** the audit records denied for authorization/state rejection or error for execution failure and never reports ok

#### Scenario: Audit access crosses a boundary
- **WHEN** a student requests audits or another-class teacher queries an audit or server ID
- **THEN** the response is respectively 403 or the ordinary 404 and does not disclose other-class tool or user metadata
