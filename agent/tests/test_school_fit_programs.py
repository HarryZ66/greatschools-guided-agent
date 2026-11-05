"""Opening a school pairs its own verified gaps with nearby programs, without saving it."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gs_agent import api, profile, programs as P
from gs_agent import needs as N


NEEDS = [{"need": "grade_level", "mode": "require", "value": ["m"]},
         {"need": "stem", "mode": "prefer"},
         {"need": "after_school_care", "mode": "require", "value": "18:00"}]
SCHOOLS = {
    "science": {"name": "Science School", "level_codes": ["m"], "entity_type": "public",
                "osp": {"school_sub_type": ["STEM"]}, "osp_as_of": "2026-09-01",
                "after_care_end_time": "17:00", "after_care_as_of": "2026-09-01"},
    "late": {"name": "Late Care School", "level_codes": ["m"], "entity_type": "public",
             "after_care_end_time": "18:00", "after_care_as_of": "2026-09-01"},
}


def program(ident="club", **changes):
    return {"program_id": ident, "name": "Library Club", "organization": "Local Library",
            "meets_on": ["Wed"], "distance_km": 1.0, "cost": "Free",
            "time_fit": {"status": N.CONFIRMED},
            "next_sessions": [{"date": "2026-11-04", "start": "15:00", "end": "18:30"}], **changes}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.rc, "enabled", lambda: False)
    monkeypatch.setattr(api.search, "get_school", SCHOOLS.get)
    monkeypatch.setattr(profile, "_guide", lambda ids: [])
    monkeypatch.setattr(api, "_sessions", {"parent": SimpleNamespace(needs=NEEDS, saved=set())})
    monkeypatch.setattr(api.store, "save_school", lambda *a, **k: pytest.fail("Opening a school must not save it"))
    return TestClient(api.app)


@pytest.mark.parametrize("via_runtime", [False, True])
def test_each_school_shows_programs_for_its_own_gaps(client, monkeypatch, via_runtime):
    calls = []

    def search(interest, **kwargs):
        calls.append((interest, kwargs))
        return {"programs": [program(kwargs["near_school_id"] + "-club")]}

    monkeypatch.setattr(P, "find_programs", search)
    for school_id, gap in [("science", "after_school_care"), ("late", "stem")]:
        if via_runtime:
            response = client.post("/invocations", json={"op": "profile", "school_id": school_id,
                                                        "session_id": "parent"})
        else:
            response = client.get(f"/api/schools/{school_id}?session_id=parent")
        assert response.status_code == 200
        result = response.json()["profile"]
        assert result["programs_status"] == "ready"
        assert [c["need"] for c in result["criteria"] if c["status"] != N.CONFIRMED] == [gap]
        assert [p["fills_need"] for p in result["programs"]] == [gap]
        assert result["programs"][0]["program_id"] == school_id + "-club"
        assert SCHOOLS[school_id]["name"] in result["programs"][0]["why"]
    assert len(calls) == 2
    assert calls[0][1]["grades"] == ["m"]
    assert (calls[0][1]["time_from"], calls[0][1]["time_to"]) == ("17:00", "18:00")
    assert api._sessions["parent"].saved == set()
    assert api._sessions["parent"].needs == NEEDS


def test_program_failure_keeps_the_school_fit_and_is_not_an_empty_search(client, monkeypatch):
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: {"programs": []})
    empty = client.get("/api/schools/science?session_id=parent").json()["profile"]

    def unavailable(*args, **kwargs):
        raise RuntimeError("Search unavailable")

    monkeypatch.setattr(P, "find_programs", unavailable)
    response = client.get("/api/schools/science?session_id=parent")
    failed = response.json()["profile"]
    assert response.status_code == 200
    assert empty["programs"] == failed["programs"] == []
    assert empty["programs_status"] == "ready" and failed["programs_status"] == "unavailable"
    assert failed["criteria"] == empty["criteria"]


@pytest.mark.parametrize("query", ["", "?session_id=expired"])
def test_no_personalized_suggestions_without_needs(client, monkeypatch, query):
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: pytest.fail("No needs to match"))
    result = client.get("/api/schools/science" + query).json()["profile"]
    assert result["criteria"] == result["programs"] == []


def test_avoided_interests_are_not_suggested_as_compensation(monkeypatch):
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: pytest.fail("Avoided interest searched"))
    assert P.for_school("science", SCHOOLS["science"], [{"need": "stem", "mode": "avoid"}]) == []


def test_stale_care_hours_do_not_create_a_zero_length_gap(monkeypatch):
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: pytest.fail("No actual time gap"))
    school = {**SCHOOLS["late"], "after_care_as_of": "2020-01-01"}
    assert N.verify(school, NEEDS[-1])["status"] == N.PARTIAL
    assert P.for_school("late", school, [NEEDS[-1]]) == []


def test_care_suggestion_must_cover_the_gap_on_all_displayed_sessions(monkeypatch):
    mixed = program("mixed", next_sessions=[
        {"date": "2026-11-04", "start": "17:00", "end": "18:30"},
        {"date": "2026-11-05", "start": "17:30", "end": "18:30"}])
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: {"programs": [mixed, program("covers-gap")]})
    picks = P.for_school("science", SCHOOLS["science"], [NEEDS[-1]])
    assert [p["program_id"] for p in picks] == ["covers-gap"]


def test_missing_care_does_not_turn_school_day_hours_into_care_hours(monkeypatch):
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: {"programs": [program()]})
    school = {"name": "No Care Listed", "osp": {"end_time": ["3:00 PM"]}}
    picks = P.for_school("unknown", school, [NEEDS[-1]])
    assert picks[0]["why"].startswith("No Care Listed doesn't list after-school care.")
