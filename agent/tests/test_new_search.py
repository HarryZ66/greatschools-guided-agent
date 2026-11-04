"""A new search forgets the conversation but keeps the parent's session and saved list."""

from fastapi.testclient import TestClient

from gs_agent import api, store
from gs_agent.agent import Decision, GuidedSession


def test_new_search_clears_the_conversation_and_keeps_saves():
    s = GuidedSession("keep")
    s.needs = [{"need": "grade_level", "mode": "require", "value": ["m"]}]
    s.last, s.pending_question, s.saved = {"results": [{"school_id": "a"}]}, {"question_id": "q"}, {"fl-1", "fl-2"}
    old_agent = s.agent
    out = s.handle({"type": "new_search"})
    assert out["session_id"] == "keep" and out["blocks"] == []
    assert s.needs == [] and s.last is None and s.pending_question is None
    assert s.saved == {"fl-1", "fl-2"} and s.agent is not old_agent
    assert [st["tool"] for st in out["trace"]["steps"]] == ["new_search"]


def test_api_new_search_returns_the_kept_list(monkeypatch):
    monkeypatch.setattr(store, "saved_schools", lambda sid: [{"school_id": "fl-1", "name": "Tamarind Cove", "at": "t"}])
    monkeypatch.setattr(store, "record_search", lambda *a, **k: None)
    client = TestClient(api.app)
    r = client.post("/api/turn", json={"session_id": "parent-1", "event": {"type": "new_search"}})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "parent-1" and body["blocks"] == []
    assert body["saved"] == [{"school_id": "fl-1", "name": "Tamarind Cove", "at": "t"}]
    # A session the server lost (e.g. after a restart) comes back with its saves from DynamoDB
    assert api._sessions["parent-1"].saved == {"fl-1"}


def test_new_search_clears_knowledge_base_citations(monkeypatch):
    """A guide entry fetched locally after reset must not cite a previous KB document."""
    from gs_agent import gateway_client as gateway

    session = GuidedSession("reset-guide")
    session.seen_content = {"charter-school": "Charter school"}
    session.seen_documents = {"charter-school": "previous-charter-school.md"}
    session.handle({"type": "new_search"})
    monkeypatch.setattr(gateway, "call", lambda *args, **kwargs: [{
        "id": "charter-school", "title": "Charter school", "body": "A public school.",
        "source": "Parent guide",
    }])
    lookup = next(tool for tool in session._tools() if tool.tool_name == "lookup_content")
    lookup(question="What is a charter school?")
    response = session._blocks(Decision(chips=[], message="A public school.", sources=["charter-school"]))
    text = next(block for block in response["blocks"] if block["type"] == "text")
    assert text["sources"] == [{"id": "charter-school", "title": "Charter school"}]
