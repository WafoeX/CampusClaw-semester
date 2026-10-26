## ADDED Requirements

### Requirement: Skill revisions declare validated tool references
The system SHALL extend existing structured skill create, update, and creator-only read responses with a bounded unique `tools` list supporting `knowledge_search` and `<tool>@<server>` references. Omitted tools on legacy create SHALL default to `["knowledge_search"]`; omitted tools on update SHALL preserve the prior revision's list. An explicit empty list SHALL disable MCP bindings but SHALL NOT disable the platform's mandatory knowledge retrieval. Tool names SHALL match `^[a-z][a-z0-9_]*$` and server names `^[a-z][a-z0-9-]{0,62}$`. Tool bindings SHALL be part of immutable skill revisions and follow existing agent revision propagation and republication behavior.

#### Scenario: Teacher saves a discovered MCP tool
- **WHEN** the skill creator saves tools containing formula_hint@campus-tools and that server belongs to the creator's class, is connected, and has discovered formula_hint
- **THEN** the new skill revision contains the validated reference and is available to the existing creator-owned agent binding workflow

#### Scenario: A binding is inaccessible or unavailable
- **WHEN** a save references another-class or nonexistent server, or a disconnected server or undiscovered tool
- **THEN** inaccessible references receive ordinary HTTP 404, unavailable same-class references receive HTTP 409, and no partial skill or agent revision is persisted

#### Scenario: Tool syntax or count is invalid
- **WHEN** a tools list contains malformed references, duplicates, or exceeds its documented bounds
- **THEN** the system returns HTTP 400 without persisting changes

#### Scenario: Legacy clients omit tools
- **WHEN** an old client creates a skill without tools or updates an existing skill without tools
- **THEN** creation uses knowledge_search and update preserves existing bindings without silently clearing MCP configuration

### Requirement: Skill editor presents discovered class tools without credentials
The teacher interface SHALL let a creator select knowledge_search and connected discovered same-class MCP references while editing their existing structured skills. It SHALL retain and label unavailable saved references so teachers can remove them, and SHALL display save rejection rather than silently dropping bindings. The system SHALL NOT introduce file import or autonomous skill routing in this change.

#### Scenario: Teacher selects a tool
- **WHEN** discovery succeeds and the creator opens the skill editor
- **THEN** formula_hint@campus-tools is selectable without any MCP token being sent to or rendered by the browser

#### Scenario: A saved tool becomes disconnected
- **WHEN** the teacher opens a skill containing a no-longer-available reference
- **THEN** the interface marks it unavailable and saving it unchanged is rejected until the tool is reconnected and discovered or the binding is removed
