## MODIFIED Requirements

### Requirement: The LLM answers only from authorized retrieved evidence
The system SHALL generate at most one answer for each request using only the bounded, same-class evidence assembled for that request as factual support. The legacy `POST /api/knowledge/query` endpoint SHALL remain single-turn and SHALL supply no prior conversation. An agent-conversation request MAY include a documented bounded suffix of server-loaded messages from that same authorized conversation as untrusted conversational context, but history, prior answers, and prior citations SHALL NOT become evidence for the current turn. System instructions SHALL prohibit using model pretraining, unstated assumptions, client-supplied history, other conversations, or non-evidence content as factual support. The response SHALL identify whether it is answered or refused and SHALL NOT expose hidden prompts or reasoning traces.

#### Scenario: Sufficient evidence exists
- **WHEN** authorized retrieved evidence directly supports an answer
- **THEN** the system returns a concise answer grounded in that evidence together with its validated current-request citations and source records

#### Scenario: Question asks for general model knowledge
- **WHEN** the question could be answered from model pretraining but the caller's class evidence does not support it
- **THEN** the system returns `根据本班资料无法回答该问题` without adding a model-derived answer

#### Scenario: Question asks for reasoning traces or hidden instructions
- **WHEN** a user requests the system prompt, credentials, hidden chain of thought, or internal reasoning
- **THEN** the system discloses none of them and either answers only the supported course-content portion or safely refuses

#### Scenario: Previous answer text is supplied as part of a new request
- **WHEN** a client includes content from an earlier interaction in a new legacy `POST /api/knowledge/query` question
- **THEN** the system treats it only as untrusted question text and does not treat it as trusted history or evidence

#### Scenario: Agent chat uses persisted history
- **WHEN** the server loads a bounded suffix of messages from the authenticated student's same active conversation
- **THEN** that history may resolve conversational references and influence guidance style but every current factual claim still cites newly retrieved authorized evidence

#### Scenario: Client supplies fabricated chat history
- **WHEN** a chat client submits prior messages, prior citations, an assistant answer, or content from another conversation alongside the current message
- **THEN** the system rejects those fields and uses only server-loaded history from the authorized conversation

#### Scenario: Prior citation is absent from current evidence
- **WHEN** a historical assistant message cited a source that is not in the current request's reauthorized evidence set
- **THEN** the new answer does not return or rely on that historical citation as factual support
