## Purpose

定义教师在服务端班级边界内创建、配置、发布和维护多个教学智能体及技能的行为，并确保学生只能使用本班已发布且满足解题引导约束的配置。

## ADDED Requirements

### Requirement: Teachers can create multiple class-scoped agents
The system SHALL allow an authenticated teacher to create multiple agents containing a bounded name, optional description, and bounded system prompt. The server SHALL derive both `class_id` and `creator_id` from the authenticated principal and SHALL ignore or reject client-supplied ownership or class fields.

#### Scenario: Teacher creates an agent
- **WHEN** a teacher submits a valid agent name, description, and prompt
- **THEN** the system creates a draft agent owned by that teacher and scoped to that teacher's class

#### Scenario: Student attempts to create an agent
- **WHEN** a student submits an agent creation request
- **THEN** the system returns HTTP 403 and creates no agent

#### Scenario: Client supplies ownership scope
- **WHEN** a creation or update request includes a class identifier or creator identifier
- **THEN** the system rejects the non-authoritative field and does not alter server-derived ownership

### Requirement: Agent configuration is bounded and safe
The system SHALL validate agent names, descriptions, and prompts against documented non-empty and maximum-length constraints. Teacher prompts SHALL be treated as untrusted configuration subordinate to platform policy and SHALL NOT change authentication, class scope, evidence grounding, citation validation, secret handling, or tool availability.

#### Scenario: Teacher saves a valid prompt
- **WHEN** the prompt is within documented bounds and does not rely on client-supplied scope
- **THEN** the system stores it as agent configuration without exposing platform instructions or credentials

#### Scenario: Prompt requests a policy override
- **WHEN** a teacher prompt requests another class, hidden instructions, credentials, unsupported tools, or ungrounded factual answers
- **THEN** the platform policy remains authoritative and the prohibited behavior is not enabled

#### Scenario: Configuration exceeds a bound
- **WHEN** a name, description, or prompt is empty where required or exceeds its documented maximum
- **THEN** the system returns HTTP 400 with a documented validation error and persists no partial update

### Requirement: Teachers maintain creator-owned skills
The system SHALL allow a teacher to create, list, read, update, and retire multiple bounded skills owned by that teacher and scoped to that teacher's class. A skill SHALL have a name, instructions, and a supported type that includes `solution_guidance`. Only the creating teacher SHALL modify or retire it.

#### Scenario: Teacher creates a solution-guidance skill
- **WHEN** a teacher submits valid skill data with type `solution_guidance`
- **THEN** the system persists the skill in that teacher's class and returns its safe metadata and instructions

#### Scenario: Another teacher modifies a skill
- **WHEN** a teacher requests mutation of a skill created by another teacher, including one in the same class
- **THEN** the system returns the same HTTP 404 response shape used for a nonexistent skill and leaves it unchanged

#### Scenario: Student reads teacher maintenance APIs
- **WHEN** a student requests a skill maintenance endpoint
- **THEN** the system returns HTTP 403 and does not disclose draft skill configuration

### Requirement: Agents bind only compatible creator-owned skills
The system SHALL allow an agent creator to bind one or more active skills created by the same teacher in the same class. Binding SHALL be idempotent, SHALL reject duplicate skill identifiers, and SHALL never permit a cross-class or other-creator skill to influence an agent.

#### Scenario: Creator binds a compatible skill
- **WHEN** an agent creator binds an active skill that they created in the same class
- **THEN** the system records one binding and returns the updated agent configuration

#### Scenario: Creator binds an inaccessible skill
- **WHEN** an agent update references a nonexistent, retired, other-creator, or other-class skill
- **THEN** the system returns HTTP 404 with the ordinary missing-resource shape and leaves all bindings unchanged

#### Scenario: Bound skill is retired
- **WHEN** a teacher retires a skill that is bound to an agent
- **THEN** the system prevents that agent from remaining usable as a published agent until its bindings again satisfy publication rules

### Requirement: Published agents include solution guidance
The system SHALL permit publication only when the agent has a valid prompt and at least one active bound `solution_guidance` skill. That skill SHALL instruct the assistant to offer hints, intermediate steps, checks, and clarifying questions without directly presenting the final answer requested by the student.

#### Scenario: Teacher publishes a valid agent
- **WHEN** the creator publishes a draft agent with a valid prompt and an active solution-guidance skill
- **THEN** the agent becomes discoverable to students in that class

#### Scenario: Required guidance skill is absent
- **WHEN** the creator attempts to publish an agent without an active solution-guidance skill
- **THEN** the system returns HTTP 409 with a documented publication-readiness error and keeps the agent unpublished

#### Scenario: Student asks for only the final answer
- **WHEN** a student uses a published solution-guidance agent and asks it to provide only the final answer
- **THEN** the assistant preserves the guidance behavior and responds with bounded hints, steps, checks, or a clarifying question rather than a direct final answer

### Requirement: Publication controls student visibility and active sessions
The system SHALL expose only published agents to students in the same class. Configuration updates to a published agent SHALL take effect on the next message of existing sessions and SHALL produce a visible configuration-updated notice in those sessions. Unpublishing or invalidating an agent SHALL prevent both new sessions and further messages in existing sessions until the agent is valid and published again.

#### Scenario: Student lists available agents
- **WHEN** a student requests the agent catalog
- **THEN** the response contains only valid published agents in the student's class and omits private prompt and skill instruction text

#### Scenario: Teacher updates a published prompt or skill
- **WHEN** the creator changes configuration used by a published agent
- **THEN** the next message in each existing session uses the latest valid configuration and the client is told that the configuration changed

#### Scenario: Agent is unpublished
- **WHEN** the creator unpublishes an agent
- **THEN** students cannot create a new session or send another message in an existing session with that agent

### Requirement: Only creators manage their agents
The system SHALL allow only the creating teacher to read private configuration, update, publish, unpublish, or retire an agent. Other users SHALL receive an existence-hiding HTTP 404 for identifier-based management requests, including users in the same class.

#### Scenario: Creator manages an agent
- **WHEN** the creating teacher requests an authorized read or mutation
- **THEN** the system performs the operation and returns the resulting resource state

#### Scenario: Another teacher manages an agent
- **WHEN** another teacher requests the private configuration or mutation of that agent
- **THEN** the system returns the same HTTP 404 response shape used for a nonexistent agent

#### Scenario: Other-class user guesses an agent identifier
- **WHEN** a user from another class requests that agent by identifier
- **THEN** the response is indistinguishable from a nonexistent agent and discloses no metadata

### Requirement: Retirement preserves referenced history without enabling use
The system SHALL retire rather than physically remove an agent or skill that is referenced by conversation history. Retired resources SHALL not appear in student catalogs, create new sessions, accept new messages, or be reused in newly published configuration, while authorized historical conversation views retain the display metadata needed to understand prior records.

#### Scenario: Creator retires an unused draft
- **WHEN** a creator retires a draft agent with no conversation references
- **THEN** it disappears from active management and student catalog results

#### Scenario: Creator retires an agent with history
- **WHEN** an agent has one or more conversations and its creator retires it
- **THEN** no new use is allowed and authorized historical views continue to show bounded agent identity metadata
