# <Name> (multi-agent system)

Several role agents coordinated by an orchestrator, each with narrow tools and its own output contract.

## Context
<The problem that is too broad for one agent, and how it splits by role.>

## Functional requirements
1. Roles: <role -> responsibility -> tools it may call>. A role cannot call another role's tools.
2. Orchestrator: decomposes the request, dispatches to roles, merges results, resolves conflicts.
3. Handoff contract: each role returns a typed result (schema) plus a confidence and open questions.
4. Disagreement rule: if two roles conflict, <a reviewer role decides | escalate to a human>.
5. Termination: stop when <acceptance condition> or after <N> rounds; report what is unresolved.
6. Trace: every message between agents is logged with sender, receiver, and token counts.

## Non-functional
- Python 3.12, Strands Agents (agents-as-tools or graph pattern).
- Total budget per request: <N> model calls; per-role budgets enforced in code.
- Roles are testable alone with a fake model and a fake peer.

## Acceptance tests
- Each role alone against fixtures.
- Orchestrated happy path.
- Conflicting role outputs trigger the disagreement rule.
- Budget exhaustion ends the run with a partial, clearly marked result.
