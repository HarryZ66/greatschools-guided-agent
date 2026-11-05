"""ZIP codes come from our data, data problems lower the rank, and times read like a clock."""

from gs_agent import needs as N
from gs_agent import programs as P
from gs_agent import search as S


def test_clock_reads_like_a_parent_would():
    assert [N.clock(t) for t in ("17:00", "09:05", "12:30", "00:15")] == ["5:00 PM", "9:05 AM", "12:30 PM", "12:15 AM"]
    assert N.clock("not a time") == "not a time"


def test_program_time_fit_uses_12_hour_times():
    fit = P._time_fit([{"start": "17:00", "end": "18:30"}], "17:00", "18:00")
    assert fit["status"] == N.CONFIRMED and fit["note"] == "Runs 5:00 PM–6:30 PM, covers 5:00 PM–6:00 PM."


def test_comparison_cell_shows_care_time_as_clock():
    assert N.plain_evidence([{"field": "after_care_end_time", "value": "17:00"}]) == "Care ends: 5:00 PM"


def test_zip_is_matched_from_our_data_exact_then_nearby(monkeypatch):
    asked = []

    def fake_center(query):
        asked.append(query)
        return {"lat": 25.8, "lon": -80.3} if "prefix" in query else None  # no exact ZIP, same area yes
    monkeypatch.setattr(S, "_center_of", fake_center)
    assert S.resolve_location({"zip": "33012", "state": "FL"}) == {"lat": 25.8, "lon": -80.3}
    assert asked[0] == {"term": {"zipcode": "33012"}} and asked[1] == {"prefix": {"zipcode": "3301"}}


def test_zip_outside_our_data_is_not_guessed(monkeypatch):
    monkeypatch.setattr(S, "_center_of", lambda q: None)
    assert S.resolve_location({"zip": "98101"}) is None  # Seattle: "no schools there", not a guess


def test_location_note_names_the_zip_when_no_city():
    school = {"city": "Hialeah", "location": {"lat": 25.86, "lon": -80.28}}
    r = N.verify(school, {"need": "location", "mode": "require",
                          "value": {"zip": "33012", "radius_km": 20, "_center": {"lat": 25.80, "lon": -80.20}}})
    assert r["status"] == N.CONFIRMED and "miles from ZIP 33012" in r["note"]


def test_schools_with_data_problems_rank_below_clean_ones(monkeypatch):
    school = {"name": "x", "entity_type": "public", "city": "Miami", "level_codes": ["m"]}
    hits = [{"_id": "bad", "_score": 1.0, "_source": {**school, "name": "Bad data", "enrollment": 1,
                                                       "student_teacher_ratio": 52}},
            {"_id": "clean", "_score": 0.9, "_source": {**school, "name": "Clean"}}]

    class FakeClient:
        def search(self, index, body):
            return {"hits": {"hits": hits}}
    monkeypatch.setattr(S, "client", lambda: FakeClient())
    out = S.find([{"need": "grade_level", "mode": "require", "value": ["m"]}])
    assert [r["school_id"] for r in out["results"]] == ["clean", "bad"]
    assert out["results"][1]["quality_flags"]


def test_data_problems_never_drop_a_school_below_one_that_meets_less(monkeypatch):
    base = {"entity_type": "public", "city": "Miami", "level_codes": ["m"], "after_care_end_time": "18:00",
            "after_care_as_of": "2026-09-01"}
    hits = [{"_id": "bad", "_score": 0.5, "_source": {**base, "name": "All yes, bad data", "enrollment": 1,
                                                       "student_teacher_ratio": 52, "attendance_rate": 30}},
            {"_id": "less", "_score": 1.0, "_source": {**base, "name": "Care ends early", "after_care_end_time": "17:00"}}]

    class FakeClient:
        def search(self, index, body):
            return {"hits": {"hits": hits}}
    monkeypatch.setattr(S, "client", lambda: FakeClient())
    out = S.find([{"need": "grade_level", "mode": "require", "value": ["m"]},
                  {"need": "after_school_care", "mode": "require", "value": "18:00"}])
    assert [r["school_id"] for r in out["results"]] == ["bad", "less"]
