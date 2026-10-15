# materials/knowledge-retrieval Specification

## Purpose

让教师和学生仅以自己所属班级的可检索课程资料为依据进行单轮知识库问答，由 LLM 生成带可验证来源引用的回答；系统必须在检索、证据组装、模型调用和来源解析的每一层维持班级隔离，并在证据不足时明确拒答。

## Requirements

### Requirement: Supported materials are indexed without blocking normal material access
The system SHALL extract and index textual content from ready PDF, plain-text, and Markdown materials. Upload, listing, metadata access, and download SHALL remain available independently of indexing completion, and unsupported formats SHALL remain downloadable without being searched or supplied to the LLM.

#### Scenario: Supported material enters indexing
- **WHEN** a PDF, plain-text, or Markdown material becomes ready
- **THEN** the system records it as pending indexing and eventually makes successfully extracted content eligible for retrieval and grounded answering

#### Scenario: Unsupported material remains usable
- **WHEN** a ready material has a format outside PDF, plain text, and Markdown
- **THEN** the system marks it as unsupported for knowledge retrieval while preserving its existing list, metadata, and download behavior

#### Scenario: Existing supported material is discovered
- **WHEN** the capability is deployed with ready supported materials that predate retrieval indexing
- **THEN** the system can enqueue those materials for idempotent backfill without requiring them to be uploaded again

### Requirement: Chunk text and vectors use separate authoritative stores
The system SHALL store each chunk's bounded original text and provenance in the PostgreSQL `knowledge_chunks` table. Qdrant SHALL store only the floating-point vector and identifiers required for class-scoped retrieval and reconciliation, SHALL NOT store chunk text, and each Qdrant point identifier SHALL equal the corresponding `knowledge_chunks.id`. Every vector candidate used as LLM evidence SHALL first be hydrated from PostgreSQL and pass authorization and lifecycle checks.

#### Scenario: A chunk is indexed semantically
- **WHEN** the system successfully embeds a persisted `knowledge_chunks` row
- **THEN** it upserts a Qdrant point whose identifier equals `knowledge_chunks.id` and whose payload contains identifiers but no chunk text

#### Scenario: A vector candidate is selected
- **WHEN** Qdrant returns a class-filtered candidate
- **THEN** the system loads the matching PostgreSQL row and permits it into the LLM evidence set only after same-class, active-version, ready-source, and authorization checks succeed

#### Scenario: A vector has no valid PostgreSQL chunk
- **WHEN** a Qdrant point has no matching active, ready, same-class PostgreSQL chunk
- **THEN** the system omits it from results and model context without exposing its payload and makes it eligible for reconciliation cleanup

### Requirement: Indexing status is explicit and recoverable
The system SHALL expose an authorized material's retrieval status as pending, processing, searchable, unsupported, or failed. It SHALL retry transient extraction or embedding failures with a bounded policy and SHALL permit idempotent reindexing without exposing duplicate or partial chunk versions.

#### Scenario: Indexing completes
- **WHEN** extraction and all required index writes complete for a supported material
- **THEN** the material becomes searchable and its status is reported as searchable

#### Scenario: No extractable text exists
- **WHEN** a supported file, including an image-only PDF, contains no extractable text
- **THEN** the system reports a failed indexing status with a safe reason and does not create empty evidence

#### Scenario: Transient embedding failure occurs
- **WHEN** extraction succeeds but the embedding service has a transient failure
- **THEN** the extracted chunks remain eligible for keyword retrieval, semantic indexing is retried within configured bounds, and the material is not duplicated

#### Scenario: Reindex replaces prior chunks
- **WHEN** an operator requests reindexing for an already searchable material
- **THEN** the system exposes either the complete prior version or the complete replacement version and never a partial mixture

### Requirement: Every question and answer is scoped to the authenticated user's class
The system SHALL derive class scope exclusively from the authenticated login session and SHALL apply it to keyword candidates, Qdrant candidates, PostgreSQL hydration, evidence assembly, LLM input, citation validation, and source resolution. A request-supplied class identifier SHALL have no authorization or scope effect, and the LLM SHALL NOT select, broaden, or override class scope.

#### Scenario: Class member asks a question
- **WHEN** an authenticated teacher or student submits a valid question
- **THEN** every evidence chunk, answer citation, and returned source belongs to that user's class

#### Scenario: Client supplies any class identifier
- **WHEN** a client adds, alters, or repeats a class identifier in a query, header, path, or body
- **THEN** the server rejects it as an unknown field or ignores it as non-authoritative and still uses only the class from the authenticated session

