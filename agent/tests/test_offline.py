"""Tests that run without AWS: rules, query building, glossary, guardrails and the API.

    cd agent && PYTHONPATH=. ../.venv/bin/python -m pytest -q
"""

import json
import pytest
from fastapi.testclient import TestClient

from gs_agent import agent as A
from gs_agent import api, glossary, search
from gs_agent import needs as N


def school(**fields) -> dict:
    base = {"name": "Heron Landing Middle", "city": "Miami", "entity_type": "public", "level_codes": ["m"],
            "osp": {"transportation": ["busses"]}}
    return {**base, **fields}


# ---------------------------------------------------------------- needs rules

def test_avoid_safety_means_want_safety():
    safe = school(reviews_full=[{"created_date": N.TODAY.isoformat(),
                                 "sentiments": [{"topic": "Bullying / Safety", "sentiment_enum": "positive"}]}])
    result = N.verify(safe, {"need": "safety", "mode": "avoid"})
    assert result["mode"] == "require"
    assert result["status"] == N.CONFIRMED


def test_avoid_still_inverts_other_needs():
    result = N.verify(school(entity_type="private"), {"need": "school_type", "mode": "avoid", "value": ["private"]})
    assert result["status"] == N.ATTENTION


def test_after_care_staleness_uses_its_own_date():
    fresh_profile_old_care = school(after_care_end_time="18:00", after_care_as_of="2020-01-01",
                                    osp_as_of=N.TODAY.date().isoformat())
    result = N.verify(fresh_profile_old_care, {"need": "after_school_care", "mode": "require", "value": "18:00"})
    assert result["status"] == N.PARTIAL
    assert "2020-01" in result["note"]


# ---------------------------------------------------------------- query building

def test_every_catalog_need_has_boosts():
    assert set(search.BOOSTS) | {"location"} == set(N.CATALOG)


def test_query_mirrors_greatschools_high_performing_need():
    needs = [{"need": "high_performing", "mode": "require"}, {"need": "stem", "mode": "prefer"}]
    filters, _ = search._filters(needs)
    query = search.build_query(needs, filters)
    rating_filter = json.dumps(filters)
    assert '"summary_rating": {"gte": 8}' in rating_filter
    assert "must_not" in rating_filter  # unrated schools stay in, shown as "missing"
    boosts = [c["constant_score"] for c in query["bool"]["should"]]
    assert {"range": {"avg_review_rating": {"gte": 4}}} in [b["filter"] for b in boosts]
    # require weighs more than prefer
    assert max(b["boost"] for b in boosts if "summary_rating" in json.dumps(b)) > \
        max(b["boost"] for b in boosts if "STEM" in json.dumps(b))


def test_avoid_needs_lower_the_score():
    query = search.build_query([{"need": "school_type", "mode": "avoid", "value": ["private"]}], [])
    assert "boosting" in query
    assert "private" in json.dumps(query["boosting"]["negative"])


def test_semantic_vector_goes_in_should_with_filters():
    filters = [{"terms": {"level_codes": ["m"]}}]
    query = search.build_query([], filters, vector=[0.1, 0.2])
    knn = query["bool"]["should"][0]["knn"]["profile_vector"]
    assert knn["filter"] == {"bool": {"filter": filters}}


# ---------------------------------------------------------------- glossary (P4)

@pytest.mark.parametrize("term, expected", [
    ("CTE", "cte"), ("what is a charter school", "charter_school"), ("IEP", "iep"),
    ("summary rating", "summary_rating"), ("ESA", "esa"),
])
def test_glossary_lookup(term, expected):
    assert glossary.lookup(term)[0]["id"] == expected


def test_glossary_unknown_term():
    assert glossary.lookup("quantum flux") == []


# ---------------------------------------------------------------- guardrails

RESULT = {"name": "Heron Landing Middle", "quality_flags": [], "criteria": [
    {"need": "stem", "status": "partial", "note": "The STEM listing is from 2023-05.",
     "evidence": [{"field": "osp.school_sub_type", "value": ["STEM"], "as_of": "2023-05-01"}]},
    {"need": "after_school_care", "status": "partial", "note": "Care ends at 17:00; you need 18:00.",
     "evidence": [{"field": "after_care_end_time", "value": "17:00"}]},
]}


@pytest.mark.parametrize("text, ok", [
    ("I checked this for you: the STEM listing is from 2023, so I treated it as a nice-to-have.", True),
    ("Care ends at 5pm, an hour before you need it.", True),
    ("Care ends at 5:00, not 6:00.", True),
    ("This school has a 9/10 rating.", False),
    ("Over 300 kids are in the robotics club.", False),
])
def test_callouts_only_use_numbers_from_the_data(text, ok):
    assert A._grounded(text, RESULT) is ok


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(A.GuidedSession, "_new_agent", lambda self, messages=None: None)
    return A.GuidedSession("test")


def test_failed_turn_falls_back_without_stale_results(session):
    session.last = {"results": [{"school_id": "fl-1"}]}  # from an earlier turn

    def boom(*a, **k):
        raise RuntimeError("model unavailable")
    session.agent = boom
    session._drop_old_thinking = lambda: None
    response = session.handle({"type": "query", "text": "what is CTE?"})
    assert response["fallback"] is True
    assert [b["type"] for b in response["blocks"]] == ["text"]
    assert session.last is not None  # kept for later chip edits


def test_suggestions_must_be_new_catalog_needs(session):
    session.needs = [{"need": "grade_level", "mode": "require", "value": ["m"]}]
    decision = A.Decision(chips=[], message="ok", unmapped=["Montessori"], suggestions=[
        A.Suggestion(need="transportation", label="School bus", why="You work until 6pm"),
        A.Suggestion(need="grade_level", label="dup", why="already set"),
        A.Suggestion(need="unicorns", label="x", why="not in catalog"),
    ])
    chips = session._blocks(decision)["blocks"][0]
    assert chips["unmapped"] == ["Montessori"]
    assert [s["need"] for s in chips["suggested"]] == ["transportation"]


def test_tool_budget(session):
    assert all(session._over_budget() is None for _ in range(A.MAX_TOOL_CALLS))
    assert "limit" in session._over_budget()


# ---------------------------------------------------------------- API

class FakeSession:
    def __init__(self, session_id=None):
        self.session_id = session_id or "fake"
        self.saved, self.last, self.needs, self.on_progress = set(), None, [], None
        self.searched_this_turn = False

    def handle(self, event):
        self.on_progress("Checked 9 schools; ranking the top 8.")
        return {"session_id": self.session_id, "blocks": [{"type": "text", "markdown": "hi"}]}


def test_stream_sends_progress_then_result(monkeypatch):
    monkeypatch.setattr(api, "GuidedSession", FakeSession)
    monkeypatch.setattr(api.store, "saved_schools", lambda sid: [{"school_id": "fl-9"}])
    with TestClient(api.app) as client:
        body = client.post("/api/turn/stream", json={"event": {"type": "query", "text": "hi"}}).text
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["progress", "result"]
    assert events[1]["response"]["blocks"][0]["markdown"] == "hi"


def test_restored_session_loads_saved_schools(monkeypatch):
    monkeypatch.setattr(api, "GuidedSession", FakeSession)
    monkeypatch.setattr(api.store, "saved_schools", lambda sid: [{"school_id": "fl-9"}])
    api._sessions.pop("lost-1", None)
    assert api._session("lost-1").saved == {"fl-9"}
