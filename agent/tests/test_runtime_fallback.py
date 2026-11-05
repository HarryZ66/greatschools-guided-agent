"""If AgentCore Runtime can't be reached, the API runs the call on Fargate (decision 038)."""

from fastapi.testclient import TestClient

from gs_agent import api
from gs_agent import runtime_client as rc


def local_turn(session, event):
    return {"session_id": session.session_id, "blocks": [{"type": "text", "markdown": "local"}],
            "trace": {"steps": [{"tool": "understand", "service": "x", "text": "y"}]}}


def runtime_down(*a, **k):
    raise rc.RuntimeUnreachable()


def setup(monkeypatch, invoke=runtime_down):
    monkeypatch.setattr(rc, "AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x")
    monkeypatch.setattr(rc, "invoke", invoke)
    monkeypatch.setattr(api, "_run_turn", local_turn)
    return TestClient(api.app)


def test_turn_runs_on_fargate_and_says_so_when_the_runtime_is_down(monkeypatch):
    r = setup(monkeypatch).post("/api/turn", json={"session_id": "p1", "event": {"type": "query", "text": "hi"}})
    body = r.json()
    assert r.status_code == 200 and body["session_id"] == "p1" and body["blocks"][0]["markdown"] == "local"
    assert [s["tool"] for s in body["trace"]["steps"]] == ["fallback", "understand"]


def test_after_a_failure_the_runtime_is_skipped_for_a_while(monkeypatch):
    calls = []

    def counting(*a, **k):
        calls.append(1)
        raise rc.RuntimeUnreachable()
    client = setup(monkeypatch, counting)
    for _ in range(3):
        assert client.post("/api/turn", json={"session_id": "p2", "event": {"type": "query", "text": "hi"}}).status_code == 200
    assert len(calls) == 1  # later turns go straight to Fargate instead of waiting on the runtime


def test_errors_the_runtime_returns_on_purpose_are_not_retried_locally(monkeypatch):
    def unknown_school(*a, **k):
        raise rc.RuntimeCallError(404, "Unknown school")
    r = setup(monkeypatch, unknown_school).get("/api/schools/fl-nope?session_id=p3")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown school"


def test_a_new_conversation_keeps_one_session_id_through_the_fallback(monkeypatch):
    body = setup(monkeypatch).post("/api/turn", json={"event": {"type": "query", "text": "hi"}}).json()
    assert body["session_id"] and body["session_id"] in api._sessions


def test_stream_falls_back_when_the_runtime_fails_before_sending_anything(monkeypatch):
    client = setup(monkeypatch)
    monkeypatch.setattr(rc, "invoke_stream", lambda *a, **k: (_ for _ in ()).throw(rc.RuntimeUnreachable()))
    r = client.post("/api/turn/stream", json={"session_id": "p4", "event": {"type": "query", "text": "hi"}})
    assert r.status_code == 200 and '"type": "result"' in r.text and '"tool": "fallback"' in r.text
    assert '"type": "error"' not in r.text


def test_stream_reports_an_error_if_the_runtime_fails_midway(monkeypatch):
    client = setup(monkeypatch)

    def half(*a, **k):
        yield b'event: progress\ndata: {"type": "progress", "text": "Searching"}\n\n'
        raise rc.RuntimeUnreachable()
    monkeypatch.setattr(rc, "invoke_stream", half)
    r = client.post("/api/turn/stream", json={"session_id": "p5", "event": {"type": "query", "text": "hi"}})
    assert '"type": "progress"' in r.text and '"type": "error"' in r.text and '"type": "result"' not in r.text
