# agent-factory

Spec in, tested and reviewed codebase out. AWS-native (paid by Activate credits); model calls go
through vertex-gateway to Gemini on Vertex (GCP trial credit) until 2026-12-16, then switch to
Bedrock by editing `agents/models.py` only.

```
spec.md ─▶ Guardrail(input) ─▶ architect ─▶ coder ─▶ tester ⇄ fixer ─▶ CodeBuild deps ─▶ CodeBuild test
            (Bedrock)          (Argon)     (Argon)  (Flash)  (Flash→Argon)  (internet,     (NO internet,
                                                                              wheels only)  S3 endpoint only)
        ─▶ reviewer ⇄ fixer ─▶ docs ─▶ Guardrail(output) ─▶ package ─▶ email approve/reject ─▶ done
           (OWASP/STRIDE/       (Flash)                       (presigned   (Step Functions task token,
            HIPAA/PCI/TRAI)                                    zip, 7 days)  7-day wait)
```

| Piece | AWS service | Why |
|---|---|---|
| Agent loop per role | **Strands harness** on **AgentCore Runtime** (direct code deploy, one microVM per role/attempt) | AWS's batteries-included agent; no hand-written loop |
| Where agent commands run | **AgentCore Code Interpreter** (`aws.codeinterpreter.v1`: no internet, no AWS credentials) via `agents/sandbox_ci.py` | generated code never runs next to the runtime's credentials or the gateway token |
| Independent test gate | **CodeBuild** two-stage: `af-deps` downloads binary wheels only; `af-test` runs tests in a VPC with no IGW/NAT | the result the pipeline trusts is not produced by the model |
| Orchestration | **Step Functions** (`infra/pipeline.asl.json`), bounded fix loops, human approval | auditable history of every run |
| Screening | **Bedrock Guardrails** via `ApplyGuardrail` (prompt attack; SSN, card, bank, IBAN, NHS, Aadhaar, PAN, secrets) | blocks injected specs and leaked identifiers |
| Evidence | S3 `runs/<id>/` (spec, workspace, per-step logs, build reports), CloudTrail | 30-day lifecycle |

## First-time setup
1. `scripts/setup-gateway-token.sh`: creates the per-client gateway token in Secrets Manager and
   redeploys vertex-gateway (allows `gemini-4-argon`). Run it yourself.
2. `scripts/package_agent.sh`: builds `build/agent.zip` (arm64, Python 3.12).
3. `cd infra && terraform apply`, then confirm the SNS subscription email sent to founder@.

## Run
`scripts/run.sh specs/prior-auth.md` and watch the execution in the Step Functions console.

## Phase 2 (not built yet)
On approval, deploy into a throwaway member account (Innovation Sandbox on AWS) and run
integration tests there.
