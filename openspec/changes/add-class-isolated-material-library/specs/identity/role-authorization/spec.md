## Purpose

Define server-enforced teacher and student permissions so user-interface choices never become the authorization boundary.

## ADDED Requirements

### Requirement: Every authenticated user has a supported role
The system SHALL associate each authenticated account with exactly one supported role, `teacher` or `student`, and SHALL reject protected operations for accounts whose role is absent or unsupported.

#### Scenario: Supported role is resolved
- **WHEN** a valid session is resolved for a teacher or student
- **THEN** the resolved role is available to server-side authorization checks

#### Scenario: Role is unsupported
- **WHEN** a session resolves to an account without a supported role
- **THEN** the system denies protected access

### Requirement: Material upload is teacher-only
The system SHALL authorize material upload on the server only for authenticated teachers. Hiding or disabling upload controls in the web client SHALL NOT replace this server-side check.

#### Scenario: Teacher invokes the upload API
- **WHEN** an authenticated teacher submits a valid material upload for their class
- **THEN** the system permits the request to proceed to material validation and persistence

#### Scenario: Student invokes the upload API
- **WHEN** an authenticated student invokes the material upload API with otherwise valid input
- **THEN** the system returns HTTP 403 and creates neither material metadata nor a stored file

#### Scenario: Upload control is not visible to a student
- **WHEN** an authenticated student views the material library
- **THEN** the web client does not offer an upload action, while the upload API remains independently protected

### Requirement: Teachers and students may read authorized class materials
The system SHALL permit both supported roles to list, inspect, and download materials only when class-isolation requirements authorize the resource.

#### Scenario: Student reads a material in their class
- **WHEN** an authenticated student requests a material that belongs to their class
- **THEN** the server authorizes the read operation

#### Scenario: Teacher reads a material in their class
- **WHEN** an authenticated teacher requests a material that belongs to their class
- **THEN** the server authorizes the read operation
