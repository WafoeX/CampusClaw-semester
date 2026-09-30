# User Authentication

## Purpose

Define secure account authentication and JWT Bearer-token behavior for teachers and students across browser pages and protected APIs.

## ADDED Requirements

### Requirement: Account and password login
The system SHALL allow active teacher and student accounts to authenticate with an account identifier and password, and SHALL return the same generic failure response for an unknown account and an incorrect password.

#### Scenario: Teacher logs in successfully
- **WHEN** an active teacher submits valid credentials
- **THEN** the system returns a successful login response containing a JWT access token and safe identity metadata

#### Scenario: Student logs in successfully
- **WHEN** an active student submits valid credentials
- **THEN** the system returns a successful login response containing a JWT access token and safe identity metadata

#### Scenario: Credentials are invalid
- **WHEN** a user submits an unknown account identifier or incorrect password
- **THEN** the system returns HTTP 401 with a generic invalid-credentials error and does not issue an access token

### Requirement: JWT Bearer access tokens
The system SHALL issue bounded-lifetime JWT access tokens signed with a server-only key and SHALL require authenticated API clients to present exactly one token in an `Authorization: Bearer <token>` header. Tokens SHALL use the approved signing algorithm and validate the signature, issuer, audience, required subject/issued/expiration claims, and expiration. Tokens SHALL NOT contain password material, role, or class identifiers.

#### Scenario: Authenticated request uses a valid token
- **WHEN** a request presents a valid, unexpired Bearer token
- **THEN** the system resolves the current associated user, role, and class from server-side data for authorization

#### Scenario: Missing, malformed, expired, or invalid token is presented
- **WHEN** a request omits the Authorization header or presents a malformed, expired, incorrectly signed, wrong-issuer, wrong-audience, or otherwise invalid Bearer token
- **THEN** the system treats the request as unauthenticated and returns HTTP 401 without redirecting to HTML

#### Scenario: Account state changes after token issuance
- **WHEN** an account becomes inactive, has an unsupported role, or loses a usable class after a token was issued
- **THEN** the system denies protected access despite the token remaining otherwise valid

### Requirement: Browser stores and sends access tokens explicitly
The web client SHALL persist a successful-login access token in `localStorage`, attach it only to same-origin protected API requests through the Authorization header, and remove it when logout completes or the API reports an unauthenticated token. The web client SHALL use authenticated fetches for downloads because ordinary navigation links cannot attach the Authorization header.

#### Scenario: Browser reloads after login
- **WHEN** a user reloads the web client before the access token expires
- **THEN** the client reads the token from localStorage and restores identity through the authenticated identity API

#### Scenario: Browser downloads a material
- **WHEN** an authenticated user selects a material download
- **THEN** the client sends the Bearer token through an authenticated fetch and offers the returned file without placing the token in a URL

### Requirement: Protected resource authentication behavior
The system SHALL require authentication for protected pages and APIs while leaving the login page, login API, logout API, and health endpoint public.

#### Scenario: Unauthenticated browser requests a protected page
- **WHEN** an unauthenticated browser requests a protected application page
- **THEN** the system redirects the browser to the login page and preserves a safe same-origin return target

#### Scenario: Unauthenticated client requests a protected API
- **WHEN** an unauthenticated client requests a protected API endpoint
- **THEN** the system returns HTTP 401 without redirecting to HTML

### Requirement: Logout clears browser authentication state
The system SHALL provide an idempotent logout endpoint and client action that remove the access token from browser localStorage. The system SHALL NOT represent logout as server-side revocation of a stateless JWT.

#### Scenario: Authenticated user logs out
- **WHEN** an authenticated user invokes logout
- **THEN** the browser removes the access token and subsequent protected requests are unauthenticated

#### Scenario: Unauthenticated client logs out
- **WHEN** a client without a valid token submits a logout request
- **THEN** the endpoint completes with HTTP 204 without revealing token details

### Requirement: Passwords are never stored in plaintext
The system SHALL store only salted adaptive password hashes and SHALL never persist or log plaintext passwords. Password verification SHALL use the stored hash and a constant-time verification routine supplied by the password-hashing implementation.

#### Scenario: Account password is provisioned
- **WHEN** an account password is created or changed
- **THEN** the persisted credential is a salted adaptive hash and contains no plaintext password

#### Scenario: Login is processed
- **WHEN** a login request is handled
- **THEN** the submitted password is used only for hash verification and is excluded from application logs

### Requirement: Authentication secrets stay server-side
The system SHALL load JWT signing and equivalent authentication secrets from server-side environment configuration and SHALL refuse to start when a required secret is absent or insecurely empty. Such secrets and issued access tokens SHALL NOT be embedded in browser assets, URLs, API logs, or unauthenticated API responses.

#### Scenario: Required signing key is missing
- **WHEN** the application starts without a required JWT signing key
- **THEN** startup fails with a configuration error that does not disclose secret values

#### Scenario: Browser assets are built
- **WHEN** the web client is built or served
- **THEN** no server authentication secret is included in the delivered assets
