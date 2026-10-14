# <Name> (task agent)

A single-purpose agent: one input, one bounded job, one structured output. No memory between runs.

## Context
<Who uses it, what job it replaces, and why one LLM call plus tools is enough.>

## Functional requirements
1. Input: <schema, e.g. JSON with fields ...>. Validate and reject bad input with a clear error.
2. Tools (stubbed with fixtures, no real network): <list each tool: name, inputs, outputs>.
3. Output: <schema>. Every output field must be traceable to the input or a tool result.
4. Failure behaviour: <what the agent returns when a tool fails or the input is ambiguous>.
5. Cost guard: max <N> model calls and <N> tool calls per run; abort with a typed error beyond that.

## Non-functional
- Python 3.12, Strands Agents. Model name comes from `agents/models.py`, never hard-coded.
- Deterministic tests: model replaced by a fake that returns scripted tool calls.
- No real personal data anywhere; fixtures use clearly fake values.

## Acceptance tests
- <happy path with expected output>
- <tool failure path>
- <bad input path>
