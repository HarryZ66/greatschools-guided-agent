"""AgentCore Gateway MCP tools (decision 027): the Lambda handler, the IAM signer and the fallback."""

import json
from types import SimpleNamespace

import httpx2

from gs_agent import gateway_client as G
from gs_agent import gateway_tools as T
from gs_agent import search


def _context(tool):
    return SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"gs-data___{tool}"}))


def test_at_least_three_tools_with_schemas():
    assert T.TOOL_NAMES == ["lookup_guide", "search_programs", "find_school_by_name", "get_school"]
    assert all(t["inputSchema"]["required"] for t in T.SCHEMAS)


def test_lambda_handler_runs_the_named_tool(monkeypatch):
    monkeypatch.setattr(search, "lookup_content", lambda q: [{"id": "charter", "title": f"About {q}"}])
    assert T.handler({"question": "charter"}, _context("lookup_guide")) == {
        "result": [{"id": "charter", "title": "About charter"}]}
    assert T.handler({}, _context("nope")) == {"error": "ValueError: Unknown tool: nope"}


def test_without_a_gateway_tools_run_in_process(monkeypatch):
    monkeypatch.setattr(G, "GATEWAY_URL", None)
    monkeypatch.setattr(search, "find_by_name", lambda name: [{"school_id": "fl-1", "name": name}])
    assert G.call("find_school_by_name", {"name": "Lanternfish", "unused": ""}) == [{"school_id": "fl-1", "name": "Lanternfish"}]


def test_gateway_requests_are_sigv4_signed(monkeypatch):
    creds = SimpleNamespace(access_key="AKIDEXAMPLE", secret_key="secret", token="session-token")
    monkeypatch.setattr(G.boto3, "Session", lambda: SimpleNamespace(
        get_credentials=lambda: SimpleNamespace(get_frozen_credentials=lambda: creds)))
    request = httpx2.Request("POST", "https://gw.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
                             content=json.dumps({"jsonrpc": "2.0"}).encode(), headers={"Content-Type": "application/json"})
    signed = next(G.SigV4().auth_flow(request))
    assert signed.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/bedrock-agentcore/aws4_request" in signed.headers["Authorization"]
    assert signed.headers["X-Amz-Security-Token"] == "session-token"
