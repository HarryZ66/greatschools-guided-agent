"""The `trace` on every response lists what really ran this turn, written by code."""

from gs_agent import agent as A
from gs_agent import needs as N
from gs_agent.agent import Callout, Decision, GuidedSession

NEEDS = [{"need": "grade_level", "mode": "require", "value": ["m"]},
         {"need": "after_school_care", "mode": "require", "value": "18:00"}]


def result(school_id, care_status, flags=()):
    return {"school_id": school_id, "name": f"School {school_id}", "entity_type": "public", "city": "Miami",
            "rank": 1, "score": 0.9, "watch_out": None, "quality_flags": [{**f, "note": "odd"} for f in flags], "cost": None,
            "criteria": [{"need": "grade_level", "status": N.CONFIRMED, "note": "", "evidence": [{"field": "level_codes", "value": "m"}]},
                         {"need": "after_school_care", "status": care_status, "note": "",
                          "evidence": [{"field": "after_care_end_time", "value": "17:00"}]}]}


FOUND = {"results": [result("a", N.CONFIRMED), result("b", N.PARTIAL, [{"field": "enrollment", "value": 1}])],
         "summary": {}, "notes": [], "question_hints": ["School b: care ends at 17:00"], "total_candidates": 42}


def tools(steps):
    return [s["tool"] for s in steps]


def test_chip_edit_trace_shows_search_and_code_checks_but_no_model(monkeypatch):
    monkeypatch.setattr(A.search, "find", lambda needs, q=None: FOUND)
    s = GuidedSession("trace-edit")
    s.needs = list(NEEDS)
    out = s.handle({"type": "chip_edit", "need": "small_classes", "mode": "prefer"})
    steps = out["trace"]["steps"]
    assert tools(steps) == ["find_schools", "verify", "trade_offs", "rerank"]
    assert steps[0]["service"] == "Amazon OpenSearch" and "42 candidate schools" in steps[0]["text"]
    assert "3 confirmed, 1 partial" in steps[1]["text"] and "1 school" in steps[1]["text"]
    assert not any("Bedrock" in st["service"] for st in steps)
    assert out["trace"]["elapsed_ms"] >= 0


def test_find_schools_tool_records_its_step_and_kept_values(monkeypatch):
    monkeypatch.setattr(A.search, "find", lambda needs, q=None: FOUND)
    s = GuidedSession("trace-tool")
    s.needs, s._answer_text = list(NEEDS), "The library club works"
    find_schools = s._tools()[0]
    find_schools(needs=[NEEDS[0], {**NEEDS[1], "value": "17:00"}], semantic_query="robotics")
    assert tools(s._trace) == ["find_schools", "verify", "trade_offs", "keep_values"]
    assert "Titan Embeddings" in s._trace[0]["service"] and "ms" in s._trace[0]
    assert "after-school care" in s._trace[-1]["text"]


def test_failed_turn_trace_says_cards_come_from_code(monkeypatch):
    s = GuidedSession("trace-fallback")

    class BrokenAgent:
        messages: list = []

        def __call__(self, *a, **k):
            raise RuntimeError("model down")
    s.agent = BrokenAgent()
    s._new_agent = lambda **k: BrokenAgent()
    out = s.handle({"type": "query", "text": "Middle school near Miami"})
    # The fast model failed, the strong model got the turn and failed too, then code answered
    assert out["fallback"] is True and tools(out["trace"]["steps"]) == ["escalate", "fallback"]


def test_trace_counts_dropped_notes():
    s = GuidedSession("trace-ground")
    s.last = {"results": [result("t", N.PARTIAL)]}
    d = Decision(chips=[], message="ok", callouts=[Callout(school_id="t", text="Care ends at 5pm."),
                                                   Callout(school_id="t", text="Rated 9 by 300 parents.")])
    s._blocks(d)
    assert s._trace[-1]["tool"] == "ground" and "1 kept, 1 dropped" in s._trace[-1]["text"]
