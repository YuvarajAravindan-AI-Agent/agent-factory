#!/usr/bin/env bash
# Run this yourself (Claude is not allowed to write secrets). It:
#  1. creates a NEW per-client token for agent-factory (never printed, never saved to disk),
#  2. stores it in AWS Secrets Manager as agent-factory/vertex-gateway-token,
#  3. redeploys vertex-gateway so it accepts that token, allows gemini-4-argon, and routes
#     gemini-4* to Vertex's global endpoint.
# The gateway's existing token and clients are unchanged. To revoke later, remove the token
# from EXTRA_GATEWAY_TOKENS on the Cloud Run service.
set -euo pipefail
AWS=~/.local/bin/aws
TOK=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))")
$AWS secretsmanager create-secret --profile enterprises --region us-east-1 \
  --name agent-factory/vertex-gateway-token \
  --description "Per-client token for vertex-gateway (agent-factory)" \
  --secret-string "$TOK" --query ARN --output text
cd ~/Projects/vertex-gateway
gcloud run deploy vertex-gateway --source . --region us-central1 \
  --project project-287c53a0-e18a-40e8-824 --account founder@ai-agentic-enterprises.com --quiet \
  --update-env-vars "^@^ALLOWED_MODELS=gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.5-pro,gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts,gemini-3.5-flash-lite,gemini-3.8-flash,gemini-3.8-flash-tts,gemini-embedding-001,gemini-4-argon@GLOBAL_MODEL_PREFIXES=gemini-3,gemini-4@EXTRA_GATEWAY_TOKENS=$TOK"
unset TOK
echo "Done. Token stored in Secrets Manager; gateway redeployed."
