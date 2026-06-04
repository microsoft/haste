---
description: "Generate unit tests for a file or function"
agent: backend-dev
tools: ["read", "edit", "search", "execute"]
argument-hint: "Specify the file or function to test"
---

Generate comprehensive unit tests for the specified code.

## Instructions

1. Read the source file to understand the code's behavior, inputs, outputs, and edge cases.
2. Create a test file in `hastelib/tests/` following pytest conventions.
3. Include:
   - Happy path tests for normal operation
   - Error/failure case tests
   - Edge case tests (empty inputs, nulls, boundary values)
   - Tests for any documented or obvious side effects
4. Mock external dependencies (Azure Blob, Cosmos DB, Azure Batch, queues).
5. Run `cd hastelib && hatch run test:pytest` to verify all tests pass.
6. Report the test count and coverage summary.
