## Purpose

Define secure account authentication and session behavior for teachers and students across browser pages and protected APIs.

## ADDED Requirements

### Requirement: Account and password login
The system SHALL allow active teacher and student accounts to authenticate with an account identifier and password, and SHALL return the same generic failure response for an unknown account and an incorrect password.

#### Scenario: Teacher logs in successfully
- **WHEN** an active teacher submits valid credentials
- **THEN** the system creates an authenticated session and returns a successful login response

#### Scenario: Student logs in successfully
- **WHEN** an active student submits valid credentials
- **THEN** the system creates an authenticated session and returns a successful login response

#### Scenario: Credentials are invalid
- **WHEN** a user submits an unknown account identifier or incorrect password
- **THEN** the system returns HTTP 401 with a generic invalid-credentials error and does not create a session

### Requirement: Server-managed sessions
The system SHALL represent browser authentication with an opaque session cookie whose authoritative session state is held server-side. The cookie SHALL be HttpOnly, SHALL use SameSite=Lax or stricter, and SHALL expire no later than the associated server-side session.

#### Scenario: Authenticated request uses a valid session
- **WHEN** a request presents a valid, unexpired session cookie
- **THEN** the system resolves the associated user, role, and class for authorization

#### Scenario: Expired or unknown session is presented
- **WHEN** a request presents an expired, revoked, or unknown session cookie
- **THEN** the system treats the request as unauthenticated

### Requirement: Protected resource authentication behavior
The system SHALL require authentication for protected pages and APIs while leaving the login page, login API, and health endpoint public.

#### Scenario: Unauthenticated browser requests a protected page
- **WHEN** an unauthenticated browser requests a protected application page
- **THEN** the system redirects the browser to the login page and preserves a safe same-origin return target

#### Scenario: Unauthenticated client requests a protected API
- **WHEN** an unauthenticated client requests a protected API endpoint
- **THEN** the system returns HTTP 401 without redirecting to HTML

### Requirement: Logout revokes the session
The system SHALL provide logout that revokes the current server-side session and clears its browser cookie.

#### Scenario: Authenticated user logs out
- **WHEN** an authenticated user submits a logout request
- **THEN** the current session is revoked, the cookie is cleared, and subsequent use of that session is unauthenticated

#### Scenario: Unauthenticated client logs out
- **WHEN** a client without a valid session submits a logout request
- **THEN** the system completes the request without revealing session details

### Requirement: Passwords are never stored in plaintext
The system SHALL store only salted adaptive password hashes and SHALL never persist or log plaintext passwords. Password verification SHALL use the stored hash and a constant-time verification routine supplied by the password-hashing implementation.

#### Scenario: Account password is provisioned
- **WHEN** an account password is created or changed
- **THEN** the persisted credential is a salted adaptive hash and contains no plaintext password

#### Scenario: Login is processed
- **WHEN** a login request is handled
- **THEN** the submitted password is used only for hash verification and is excluded from application logs

### Requirement: Authentication secrets stay server-side
The system SHALL load session-signing, encryption, and equivalent authentication secrets from server-side environment configuration and SHALL refuse to start when a required secret is absent or insecurely empty. Such secrets SHALL NOT be embedded in browser assets or API responses.

#### Scenario: Required secret is missing
- **WHEN** the application starts without a required authentication secret
- **THEN** startup fails with a configuration error that does not disclose secret values

#### Scenario: Browser assets are built
- **WHEN** the web client is built or served
- **THEN** no server authentication secret is included in the delivered assets
