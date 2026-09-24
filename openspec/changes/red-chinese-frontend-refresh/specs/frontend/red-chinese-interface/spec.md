## Purpose

为登录、材料列表与材料上传页面提供一致的红色视觉主题和中文交互控件，同时保持既有业务流程、响应式体验与可访问性。

## ADDED Requirements

### Requirement: Frontend uses a consistent red visual theme
The frontend SHALL present the login, material library, and material upload pages with a consistent red primary color, neutral readable surfaces, clear visual hierarchy, and coherent component styling.

#### Scenario: User opens a supported frontend page
- **WHEN** a user opens the login, material library, or material upload page
- **THEN** the page uses the shared red theme for primary actions, accents, focus states, and supporting visual details without reducing text readability

### Requirement: Interactive actions use Chinese labels
The frontend SHALL show Chinese visible labels for user actions, including sign-in, refresh, upload, download, return-to-library, and sign-out controls, and SHALL use corresponding Chinese progress labels while an action is pending.

#### Scenario: User views available actions
- **WHEN** the frontend renders an action control on the login, material library, or upload page
- **THEN** the control exposes an understandable Chinese visible label that describes the existing action

#### Scenario: User starts an asynchronous action
- **WHEN** sign-in, refresh, or upload is in progress
- **THEN** the affected control or status indicator presents a Chinese progress message and prevents unintended duplicate submission where the existing flow already does so

### Requirement: Visual refresh preserves existing behavior
The frontend SHALL retain the existing routes, API requests, authentication transitions, role-based upload visibility, upload validation, material listing, and file download behavior while changing presentation and visible action labels.

#### Scenario: Teacher uses the refreshed interface
- **WHEN** an authenticated teacher lists materials, opens the upload page, uploads one valid file, downloads a material, and signs out
- **THEN** each operation follows the same route, request contract, authorization rule, and result as before the visual refresh

#### Scenario: Student uses the refreshed interface
- **WHEN** an authenticated student opens the material library
- **THEN** the student can list and download authorized materials but is not offered an upload action

### Requirement: Refreshed pages remain usable across screen sizes and input methods
The frontend SHALL keep primary content and actions usable on desktop and narrow mobile viewports, SHALL provide visible keyboard focus states, and SHALL visually distinguish hover, active, disabled, loading, error, and empty states where applicable.

#### Scenario: User operates the interface on a narrow viewport
- **WHEN** the viewport width is 600 CSS pixels or less
- **THEN** page headers, action groups, forms, and material cards reflow without horizontal page overflow or inaccessible controls

#### Scenario: Keyboard user navigates interactive controls
- **WHEN** a user navigates links, buttons, and form fields using the keyboard
- **THEN** the currently focused control has a visible focus indication consistent with the red theme
