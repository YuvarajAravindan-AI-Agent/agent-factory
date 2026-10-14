"""AgentCore Runtime entrypoint.

Step Functions calls a tiny Lambda with a task token; the Lambda invokes this runtime, which
accepts the job, works in the background (ping reports HealthyBusy so the session stays alive,
up to 8 h) and reports back with SendTaskSuccess/SendTaskFailure. No step is bound by Lambda's
15-minute limit."""
import json
import threading

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from roles import run_role

app = BedrockAgentCoreApp()
sfn = boto3.client("stepfunctions")


@app.entrypoint
def handler(payload, context=None):
    token = payload.pop("task_token", None)
    if not token:  # synchronous call (local testing)
        return run_role(payload)
    task_id = app.add_async_task(payload["role"], {"run_id": payload["run_id"]})

    def work():
        try:
            sfn.send_task_success(taskToken=token, output=json.dumps(run_role(payload)))
        except Exception as e:  # report every failure so the workflow never hangs
            sfn.send_task_failure(taskToken=token, error=type(e).__name__[:256], cause=str(e)[:30000])
        finally:
            app.complete_async_task(task_id)

    threading.Thread(target=work, daemon=True).start()
    return {"accepted": True, "role": payload["role"], "run_id": payload["run_id"]}


if __name__ == "__main__":
    app.run()
