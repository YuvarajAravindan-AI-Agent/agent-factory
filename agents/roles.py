"""Pipeline roles. Each role is a Strands harness agent with its own instructions and model tier,
working on a shared workspace that is persisted to S3 between steps.

Gates are deterministic: after the agent finishes, the runtime re-runs the tests itself and
reports the real exit code, so a step never passes because the model *said* it passed.
Checklist ideas in REVIEWER/ARCHITECT are adapted from garrytan/gstack (MIT)."""
import io
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import boto3
from strands import tool
from strands_harness import create_harness

from models import model
from sandbox_ci import CodeInterpreterSandbox

BUCKET = os.environ.get("WORKSPACE_BUCKET", "")
s3 = boto3.client("s3")

COMMON = """You are one role in an automated software factory for regulated industries
(healthcare, finance, telecom). The workspace root is your current directory. SPEC.md is the
customer's requirement. Never invent real patient, customer or card data: use obviously fake
fixtures. There is no internet in your sandbox: after editing requirements.txt call the
install_requirements tool (never pip install directly). Python 3.12, FastAPI preferred for APIs.
Keep files small and readable. When done, end with a 3-6 line summary of what you changed."""

ROLES = {
    "architect": ("strong", """ROLE: architect. Read SPEC.md. Write docs/PLAN.md (scope, assumptions,
acceptance criteria as a numbered list, file layout, data model, API endpoints) and
docs/ARCHITECTURE.md (components, data flow, trust boundaries, which regulation clauses apply and
how the design meets them: e.g. HIPAA minimum-necessary and audit logging, PCI DSS data
minimisation, TRAI/consent). Lock decisions; list explicit non-goals. Write NO application code."""),
    "coder": ("strong", """ROLE: coder. Implement docs/PLAN.md exactly: application code under app/,
requirements.txt (pinned, minimal), and starter tests under tests/ covering each acceptance
criterion. Include structured audit logging for every state-changing action and input validation
on every endpoint. Run `python3 -m pytest -q` and fix what you broke before finishing."""),
    "tester": ("fast", """ROLE: tester. Read docs/PLAN.md acceptance criteria and the code. Add or fix
tests in tests/ so every criterion has at least one test, plus edge cases (bad input, missing
fields, authorisation failures). Run `python3 -m pytest -q`. If a failure is a genuine app bug,
fix the app minimally. Do not delete or weaken tests to make them pass."""),
    "fixer": ("fast", """ROLE: fixer. FAILURE.md contains a failing test or build log. Find the root
cause and make the smallest correct fix. Do not delete or weaken tests. Run `python3 -m pytest -q`
until green, then explain the root cause in your summary."""),
    "reviewer": ("fast", """ROLE: security and compliance reviewer. Review the code read-only (do not
edit app code). Check: OWASP Top 10 (injection, broken auth/authz, sensitive data exposure,
SSRF, insecure deserialisation), STRIDE threats at each trust boundary in docs/ARCHITECTURE.md,
secrets in code, PII/PHI in logs, missing audit trail, missing input validation, dependency risk.
Write docs/REVIEW.md with a findings table (id, severity critical/high/medium/low, file:line,
issue, fix). Also write review.json: {"blocking": <count of critical+high>, "findings": [...]}."""),
    "docs": ("fast", """ROLE: technical writer. Write README.md (what it does, how to run, how to test,
API summary) and docs/RUNBOOK.md (deploy, config, health checks, audit-log location, incident
steps). Keep them accurate to the code; do not change code."""),
}


RETRYABLE_TEXT = ("model turn", "429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
                  "timed out", "timeout", "connection", "disconnected", "reset by peer")
RETRYABLE_TYPES = ("Timeout", "ConnectError", "ReadError", "RemoteProtocolError", "ConnectionError",
                   "ServerError")


def describe(e: BaseException) -> str:
    """Type + message for e and everything it wraps. Strands wraps model errors in EventLoopException
    whose str() is empty when the inner error (e.g. an HTTP timeout) has no message."""
    parts, seen = [], set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        parts.append(f"{type(e).__name__}: {e}")
        e = getattr(e, "original_exception", None) or e.__cause__ or e.__context__
    return " <- ".join(parts)


def is_transient(e: BaseException) -> bool:
    d = describe(e)
    return any(k.lower() in d.lower() for k in RETRYABLE_TEXT + RETRYABLE_TYPES)


def _ws_key(run_id: str) -> str:
    return f"runs/{run_id}/workspace.zip"


