## Purpose

Provide a durable class-scoped file library where teachers upload teaching materials and authorized class members list and download them.

## ADDED Requirements

### Requirement: Teacher can upload one material
The system SHALL accept a teacher upload containing exactly one file and a non-empty title, SHALL enforce a configured maximum file size while receiving the content, and SHALL reject malformed or oversized input without creating a visible material.

#### Scenario: Valid material is uploaded
- **WHEN** an authenticated teacher submits one file and a non-empty title within the configured size limit
- **THEN** the system returns HTTP 201 with the created material metadata

#### Scenario: Required upload data is missing
- **WHEN** an authorized upload omits the file or supplies an empty title
- **THEN** the system returns HTTP 400 and creates no material

#### Scenario: File exceeds the configured limit
- **WHEN** an authorized upload exceeds the configured maximum file size
- **THEN** the system returns HTTP 413 and retains neither material metadata nor a partial file

### Requirement: Material file and metadata are persisted consistently
The system SHALL durably store the uploaded file and metadata including a generated material identifier, class, uploader, title, original filename, media type, byte size, SHA-256 digest, storage key, and creation time. A material SHALL become visible only when its metadata and complete file are both available.

#### Scenario: Persistence succeeds
- **WHEN** a valid upload is fully received and persistence completes
- **THEN** the material metadata and complete file are durable and the material becomes visible in its class list

#### Scenario: Persistence fails
- **WHEN** metadata or file persistence fails during upload
- **THEN** the system reports an error and cleans up partial state so no list entry points to a missing or incomplete file

### Requirement: Users can list materials for their class
The system SHALL return metadata for materials authorized by the caller's class, ordered deterministically with newest materials first.

#### Scenario: Uploaded material appears in the class list
- **WHEN** a teacher successfully uploads a material and a member of that class requests the material list
- **THEN** the list includes that material's identifier, title, original filename, media type, byte size, uploader, and creation time

#### Scenario: Class has no materials
- **WHEN** an authenticated user in a class with no materials requests the list
- **THEN** the system returns HTTP 200 with an empty collection

### Requirement: Users can inspect authorized material metadata
The system SHALL return stored metadata for a requested material only when the caller is authorized for its class.

#### Scenario: Authorized metadata request
- **WHEN** an authenticated class member requests metadata for a material in their class
- **THEN** the system returns HTTP 200 with the stored metadata

### Requirement: Users can download an authorized material
The system SHALL stream the complete stored file for an authorized material using its stored media type and original filename, and SHALL mark the response as an attachment.

#### Scenario: Authorized download succeeds
- **WHEN** an authenticated class member downloads a material in their class
- **THEN** the system returns HTTP 200, streams bytes whose size and SHA-256 digest match the stored metadata, and provides an attachment filename derived safely from the original filename

#### Scenario: Stored file is unavailable
- **WHEN** metadata exists for an authorized material but its stored file cannot be opened or verified
- **THEN** the system returns a server error without returning a partial successful download

### Requirement: File names do not control storage paths
The system SHALL generate storage keys independently of client-supplied filenames and SHALL prevent uploaded filenames from traversing or selecting server filesystem paths.

#### Scenario: Filename contains path syntax
- **WHEN** an upload supplies a filename containing directory separators or traversal sequences
- **THEN** the file is stored only under a server-generated storage key and the original filename is retained solely as sanitized metadata