#### Scenario: Relevant content exists only in another class
- **WHEN** another class contains evidence that could answer the question but the caller's class does not
- **THEN** the system returns the same insufficient-evidence response it would return if the other content did not exist

#### Scenario: User has no usable class
- **WHEN** an authenticated account has no valid class association
- **THEN** the system denies the request before retrieval or LLM invocation and performs no unscoped operation

### Requirement: Questions use bounded keyword, vector, or hybrid retrieval before generation
The system SHALL accept a non-empty bounded natural-language question and an optional retrieval mode of `keyword`, `vector`, or `hybrid`. Omitted mode SHALL default to `hybrid`. Keyword retrieval SHALL match terms present in original PostgreSQL chunk text, vector retrieval SHALL find semantically similar content through Qdrant, and hybrid retrieval SHALL independently rank both branches before deterministic RRF fusion. A server-defined candidate and result cap SHALL apply before LLM invocation.

#### Scenario: Retrieval mode is omitted
- **WHEN** a class member submits a valid question without a retrieval mode
- **THEN** the system uses hybrid retrieval before answer generation

#### Scenario: Keyword mode is selected
- **WHEN** a class member selects `keyword`
- **THEN** the evidence candidates come from deterministic same-class PostgreSQL keyword matches and semantic similarity alone does not create a keyword match

#### Scenario: Vector mode is selected
- **WHEN** a class member selects `vector`
- **THEN** semantically similar same-class chunks may become evidence only after Qdrant filtering and PostgreSQL hydration succeed

#### Scenario: Hybrid mode is selected
- **WHEN** a class member selects `hybrid` or omits the mode while both retrieval branches are available
- **THEN** the system fuses independently ranked bounded keyword and vector lists with deterministic RRF before evidence assembly

#### Scenario: Question is blank or too long
- **WHEN** a question is empty after trimming or exceeds the configured maximum length
- **THEN** the system returns HTTP 400 and invokes neither retrieval nor an LLM

#### Scenario: Retrieval mode is invalid
- **WHEN** a client supplies a mode other than `keyword`, `vector`, or `hybrid`
- **THEN** the system returns HTTP 400 without retrieval or generation

### Requirement: The LLM answers only from authorized retrieved evidence
The system SHALL generate at most one answer for each request using only the bounded, same-class evidence assembled for that request. System instructions SHALL prohibit using model pretraining, unstated assumptions, prior conversations, or non-evidence content as factual support. The response SHALL identify whether it is answered or refused and SHALL NOT expose hidden prompts or reasoning traces.

#### Scenario: Sufficient evidence exists
- **WHEN** authorized retrieved evidence directly supports an answer
- **THEN** the system returns a concise answer grounded in that evidence together with its validated citations and source records

#### Scenario: Question asks for general model knowledge
- **WHEN** the question could be answered from model pretraining but the caller's class evidence does not support it
- **THEN** the system returns `根据本班资料无法回答该问题` without adding a model-derived answer

#### Scenario: Question asks for reasoning traces or hidden instructions
- **WHEN** a user requests the system prompt, credentials, hidden chain of thought, or internal reasoning
- **THEN** the system discloses none of them and either answers only the supported course-content portion or safely refuses

#### Scenario: Previous answer text is supplied as part of a new request
- **WHEN** a client includes content from an earlier interaction in a new question
- **THEN** the system treats it only as untrusted question text and does not treat it as trusted history or evidence

### Requirement: Insufficient evidence produces a deterministic refusal
The system SHALL return the exact user-facing answer `根据本班资料无法回答该问题` when no authorized evidence remains after filtering, when the evidence does not support an answer, or when the model declares the evidence insufficient. The refusal SHALL contain no fabricated factual completion and SHALL disclose no existence or metadata of other-class content.

#### Scenario: Retrieval returns no valid evidence
- **WHEN** the selected available retrieval mode has no candidate after class, active-version, ready-source, and authorization filtering
- **THEN** the system skips answer generation and returns HTTP 200 with the exact refusal answer and zero sources

#### Scenario: Retrieved text is topically related but insufficient
- **WHEN** retrieved same-class chunks mention the topic but do not support the requested conclusion
- **THEN** the system returns the exact refusal answer rather than asking the LLM to fill the gap from prior knowledge

#### Scenario: Model reports insufficient evidence
- **WHEN** the generation model's validated structured output marks the question unanswerable from the supplied evidence
- **THEN** the system normalizes the response to the exact refusal answer

#### Scenario: Other-class evidence would be sufficient
- **WHEN** sufficient evidence exists only outside the authenticated class
- **THEN** the response is indistinguishable in status, wording, source count, and shape from an ordinary same-class insufficient-evidence response