def _load_workspace(run_id: str, local: Path) -> None:
    shutil.rmtree(local, ignore_errors=True)
    local.mkdir(parents=True)
    try:
        body = s3.get_object(Bucket=BUCKET, Key=_ws_key(run_id))["Body"].read()
        zipfile.ZipFile(io.BytesIO(body)).extractall(local)
    except s3.exceptions.NoSuchKey:
        spec = s3.get_object(Bucket=BUCKET, Key=f"runs/{run_id}/spec.md")["Body"].read()
        (local / "SPEC.md").write_bytes(spec)


def _save_workspace(run_id: str, local: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in local.rglob("*"):
            if f.is_file() and not ({"__pycache__", ".pytest_cache", "wheels"} & set(f.parts)):
                z.write(f, f.relative_to(local))
    s3.put_object(Bucket=BUCKET, Key=_ws_key(run_id), Body=buf.getvalue())


def run_role(payload: dict) -> dict:
    role, run_id = payload["role"], payload["run_id"]
    attempt = int(payload.get("attempt", 1))
    tier, prompt = ROLES[role]
    if role == "fixer" and attempt >= 2:
        tier = "strong"  # escalate repeated failures to the strong model
    local = Path(f"/tmp/runs/{run_id}/ws")
    _load_workspace(run_id, local)
    if payload.get("failure_log"):
        (local / "FAILURE.md").write_text(payload["failure_log"][-20000:])

    sb = CodeInterpreterSandbox()
    started = time.time()
    try:
        sb.start()
        sb.push_dir(local)
        sb.install_requirements(local / "requirements.txt")
        @tool
        def install_requirements() -> str:
            """Install the packages listed in requirements.txt into the sandbox. The sandbox has no
            internet, so call this after you add or change requirements.txt instead of pip."""
            sb.pull_dir(local)
            r = sb.install_requirements(local / "requirements.txt")
            return f"exit={r.exit_code}\n{r.stdout}\n{r.stderr}"

        def build():
            return create_harness(
                tools=[install_requirements],
                model=model(tier),
                instructions=COMMON + "\n\n" + prompt,
                builtin_tools=["shell", "read", "write", "edit"],
                builtin_plugins=[],
                session=False, memory=False, skills=False, context_manager=False,
                sandbox=sb,
            )

        # Gemini occasionally answers 400 "requests ending with a model turn" or 429/5xx mid-loop.
        # The sandbox keeps the work done so far, so retrying with a fresh agent is safe.
        reply, last = "", None
        for n in range(1, 4):
            try:
                note = "" if n == 1 else (" Earlier work in this workspace is kept: inspect the files first and "
                                          "continue where you left off.")
                reply = str(build()(f"Do your {role} step now. Attempt {attempt}.{note}"))
                last = None
                break
            except Exception as e:  # noqa: BLE001
                last = e
                if not is_transient(e):
                    raise
                time.sleep(10 * n)
        if last is not None:
            raise RuntimeError(f"model call failed after 3 attempts: {describe(last)}") from last
        # Deterministic gate, independent of what the model claims.
        sb.pull_dir(local)
        sb.install_requirements(local / "requirements.txt")
        tests = sb._run_sync(f"cd {sb.root} && timeout 600 python3 -m pytest -q 2>&1 | tail -40")
        sb.pull_dir(local)
    finally:
        sb.stop()

    (local / "FAILURE.md").unlink(missing_ok=True)
    _save_workspace(run_id, local)
    has_tests = (local / "tests").exists()
    tests_ok = has_tests and "passed" in tests.stdout and "failed" not in tests.stdout and "error" not in tests.stdout.lower()
    review = {}
    if role == "reviewer" and (local / "review.json").exists():
        try:
            review = json.loads((local / "review.json").read_text())
        except ValueError:
            review = {"blocking": 1, "findings": [], "note": "review.json was not valid JSON"}
    log = f"# {role} (attempt {attempt}, model tier {tier})\n\n{reply}\n\n## pytest\n```\n{tests.stdout}\n```\n"
    s3.put_object(Bucket=BUCKET, Key=f"runs/{run_id}/logs/{int(started)}-{role}-{attempt}.md", Body=log.encode())
    return {
        "role": role, "run_id": run_id, "attempt": attempt, "tier": tier,
        "seconds": int(time.time() - started),
        "tests_ok": tests_ok, "has_tests": has_tests,
        "test_tail": tests.stdout[-3000:],
        "blocking": int(review.get("blocking", 0)) if role == "reviewer" else 0,
        "summary": reply[-1500:],
    }
