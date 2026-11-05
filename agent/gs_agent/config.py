import json
import os
from datetime import datetime, timezone
from pathlib import Path

REGION = os.environ.get("AWS_REGION", "us-east-1")
REPO_ROOT = Path(__file__).resolve().parents[2]

# Model tiers (decision 034): most turns on the fast model, sensitive or failed ones on the strong one.
FAST_MODEL = os.environ.get("FAST_MODEL", "us.anthropic.claude-haiku-5-5")
STRONG_MODEL = os.environ.get("STRONG_MODEL", "us.anthropic.claude-sonnet-5-5")
# Set MAIN_MODEL to run every turn on one model (the evals use it to compare models).
MAIN_MODEL = os.environ.get("MAIN_MODEL") or None
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIMS = 1024
SCHOOLS_INDEX = "schools"

# Freshness thresholds (docs/contract.md, section 2)
FIELD_STALE_DAYS = 548  # ~18 months
REVIEW_STALE_DAYS = 3 * 365

# Fixed "today" can be overridden so demos and evals are reproducible.
TODAY = datetime.fromisoformat(os.environ["GS_TODAY"]).replace(tzinfo=timezone.utc) if os.environ.get("GS_TODAY") \
    else datetime.now(timezone.utc)


def search_endpoint() -> str:
    if os.environ.get("SEARCH_ENDPOINT"):
        return os.environ["SEARCH_ENDPOINT"]
    outputs = json.loads((REPO_ROOT / "infra" / "cdk-outputs.json").read_text())
    return outputs["GsDataStack"]["SearchEndpoint"]
