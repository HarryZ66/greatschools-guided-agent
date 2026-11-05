"""Agent turns on AgentCore Runtime (decision 025): the API passes them on, the runtime serves them."""

import io
import json

from fastapi.testclient import TestClient

from gs_agent import api
from gs_agent import runtime_client as rc


class FakeAgentCore:
    """Stands in for boto3's bedrock-agentcore client."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append({**kwargs, "payload": json.loads(kwargs["payload"])})
        if kwargs["accept"] == "text/event-stream":
            return {"response": FakeStream(self.answer)}
        return {"response": io.BytesIO(json.dumps(self.answer).encode())}


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_chunks(self):
        yield from self.chunks


def _use_runtime(monkeypatch, answer):
    fake = FakeAgentCore(answer)
    monkeypatch.setattr(rc, "AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/gs")
    monkeypatch.setattr(rc, "_client", fake)
    return fake


def test_a_new_conversation_gets_its_own_runtime_session(monkeypatch):
    fake = _use_runtime(monkeypatch, {"session_id": "x", "blocks": []})
    body = TestClient(api.app).post("/api/turn", json={"event": {"type": "query", "text": "STEM near Miami"}}).json()
    assert body == {"session_id": "x", "blocks": []}
    call = fake.calls[0]
    sent = call["payload"]["request"]
    assert call["payload"]["op"] == "turn" and sent["event"] == {"type": "query", "text": "STEM near Miami"}
    assert sent["session_id"] and call["runtimeSessionId"] == rc.runtime_session_id(sent["session_id"])
    assert len(call["runtimeSessionId"]) >= 33  # AgentCore's minimum


def test_runtime_errors_reach_the_parent_app(monkeypatch):
    _use_runtime(monkeypatch, {"_error": {"status": 400, "detail": "No open question"}})
    r = TestClient(api.app).post("/api/turn", json={"session_id": "abc", "event": {"type": "answer", "option_id": "a"}})
    assert r.status_code == 400 and r.json()["detail"] == "No open question"


def test_streamed_turns_pass_through(monkeypatch):
    events = [b'event: progress\ndata: {"type": "progress", "text": "Searching"}\n\n',
              b'event: result\ndata: {"type": "result", "response": {"turn": 1}}\n\n']
    fake = _use_runtime(monkeypatch, events)
    r = TestClient(api.app).post("/api/turn/stream", json={"session_id": "abc", "event": {"type": "query", "text": "hi"}})
    assert r.text == b"".join(events).decode()
    assert fake.calls[0]["payload"]["op"] == "turn_stream"


def test_new_search_uses_the_existing_runtime_session_and_keeps_saves(monkeypatch):
    answer = {"session_id": "parent-1", "blocks": [],
              "saved": [{"school_id": "fl-1", "name": "Tamarind Cove", "at": "t"}]}
    fake = _use_runtime(monkeypatch, answer)
    client = TestClient(api.app)
    response = client.post("/api/turn", json={
        "session_id": "parent-1", "event": {"type": "new_search"},
    })
    assert response.status_code == 200 and response.json() == answer
    call = fake.calls[0]
    assert call["runtimeSessionId"] == rc.runtime_session_id("parent-1")
    assert call["payload"]["request"]["event"] == {"type": "new_search"}

    events = [f"event: result\ndata: {json.dumps({'type': 'result', 'response': answer})}\n\n".encode()]
    fake = _use_runtime(monkeypatch, events)
    response = client.post("/api/turn/stream", json={
        "session_id": "parent-1", "event": {"type": "new_search"},
    })
    assert response.text == b"".join(events).decode()
    assert fake.calls[0]["runtimeSessionId"] == rc.runtime_session_id("parent-1")
    assert fake.calls[0]["payload"]["op"] == "turn_stream"


def test_saves_and_profiles_use_the_conversation_on_the_runtime(monkeypatch):
    fake = _use_runtime(monkeypatch, {"saved": [], "programs": []})
    client = TestClient(api.app)
    client.post("/api/saved", json={"session_id": "abc", "school_id": "fl-1"})
    client.delete("/api/saved/fl-1", params={"session_id": "abc"})
    client.get("/api/schools/fl-1", params={"session_id": "abc"})
    assert [c["payload"]["op"] for c in fake.calls] == ["save", "unsave", "profile"]
    assert {c["runtimeSessionId"] for c in fake.calls} == {rc.runtime_session_id("abc")}


def test_runtime_service_contract(monkeypatch):
    monkeypatch.setattr(rc, "AGENT_RUNTIME_ARN", None)
    client = TestClient(api.app)
    assert client.get("/ping").json() == {"status": "Healthy"}
    assert client.post("/invocations", json={"op": "nope"}).json() == {"_error": {"status": 400, "detail": "Unknown operation: nope"}}


class FakeResponse:
    def __init__(self, status, data):
        self.status, self.data, self._buf = status, data, io.BytesIO(data)

    def read(self, n=-1):
        return self._buf.read(n)

    def read1(self, n=-1):
        return self._buf.read1(n)


class FakeHttp:
    """Stands in for urllib3: Cognito's token endpoint and the runtime's HTTPS endpoint."""

    def __init__(self, runtime_status=200, runtime_body=b'{"ok": true}'):
        self.calls, self.runtime_status, self.runtime_body = [], runtime_status, runtime_body

    def request(self, method, url, body=None, headers=None, preload_content=True):
        self.calls.append({"url": url, "headers": headers or {}, "body": body})
        if url.endswith("/oauth2/token"):
            return FakeResponse(200, json.dumps({"access_token": "tok-1", "expires_in": 3600}).encode())
        return FakeResponse(self.runtime_status, self.runtime_body)


def _use_oauth(monkeypatch, http):
    monkeypatch.setattr(rc, "AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/gs")
    monkeypatch.setattr(rc, "OAUTH_TOKEN_URL", "https://example.auth.us-east-1.amazoncognito.com/oauth2/token")
    monkeypatch.setattr(rc, "OAUTH_CLIENT_ID", "client")
    monkeypatch.setattr(rc, "OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(rc, "OAUTH_SCOPE", "greatschools-agent/invoke")
    monkeypatch.setattr(rc, "_http", http)
    monkeypatch.setattr(rc, "_token", {"value": None, "expires": 0.0})


def test_oauth_calls_carry_a_cached_bearer_token(monkeypatch):
    http = FakeHttp()
    _use_oauth(monkeypatch, http)
    assert rc.invoke("profile", "abc", {}) == {"ok": True}
    assert rc.invoke("profile", "abc", {}) == {"ok": True}
    token_calls = [c for c in http.calls if c["url"].endswith("/oauth2/token")]
    runtime_calls = [c for c in http.calls if "/invocations" in c["url"]]
    assert len(token_calls) == 1  # cached
    assert "grant_type=client_credentials" in token_calls[0]["body"]
    assert runtime_calls[0]["url"] == ("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/"
                                       "arn%3Aaws%3Abedrock-agentcore%3Aus-east-1%3A1%3Aruntime%2Fgs/invocations?qualifier=DEFAULT")
    assert runtime_calls[0]["headers"]["Authorization"] == "Bearer tok-1"
    assert runtime_calls[0]["headers"][rc.SESSION_HEADER] == rc.runtime_session_id("abc")


def test_a_rejected_token_is_dropped_and_the_turn_runs_on_fargate(monkeypatch):
    http = FakeHttp(runtime_status=401, runtime_body=b'{"message": "Unauthorized"}')
    _use_oauth(monkeypatch, http)
    monkeypatch.setattr(api, "_run_turn", lambda session, event: {"session_id": session.session_id, "blocks": [],
                                                                   "trace": {"steps": []}})
    r = TestClient(api.app).post("/api/turn", json={"session_id": "abc", "event": {"type": "query", "text": "hi"}})
    assert r.status_code == 200 and r.json()["trace"]["steps"][0]["tool"] == "fallback"
    assert rc._token["value"] is None


def test_oauth_streams_pass_through(monkeypatch):
    events = b'event: result\ndata: {"type": "result", "response": {"turn": 1}}\n\n'
    _use_oauth(monkeypatch, FakeHttp(runtime_body=events))
    r = TestClient(api.app).post("/api/turn/stream", json={"session_id": "abc", "event": {"type": "query", "text": "hi"}})
    assert r.text == events.decode()
