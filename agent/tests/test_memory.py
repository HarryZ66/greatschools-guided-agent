"""Conversations outlive their process, in AgentCore Memory (decision 036)."""

from datetime import datetime, timedelta, timezone

import pytest

from gs_agent import api, memory
from gs_agent.agent import GuidedSession


class FakeMemory:
    """Stands in for the bedrock-agentcore client: events per (actor, session), listed out of order."""

    def __init__(self, fail=False):
        self.events, self.fail = [], fail

    def create_event(self, memoryId, actorId, sessionId, eventTimestamp, payload):
        if self.fail:
            raise RuntimeError("memory down")
        self.events.append({"memoryId": memoryId, "actorId": actorId, "sessionId": sessionId,
                            "eventId": f"e{len(self.events)}", "eventTimestamp": eventTimestamp, "payload": payload})

    def list_events(self, memoryId, actorId, sessionId, includePayloads, maxResults, nextToken=None):
        if self.fail:
            raise RuntimeError("memory down")
        mine = [{k: v for k, v in e.items() if k != "payload"} for e in self.events
                if e["actorId"] == actorId and e["sessionId"] == sessionId]
        return {"events": list(reversed(mine))}  # no promised order

    def get_event(self, memoryId, actorId, sessionId, eventId):
        event = next(e for e in self.events if e["eventId"] == eventId)
        # Like the real service: a string blob comes back as sent, an object as a Java-style map string
        blob = event["payload"][0]["blob"]
        if isinstance(blob, dict):
            blob = "{" + ", ".join(f"{k}={v}" for k, v in blob.items()) + "}"
        return {"event": {**event, "payload": [{"blob": blob}]}}


@pytest.fixture
def fake(monkeypatch):
    client = FakeMemory()
    monkeypatch.setenv("MEMORY_ID", "greatschools_conversations-abc123")
    monkeypatch.setattr(memory, "_client", lambda: client)
    return client


def test_the_newest_saved_state_comes_back(fake, monkeypatch):
    times = iter([datetime(2026, 11, 4, tzinfo=timezone.utc) + timedelta(seconds=i) for i in range(3)])

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)
    monkeypatch.setattr(memory, "datetime", Clock)
    for turn in (1, 2, 3):
        memory.save("parent-1", {"turn": turn})
    assert memory.load("parent-1") == {"turn": 3}
    assert memory.load("someone-else") is None
    assert {e["actorId"] for e in fake.events} == {"parent-parent-1"}


def test_memory_is_off_without_a_memory_id(monkeypatch):
    monkeypatch.delenv("MEMORY_ID", raising=False)
    monkeypatch.setattr(memory, "_client", lambda: pytest.fail("no call without MEMORY_ID"))
    memory.save("x", {"a": 1})
    assert memory.load("x") is None


def test_a_memory_failure_never_fails_a_turn(monkeypatch):
    monkeypatch.setenv("MEMORY_ID", "m-123456789012")
    monkeypatch.setattr(memory, "_client", lambda: FakeMemory(fail=True))
    memory.save("x", {"a": 1})
    assert memory.load("x") is None


def test_a_new_process_picks_up_the_conversation(fake, monkeypatch):
    monkeypatch.setattr(api.store, "saved_schools", lambda sid: [])
    monkeypatch.setattr(api.store, "record_search", lambda *a: None)
    monkeypatch.setattr(api, "_sessions", {})
    monkeypatch.setattr(api, "_locks", {})

    first = api._session("parent-2")
    first.needs = [{"need": "grade_level", "mode": "require", "value": ["m"]}]
    first.pending_question = {"question_id": "q-1", "text": "Is 5pm ok?", "options": [{"id": "o1", "label": "Yes"}]}
    monkeypatch.setattr(GuidedSession, "handle", lambda self, event: {"session_id": self.session_id, "blocks": [],
                                                                      "trace": {"steps": []}})
    api._run_turn(first, api.Event(type="query", text="middle school"))
    assert len(fake.events) == 1

    api._sessions.clear()  # the microVM ended
    second = api._session("parent-2")
    assert second is not first
    assert second.needs == first.needs and second.pending_question == first.pending_question
    assert second.turn_count == 1
    out = api._run_turn(second, api.Event(type="query", text="and a bus"))
    assert out["trace"]["steps"][0]["tool"] == "memory" and out["turn"] == 2
    assert len(fake.events) == 2
