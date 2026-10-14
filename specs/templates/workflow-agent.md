# <Name> (workflow agent)

A fixed sequence of steps with branches decided by code, where the LLM fills in individual steps.

## Context
<The business process, its stages, and who approves what.>

## Functional requirements
1. Stages, in order: <stage 1 -> stage 2 -> ...>. The order is enforced by code, not by the prompt.
2. Each stage has: input schema, output schema, a validator, and a retry limit (default 2).
3. Branching rules (plain code): <if X then stage A else stage B>.
4. Human approval gate before <irreversible action>; the run pauses and records approver and time.
5. State is persisted after every stage so a failed run resumes from the last good stage.
6. Audit log (JSON lines): stage, input hash, output hash, timestamp, actor. No sensitive free text.

## Non-functional
- Python 3.12; state store behind an interface (in-memory for tests).
- Idempotent stages: re-running a completed stage must not repeat side effects.

## Acceptance tests
- Full run through every branch.
- Crash after stage N, then resume without repeating stages 1..N.
- Approval rejected: no irreversible action taken.
