"""Trade-off hints, program fit checks, and the guard on what the model may cite."""

from gs_agent import needs as N
from gs_agent import programs as P
from gs_agent.search import question_hints

NEEDS = [{"need": "grade_level", "mode": "require", "value": ["m"]},
         {"need": "stem", "mode": "require"},
         {"need": "after_school_care", "mode": "require", "value": "18:00"}]


def result(school_id, name, rank, stem, care, care_end=None):
    care_ev = [{"field": "after_care_end_time", "value": care_end}] if care_end else []
    return {"school_id": school_id, "name": name, "rank": rank, "criteria": [
        {"need": "grade_level", "status": N.CONFIRMED, "evidence": [], "note": None},
        {"need": "stem", "status": stem, "evidence": [], "note": "Some STEM activity" if stem == N.PARTIAL else None},
        {"need": "after_school_care", "status": care, "evidence": care_ev,
         "note": f"Care ends at {care_end}; you need 18:00." if care == N.PARTIAL else None},
    ]}


def test_concrete_time_gap_is_the_top_hint_and_suggests_programs():
    results = [result("a", "Vague Partial School", 1, N.PARTIAL, N.CONFIRMED),
               result("t", "Tamarind Cove", 9, N.CONFIRMED, N.PARTIAL, care_end="17:00")]
    hints, hinted = question_hints(NEEDS, results)
    assert hints[0].startswith("Trade-off: Tamarind Cove")
    assert "search_programs" in hints[0] and "time_from='17:00'" in hints[0]
    assert "t" in hinted


def test_must_have_confirmed_nowhere_produces_relax_hint():
    results = [result("a", "A", 1, N.MISSING, N.CONFIRMED), result("b", "B", 2, N.MISSING, N.CONFIRMED)]
    hints, _ = question_hints(NEEDS, results)
    assert any("No result confirms the must-have 'STEM'" in h for h in hints)


def test_no_hints_when_everything_is_confirmed():
    hints, hinted = question_hints(NEEDS, [result("a", "A", 1, N.CONFIRMED, N.CONFIRMED)])
    assert hints == [] and hinted == set()


# ---------------------------------------------------------------- programs

SESSION = [{"date": "2026-11-03", "day": "Tue", "start": "17:00", "end": "18:30"}]


def test_program_time_fit():
    assert P._time_fit(SESSION, "17:00", "18:00")["status"] == N.CONFIRMED
    assert P._time_fit(SESSION, "16:00", "18:00")["status"] == N.PARTIAL
    assert P._time_fit(SESSION, "09:00", "12:00")["status"] == N.ATTENTION
    assert P._time_fit(SESSION, None, None) is None


def instance(date, status, start="17:00", end="18:30"):
    return {"start_date": date, "status": status, "start_time": f"2000-01-01T{start}:00-05:00",
            "end_time": f"2000-01-01T{end}:00-05:00"}


def test_past_sessions_are_never_offered():
    program = {"instances": [instance("2026-08-01", "past"), instance("2026-11-05", "upcoming")]}
    assert [s["date"] for s in P._sessions(program)] == ["2026-11-05"]
    assert P._sessions({"instances": [instance("2026-08-01", "past")]}) == []


def test_meeting_days_come_from_all_upcoming_sessions():
    program = {"instances": [instance("2026-11-09", "upcoming"), instance("2026-11-12", "upcoming"),
                             instance("2026-11-03", "current")]}
    assert P._weekdays(program) == ["Mon", "Tue", "Thu"]


def test_program_flags_bad_zip_and_end_before_start():
    flags = P._flags({"state": "FL", "zipcode": "30306",
                      "instances": [instance("2026-11-05", "upcoming", start="05:00", end="04:59")]})
    assert {f["field"] for f in flags} == {"zipcode", "instances.end_time"}
    assert P._flags({"state": "FL", "zipcode": "33130", "instances": [instance("2026-11-05", "upcoming")]}) == []


# ---------------------------------------------------------------- what the model may cite

def test_blocks_drop_callouts_and_sources_the_tools_never_returned():
    from gs_agent.agent import Callout, Decision, GuidedSession

    session = GuidedSession("test")
    session.needs = [{"need": "grade_level", "mode": "require", "value": ["m"]}]
    session.last = {"results": [{**result("real", "Real School", 1, N.CONFIRMED, N.CONFIRMED),
                                 "entity_type": "public", "city": "Miami", "score": 1.0,
                                 "watch_out": None, "quality_flags": []}]}
    session.seen_content = {"cte": "CTE"}
    decision = Decision(chips=[], message="Hi", sources=["cte", "invented-entry"],
                        callouts=[Callout(school_id="real", text="ok"), Callout(school_id="made-up", text="no")])
    blocks = session._blocks(decision)["blocks"]

    callouts = [b["school_id"] for b in blocks if b["type"] == "evidence_callout"]
    sources = [s["id"] for b in blocks if b["type"] == "text" for s in b.get("sources", [])]
    assert callouts == ["real"]
    assert sources == ["cte"]
