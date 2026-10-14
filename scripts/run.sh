#!/usr/bin/env bash
# Start a factory run from a spec file:  scripts/run.sh specs/prior-auth.md
set -euo pipefail
cd "$(dirname "$0")/.."
SPEC=${1:?usage: scripts/run.sh <spec.md>}
AWS="${AWS_BIN:-$HOME/.local/bin/aws} --profile enterprises --region us-east-1"
OUT=$(terraform -chdir=infra output -json)
BUCKET=$(echo "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["bucket"]["value"])')
SM=$(echo "$OUT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["state_machine_arn"]["value"])')
RUN="$(basename "$SPEC" .md)-$(date +%Y%m%d-%H%M%S)"
$AWS s3 cp "$SPEC" "s3://$BUCKET/runs/$RUN/spec.md" --only-show-errors
$AWS stepfunctions start-execution --state-machine-arn "$SM" --name "$RUN" \
  --input "{\"run_id\":\"$RUN\"}" --query executionArn --output text
echo "run_id=$RUN  (watch it in the Step Functions console, logs in s3://$BUCKET/runs/$RUN/logs/)"
