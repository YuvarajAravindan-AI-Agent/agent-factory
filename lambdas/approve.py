"""Approve/reject endpoint (Lambda Function URL). The Step Functions task token in the link is
the credential: it is unguessable, single-use and expires with the workflow's 7-day wait.

GET only shows a confirmation page; the decision is sent by POST from that page, so email link
scanners that pre-open URLs can never approve a run by accident."""
import base64
import html
import json
from urllib.parse import parse_qs

import boto3

sfn = boto3.client("stepfunctions")


def _page(body, code=200):
    return {"statusCode": code, "headers": {"content-type": "text/html; charset=utf-8"},
            "body": "<!doctype html><meta name=viewport content='width=device-width'>"
                    f"<body style='font-family:system-ui;padding:24px;max-width:640px'>{body}</body>"}


def handler(event, _ctx):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method == "GET":
        q = event.get("queryStringParameters") or {}
        token, action = q.get("token"), q.get("action")
        if not token or action not in ("approve", "reject"):
            return _page("<h2>Missing or invalid link.</h2>", 400)
        return _page(f"<h2>{action.title()} this run?</h2>"
                     f"<form method=post><input type=hidden name=token value=\"{html.escape(token)}\">"
                     f"<input type=hidden name=action value={action}>"
                     f"<button style='font-size:18px;padding:10px 20px'>Confirm {action}</button></form>")
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    form = {k: v[0] for k, v in parse_qs(raw).items()}
    token, action = form.get("token"), form.get("action")
    if not token or action not in ("approve", "reject"):
        return _page("<h2>Invalid request.</h2>", 400)
    try:
        if action == "approve":
            sfn.send_task_success(taskToken=token, output=json.dumps({"approved": True}))
            return _page("<h2>Approved.</h2><p>The run will finish now.</p>")
        sfn.send_task_failure(taskToken=token, error="Rejected", cause="Rejected by approver")
        return _page("<h2>Rejected.</h2><p>The run has been stopped.</p>")
    except (sfn.exceptions.TaskTimedOut, sfn.exceptions.InvalidToken, sfn.exceptions.TaskDoesNotExist):
        return _page("<h2>This link has expired or was already used.</h2>", 410)
