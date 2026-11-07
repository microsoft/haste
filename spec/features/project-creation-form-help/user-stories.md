# Project Creation Form Help User Stories

## Stories

### US-001: Understand project fields

As an assessment coordinator, I want concise guidance near unfamiliar fields so that I can enter useful project metadata before validation.

**Acceptance criteria:**

- Name, description, event date, affected countries, and event types explain what information is expected.
- Guidance remains concise and does not obscure validation messages.

### US-002: Tour the drawer from any page

As a first-time user, I want the project creation tour to work wherever I open the global drawer so that guidance does not depend on my current page.

**Acceptance criteria:**

- The tour starts after the create drawer loads.
- The drawer header can restart the tour.
- Closing the drawer removes its tour overlay.

## Agent Assignment Map

| Story | Implementing agent | Validating agent |
| --- | --- | --- |
| US-001 | `ui` | `ui-validation` |
| US-002 | `ui` | `ui-validation` |