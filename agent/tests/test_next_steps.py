"""Sanchit's next-steps tasks: mental health need, cost after aid, profile view, programs on save."""

from gs_agent import funding
from gs_agent import needs as N
from gs_agent import profile
from gs_agent import programs as P
from gs_agent.search import BOOSTS

MH = {"need": "mental_health", "mode": "prefer"}


def review(topic, sentiment, date="2026-06-01T00:00:00-07:00"):
    return {"created_date": date, "text": f"Opener. A sentence about {topic}. Closer.",
            "sentiments": [{"topic": topic, "sentiment_enum": sentiment}]}


# ---------------------------------------------------------------- task 1: mental health

def test_mental_health_confirmed_with_counselors_on_a_fresh_profile():
    s = {"osp": {"mental_health": ["school_counselors"]}, "osp_as_of": "2026-09-01"}
    assert N.verify(s, MH)["status"] == N.CONFIRMED


def test_mental_health_partial_when_profile_is_stale_or_only_reviews():
    stale = {"osp": {"mental_health": ["school_counselors"]}, "osp_as_of": "2023-01-01"}
    reviews_only = {"reviews_full": [review("Mental Health", "positive")]}
    assert N.verify(stale, MH)["status"] == N.PARTIAL
    assert N.verify(reviews_only, MH)["status"] == N.PARTIAL


def test_mental_health_needs_attention_when_recent_reviews_are_negative():
    s = {"reviews_full": [review("Mental Health", "negative"), review("Mental Health", "negative")]}
    assert N.verify(s, MH)["status"] == N.ATTENTION


def test_mental_health_missing_without_any_data():
    assert N.verify({}, MH)["status"] == N.MISSING
    assert "mental_health" in N.CATALOG and BOOSTS["mental_health"](None)


# ---------------------------------------------------------------- task 2: cost after aid

PRIVATE = {"entity_type": "private", "state": "FL", "tuition": 16500}


def test_after_aid_estimate_subtracts_the_typical_florida_award():
    cost = funding.cost_summary(PRIVATE)
    typical = funding.programs()["fl_fes_eo_ftc"]["typical_amount"]
    assert cost["after_aid_estimate"] == 16500 - typical
    assert funding.cost_summary({**PRIVATE, "tuition": 5000})["after_aid_estimate"] == 0


def test_public_and_charter_are_free_and_unlisted_tuition_stays_unknown():
    assert funding.cost_summary({"entity_type": "charter"}) == {"tuition": 0}
    assert funding.cost_summary({"entity_type": "private", "state": "FL"}) == {"tuition": None}


def test_cost_status_with_aid_estimate():
    fits = N.verify(PRIVATE, {"need": "cost", "mode": "require", "value": 10000})
    too_much = N.verify(PRIVATE, {"need": "cost", "mode": "require", "value": 5000})
    free_only = N.verify(PRIVATE, {"need": "cost", "mode": "require", "value": None})
    assert fits["status"] == N.PARTIAL and "estimate" in fits["note"]
    assert too_much["status"] == N.ATTENTION
    assert free_only["status"] == N.ATTENTION and "scholarship" in free_only["note"]
    assert N.verify(PRIVATE, {"need": "cost", "mode": "require", "value": 20000})["status"] == N.CONFIRMED


def test_every_funding_fact_names_its_source_and_year():
    for p in funding.programs().values():
        assert p["source"] and p["as_of"]


# ---------------------------------------------------------------- task 3: profile view

def test_profile_terms_match_what_is_on_the_page():
    school = {"entity_type": "charter", "summary_rating": 8, "after_care_end_time": "18:00",
              "osp": {"school_sub_type": ["STEM"]}}
    terms = profile._terms_for(school)
    assert terms[0] == "charter-school"
    assert {"stem", "gs-summary-rating", "after-school-care", "app-statuses"} <= set(terms)


def test_profile_reviews_split_recent_and_older_with_excerpts():
    school = {"reviews_full": [review("Bullying / Safety", "negative", "2012-03-01T00:00:00-07:00"),
                               review("Bullying / Safety", "positive")]}
    r = profile._reviews(school)
    assert r["by_topic"]["Bullying / Safety"] == {"recent_pos": 1, "recent_neg": 0, "old_pos": 0, "old_neg": 1}
    assert [e["older"] for e in r["excerpts"]] == [False, True]
    assert r["excerpts"][0]["text"].startswith("A sentence")  # stock opener skipped


# ---------------------------------------------------------------- task 4: programs on save

def test_school_day_end_parses_the_profile_time():
    assert P._school_day_end({"osp": {"end_time": ["3:30 PM"]}}) == "15:30"
    assert P._school_day_end({}) == "15:00"


def test_no_programs_when_every_need_is_met(monkeypatch):
    monkeypatch.setattr(P, "find_programs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("searched")))
    school = {"name": "Good School", "osp": {"school_sub_type": ["STEM"]}, "osp_as_of": "2026-09-01"}
    assert P.for_school("x", school, [{"need": "stem", "mode": "require"}]) == []


def test_care_gap_is_filled_only_by_a_program_covering_the_time(monkeypatch):
    def fake(interest, near_school_id="", grades=None, time_from="", time_to="", size=3):
        assert (time_from, time_to) == ("17:00", "18:00")
        base = {"organization": "Lib", "meets_on": ["Mon"], "distance_km": 1.0, "cost": "Free"}
        return {"programs": [
            {**base, "program_id": "early", "name": "Early Club", "time_fit": {"status": N.PARTIAL},
             "next_sessions": [{"date": "2026-11-04", "start": "15:00", "end": "17:00"}]},
            {**base, "program_id": "late", "name": "Late Club", "time_fit": {"status": N.CONFIRMED},
             "next_sessions": [{"date": "2026-11-05", "start": "17:00", "end": "18:30"}]}]}
    monkeypatch.setattr(P, "find_programs", fake)
    school = {"name": "Tamarind Cove", "after_care_end_time": "17:00", "after_care_as_of": "2026-09-01"}
    picks = P.for_school("t", school, [{"need": "after_school_care", "mode": "require", "value": "18:00"}])
    assert [p["program_id"] for p in picks] == ["late"]
    assert picks[0]["why"].startswith("Care at Tamarind Cove ends at 5:00 PM.")
