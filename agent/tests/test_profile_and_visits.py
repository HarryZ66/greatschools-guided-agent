"""The agent keeps asking to build the family profile, and closes with a local partner visit (decision 042)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from gs_agent import agent as A
from gs_agent import api, family, partners, store
from gs_agent import needs as N
from gs_agent.agent import Decision, GuidedSession, Question

BASICS = [{"need": "grade_level", "mode": "require", "value": ["m"]},
          {"need": "location", "mode": "require", "value": {"city": "Miami", "state": "FL"}}]


def result(school_id, city="Miami"):
    return {"school_id": school_id, "name": f"School {school_id}", "entity_type": "public", "city": city,
            "rank": 1, "score": 0.9, "watch_out": None, "quality_flags": [], "cost": None, "badge": None,
            "criteria": [{"need": "grade_level", "status": N.CONFIRMED, "note": "", "evidence": []}]}


FOUND = {"results": [result("a"), result("b", "Hialeah"), result("c", "Orlando")], "summary": {}, "notes": [],
         "question_hints": [], "total_candidates": 3}


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(A.search, "find", lambda needs, q=None: FOUND)
    monkeypatch.setattr(A.search, "get_school", lambda sid: next((r for r in FOUND["results"] if r["school_id"] == sid), None))
    s = GuidedSession("profile")
    s.needs, s.last = [dict(n) for n in BASICS], FOUND
    return s


def block(response, kind):
    return next((b for b in response["blocks"] if b["type"] == kind), None)


# ---------------------------------------------------------------- the profile

def test_topics_are_covered_by_needs_or_answers():
    needs = BASICS + [{"need": "transportation", "mode": "prefer"}]
    assert family.covered(needs, set()) == {"schedule"}
    assert family.covered(needs, {"learning"}) == {"schedule", "learning"}
    left = family.remaining(needs, {"learning"}, {"wellbeing"})
    assert [t.id for t in left] == ["academics", "interests", "budget"]
    m = family.meter(needs, {"learning"})
    assert (m["done"], m["total"]) == (2, 6)


def test_every_model_turn_carries_the_profile_note():
    note = family.prompt_note(BASICS, set(), {"learning"})
    assert "still unknown" in note and "schedule (" in note and "learning (" not in note
    all_ids = {t.id for t in family.TOPICS}
    assert "complete" in family.prompt_note(BASICS, all_ids, set())


def test_a_chip_edit_asks_the_next_profile_question_without_the_model(session):
    out = session.handle({"type": "chip_edit", "need": "special_ed", "mode": "prefer"})
    q = block(out, "clarifying_question")
    assert q["topic"] == "schedule" and len(q["options"]) >= 2  # learning is now covered by the chip
    assert session.pending_question["question_id"] == q["question_id"]
    assert "schedule" in session.asked_topics
    assert block(out, "criteria_chips")["profile"]["done"] == 1
    assert not any("Bedrock" in st["service"] for st in out["trace"]["steps"])


def test_a_chip_edit_keeps_the_open_question_unless_it_answered_it(session):
    session.pending_question = {"question_id": "q-open", "text": "Bus?", "why": "", "options": [], "topic": "schedule"}
    out = session.handle({"type": "chip_edit", "need": "small_classes", "mode": "prefer"})
    assert block(out, "clarifying_question")["question_id"] == "q-open"
    out = session.handle({"type": "chip_edit", "need": "transportation", "mode": "prefer"})
    assert block(out, "clarifying_question")["topic"] == "learning"


def test_the_model_question_records_its_topic_and_the_answer_counts(session, monkeypatch):
    decision = Decision(chips=[], message="Here are schools.",
                        question=Question(text="Does she need extra help?", why="It changes the list.",
                                          options=["Yes", "No"], topic="learning"))
    out = session._blocks(decision)
    assert block(out, "clarifying_question")["topic"] == "learning" and "learning" in session.asked_topics
    monkeypatch.setattr(GuidedSession, "_agent_turn", lambda self, text: {"blocks": [], "session_id": self.session_id})
    session.handle({"type": "answer", "option_id": "o2"})
    assert "learning" in session.answered_topics


def test_an_unknown_topic_from_the_model_is_dropped(session):
    out = session._blocks(Decision(chips=[], message="Hi", question=Question(text="Q?", why="w", options=["a", "b"],
                                                                             topic="favorite color")))
    assert "topic" not in block(out, "clarifying_question")


def test_after_saving_the_agent_asks_next_then_offers_a_visit(session):
    session.saved = {"a"}
    first = session.after_save()
    assert first[0]["type"] == "clarifying_question" and first[0]["topic"] == "learning"
    assert session.after_save() == []  # one open question at a time
    session.pending_question = None
    session.answered_topics = {t.id for t in family.TOPICS}
    offer = session.after_save()[0]
    assert offer["type"] == "visit_offer" and offer["schools"] == [{"school_id": "a", "name": "School a"}]
    assert offer["partners"][0]["partner_id"] == "tidewater-navigators"
    assert session.after_save() == []  # offered once on its own


def test_comparing_offers_a_visit_for_the_two_schools(session, monkeypatch):
    session.comparison = {"school_ids": ["a", "b"], "names": ["School a", "School b"], "rows": []}
    out = session._blocks(Decision(chips=[], message="A has the bus."))
    offer = block(out, "visit_offer")
    assert [p["partner_id"] for p in offer["partners"]] == ["tidewater-navigators", "sawgrass-parent-partners"]
    assert "School a and School b" in offer["text"]
    assert block(out, "comparison") is not None


def test_the_model_can_ask_for_the_visit_offer(session):
    out = session._blocks(Decision(chips=[], message="A local partner can help.", offer_visit=True))
    assert block(out, "visit_offer") is not None  # no saves: the top results are used
    assert block(session._blocks(Decision(chips=[], message="Hi")), "visit_offer") is None


def test_profile_state_survives_a_restore_and_a_new_search(session):
    session.asked_topics, session.answered_topics, session.visit_offered = {"learning"}, {"learning"}, True
    other = GuidedSession("profile")
    other.restore(session.snapshot())
    assert other.asked_topics == {"learning"} and other.answered_topics == {"learning"} and other.visit_offered
    other.handle({"type": "new_search"})
    assert other.asked_topics == set() and not other.visit_offered


# ---------------------------------------------------------------- partners and requests

def test_partners_serve_cities_and_requests_are_checked():
    found = partners.for_schools([{"school_id": "a", "name": "A", "city": "Kendall"}])
    assert {p["partner_id"] for p in found} == {"sawgrass-parent-partners", "mangrove-education-circle"}
    assert all(p["sample"] for p in found)
    schools = [{"school_id": "a", "name": "A", "city": "Miami"}, {"school_id": "z", "name": "Z", "city": "Orlando"}]
    r = partners.build_request("tidewater-navigators", schools, "visit", "Saturdays", "Spanish", "  Ask about the bus ",
                               today=date(2026, 11, 6))  # a Friday
    assert r["schools"] == [{"school_id": "a", "name": "A"}] and r["note"] == "Ask about the bus"
    assert r["reply_by"] == "2026-11-10" and r["status"] == "sent"
    with pytest.raises(ValueError, match="doesn't serve"):
        partners.build_request("harborlight-parent-guides", schools, "visit", "Saturdays", "Spanish")
    with pytest.raises(ValueError, match="works in"):
        partners.build_request("tidewater-navigators", schools, "visit", "Saturdays", "French")


def test_visit_api_stores_the_request(monkeypatch):
    stored = []
    monkeypatch.setattr(api.search, "get_school", lambda sid: {"name": "School a", "city": "Miami"} if sid == "a" else None)
    monkeypatch.setattr(store, "save_visit", lambda sid, r: stored.append((sid, r)))
    monkeypatch.setattr(store, "visits", lambda sid: [r for _, r in stored])
    monkeypatch.setattr(store, "saved_schools", lambda sid: [{"school_id": "a", "name": "School a", "at": "t"}])
    client = TestClient(api.app)
    listed = client.get("/api/partners", params={"session_id": "v1"}).json()
    assert listed["partners"][0]["partner_id"] == "tidewater-navigators" and "Saturdays" in listed["times"]
    r = client.post("/api/visits", json={"session_id": "v1", "partner_id": "tidewater-navigators", "school_ids": ["a"],
                                         "way": "call", "when": "Evenings", "language": "English"})
    assert r.status_code == 200 and r.json()["request"]["way_label"] == "Talk with a guide first"
    assert stored[0][0] == "v1" and len(r.json()["requests"]) == 1
    bad = client.post("/api/visits", json={"session_id": "v1", "partner_id": "tidewater-navigators", "school_ids": ["a"],
                                           "way": "visit", "when": "Midnight", "language": "English"})
    assert bad.status_code == 400 and "free" in bad.json()["detail"]


def test_a_chip_edit_keeps_a_question_whose_topic_was_already_known(session):
    """The model tagged a trade-off about English help as `learning`, already covered by a chip."""
    session.needs.append({"need": "ell_support", "mode": "require"})
    session.pending_question = {"question_id": "q-ell", "text": "Average English help OK?", "why": "", "options": [],
                                "topic": "learning"}
    out = session.handle({"type": "chip_edit", "need": "transportation", "mode": "prefer"})
    assert block(out, "clarifying_question")["question_id"] == "q-ell"


def test_turning_a_chip_off_counts_as_a_decision_on_its_topic(session):
    """A parent who turns off "School bus" isn't asked how their child gets to school."""
    session.needs.append({"need": "transportation", "mode": "prefer"})
    out = session.handle({"type": "chip_edit", "need": "transportation", "removed": True})
    assert block(out, "clarifying_question")["topic"] == "learning"
    assert "schedule" not in [t.id for t in family.remaining(session._profile_needs(), set(), session.asked_topics)]
