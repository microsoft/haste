# User story: checks follow the pull request

## US-001

As a contributor, I want a prerequisite-based pull request to receive the
same eligible checks as a pull request to main.

Acceptance: changing a PR base to another branch does not exclude its
pull-request event. Existing path filters, permissions and publication
guards continue to apply.

## Agent Assignment Map

| Story | Implementing agent | Validating agent |
|---|---|---|
| US-001 | backend-dev | backend-validation |
