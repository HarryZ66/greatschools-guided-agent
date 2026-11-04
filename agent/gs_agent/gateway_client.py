"""The agent's MCP client for the AgentCore Gateway (decision 027).

With GATEWAY_URL set, the agent's data lookups (parent guide, programs, school by name, school
record) go to the Gateway's MCP tools, which run in a Lambda function. The Gateway uses IAM
inbound auth, so every MCP request is SigV4-signed with the agent's role. Without GATEWAY_URL
(local runs, tests) the same code runs in-process.
"""

import json
import logging
import os
import uuid
from collections.abc import Generator

import boto3
import httpx2
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from strands.tools.mcp import MCPClient

from . import gateway_tools
from .config import REGION

log = logging.getLogger("gs_agent.gateway")

GATEWAY_URL = os.environ.get("GATEWAY_URL")
TARGET = os.environ.get("GATEWAY_TARGET", "gs-data")
SERVICE = "AgentCore Gateway (MCP) → AWS Lambda"


class GatewayError(Exception):
    pass


def enabled() -> bool:
    return bool(GATEWAY_URL)


class SigV4(httpx2.Auth):
    """Signs each MCP HTTP request for the Gateway's IAM authorizer."""

    requires_request_body = True

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        credentials = boto3.Session().get_credentials().get_frozen_credentials()
        signed = AWSRequest(method=request.method, url=str(request.url), data=request.content,
                            headers={"Content-Type": request.headers.get("Content-Type", "application/json")})
        SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(signed)
        for key, value in signed.headers.items():
            request.headers[key] = value
        yield request


def _transport():
    return streamable_http_client(GATEWAY_URL, http_client=create_mcp_http_client(auth=SigV4()))


def call(tool: str, args: dict):
    """Run one tool: through the Gateway over MCP if configured, otherwise in-process."""
    args = {k: v for k, v in args.items() if v not in (None, "", [])}
    if not enabled():
        return gateway_tools.run(tool, args)
    client = MCPClient(_transport)
    with client:
        result = client.call_tool_sync(tool_use_id=uuid.uuid4().hex, name=f"{TARGET}___{tool}", arguments=args)
    text = "".join(c.get("text", "") for c in result.get("content", []))
    if result.get("status") != "success":
        log.error("gateway tool %s failed: %s", tool, text[:300])
        raise GatewayError(f"The {tool} tool failed")
    data = json.loads(text) if text else {}
    if isinstance(data, dict) and "error" in data:
        log.error("gateway tool %s returned an error: %s", tool, data["error"])
        raise GatewayError(data["error"])
    return data.get("result") if isinstance(data, dict) else data
