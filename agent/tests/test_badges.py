"""The one "Best for ..." badge per card: decided in code, never claimed on a tie (decision 032)."""

from gs_agent import badges
from gs_agent import needs as N


def need(name, mode="prefer", value=None):
    return {"need": name, "mode": mode, "value": value}


def school(sid, **doc):
    return sid, {"entity_type": "public", **doc}


def results_for(asked, *schools):
    docs = dict(schools)
    results = [{"school_id": sid, "criteria": [N.verify(doc, n) for n in asked]} for sid, doc in schools]
    badges.assign(asked, results, docs)
    return {r["school_id"]: r["badge"] for r in results}


def care(end):
    return {"after_care_end_time": end, "after_care_as_of": "2026-08-01"}


def test_single_strongest_school_gets_best_for_with_the_value_why():
    asked = [need("after_school_care", value="17:00")]
    got = results_for(asked, school("a", **care("18:30")), school("b", **care("17:30")))
    assert got["a"]["label"] == "Best for after-school care"
    assert got["a"]["asked"] is True
    assert "6:30pm" in got["a"]["why"] and "2 schools" in got["a"]["why"]
    assert got["b"] is None


def test_a_tie_gives_nobody_the_badge():
    asked = [need("after_school_care", value="17:00")]
    got = results_for(asked, school("a", **care("18:00")), school("b", **care("18:00")))
    assert got == {"a": None, "b": None}


def test_only_confirmed_schools_can_be_best():
    asked = [need("after_school_care", value="18:00")]
    # Care until 17:30 is only partial for a parent who needs 18:00, so it can't be "best".
    got = results_for(asked, school("a", **care("17:30")), school("b"))
    assert got["a"] is None


def test_one_badge_per_school_and_the_parents_needs_come_first():
    asked = [need("small_classes", "require"), need("after_school_care", value="17:00")]
    a = school("a", student_teacher_ratio=11, class_size={"tier": "small", "source_generated_at": "2026-06-01"}, **care("18:30"))
    b = school("b", student_teacher_ratio=18, class_size={"tier": "small", "source_generated_at": "2026-06-01"}, **care("17:30"))
    got = results_for(asked, a, b)
    assert got["a"]["need"] == "small_classes"  # the must-have wins; the care badge isn't given twice
    assert got["b"] is None


def test_extra_needs_skip_language_and_disability():
    # A school strong on English-learner support the parent didn't ask about gets no such badge.
    strong_ell = school("a", ell={"tier": "high", "source_generated_at": "2026-06-01"})
    got = results_for([need("grade_level", "require", ["e"])], strong_ell, school("b"))
    assert got["a"] is None
    assert "ell_support" not in badges.EXTRA_NEEDS and "special_ed" not in badges.EXTRA_NEEDS


def test_extra_need_badge_is_marked_not_asked():
    arts = {"osp": {"arts_music": ["band", "choir"], "arts_visual": ["painting"]}}
    got = results_for([need("grade_level", "require", ["e"])], school("a", **arts),
                      school("b", osp={"arts_music": ["band"]}))
    assert got["a"]["label"] == "Best for the arts" and got["a"]["asked"] is False


def test_mixed_safety_reviews_are_not_best():
    review = lambda s: {"created_date": "2026-05-01", "sentiments": [{"topic": "Bullying / Safety", "sentiment_enum": s}]}
    mixed = school("a", reviews_full=[review("positive"), review("negative")])
    got = results_for([need("safety")], mixed, school("b"))
    assert got["a"] is None


def test_avoid_needs_and_a_single_result_get_no_badge():
    assert results_for([need("after_school_care", "avoid")], school("a", **care("18:00")), school("b"))["a"] is None
    assert results_for([need("after_school_care")], school("a", **care("18:00"))) == {"a": None}
