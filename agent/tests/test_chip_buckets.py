"""Chips: moving between Must have and Nice to have, turning off and back on, and an
"Also worth checking?" list that never runs dry (decision 041)."""

from gs_agent import agent as A
from gs_agent import search
from gs_agent.agent import GuidedSession


def session(monkeypatch, needs):
    monkeypatch.setattr(search, "find", lambda needs, q=None: {"results": [], "summary": {}, "notes": [],
                                                                "question_hints": [], "total_candidates": 0})
    s = GuidedSession("chips")
    s.needs = needs
    return s


def chips_of(out):
    return next(b for b in out["blocks"] if b["type"] == "criteria_chips")


CARE = {"need": "after_school_care", "mode": "require", "value": "18:00"}
GRADE = {"need": "grade_level", "mode": "require", "value": ["m"]}


def test_moving_a_chip_keeps_its_value(monkeypatch):
    s = session(monkeypatch, [GRADE, dict(CARE)])
    out = s.handle({"type": "chip_edit", "need": "after_school_care", "mode": "prefer"})
    care = next(c for c in chips_of(out)["chips"] if c["need"] == "after_school_care")
    assert care["mode"] == "prefer" and care["value"] == "18:00"


def test_turning_a_need_off_and_back_on_restores_it_and_keeps_it_out_of_suggestions(monkeypatch):
    s = session(monkeypatch, [GRADE, {"need": "mental_health", "mode": "prefer", "value": None}])
    out = s.handle({"type": "chip_edit", "need": "mental_health", "removed": True})
    got = chips_of(out)
    assert "mental_health" not in [c["need"] for c in got["chips"]]
    assert "mental_health" not in [g["need"] for g in got["suggested"]]  # not offered straight back
    out = s.handle({"type": "chip_edit", "need": "mental_health", "mode": "prefer", "value": None})
    assert "mental_health" in [c["need"] for c in chips_of(out)["chips"]] and s.turned_off == []


def test_adding_suggestions_always_leaves_more(monkeypatch):
    s = session(monkeypatch, [GRADE])
    for _ in range(4):
        offered = chips_of(s._blocks(None))["suggested"]
        assert len(offered) == A.SUGGESTED
        s.handle({"type": "chip_edit", "need": offered[0]["need"], "mode": "prefer"})
    assert len(chips_of(s._blocks(None))["suggested"]) == A.SUGGESTED


def test_code_never_suggests_disability_language_or_cost_and_college_prep_only_for_high_school():
    assert not set(A.MORE_NEEDS) & {"special_ed", "ell_support", "cost"}
    all_mid = [g["need"] for g in A.top_up_suggestions([], [GRADE], set(A.MORE_NEEDS) - {"college_prep"})]
    assert "college_prep" not in all_mid
    all_high = [g["need"] for g in A.top_up_suggestions([], [{"need": "grade_level", "mode": "require", "value": ["h"]}],
                                                       set(A.MORE_NEEDS) - {"college_prep"})]
    assert all_high == ["college_prep"]


def test_model_suggestions_come_first():
    model = [{"need": "transportation", "label": "School bus", "why": "You work until 6pm"}]
    got = A.top_up_suggestions(model, [GRADE], set())
    assert got[0] == model[0] and len(got) == A.SUGGESTED


def test_the_agent_sees_the_top_eight_and_hinted_schools_only():
    results = [{"school_id": str(i), "rank": i, "hinted": i == 12} for i in range(1, 17)]
    assert [r["school_id"] for r in search.model_view(results)] == [str(i) for i in range(1, 9)] + ["12"]
    assert search.RESULTS == 16
