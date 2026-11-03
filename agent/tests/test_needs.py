"""Verify rules, data quality flags and scoring: the code that decides statuses, not the model."""

from gs_agent import needs as N


def need(name, mode="require", value=None):
    return {"need": name, "mode": mode, "value": value}


def osp_school(**kw):
    return {"osp": {"school_sub_type": ["STEM"]}, "osp_as_of": "2026-09-01", **kw}


# ---------------------------------------------------------------- STEM and freshness

def test_stem_confirmed_when_listed_and_fresh():
    r = N.verify(osp_school(), need("stem"))
    assert r["status"] == N.CONFIRMED
    assert r["evidence"][0]["field"] == "osp.school_sub_type"


def test_stem_listing_older_than_18_months_is_only_partial():
    r = N.verify(osp_school(osp_as_of="2024-02-10"), need("stem"))
    assert r["status"] == N.PARTIAL
    assert "2024-02" in r["note"]


def test_stem_missing_without_profile_is_missing_not_attention():
    r = N.verify({}, need("stem"))
    assert r["status"] == N.MISSING


# ---------------------------------------------------------------- after-school care

def test_care_ending_before_needed_time_is_partial():
    r = N.verify(osp_school(after_care_end_time="17:00", after_care_as_of="2026-09-01"),
                 need("after_school_care", value="18:00"))
    assert r["status"] == N.PARTIAL
    assert "17:00" in r["note"] and "18:00" in r["note"]


def test_care_until_needed_time_is_confirmed():
    r = N.verify(osp_school(after_care_end_time="18:30", after_care_as_of="2026-09-01"),
                 need("after_school_care", value="18:00"))
    assert r["status"] == N.CONFIRMED


def test_no_care_data_is_missing():
    assert N.verify({}, need("after_school_care", value="18:00"))["status"] == N.MISSING


# ---------------------------------------------------------------- ratings, cost, safety

def test_high_performing_thresholds():
    assert N.verify({"summary_rating": 9}, need("high_performing"))["status"] == N.CONFIRMED
    assert N.verify({"summary_rating": 6}, need("high_performing"))["status"] == N.PARTIAL
    assert N.verify({"summary_rating": 4}, need("high_performing"))["status"] == N.ATTENTION
    assert N.verify({}, need("high_performing"))["status"] == N.MISSING


def test_cost_public_free_private_missing_or_over_budget():
    assert N.verify({"entity_type": "charter"}, need("cost"))["status"] == N.CONFIRMED
    assert N.verify({"entity_type": "private"}, need("cost"))["status"] == N.MISSING
    assert N.verify({"entity_type": "private", "tuition": 16500}, need("cost", value=12000))["status"] == N.ATTENTION
    assert N.verify({"entity_type": "private", "tuition": 9000}, need("cost", value=12000))["status"] == N.CONFIRMED


def review(topic, sentiment, date):
    return {"created_date": date, "sentiments": [{"topic": topic, "sentiment_enum": sentiment}]}


def test_safety_old_reviews_only_is_partial_with_date_note():
    school = {"reviews_full": [review("Bullying / Safety", "negative", "2014-08-18T00:00:00-07:00")]}
    r = N.verify(school, need("safety", "prefer"))
    assert r["status"] == N.PARTIAL
    assert "older" in r["note"].lower()


def test_safety_recent_negative_reviews_need_attention():
    school = {"reviews_full": [review("Bullying / Safety", "negative", "2026-06-01T00:00:00-07:00"),
                               review("Bullying / Safety", "negative", "2026-03-01T00:00:00-07:00")]}
    assert N.verify(school, need("safety", "prefer"))["status"] == N.ATTENTION


# ---------------------------------------------------------------- modes and scoring

def test_avoid_mode_inverts_confirmed_and_attention():
    r = N.verify({"entity_type": "private"}, need("school_type", "avoid", ["private"]))
    assert r["status"] == N.ATTENTION


def test_required_needs_weigh_more_than_preferences():
    meets_required = [{"mode": "require", "status": N.CONFIRMED}, {"mode": "prefer", "status": N.ATTENTION}]
    meets_preferred = [{"mode": "require", "status": N.ATTENTION}, {"mode": "prefer", "status": N.CONFIRMED}]
    assert N.score(meets_required) > N.score(meets_preferred)


def test_location_within_radius_is_confirmed_with_distance():
    school = {"city": "Doral", "location": {"lat": 25.8195, "lon": -80.3553}}
    r = N.verify(school, need("location", value={"city": "Miami", "radius_km": 20,
                                                 "_center": {"lat": 25.7617, "lon": -80.1918}}))
    assert r["status"] == N.CONFIRMED
    assert any(e["field"] == "distance_km" for e in r["evidence"])


# ---------------------------------------------------------------- data quality

def test_quality_flags_catch_the_sample_data_problems():
    school = {"enrollment": 1, "student_teacher_ratio": 118, "attendance_rate": 40.4,
              "osp": {"start_time": ["8:25 PM"]}}
    fields = {f["field"] for f in N.quality_flags(school)}
    assert fields == {"enrollment", "student_teacher_ratio", "osp.start_time", "attendance_rate"}


def test_impossible_ratio_is_never_used_as_evidence():
    r = N.verify({"student_teacher_ratio": 118}, need("small_classes", "prefer"))
    assert r["status"] == N.MISSING
    assert not any(e["field"] == "student_teacher_ratio" for e in r["evidence"])


def test_clean_school_has_no_flags():
    assert N.quality_flags({"enrollment": 450, "student_teacher_ratio": 16, "attendance_rate": 94.0}) == []
