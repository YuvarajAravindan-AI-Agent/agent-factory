# <Name> (autonomous agent)

A goal-driven agent that plans and acts over many steps with minimal supervision. Highest risk tier.

## Context
<The standing goal, the environment it acts in, and what "done" and "stuck" look like.>

## Functional requirements
1. Goal intake: a goal plus constraints (budget, deadline, forbidden actions) validated up front.
2. Plan-act-observe loop with a persisted plan; each step records the reason for the action.
3. Allow-list of actions with per-action limits (count, amount, scope). Anything outside is refused.
4. Irreversible or external actions need human approval; the default is dry-run.
5. Stop conditions: goal met, budget spent, N steps without progress, or any policy violation.
6. Kill switch: a flag checked before every step that halts the agent cleanly.
7. Full replayable trace; a run can be reconstructed from the log alone.

## Non-functional
- Python 3.12, Strands Agents. Actions run only in the sandbox; the environment is simulated in tests.
- No credentials or real endpoints in code or fixtures.

## Acceptance tests
- Goal met within budget.
- Out-of-allow-list action refused and logged.
- No-progress loop stops after N steps.
- Kill switch halts mid-run.
- Approval-required action is not executed without approval.
