## ADDED Requirements

### Requirement: MCP acceptance uses the real demo service in isolation
The independent API-test Compose stack SHALL build and run the repository's actual mcp-server implementation with synthetic runtime credentials on its internal network. MCP operation cases SHALL follow the existing URL/method file organization and cover registration, connect, tools, disconnect, audit, student 403, cross-class 404, validation, bad remote token, and discovery/timeout failure. Existing deterministic model substitutes SHALL remain in use; no real external model or development database SHALL be required.

#### Scenario: End-to-end MCP workflow is tested
- **WHEN** run_all.py executes the MCP workflow with controlled teacher/student accounts and same-class supporting material
- **THEN** it registers and connects the demo, discovers formula_hint, saves formula_hint@campus-tools in a skill, publishes its bound agent, sends a student turn, and verifies matching ok stream metadata and audit rows using read-only database observation

#### Scenario: Disconnect is tested
- **WHEN** the workflow disconnects the server and sends another turn using the same saved skill
- **THEN** tools is empty, the remote tool is not dispatched again, saving the unavailable reference is rejected, and the turn records denied rather than ok

#### Scenario: Independent protocol and injection checks run
- **WHEN** tests exercise health, missing/wrong Bearer, initialize/list/call, malformed JSON-RPC, tool-result injection, and oversize/error results
- **THEN** actual protocol responses and host data/credential boundaries satisfy their respective specs without mocking away the host-to-demo connection

### Requirement: MCP reports and evidence preserve secret boundaries
The existing run_all.py SHALL include the added operations in its timestamped HTML report, retain nonzero failure exits and safe fixed diagnostics, and leave reports untracked. Acceptance evidence SHALL distinguish tests actually executed from planned/manual checks and SHALL include same-origin browser Swagger checks and runtime-secret verification without printing token values.

#### Scenario: Full report is generated
- **WHEN** the isolated API suite completes
- **THEN** its HTML report lists the MCP operations, statuses and safe assertion labels and is ignored by Git

#### Scenario: Secret or deployment checks are recorded
- **WHEN** an operator compares API/server runtime credential consistency, tracked files, frontend bundles, and image layers
- **THEN** evidence contains only safe pass/fail assertions and no MCP token, request authorization header, or secret-bearing environment dump
