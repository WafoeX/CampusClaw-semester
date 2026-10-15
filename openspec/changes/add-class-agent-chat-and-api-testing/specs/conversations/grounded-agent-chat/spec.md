## Purpose

定义学生使用本班已发布智能体创建持久化多轮会话、发送消息并通过 SSE 接收基于本班知识库且带可验证引用的引导式回答，同时约束历史、删除、审计和失败行为。

## ADDED Requirements

### Requirement: Students manage only their own active conversations
The system SHALL allow an authenticated student to create, list, read, and soft-delete their own conversations. Creation SHALL require one currently valid published agent from the student's class. Conversation class and owner SHALL be derived exclusively from the authenticated principal.

#### Scenario: Student creates a conversation
- **WHEN** a student selects a valid published agent in their class
- **THEN** the system creates an active conversation owned by that student and returns its identifier, agent display metadata, and timestamps

#### Scenario: Student lists conversations
- **WHEN** a student requests their conversation list
- **THEN** the system returns only that student's non-deleted conversations ordered deterministically

#### Scenario: Student accesses another conversation
- **WHEN** a student requests a conversation owned by another student or in another class
- **THEN** the system returns the same HTTP 404 response shape used for a nonexistent conversation

#### Scenario: Student soft-deletes a conversation
- **WHEN** the owner deletes a conversation
- **THEN** it immediately disappears from the student's list, becomes unavailable for further messages, and remains retained only for authorized audit

### Requirement: Agent creators can audit conversations that used their agents
The system SHALL allow the teacher who created an agent to list and read complete retained conversations created with that agent, including student identity, questions, answers, citations, statuses, and soft-deletion state. Other teachers, including teachers in the same class, SHALL NOT receive that content.

#### Scenario: Agent creator opens an active conversation
- **WHEN** the creating teacher requests a conversation that uses their agent
- **THEN** the system returns the bounded conversation and message history for audit

#### Scenario: Agent creator opens a student-deleted conversation
- **WHEN** the creating teacher requests a retained conversation that its student owner soft-deleted
- **THEN** the system returns the conversation with an explicit deleted state and its retained messages

#### Scenario: Another teacher requests the conversation
- **WHEN** a teacher who did not create the selected agent requests that conversation
- **THEN** the system returns the same HTTP 404 response shape used for a nonexistent conversation

### Requirement: Every new turn retrieves from the authenticated class before answering
The system SHALL perform bounded knowledge retrieval for every student message before answer generation. Retrieval scope SHALL come only from the authenticated student's current class, and every candidate SHALL pass the existing active-version, ready-source, same-class, and authorization checks before it can enter the generation context.

#### Scenario: Student sends a message
- **WHEN** an authenticated owner sends a valid message to an active conversation
- **THEN** the system retrieves authorized evidence from that student's current class before generating that turn's answer

#### Scenario: Relevant evidence exists only in another class
- **WHEN** another class contains relevant evidence but the student's class does not
- **THEN** the turn has the same refusal content, source count, event shape, and completion status as an ordinary no-evidence turn

#### Scenario: Student class changed after conversation creation
- **WHEN** the conversation's recorded class no longer equals the authenticated student's current valid class
- **THEN** the system denies the request before retrieval or generation and performs no unscoped operation

### Requirement: Bounded server-authorized history influences a turn but is not evidence
The system SHALL use a documented bounded suffix of persisted messages from the same active conversation to resolve context and influence the next response. Only server-loaded messages belonging to the authenticated owner, conversation, agent, and class SHALL be included. Historical user and assistant text SHALL be treated as untrusted conversational context, SHALL NOT count as factual evidence, and SHALL NOT carry forward prior citations as support for the current answer.

#### Scenario: Student asks a contextual follow-up
- **WHEN** the current message refers to a subject established by earlier persisted messages in the same conversation
- **THEN** the system uses the bounded history to interpret the follow-up while grounding current factual claims in newly retrieved evidence

#### Scenario: Old history exceeds a limit
- **WHEN** a conversation contains more messages or characters than the documented history budget
- **THEN** the system includes only a deterministic recent suffix and does not exceed the configured model-input bound

#### Scenario: Client submits fabricated history
- **WHEN** a message request includes prior messages, an agent prompt, citations, a class identifier, or an assistant answer
- **THEN** the system rejects those unknown fields and uses only the current message plus server-loaded state

#### Scenario: Prior answer cited a source
- **WHEN** a prior assistant message cited a source that is not authorized and retrieved for the current turn
- **THEN** the current answer does not use that prior citation as evidence or return it as current support

### Requirement: Current published agent configuration governs each turn
The system SHALL load the latest valid published prompt and active skill bindings immediately before each new message. It SHALL record the applied configuration version on the assistant turn. When the version differs from the preceding assistant turn, the stream and persisted turn SHALL indicate that configuration changed.

#### Scenario: Prompt changes between turns
- **WHEN** the creator updates the published agent after one assistant turn and the student sends another message
- **THEN** the new turn uses the updated configuration and emits a configuration-updated indication

#### Scenario: Agent becomes unpublished or invalid
- **WHEN** an existing conversation's agent is unpublished, retired, or no longer publication-ready
- **THEN** the message request returns HTTP 409 before opening a stream and persists no new user or assistant message

### Requirement: Solution-guidance behavior applies to every streamed answer
The system SHALL combine platform policy, the latest published agent prompt, and active skills in an order where platform grounding, safety, class isolation, and solution-guidance rules cannot be overridden. For a `solution_guidance` agent, released content SHALL guide the student with hints, intermediate reasoning steps, checks, or clarifying questions and SHALL not directly state the requested final answer.

