"""Calls the agent on Amazon Bedrock AgentCore Runtime (docs/decisions.md, 025 and 026).

The public API (Fargate) runs agent turns here when AGENT_RUNTIME_ARN is set. AgentCore gives each
parent's conversation its own session, kept warm between turns, so the conversation state that
lives in memory stays with that parent. The runtime runs the same image, and its `/invocations`
endpoint (api.py) handles the operations below.

The runtime only accepts OAuth access tokens (inbound auth through AgentCore Identity, decision 026).
With OAUTH_TOKEN_URL set, the API gets a token from Cognito with the client-credentials grant,
caches it until shortly before it expires and calls the runtime's HTTPS endpoint with it. Without
it (a runtime with no authorizer), the API calls InvokeAgentRuntime signed with its IAM role.
"""

import base64
import json
import logging
import os
import threading
import time
import urllib.parse
from collections.abc import Iterator

import boto3
import urllib3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import REGION

log = logging.getLogger("gs_agent.runtime")

AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN")
# AgentCore session ids must be at least 33 characters
SESSION_PREFIX = "greatschools-guided-search-session-"
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"

OAUTH_TOKEN_URL = os.environ.get("OAUTH_TOKEN_URL")
OAUTH_CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET")
OAUTH_SCOPE = os.environ.get("OAUTH_SCOPE")

UNREACHABLE = "Our assistant is not reachable right now. Please try again in a moment."
# A turn can take most of a minute (several model calls); CloudFront waits 60s.
TIMEOUT = urllib3.Timeout(connect=10, read=120)

_client = None
_http = urllib3.PoolManager(retries=False, timeout=TIMEOUT)
_token: dict = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()


class RuntimeCallError(Exception):
    """The runtime answered with an error: `status` and `detail` go back to the parent app."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class RuntimeUnreachable(RuntimeCallError):
    """The runtime couldn't be reached or didn't answer (network, auth, throttling, 5xx).

    Unlike an error the runtime returns on purpose (an unknown school, a bad request), the API
    can recover from this by running the call on Fargate (api.py, decision 038).
    """

    def __init__(self):
        super().__init__(502, UNREACHABLE)


def enabled() -> bool:
    return bool(AGENT_RUNTIME_ARN)


def uses_oauth() -> bool:
    return bool(OAUTH_TOKEN_URL)


def runtime_session_id(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def invocation_url(arn: str, region: str = REGION) -> str:
    """The runtime's HTTPS endpoint, for callers with an OAuth token."""
    return (f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
            f"{urllib.parse.quote(arn, safe='')}/invocations?qualifier=DEFAULT")


def access_token() -> str:
    """A Cognito access token for the runtime (client-credentials grant), cached until near expiry."""
    with _token_lock:
        if _token["value"] and time.time() < _token["expires"] - 60:
            return _token["value"]
        basic = base64.b64encode(f"{OAUTH_CLIENT_ID}:{OAUTH_CLIENT_SECRET}".encode()).decode()
        r = _http.request("POST", OAUTH_TOKEN_URL,
                          body=urllib.parse.urlencode({"grant_type": "client_credentials", "scope": OAUTH_SCOPE}),
                          headers={"Authorization": f"Basic {basic}",
                                   "Content-Type": "application/x-www-form-urlencoded"})
        if r.status != 200:
            log.error("token request failed: %s %s", r.status, r.data[:200])
            raise RuntimeUnreachable()
        data = json.loads(r.data)
        _token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in", 3600)))
        return _token["value"]


def _bedrock_agentcore():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agentcore", region_name=REGION,
                               config=Config(read_timeout=120, connect_timeout=10, retries={"max_attempts": 2}))
    return _client


def _invoke(op: str, session_id: str, body: dict, accept: str):
    """Start one call; returns a response body with read() (and read1() when it can stream)."""
    payload = json.dumps({"op": op, **body}).encode()
    if uses_oauth():
        try:
            r = _http.request("POST", invocation_url(AGENT_RUNTIME_ARN), body=payload, preload_content=False,
                              headers={"Authorization": f"Bearer {access_token()}",
                                       "Content-Type": "application/json", "Accept": accept,
                                       SESSION_HEADER: runtime_session_id(session_id)})
        except urllib3.exceptions.HTTPError:
            log.exception("AgentCore Runtime call failed (%s, session %s)", op, session_id)
            raise RuntimeUnreachable()
        if r.status != 200:
            log.error("AgentCore Runtime answered %s (%s, session %s): %s",
                      r.status, op, session_id, r.read(300))
            if r.status in (401, 403):  # let the next call fetch a fresh token
                _token["value"] = None
            raise RuntimeUnreachable()
        return r
    try:
        return _bedrock_agentcore().invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            runtimeSessionId=runtime_session_id(session_id),
            contentType="application/json",
            accept=accept,
            payload=payload,
        )["response"]
    except (ClientError, BotoCoreError):
        log.exception("AgentCore Runtime call failed (%s, session %s)", op, session_id)
        raise RuntimeUnreachable()


def invoke(op: str, session_id: str, body: dict) -> dict:
    """One operation on the session's runtime; returns its JSON answer or raises RuntimeCallError."""
    data = json.loads(_invoke(op, session_id, body, "application/json").read())
    if isinstance(data, dict) and "_error" in data:
        raise RuntimeCallError(data["_error"]["status"], data["_error"]["detail"])
    return data


def invoke_stream(session_id: str, body: dict) -> Iterator[bytes]:
    """A streamed turn: yields the runtime's server-sent events unchanged."""
    stream = _invoke("turn_stream", session_id, body, "text/event-stream")
    # boto3's iter_chunks() waits for 1 KB blocks, which holds short progress events back until the
    # answer arrives. read1() returns whatever bytes have arrived, so progress shows as it happens.
    raw = getattr(stream, "_raw_stream", stream)
    if hasattr(raw, "read1"):
        while chunk := raw.read1(65536):
            yield chunk
    else:
        yield from stream.iter_chunks()
