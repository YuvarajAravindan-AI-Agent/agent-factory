# Agent Factory: architecture, configuration and handoff

Written at the end of a working session so the design survives even if the AWS and GCP resources are
torn down. It describes what is in this repo and what is not. No account ids, tokens or run ids are
recorded here; placeholders are in angle brackets.

## 1. What it is

A spec-to-codebase pipeline. A markdown spec goes in. Specialised AI agents plan, code, test, review
and document it. Independent machine checks verify the result, and a human approves by email.
Everything runs on AWS except the language model, which is Gemini on Vertex AI reached through a
gateway on GCP Cloud Run (planned switch to Bedrock after 2026-12-16, by editing `agents/models.py`).

Principle: agents never grade their own work. Agents write; deterministic checks verify; a person decides.

## 2. Components (all defined in `infra/`)

| Piece | AWS service | File | Notes |
|---|---|---|---|
| Orchestration | Step Functions `af-pipeline` | `infra/pipeline.asl.json`, `sfn.tf` | Bounded retry loops, 7-day approval wait |
| Agent roles | AgentCore Runtime (Strands harness, direct code deploy, arm64 Python 3.12) | `runtime.tf`, `agents/` | One microVM per role and attempt |
| Agent sandbox | AgentCore Code Interpreter `aws.codeinterpreter.v1` | `agents/sandbox_ci.py` | No internet, no AWS credentials |
| Independent test gate | CodeBuild `af-deps` (internet, wheels only) then `af-test` (no internet) | `codebuild.tf`, `buildspecs/` | Private VPC with S3 endpoint only |
| Screening | Bedrock Guardrails via `ApplyGuardrail` | `guardrail.tf`, `lambdas/tasks.py` | Input spec and output docs |
| Glue | Lambda `af-tasks`, Lambda `af-approve` (function URL) | `lambdas.tf`, `lambdas/` | Starts agents, reads build logs, approval links |
| Approval | SNS topic `af-approvals` plus email | `lambdas.tf` | Task token in the link, confirmation page then POST |
| Evidence | S3 `af-workspace-<account-id>` | `main.tf` | `runs/<run_id>/` spec, workspace, logs, reports; 30-day lifecycle; `force_destroy = true` |
| Model | Secrets Manager secret `agent-factory/vertex-gateway-token` + Cloud Run `vertex-gateway` | `agents/models.py` | Gateway is NOT in this repo |
| State | S3 `af-tfstate-<account-id>`, key `agent-factory/terraform.tfstate` | `backend.tf`, `scripts/migrate-state.sh` | Versioned bucket |

Defaults (`infra/main.tf`): region `us-east-1`, AWS profile `enterprises`, name prefix `af`, approval
email in `var.notify_email`, gateway URL in `var.gateway_url`.

Runtime environment (`infra/runtime.tf`): `WORKSPACE_BUCKET`, `GATEWAY_URL`, `GATEWAY_TOKEN_SECRET`,
`MODEL_STRONG=gemini-4-argon`, `MODEL_FAST=gemini-3.8-flash`.

Model tiers (`agents/models.py`): strong = Architect, Coder, and the Fixer from its second attempt;
fast = Tester, Reviewer, Docs, first-attempt Fixer.

## 3. The pipeline

```
spec ─▶ GuardInput ─▶ Architect ─▶ Coder ─▶ Tester ⇄ FixTests (max 3 rounds)
     ─▶ BuildDeps (internet, wheels only) ─▶ BuildTest (no internet) ⇄ FixBuild (1 fix, back to Tester)
     ─▶ Reviewer ⇄ FixFindings (1 round, then re-test and re-review) ─▶ Docs ─▶ GuardOutput
     ─▶ Package (zip + 7-day link) ─▶ AwaitApproval (email, 7 days) ─▶ Approved | Rejected | Expired
```

Stop conditions: `InputBlocked`, `TestsFailed`, `SandboxBuildFailed`, `BlockingFindings`, `OutputBlocked`,
`Rejected`, `ApprovalExpired`, `AgentStepFailed`. Approval does not deploy anything; deployment
into a throwaway sandbox account is Phase 2 and not built.

