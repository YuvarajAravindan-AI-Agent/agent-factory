"""Small glue steps for the factory workflow, dispatched by "op".

invoke   start an agent role on AgentCore Runtime (returns at once; the role reports back
         to Step Functions with the task token when it finishes)
guard    run the Bedrock guardrail over the spec (input) or generated docs (output)
buildlog fetch the tail of a failed CodeBuild log so the fixer can read it
package  copy the finished workspace to deliverables/ and presign a download link
notify   email an approve/reject request carrying the task token
"""
import io
import json
import os
import uuid
import zipfile
from urllib.parse import quote

import boto3

BUCKET = os.environ["WORKSPACE_BUCKET"]
s3 = boto3.client("s3")


def handler(event, _ctx):
    return {"invoke": invoke, "guard": guard, "buildlog": buildlog,
            "package": package, "notify": notify}[event["op"]](event)


def invoke(e):
    payload = {k: e[k] for k in ("role", "run_id", "attempt", "task_token", "failure_log") if e.get(k) is not None}
    # One microVM per role/attempt keeps steps isolated from each other.
    session = f"{e['run_id']}-{e['role']}-{e.get('attempt', 1)}-{uuid.uuid4().hex}"[:100]
    r = boto3.client("bedrock-agentcore").invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"], runtimeSessionId=session,
        payload=json.dumps(payload).encode())
    body = r["response"].read() if hasattr(r.get("response"), "read") else b""
    return {"accepted": True, "session": session, "ack": body[:500].decode(errors="replace")}


def _workspace(run_id):
    body = s3.get_object(Bucket=BUCKET, Key=f"runs/{run_id}/workspace.zip")["Body"].read()
    return zipfile.ZipFile(io.BytesIO(body))


def guard(e):
    run_id, stage = e["run_id"], e["stage"]
    if stage == "input":
        texts = [s3.get_object(Bucket=BUCKET, Key=f"runs/{run_id}/spec.md")["Body"].read().decode()]
        source = "INPUT"
    else:
        z = _workspace(run_id)
        texts = [z.read(n).decode(errors="replace") for n in z.namelist()
                 if n.endswith(".md") and not n.startswith("tests/")]
        source = "OUTPUT"
    br = boto3.client("bedrock-runtime")
    findings = []
    for t in texts:
        for i in range(0, len(t), 20000):  # stay under the per-call text limit
            r = br.apply_guardrail(guardrailIdentifier=os.environ["GUARDRAIL_ID"],
                                   guardrailVersion=os.environ["GUARDRAIL_VERSION"],
                                   source=source, content=[{"text": {"text": t[i:i + 20000]}}])
            if r["action"] == "GUARDRAIL_INTERVENED":
                for a in r.get("assessments", []):
                    sip = a.get("sensitiveInformationPolicy", {})
                    for p in sip.get("piiEntities", []):
                        findings.append(f"PII:{p['type']}")
                    for rx in sip.get("regexes", []):
                        findings.append(f"PATTERN:{rx.get('name')}")
                    for f in a.get("contentPolicy", {}).get("filters", []):
                        findings.append(f"CONTENT:{f['type']}")
    return {"blocked": bool(findings), "findings": sorted(set(findings))[:50]}


def buildlog(e):
    cause = e.get("error", {}).get("Cause", "{}")
    try:
        build_id = json.loads(cause)["Build"]["Id"]
    except (ValueError, KeyError, TypeError):
        return {"log": f"Build failed before it started:\n{cause[:5000]}"}
    b = boto3.client("codebuild").batch_get_builds(ids=[build_id])["builds"][0]
    loc = b.get("logs", {}).get("s3LogsArn", "")  # arn:aws:s3:::bucket/key
    text = ""
    if loc:
        bucket, key = loc.split(":::", 1)[1].split("/", 1)
        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        try:
            import gzip
            raw = gzip.decompress(raw)
        except OSError:
            pass
        text = raw.decode(errors="replace")
    phase = next((p for p in b.get("phases", []) if p.get("phaseStatus") == "FAILED"), {})
    return {"log": f"CodeBuild {b['projectName']} failed in phase {phase.get('phaseType')}\n\n{text[-15000:]}"}


def package(e):
    run_id = e["run_id"]
    key = f"deliverables/{run_id}.zip"
    s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": f"runs/{run_id}/workspace.zip"}, Key=key)
    url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=7 * 24 * 3600)
    return {"key": key, "url": url}


def notify(e):
    base = os.environ["APPROVAL_URL"].rstrip("/")
    tok = quote(e["task_token"], safe="")
    msg = (f"Agent factory run {e['run_id']} passed tests, build sandbox, review and guardrails.\n\n"
           f"Download the codebase (link valid 7 days):\n{e['package_url']}\n\n"
           f"APPROVE: {base}/?action=approve&token={tok}\n\n"
           f"REJECT:  {base}/?action=reject&token={tok}\n")
    boto3.client("sns").publish(TopicArn=os.environ["TOPIC_ARN"],
                                Subject=f"[agent-factory] approve run {e['run_id']}"[:100], Message=msg)
    return {"sent": True}
