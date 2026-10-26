## ADDED Requirements

### Requirement: MCP workflows are documented and usable through Swagger
The OpenAPI document SHALL describe MCP registration/listing, connect, tools, disconnect, audit listing, skill tools validation, and terminal SSE meta schemas. It SHALL document safe 400/401/403/404/409/503 outcomes as applicable, with synthetic examples and the existing HTTP Bearer JWT scheme. Swagger at /api/docs SHALL permit an authenticated teacher to exercise registration, connect, tools, and skill saving through the same-origin gateway. MCP runtime token values SHALL NOT appear in documentation, browser requests, or responses.

#### Scenario: Teacher tries the workflow in a browser
- **WHEN** a teacher authenticates in Swagger and registers the approved demo URL, connects, lists tools, and saves a skill reference
- **THEN** the browser displays schema-conformant success responses with the actual discovered tool names and no MCP credential

#### Scenario: Error and stream contracts are inspected
- **WHEN** a caller inspects connection failure, invalid skill binding, or streamed tool execution documentation
- **THEN** the documented status/error and terminal meta.tool_calls structures match the actual response contracts