How an agent step works: Step Functions calls `af-tasks` with a task token. The Lambda invokes the
AgentCore runtime with a fresh session id and returns at once. The runtime works in a background
thread (no 15-minute Lambda limit), then reports with `SendTaskSuccess` or `SendTaskFailure`
(error type, error chain and traceback). The runtime also re-runs pytest itself after each agent, so
a pass is never just the model's claim.

Diagram: `docs/diagrams/agent-factory-flow.html` (open in a browser).

## 4. Rebuild from scratch

1. AWS credentials with admin rights (the project used the `enterprises` profile).
2. Gateway: deploy `vertex-gateway` on Cloud Run (separate repo, see section 7), then run
   `scripts/setup-gateway-token.sh` to create the per-client token in Secrets Manager.
3. `scripts/package_agent.sh` (needs `uv`) builds `build/agent.zip`.
4. Terraform backend, then apply:
   ```
   terraform -chdir=infra init \
     -backend-config="bucket=af-tfstate-<account-id>" \
     -backend-config="key=agent-factory/terraform.tfstate" \
     -backend-config="region=us-east-1" -backend-config="use_lockfile=true"
   terraform -chdir=infra apply
   ```
   Confirm the SNS subscription email once.
5. `scripts/run.sh specs/<name>.md`, then watch the Step Functions execution and `runs/<run_id>/logs/`.

If the tfstate bucket is gone, create it first (see `scripts/migrate-state.sh`) or use a local state.

## 5. Problems found and fixed (so they are not repeated)

| Symptom | Cause | Fix |
|---|---|---|
| `af-deps` never started: `YAML_FILE_ERROR` | `--only-binary=:all: -d` contains a colon and a space, so YAML read the command as a mapping | Quote the command in `buildspecs/deps.yml` |
| Reviewer failed with `EventLoopException` and an empty cause | Strands wraps the model or network error and its message was empty, so keyword retry never matched | `describe()` and `is_transient()` in `agents/roles.py`; `agents/app.py` reports the chain and traceback |
| Review gate never converged | Reviewer demanded a database although the spec allowed in-memory, and reported fixed issues | Reviewer reads `SPEC.md`, quotes code, lists spec-accepted limits separately |
| Fixer could not fix review findings | `FixFindings` passed only the last 1,500 characters of the reviewer's chat reply | Fixer prompt reads `review.json` and `docs/REVIEW.md` |
| Specs lacked security requirements | Reviewer can only check what the spec asks | Requirements 8 to 13 added to `specs/prior-auth.md` |

## 6. Status and known gaps

- One spec (`specs/prior-auth.md`) has run end to end; the last run passed review with 0 blocking
  findings and 68 tests passed locally. The other templates in `specs/templates/` have not been run.
- The last run was left at the approval step. Approving ends the run and deploys nothing.
- Generated code varies per run. One run created its audit log with default file permissions;
  a Coder-prompt line requiring mode 0600 was proposed but not added.
- Gemini to Bedrock switch: untested. The runtime role in `runtime.tf` allows S3 on `runs/*`, reading the gateway secret, Step Functions
  task callbacks, Code Interpreter, logs and telemetry. It has no Bedrock model-invoke permission, so
  that would need adding.
- Phase 2 (deploy approved code into a throwaway sandbox account) is not built.
- The fixes live on branch `fix-deps-buildspec-yaml` and are not merged to the main branch.

## 7. What is NOT in this repo

- `vertex-gateway`: the Cloud Run service (a separate project, kept on the owner's laptop at
  `~/Projects/vertex-gateway` according to `scripts/setup-gateway-token.sh`). It has other clients.
  Keep a private copy of that repo. Its service config can be exported with
  `gcloud run services describe vertex-gateway --region us-central1 --format export`, but that output
  contains environment variables including tokens, so store it privately and never commit it.
- Terraform state: in the versioned tfstate bucket, not in git.
- Run outputs (generated code, logs): in the workspace bucket and expire after 30 days.
- The secret value in Secrets Manager.

## 8. Media

`docs/media/` holds the walkthrough video, the LinkedIn short and the post text. `docs/media-source/`
holds the scripts that generate them (slides rendered with Chromium, narration with the open-source
Kokoro model, assembled with ffmpeg). The Kokoro model files are not included.
