"""Parents don't know school jargon (Vision doc): labels, notes and comparisons use plain words and miles."""

from fastapi.testclient import TestClient

from gs_agent import api
from gs_agent import needs as N
from gs_agent.agent import JARGON, ChipLabel, Decision, GuidedSession, Question, plain_label


def test_catalog_labels_have_no_school_jargon():
    assert not [c["label"] for c in N.CATALOG.values() if JARGON.search(c["label"])]


def test_plain_label_drops_jargon_asides_and_falls_back():
    assert plain_label("Extra help for ADHD (IEP/504)", "Extra help with learning") == "Extra help for ADHD"
    assert plain_label("IEP support", "Extra help with learning") == "Extra help with learning"
    assert plain_label("Free (no tuition)") == "Free (no tuition)"


def test_chips_options_and_suggestions_are_cleaned_in_the_response():
    s = GuidedSession("plain")
    s.needs = [{"need": "special_ed", "mode": "prefer", "value": None}]
    d = Decision(chips=[ChipLabel(need="special_ed", label="Extra help for ADHD (IEP/504)", source="stated")],
                 message="ok", question=Question(text="Which matters?", why="It changes the ranking.",
                                                 options=["Learning support (IEP or 504)",
                                                          "A school bus"]))
    blocks = {b["type"]: b for b in s._blocks(d)["blocks"]}
    assert blocks["criteria_chips"]["chips"][0]["label"] == "Extra help for ADHD"
    assert blocks["clarifying_question"]["options"] == [{"id": "o1", "label": "Learning support"},
                                                        {"id": "o2", "label": "A school bus"}]


def test_location_note_is_in_miles():
    school = {"city": "Doral", "zipcode": "33166", "location": {"lat": 25.82, "lon": -80.35}}
    r = N.verify(school, {"need": "location", "mode": "require",
                          "value": {"city": "Hialeah", "radius_km": 20, "_center": {"lat": 25.86, "lon": -80.28}}})
    assert "miles from Hialeah" in r["note"] and "km" not in r["note"]
    assert any(e["field"] == "distance_miles" for e in r["evidence"])


def test_extra_help_note_explains_the_data_without_acronyms():
    school = {"swd_test_scores_rating": 4, "reviews_full": []}
    r = N.verify(school, {"need": "special_ed", "mode": "prefer"})
    assert r["status"] == N.PARTIAL
    assert "4 out of 10" in r["note"] and not JARGON.search(r["note"])


def test_comparison_cells_never_show_raw_field_names():
    assert N.plain_evidence([{"field": "level_codes", "value": ["e", "m", "p"]}]) == "Grades: pre-K, elementary and middle"
    assert N.plain_evidence([{"field": "class_size.tier", "value": "very_small"}]) == "Class size: very small"
    assert N.plain_evidence([{"field": "summary_rating", "value": 7}]) == "GreatSchools rating: 7 out of 10"


def test_grade_note_names_the_grades():
    r = N.verify({"level_codes": ["e", "m"]}, {"need": "grade_level", "mode": "require", "value": ["m"]})
    assert r["note"] == "Serves elementary and middle grades."


def test_parent_can_rate_a_reply_by_turn(monkeypatch):
    votes = []
    monkeypatch.setattr(api.store, "record_feedback", lambda sid, vote, school_id=None, turn=None: votes.append((sid, vote, school_id, turn)))
    client = TestClient(api.app)
    assert client.post("/api/feedback", json={"session_id": "s1", "turn": 3, "vote": "up"}).json() == {"ok": True}
    assert client.post("/api/feedback", json={"session_id": "s1", "school_id": "fl-1", "vote": "down"}).status_code == 200
    assert client.post("/api/feedback", json={"session_id": "s1", "vote": "up"}).status_code == 400
    assert votes == [("s1", "up", None, 3), ("s1", "down", "fl-1", None)]
