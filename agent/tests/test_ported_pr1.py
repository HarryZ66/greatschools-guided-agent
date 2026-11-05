"""Changes ported from Sanchit Arora's PR #1: query building, mode fixes, grounding, budget, fallback."""

import json

from gs_agent import needs as N
from gs_agent.agent import MAX_TOOL_CALLS, Callout, Decision, GuidedSession, Suggestion, _grounded
from gs_agent.search import BOOSTS, build_query


# ---------------------------------------------------------------- needs -> OpenSearch query

def test_every_catalog_need_has_query_clauses():
    assert set(BOOSTS) == set(N.RULES)


def test_require_boosts_weigh_more_than_prefer():
    req = build_query([{"need": "stem", "mode": "require"}], [])
    pref = build_query([{"need": "stem", "mode": "prefer"}], [])
    top = lambda q: max(c["constant_score"]["boost"] for c in q["bool"]["should"])
    assert top(req) == 3 * top(pref)


def test_avoid_needs_lower_the_score_instead_of_filtering():
    q = build_query([{"need": "school_type", "mode": "avoid", "value": ["private"]}], [{"term": {"x": 1}}])
    assert "boosting" in q and q["boosting"]["negative_boost"] < 1
    assert q["boosting"]["positive"]["bool"]["filter"] == [{"term": {"x": 1}}]


def test_semantic_query_adds_a_knn_clause_with_the_same_filters():
    filters = [{"terms": {"level_codes": ["m"]}}]
    q = build_query([], filters, vector=[0.1] * 4)
    knn = q["bool"]["should"][0]["knn"]["profile_vector"]
    assert knn["filter"] == {"bool": {"filter": filters}}


# ---------------------------------------------------------------- mode and freshness fixes

def test_avoid_bullying_reads_as_wanting_safety():
    assert N.normalize_mode({"need": "safety", "mode": "avoid"}) == "require"
    assert N.normalize_mode({"need": "school_type", "mode": "avoid"}) == "avoid"


def test_safe_school_is_not_flagged_when_parent_says_avoid_bullying():
    school = {"reviews_full": [{"created_date": "2026-06-01T00:00:00-07:00",
                                "sentiments": [{"topic": "Bullying / Safety", "sentiment_enum": "positive"}]}]}
    assert N.verify(school, {"need": "safety", "mode": "avoid"})["status"] == N.CONFIRMED


def test_after_care_freshness_uses_its_own_date_not_the_profile_date():
    school = {"after_care_end_time": "18:00", "after_care_as_of": "2026-09-01", "osp_as_of": "2023-01-01"}
    assert N.verify(school, {"need": "after_school_care", "mode": "require", "value": "18:00"})["status"] == N.CONFIRMED
    stale = {**school, "after_care_as_of": "2024-01-01"}
    assert N.verify(stale, {"need": "after_school_care", "mode": "require", "value": "18:00"})["status"] == N.PARTIAL


# ---------------------------------------------------------------- callout grounding

RESULT = {"name": "Tamarind Cove STEM Academy", "quality_flags": [], "criteria": [
    {"need": "after_school_care", "status": N.PARTIAL, "note": "Care ends at 17:00; you need 18:00.",
     "evidence": [{"field": "after_care_end_time", "value": "17:00", "as_of": "2026-09-01"}]},
    {"need": "location", "status": N.CONFIRMED, "note": None, "evidence": [{"field": "distance_km", "value": 1.6}]},
]}
PROGRAMS = [{"name": "After-School Robotics Club", "distance_km": 1.0,
             "next_sessions": [{"start": "17:00", "end": "18:30"}]}]


def test_callout_with_data_numbers_is_grounded():
    assert _grounded("Care ends at 5pm, not 6pm, as of 2026.", RESULT)
    assert _grounded("It's about 2 km away; care ends at 5:00.", RESULT)


def test_callout_may_cite_a_program_shown_this_turn():
    text = "Care ends at 5pm, but a library club 1 km away runs until 6:30."
    assert not _grounded(text, RESULT)
    assert _grounded(text, RESULT, PROGRAMS)


def test_callout_with_an_invented_number_is_dropped():
    assert not _grounded("Its summary rating is 9 out of 10.", RESULT)


# ---------------------------------------------------------------- budget, gaps, fallback

def test_tool_budget_stops_after_the_limit():
    s = GuidedSession("budget")
    assert all(s._over_budget() is None for _ in range(MAX_TOOL_CALLS))
    assert "Tool limit" in json.loads(s._over_budget())["error"]


def test_unmapped_and_suggested_chips_skip_needs_already_chosen():
    s = GuidedSession("gaps")
    s.needs = [{"need": "grade_level", "mode": "require", "value": ["m"]}]
    d = Decision(chips=[], message="ok", unmapped=["Montessori"],
                 suggestions=[Suggestion(need="transportation", label="School bus", why="You work until 6pm"),
                              Suggestion(need="grade_level", label="Middle", why="dup"),
                              Suggestion(need="not_a_need", label="x", why="y")])
    chips = s._blocks(d)["blocks"][0]
    assert chips["unmapped"] == ["Montessori"]
    assert [g["need"] for g in chips["suggested"]] == ["transportation"]


def test_failed_model_turn_answers_from_code_without_stale_results():
    s = GuidedSession("fallback")
    s.last = {"results": [{"school_id": "old", "name": "Old", "entity_type": "public", "city": "Miami", "rank": 1,
                           "score": 1, "criteria": [], "watch_out": None, "quality_flags": []}]}

    class BrokenAgent:
        messages: list = []

        def __call__(self, *a, **k):
            raise RuntimeError("model down")
    s.agent = BrokenAgent()
    s._new_agent = lambda **k: BrokenAgent()  # the retry and the fallback start fresh agents
    out = s._agent_turn("Middle school near Miami")
    assert out["fallback"] is True
    assert not any(b["type"] == "school_results" for b in out["blocks"])  # no search ran this turn
    assert any(b["type"] == "text" and "couldn't" in b["markdown"] for b in out["blocks"])


def test_blocks_drop_callouts_that_invent_numbers():
    s = GuidedSession("ground")
    s.last = {"results": [{**RESULT, "school_id": "t", "entity_type": "charter", "city": "Miami", "rank": 1,
                           "score": 0.9, "watch_out": None}]}
    d = Decision(chips=[], message="ok", callouts=[Callout(school_id="t", text="Care ends at 5pm."),
                                                   Callout(school_id="t", text="Rated 9 by 300 parents.")])
    texts = [b["text"] for b in s._blocks(d)["blocks"] if b["type"] == "evidence_callout"]
    assert texts == ["Care ends at 5pm."]
