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
