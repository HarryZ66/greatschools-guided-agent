import os
import sys
from pathlib import Path

# Fixed "today" so freshness rules are reproducible; set before gs_agent.config is imported.
os.environ.setdefault("GS_TODAY", "2026-11-03")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _runtime_reachable_again():
    """Each test starts with AgentCore Runtime considered reachable (api.py's short circuit breaker)."""
    api = sys.modules.get("gs_agent.api")
    if api is not None:
        api._runtime_down_until = 0.0
    yield
    if (api := sys.modules.get("gs_agent.api")) is not None:
        api._runtime_down_until = 0.0
