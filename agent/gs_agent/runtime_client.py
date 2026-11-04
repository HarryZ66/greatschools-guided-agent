"""Calls the agent on Amazon Bedrock AgentCore Runtime (docs/decisions.md, 025).

The public API (Fargate) runs agent turns here when AGENT_RUNTIME_ARN is set. AgentCore gives each
parent's conversation its own session, kept warm between turns, so the conversation state that
lives in memory stays with that parent. The runtime runs the same image, and its `/invocations`
endpoint (api.py) handles the operations below.
"""

import json
import logging
import os
from collections.abc import Iterator

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import REGION

log = logging.getLogger("gs_agent.runtime")

AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN")
# AgentCore session ids must be at least 33 characters
SESSION_PREFIX = "greatschools-guided-search-session-"

_client = None


class RuntimeCallError(Exception):
    """The runtime answered with an error: `status` and `detail` go back to the parent app."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def enabled() -> bool:
    return bool(AGENT_RUNTIME_ARN)


def runtime_session_id(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def _bedrock_agentcore():
    global _client
    if _client is None:
        # A turn can take most of a minute (several model calls); CloudFront waits 60s.
        _client = boto3.client("bedrock-agentcore", region_name=REGION,
                               config=Config(read_timeout=120, connect_timeout=10, retries={"max_attempts": 2}))
    return _client


def _invoke(op: str, session_id: str, body: dict, accept: str):
    try:
        return _bedrock_agentcore().invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            runtimeSessionId=runtime_session_id(session_id),
            contentType="application/json",
            accept=accept,
            payload=json.dumps({"op": op, **body}).encode(),
        )
    except (ClientError, BotoCoreError):
        log.exception("AgentCore Runtime call failed (%s, session %s)", op, session_id)
        raise RuntimeCallError(502, "Our assistant is not reachable right now. Please try again in a moment.")


def invoke(op: str, session_id: str, body: dict) -> dict:
    """One operation on the session's runtime; returns its JSON answer or raises RuntimeCallError."""
    data = json.loads(_invoke(op, session_id, body, "application/json")["response"].read())
    if isinstance(data, dict) and "_error" in data:
        raise RuntimeCallError(data["_error"]["status"], data["_error"]["detail"])
    return data


def invoke_stream(session_id: str, body: dict) -> Iterator[bytes]:
    """A streamed turn: yields the runtime's server-sent events unchanged."""
    body_stream = _invoke("turn_stream", session_id, body, "text/event-stream")["response"]
    # iter_chunks() waits for 1 KB blocks, which holds short progress events back until the
    # answer arrives. read1() returns whatever bytes have arrived, so progress shows as it happens.
    raw = getattr(body_stream, "_raw_stream", None)
    if raw is not None and hasattr(raw, "read1"):
        while chunk := raw.read1(65536):
            yield chunk
    else:
        yield from body_stream.iter_chunks()
