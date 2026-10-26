## ADDED Requirements

### Requirement: Published bound skills trigger bounded server-controlled MCP calls
For each accepted student turn, the system SHALL treat all active skills in the selected published agent revision as matched. It SHALL deduplicate their MCP references, validate each against the authenticated class and current connection/discovery state, and execute each eligible reference at most once with bounded arguments derived only from the current question. A teacher's text, retrieved evidence, history, or model output SHALL NOT add references, select endpoints, supply credentials, or trigger recursive calls. Platform knowledge retrieval SHALL still run for every turn.

#### Scenario: A bound skill triggers its tool
- **WHEN** a student sends a valid question to a published agent whose active skill binds formula_hint@campus-tools
- **THEN** the server sends authenticated tools/call to the actual registered MCP server and records its outcome for that turn

#### Scenario: Two skills reference the same tool
- **WHEN** multiple matched skills bind the same MCP reference
- **THEN** that reference is dispatched at most once for the turn

#### Scenario: An old binding is no longer authorized
- **WHEN** a saved tool belongs to another class, is disconnected, or is absent from current discovery
- **THEN** the system emits and persists a denied outcome and does not send an unauthorized remote request

### Requirement: MCP text is untrusted auxiliary user data
The system SHALL place bounded authorized successful tool text in a distinct auxiliary-data section of the model's user message, never in system instructions. MCP text SHALL NOT replace current same-class material evidence, create source IDs, weaken solution guidance, or be factual support on its own. Failed or denied calls SHALL be excluded from auxiliary text. No-evidence turns SHALL still attempt eligible tools and record their outcomes, but SHALL skip generation and return the existing exact insufficient-evidence answer with no citations.

#### Scenario: Tool result contains instructions
- **WHEN** tool text asks to override policy, expose secrets, change class, or invoke additional tools
- **THEN** it is treated as quoted data and none of those actions is authorized

#### Scenario: Tool succeeds but no materials support the answer
- **WHEN** the tool returns useful text but the turn has no authorized material evidence
- **THEN** the answer remains 根据本班资料无法回答该问题 with no citations while the real tool outcome remains visible in metadata and audit

#### Scenario: MCP fails while ordinary chat is answerable
- **WHEN** a tool times out or fails while authorized class evidence and generation are available
- **THEN** the turn may complete its ordinary validated guidance and citations with an explicit error tool outcome rather than failing the main chat solely because of MCP

### Requirement: Stream terminal metadata and history expose safe tool outcomes
The existing SSE event names, ordering, identifiers, and sequence rules SHALL remain unchanged. Both terminal message.completed and message.error events SHALL include `meta.tool_calls`, an ordered list of safe entries containing `tool_ref`, status `ok`, `denied`, or `error`, and a safe code. Turns without MCP calls SHALL expose an empty list. The persisted assistant message and authorized history response SHALL expose the same finalized entries, without credentials, arguments, raw results, or other-class identifiers. Tool status SHALL describe execution independently of answer success.

#### Scenario: Tool call and answer succeed
- **WHEN** the client receives message.completed for a turn with a successful tool
- **THEN** meta.tool_calls contains formula_hint@campus-tools with status ok, matching the stored assistant metadata and audit

#### Scenario: Generation fails after tool execution
- **WHEN** generation fails after a tool outcome is finalized
- **THEN** message.error and persisted failed message retain that outcome without releasing tool text or invalid model output

#### Scenario: Disconnected tool is used from an existing conversation
- **WHEN** a student asks again using the same published skill after disconnect
- **THEN** meta.tool_calls contains denied, audit agrees, and the UI does not present the tool as successful

#### Scenario: Client disconnects or work times out
- **WHEN** the client leaves or turn execution reaches its deadline
- **THEN** bounded supervision finalizes safe tool outcomes and assistant state, and late workers cannot overwrite them or add another dispatch for that turn
