## Purpose

Make class membership the mandatory server-side data boundary for every material query, upload, metadata read, and download.

## ADDED Requirements

### Requirement: Each user belongs to exactly one class
The system SHALL associate every teacher and student account that can use protected material features with exactly one class.

#### Scenario: Account with one class accesses materials
- **WHEN** an authenticated account has exactly one class membership
- **THEN** the server uses that class as the scope for all material operations

#### Scenario: Account has no usable class
- **WHEN** an authenticated account has no class association or an invalid class association
- **THEN** the server denies material access and does not execute an unscoped material query

### Requirement: Material queries are scoped on the server
The system SHALL apply the authenticated user's class identifier in the server-side data query for material lists, metadata reads, and downloads. Client-supplied filters and hidden user-interface elements SHALL NOT be relied upon for isolation.

#### Scenario: User lists class materials
- **WHEN** an authenticated user requests the material list
- **THEN** every returned material belongs to that user's class

#### Scenario: Client supplies another class identifier
- **WHEN** a client supplies or alters a class identifier in a material request
- **THEN** the server ignores it for authorization and scopes the operation to the authenticated user's class

### Requirement: Cross-class resource access does not disclose existence
The system SHALL deny access to a material outside the authenticated user's class and SHALL make that response indistinguishable from a request for a nonexistent material.

#### Scenario: User requests another class's metadata
- **WHEN** an authenticated user requests metadata for a material belonging to a different class
- **THEN** the system returns HTTP 404 with the same error shape used for a nonexistent material

#### Scenario: User requests another class's file
- **WHEN** an authenticated user requests download of a material belonging to a different class
- **THEN** the system returns HTTP 404 and does not stream any file bytes

### Requirement: Upload class is derived from the authenticated user
The system SHALL assign an uploaded material to the authenticated teacher's class and SHALL NOT accept a client-selected class as the authoritative class assignment.

#### Scenario: Teacher uploads without a class field
- **WHEN** an authenticated teacher submits a valid upload
- **THEN** the created material is assigned to the teacher's class

#### Scenario: Teacher submits a different class identifier
- **WHEN** an authenticated teacher attempts to submit a class identifier other than their own
- **THEN** the server does not assign the material to that other class
