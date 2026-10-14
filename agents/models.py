"""Model wiring. Every model call goes through vertex-gateway (Gemini on Vertex, billed to the
GCP trial credit until 2026-12-16). After that date only this file changes: swap GeminiModel
for BedrockModel and keep the role -> tier mapping."""
import functools
import os

import boto3
from strands.models.gemini import GeminiModel

GATEWAY_URL = os.environ.get("GATEWAY_URL", "https://vertex-gateway-714593281128.us-central1.run.app")
TOKEN_SECRET = os.environ.get("GATEWAY_TOKEN_SECRET", "agent-factory/vertex-gateway-token")

# Two tiers: the strong model plans, designs and writes the first cut; the fast one does the
# many routine calls (tests, docs, review, small fixes).
TIERS = {
    "strong": os.environ.get("MODEL_STRONG", "gemini-4-argon"),
    "fast": os.environ.get("MODEL_FAST", "gemini-3.8-flash"),
}


@functools.cache
def _token() -> str:
    # Read once per process; the value is never logged or written to disk.
    sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return sm.get_secret_value(SecretId=TOKEN_SECRET)["SecretString"]


def model(tier: str) -> GeminiModel:
    return GeminiModel(
        client_args={"api_key": _token(), "http_options": {"base_url": GATEWAY_URL}},
        model_id=TIERS[tier],
    )