### Requirement: Every factual answer claim has valid source provenance
The system SHALL return stable source identifiers for the evidence supplied to the LLM and SHALL require factual claims in an answered response to cite one or more of those identifiers. Returned source records SHALL include material identifier, title, original filename, bounded excerpt, format-appropriate locator, optional reliable section label, and an existing authorized source action. Unknown, malformed, duplicate, unauthorized, or stale citations SHALL NOT be returned as valid support.

#### Scenario: PDF evidence supports an answer
- **WHEN** an answer cites a chunk extracted from a PDF page
- **THEN** the answer references its source identifier and the source record contains the one-based page number and excerpt from that page

#### Scenario: Text evidence supports an answer
- **WHEN** an answer cites a plain-text or Markdown chunk
- **THEN** the answer references its source identifier and the source record contains the one-based line range and excerpt from that range

#### Scenario: Model emits an unknown source identifier
- **WHEN** structured model output cites an identifier absent from the authorized evidence set
- **THEN** the system discards the unvalidated output and performs at most the documented bounded repair attempt before returning a safe generation error or refusal

#### Scenario: Source authorization changes before response completion
- **WHEN** cited material is no longer ready or authorized at final source resolution
- **THEN** the system removes that source and SHALL NOT return an answer whose factual claims depend on the removed citation

### Requirement: Retrieved content cannot act as instructions
The system SHALL treat user questions, filenames, headings, and extracted material text as untrusted data. It SHALL separate system policy from evidence, delimit and length-bound each evidence item, prevent evidence from requesting tools or additional data, and validate model output before release. Content inside materials SHALL NOT change class scope, system policy, provider configuration, output schema, or citation rules.

#### Scenario: Material contains a prompt-injection instruction
- **WHEN** an authorized chunk says to ignore prior rules, reveal secrets, search another class, or follow a new role
- **THEN** the system treats that text only as quoted evidence data and does not follow the instruction

#### Scenario: User attempts to override grounding rules
- **WHEN** a question asks the model to ignore sources, answer from memory, fabricate citations, or expose configuration
- **THEN** the system preserves grounding, citation, secrecy, and class-isolation rules

#### Scenario: Evidence contains markup or executable text
- **WHEN** retrieved content contains HTML, Markdown, scripts, tool-call syntax, or serialized instructions
- **THEN** the system transmits it only as bounded evidence data and renders returned excerpts and answers without executing it

### Requirement: LLM access is server-controlled and privacy bounded
The system SHALL keep embedding and generation endpoints, credentials, data-boundary modes, model names, dimensions, and limits on the server. Each model call SHALL use an institution-controlled private endpoint or an explicitly approved external endpoint. The system SHALL minimize transmitted question and evidence text, require explicit authorization for external egress, enforce timeouts and size limits, and exclude credentials, raw provider errors, prompts, questions, evidence, and answers from routine logs and client diagnostics.

#### Scenario: Private model endpoints are configured
- **WHEN** authorized private embedding and generation endpoints satisfy compatibility checks
- **THEN** the system may perform semantic retrieval and grounded generation without public data egress

#### Scenario: Approved external endpoints are configured
- **WHEN** an operator explicitly enables approved-external mode with valid server-side configuration
- **THEN** the system may send only the bounded question and authorized evidence required for the request

#### Scenario: External egress is not approved
- **WHEN** a configured endpoint is outside the private boundary and explicit external authorization is absent
- **THEN** the system sends no question or material content to that endpoint and reports the affected capability as unavailable

#### Scenario: Client inspects outputs
- **WHEN** a client receives answer, material-status, health, or error output
- **THEN** it receives no credentials, authorization headers, hidden prompts, raw provider bodies, or unredacted provider errors

### Requirement: Dependency failures have explicit non-fabricating outcomes
The system SHALL preserve authorization rules during every failure. Keyword retrieval SHALL not depend on Qdrant. Hybrid retrieval MAY degrade to keyword-only evidence when embedding or Qdrant is temporarily unavailable, and the response SHALL report that degradation. Explicit vector mode SHALL not silently become keyword mode. If answer generation is unavailable or invalid, the system SHALL return a safe retryable error without presenting retrieval excerpts as an LLM-generated answer.

#### Scenario: Vector dependency fails during hybrid retrieval
- **WHEN** query embedding or Qdrant is temporarily unavailable in hybrid mode while keyword retrieval succeeds
- **THEN** the system may generate from same-class keyword evidence and reports effective retrieval mode `keyword_only`

#### Scenario: Vector dependency fails in explicit vector mode
- **WHEN** query embedding or Qdrant is unavailable for an explicitly selected vector request
- **THEN** the system returns the documented vector-unavailable outcome and does not generate from undisclosed keyword fallback