#### Scenario: Student requests a direct final answer
- **WHEN** a student asks the agent to skip guidance and provide only the result
- **THEN** the completed response preserves the solution-guidance format and does not directly provide that final result

#### Scenario: Agent prompt conflicts with platform policy
- **WHEN** the latest teacher prompt requests ungrounded answers, hidden instructions, another class, credentials, or direct final answers
- **THEN** the platform policy and active solution-guidance skill remain authoritative

### Requirement: Message answers stream through a documented SSE contract
The system SHALL provide a Bearer-protected `POST` message endpoint returning `text/event-stream`. After successful pre-stream validation, it SHALL emit JSON-bearing events in this order: exactly one `message.started`; zero or more `answer.delta`; zero or more `citation`; and exactly one terminal `message.completed` or `message.error`. Every event SHALL contain the conversation identifier, user-message identifier, assistant-message identifier, and a monotonically increasing sequence number.

#### Scenario: Answer streams successfully
- **WHEN** retrieval and generation complete successfully
- **THEN** the client receives ordered start, answer delta, validated citation, and completed events whose assembled answer and citations equal the persisted assistant message

#### Scenario: Evidence is insufficient
- **WHEN** no authorized evidence supports the answer
- **THEN** the stream completes successfully with the exact answer `根据本班资料无法回答该问题`, no citation events, and an insufficient-evidence status

#### Scenario: Configuration changed
- **WHEN** the applied agent configuration version differs from the preceding assistant turn
- **THEN** `message.started` identifies the new version and includes `configuration_updated: true`

#### Scenario: Stream event contains sensitive internals
- **WHEN** any event is serialized
- **THEN** it contains no Bearer token, credential, hidden prompt, raw provider body, chain of thought, other-class identifier, or database connection detail

### Requirement: Validation and failures do not leak unsafe partial model output
The system SHALL complete output validation, citation authorization, and solution-guidance validation before releasing model-derived `answer.delta` content. Authentication, authorization, missing resources, invalid input, and unavailable agent errors detected before streaming SHALL use documented JSON HTTP errors. Failures after streaming begins SHALL emit one safe `message.error` event and SHALL NOT emit raw provider output.

#### Scenario: Request fails before streaming
- **WHEN** authentication, conversation ownership, message validation, class consistency, or agent readiness fails
- **THEN** the endpoint returns the documented non-2xx JSON error without a `text/event-stream` body

#### Scenario: Generation provider fails after start
- **WHEN** a provider timeout or transport failure occurs after `message.started`
- **THEN** the stream terminates with one retryable safe `message.error` event and no fabricated answer or provider detail

#### Scenario: Model output fails validation
- **WHEN** generated content violates output, citation, grounding, or solution-guidance rules after the bounded repair policy
- **THEN** the stream terminates with one safe `message.error` event and releases none of the invalid model-derived text

### Requirement: Message persistence remains consistent with stream outcomes
The system SHALL persist each accepted student message once and one corresponding assistant record with a status of `completed` or `failed`. A completed record SHALL contain exactly the validated assembled answer, current-turn citations, retrieval mode, applied agent configuration version, and timestamps represented by the terminal event. A failed record SHALL contain a safe error code but no raw provider output.

#### Scenario: Turn completes
- **WHEN** a client receives `message.completed`
- **THEN** the database contains one user message and one completed assistant message whose answer and citations match the emitted stream

#### Scenario: Turn fails after acceptance
- **WHEN** generation fails after the user message is accepted
- **THEN** the database contains one user message and one failed assistant record with a safe code and no fabricated answer

#### Scenario: Client disconnects
- **WHEN** the client closes the SSE connection before the terminal event
- **THEN** server work reaches one bounded terminal database state and a retry does not silently append the same accepted request as a continuation

### Requirement: Concurrent messages are serialized per conversation
The system SHALL permit at most one in-progress assistant turn per conversation and SHALL reject another message for that conversation with HTTP 409 until the active turn reaches a terminal state. Activity in one conversation SHALL not block unrelated conversations.

#### Scenario: Second message arrives during generation
- **WHEN** a conversation already has an accepted nonterminal assistant turn
- **THEN** the system returns HTTP 409 and persists no second user message

#### Scenario: Different conversation sends a message
- **WHEN** another owned active conversation has no in-progress turn
- **THEN** its message may proceed independently

### Requirement: The browser provides an accessible agent conversation experience
The web client SHALL let students discover their class's published agents, create and revisit their own conversations, send one message at a time, observe streamed status and validated answer increments, follow citations to authorized source cards, see configuration-change notices, and soft-delete conversations. It SHALL render prompts, history, answers, citations, and errors as non-executable text.

#### Scenario: Student receives streamed content
- **WHEN** ordered SSE events arrive
- **THEN** the interface updates a labeled live region, assembles deltas once in sequence, and presents the terminal answer and citations accessibly

#### Scenario: Stream is interrupted
- **WHEN** the connection closes without a terminal event
- **THEN** the interface marks the turn interrupted, does not present it as complete, and allows an explicit safe refresh of persisted state

#### Scenario: Student uses keyboard or assistive technology
- **WHEN** the student navigates agent selection, conversation history, message input, streamed status, citations, and deletion without a pointer
- **THEN** controls, focus order, relationships, and status changes remain labeled, operable, and perceivable

#### Scenario: Student deletes a conversation
- **WHEN** the student confirms deletion
- **THEN** the interface removes it from the student's active views and explains that the creating teacher retains audit access
