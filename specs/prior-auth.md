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
8. Access control on reads: `GET /pa-requests/{id}` requires an `X-Provider-NPI` header and returns
   403 unless it equals the `provider_npi` stored on the request (a caller must not be able to read
   another provider's requests). Unknown ids return 404.
9. Audit reads too: every `GET /pa-requests/{id}` (found, forbidden or not found) writes an audit
   entry with request id, outcome and timestamp. Still no clinical notes or member id in the log.
10. Security headers on every response: `Cache-Control: no-store`, `Pragma: no-cache`,
    `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.
11. Interactive docs (`/docs`, `/redoc`, `/openapi.json`) are disabled unless the environment
    variable `PA_ENABLE_DOCS=true`.
12. The API key must be at least 32 characters: the service refuses to start otherwise.
13. The in-memory store must never silently drop a request. When it reaches its capacity (default
    10,000) new submissions get 503 instead of evicting older records.

## Non-functional
- Python 3.12, FastAPI, in-memory store is fine (pluggable interface for a database later).
- No real member or provider data anywhere: fixtures must use clearly fake values.
- API key auth via `X-API-Key` header (key from an environment variable); 401 without it.
- Accepted for this phase (not defects): a single shared API key (no per-provider tokens or key
  rotation), an in-memory store with no database, no rate limiting (done at the gateway), a local
  audit file without hash chaining, and unpinned transitive dependencies.