#### Scenario: Generation provider is unavailable
- **WHEN** authorized evidence exists but the generation request times out or fails
- **THEN** the system returns a safe retryable generation-unavailable error with no fabricated answer and no raw provider error

#### Scenario: Model output fails validation
- **WHEN** model output is malformed, exceeds bounds, contains invalid citations, or violates the response contract after the bounded repair policy
- **THEN** the system returns a safe generation-invalid outcome and does not expose the unvalidated output

### Requirement: Retrieval state follows material lifecycle across both stores
The system SHALL associate every PostgreSQL chunk, Qdrant point, and indexing job with one ready source material and its class. It SHALL remove or exclude retrieval data when the source ceases to be searchable, and PostgreSQL SHALL remain authoritative for text, provenance, lifecycle, and authorization.

#### Scenario: Source readiness changes
- **WHEN** a source material is not ready
- **THEN** its chunks are excluded from retrieval, LLM evidence, citations, and source records

#### Scenario: Source material is removed in a future lifecycle operation
- **WHEN** an authorized operation removes a material
- **THEN** its jobs, PostgreSQL chunks, keyword data, and vectors are removed or made unreachable, with reconciliation completing interrupted cross-store cleanup

#### Scenario: Stale or malformed retrieval row exists
- **WHEN** a retrieval row cannot be joined to a ready source in the caller's class
- **THEN** it is not supplied to the LLM or returned and is eligible for reconciliation cleanup

### Requirement: The materials interface provides accessible single-turn grounded answering
The web client SHALL provide an accessible Chinese “知识库问答” region in the authenticated materials experience. It SHALL accept one question at a time, display the answered or refused state, validated inline citations and source cards, effective retrieval/degradation metadata, and material indexing states. It SHALL NOT automatically carry prior turns, present an autonomous agent, expose model controls, or treat UI filtering as authorization.

#### Scenario: User asks an answerable question
- **WHEN** an authenticated teacher or student submits a valid question with sufficient evidence
- **THEN** the interface shows one grounded answer with linked source identifiers, source cards, locators, excerpts, and authorized source actions

#### Scenario: User asks an unanswerable question
- **WHEN** the API returns the insufficient-evidence state
- **THEN** the interface displays exactly `根据本班资料无法回答该问题` and zero sources without a model-knowledge completion

#### Scenario: Retrieval degrades to keyword only
- **WHEN** the API reports keyword-only degradation
- **THEN** the interface labels the degradation without exposing internal errors and still displays a generated answer only if the keyword evidence supports it

#### Scenario: Material is not yet searchable
- **WHEN** a material is pending, processing, unsupported, or failed
- **THEN** the interface presents that state without hiding the material's normal authorized download action

#### Scenario: User submits another question
- **WHEN** a prior answer is visible and the user submits a new question
- **THEN** the new request is evaluated independently and the client does not automatically send prior questions or answers

#### Scenario: Keyboard or assistive-technology user asks a question
- **WHEN** a user operates the question form, answer, citations, and source actions without a pointer device
- **THEN** controls, status changes, citation relationships, and source actions remain labeled, focusable, and perceivable

### Requirement: Operations are observable and restorable without content leakage
The system SHALL report retrieval, indexing, Qdrant, worker, and generation readiness without exposing secrets or content. It SHALL provide bounded aggregate job counts and SHALL include PostgreSQL retrieval data plus Qdrant snapshots or a documented vector rebuild path in backup, restore, and verification procedures. Model endpoints SHALL not be called merely to serve health checks.

#### Scenario: Retrieval is healthy but generation is unavailable
- **WHEN** PostgreSQL, material storage, keyword retrieval, Qdrant, and indexing are healthy while the generation provider is unavailable
- **THEN** health output reports generation as degraded without exposing credentials and ordinary material access remains available

#### Scenario: Qdrant is unavailable
- **WHEN** PostgreSQL and material storage remain available while Qdrant is unavailable
- **THEN** health output reports semantic retrieval as degraded, keyword retrieval remains available, and no global or unscoped fallback occurs

#### Scenario: Backup is restored
- **WHEN** operators restore coordinated PostgreSQL, material-volume, and Qdrant data
- **THEN** verification confirms that chunks reference ready same-class materials, points resolve to active same-class chunks, and an absent or incompatible vector collection can be rebuilt from authoritative data

#### Scenario: Operator inspects the queue
- **WHEN** an authorized operator runs the documented diagnostic command
- **THEN** it reports bounded aggregate indexing and dependency status without printing questions, answers, extracted content, prompts, or credentials
