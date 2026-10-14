# Prior-authorisation intake service (health plan / payer)

## Context
A US health plan receives prior-authorisation (PA) requests from providers for procedures and
specialty drugs. Today they arrive by fax and are keyed in by hand. We need a small API service
that accepts structured PA requests, checks them against the plan's coverage rules, and routes
each one to auto-approve, clinical review, or "more information needed".

## Functional requirements
1. `POST /pa-requests` accepts a request: member id, provider NPI (10 digits), CPT/HCPCS code,
   ICD-10 diagnosis codes (1-12), place of service, requested units, clinical notes (free text).
2. Validate formats (NPI Luhn check per CMS, ICD-10 pattern, CPT 5 chars). Reject bad input with 422.
3. Coverage rules live in a JSON file (`rules/coverage.json`): per CPT code: covered (bool),
   requires_pa (bool), max_units, required diagnosis code prefixes. Load at start-up.
4. Decision logic:
   - CPT not covered -> `denied_not_covered`
   - CPT does not require PA -> `no_pa_required`
   - diagnosis matches a required prefix and units <= max_units -> `auto_approved`
   - clinical notes shorter than 50 characters -> `pended_more_info`
   - otherwise -> `clinical_review`
5. `GET /pa-requests/{id}` returns status and decision reason.
6. Every decision is written to an append-only audit log (JSON lines) with request id, rule
   applied, timestamp, and actor "system". Clinical notes must NOT be written to logs (HIPAA
   minimum necessary).
7. Turnaround timestamps: record received_at and decided_at; expose `due_by` = received_at + 72h
   (urgent: 24h if `urgent: true`), in line with CMS-0057-F timelines.

## Non-functional
- Python 3.12, FastAPI, in-memory store is fine (pluggable interface for a database later).
- No real member or provider data anywhere: fixtures must use clearly fake values.
- API key auth via `X-API-Key` header (key from an environment variable); 401 without it.
