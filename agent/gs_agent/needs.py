"""Needs catalog and verification rules.

Whether a school meets a need is decided here, in plain code, from the data fields.
The LLM never decides a status and never writes evidence. See docs/contract.md.
"""

import math
from datetime import datetime, timezone
from typing import Any, Callable

from . import funding
from .config import FIELD_STALE_DAYS, REVIEW_STALE_DAYS, TODAY

CONFIRMED, PARTIAL, ATTENTION, MISSING = "confirmed", "partial", "needs_attention", "missing"

# id -> (label, how the agent should fill `value`, description for the prompt)
CATALOG: dict[str, dict[str, str]] = {
    "grade_level": {"label": "Grade level", "value": 'list of level codes: "p" pre-K, "e" elementary (K-5), "m" middle (6-8), "h" high (9-12)'},
    "location": {"label": "Location", "value": '{"city": "Miami", "state": "FL", "radius_km": 20}'},
    "school_type": {"label": "School type", "value": 'list of "public", "charter", "private"'},
    "high_performing": {"label": "High ratings", "value": "none"},
    "stem": {"label": "STEM", "value": "none"},
    "after_school_care": {"label": "After-school care", "value": 'latest pickup time needed, "HH:MM" 24h, or null'},
    "transportation": {"label": "School bus", "value": "none"},
    "small_classes": {"label": "Small classes", "value": "none"},
    "gifted": {"label": "Gifted program", "value": "none"},
    "special_ed": {"label": "Special ed / IEP support", "value": "none"},
    "ell_support": {"label": "English learner support", "value": "none"},
    "safety": {"label": "Safe, low bullying", "value": "none. Means the parent wants a safe school; use require or prefer, never avoid"},
    "attendance": {"label": "Good attendance", "value": "none"},
    "mental_health": {"label": "Counseling and mental health support", "value": "none"},
    "arts": {"label": "Arts", "value": "none"},
    "sports": {"label": "Sports", "value": "none"},
    "college_prep": {"label": "College prep", "value": "none"},
    "cost": {"label": "Tuition-free / affordable", "value": "max yearly tuition in USD, or null for free only"},
}

LEVEL_NAMES = {"p": "pre-K", "e": "elementary", "m": "middle", "h": "high"}


# ---------------------------------------------------------------- helpers

def _ev(field: str, value: Any, as_of: str | None = None, confidence: str | None = None) -> dict:
    item = {"field": field, "value": value}
    if as_of:
        item["as_of"] = as_of[:10]
    if confidence:
        item["confidence"] = confidence
    return item


def _result(need: str, status: str, evidence: list[dict], note: str | None = None) -> dict:
    return {"need": need, "status": status, "evidence": evidence, "note": note}


def _age_days(iso: str | None) -> int | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:  # plain dates like osp_as_of "2026-05-01"
        dt = dt.replace(tzinfo=timezone.utc)
    return (TODAY - dt).days


def _tier_check(school: dict, need: str, field: str, good: set, ok: set, bad: set) -> dict:
    """Shared rule for the GreatSchools 'tier' objects (class_size, ell, high_attendance...)."""
    obj = school.get(field)
    if not isinstance(obj, dict) or "tier" not in obj:
        return _result(need, MISSING, [], f"No {field.replace('_', ' ')} data for this school.")
    tier, as_of = obj["tier"], obj.get("source_generated_at")
    evidence = [_ev(f"{field}.tier", tier, as_of, obj.get("confidence"))]
    status = CONFIRMED if tier in good else PARTIAL if tier in ok else ATTENTION if tier in bad else PARTIAL
    note = None
    age = _age_days(as_of)
    if status == CONFIRMED and age is not None and age > FIELD_STALE_DAYS:
        status, note = PARTIAL, f"Data is from {as_of[:10]}, so it may be out of date."
    return _result(need, status, evidence, note)


def osp(school: dict, key: str) -> list:
    return school.get("osp", {}).get(key, [])


def has_profile(school: dict) -> bool:
    return bool(school.get("osp"))


def review_topic(school: dict, topic: str) -> dict:
    """Count positive/negative review mentions of a topic, split into recent and older."""
    counts = {"recent_pos": 0, "recent_neg": 0, "old_pos": 0, "old_neg": 0, "latest": None}
    for review in school.get("reviews_full", []):
        age = _age_days(review.get("created_date"))
        recent = age is not None and age <= REVIEW_STALE_DAYS
        for s in review.get("sentiments", []):
            if s.get("topic") != topic:
                continue
            key = ("recent_" if recent else "old_") + ("pos" if s.get("sentiment_enum") == "positive" else "neg")
            if s.get("sentiment_enum") in ("positive", "negative"):
                counts[key] += 1
            date = review.get("created_date", "")[:10]
            counts["latest"] = max(counts["latest"] or date, date)
    return counts


def haversine_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- per-need rules

def v_grade_level(school: dict, value: Any) -> dict:
    wanted = set(value or [])
    have = set(school.get("level_codes", []))
    ev = [_ev("level_codes", sorted(have))]
    if not wanted:
        return _result("grade_level", MISSING, ev, "Grade level not specified.")
    if wanted <= have:
        return _result("grade_level", CONFIRMED, ev)
    if wanted & have:
        return _result("grade_level", PARTIAL, ev, "Covers only some of the grades asked for.")
    return _result("grade_level", ATTENTION, ev, "Doesn't serve these grades.")


def v_location(school: dict, value: Any) -> dict:
    value = value or {}
    ev = [_ev("city", school.get("city")), _ev("zipcode", school.get("zipcode"))]
    center = value.get("_center")
    if center and school.get("location"):
        km = round(haversine_km(center, school["location"]), 1)
        ev.append(_ev("distance_km", km))
        if school.get("city", "").lower() == str(value.get("city", "")).lower():
            return _result("location", CONFIRMED, ev)
        radius = value.get("radius_km", 20)
        status = CONFIRMED if km <= radius else PARTIAL
        return _result("location", status, ev, f"About {km} km from {value.get('city')}.")
    if school.get("city", "").lower() == str(value.get("city", "")).lower():
        return _result("location", CONFIRMED, ev)
    return _result("location", PARTIAL, ev, "Outside the requested city.")


def v_school_type(school: dict, value: Any) -> dict:
    kind = school.get("entity_type")
    ev = [_ev("entity_type", kind)]
    return _result("school_type", CONFIRMED if kind in (value or []) else ATTENTION, ev)


def v_high_performing(school: dict, value: Any) -> dict:
    rating = school.get("summary_rating")
    stars = school.get("avg_review_rating")
    ev = [_ev("summary_rating", rating)] if rating is not None else []
    if stars:
        ev.append(_ev("avg_review_rating", stars))
    if rating is None:
        return _result("high_performing", MISSING, ev, "No GreatSchools summary rating for this school.")
    if rating >= 8:
        return _result("high_performing", CONFIRMED, ev)
    if rating >= 6:
        return _result("high_performing", PARTIAL, ev, f"Rated {rating}/10: average, not top.")
    return _result("high_performing", ATTENTION, ev, f"Rated {rating}/10.")


def _profile_stale(school: dict) -> bool:
    age = _age_days(school.get("osp_as_of"))
    return age is not None and age > FIELD_STALE_DAYS


def v_stem(school: dict, value: Any) -> dict:
    sub = osp(school, "school_sub_type")
    clubs = [c for c in osp(school, "student_clubs") if c in ("science_club", "math_club")]
    topic = review_topic(school, "STEM / Coding")
    if "STEM" in sub:
        ev = [_ev("osp.school_sub_type", sub, school.get("osp_as_of"))]
        if _profile_stale(school):
            return _result("stem", PARTIAL, ev, f"The STEM listing is from {school['osp_as_of'][:7]}, "
                                                "so I treated it as a nice-to-have. Ask if it still runs.")
        return _result("stem", CONFIRMED, ev, "School-reported.")
    ev = []
    if clubs:
        ev.append(_ev("osp.student_clubs", clubs))
    if topic["recent_pos"] > topic["recent_neg"]:
        ev.append(_ev("reviews: STEM / Coding", f"{topic['recent_pos']} positive recent mentions"))
    if ev:
        return _result("stem", PARTIAL, ev, "Some STEM activity, but no STEM program listed.")
    return _result("stem", MISSING, [], "The school profile doesn't mention STEM." if has_profile(school)
                   else "No detailed school profile.")


def v_after_school_care(school: dict, value: Any) -> dict:
    end = school.get("after_care_end_time")
    if end is None:
        day_end = osp(school, "end_time")
        ev = [_ev("osp.end_time", day_end)] if day_end else []
        return _result("after_school_care", MISSING, ev, "No after-school care information. Ask the school.")
    ev = [_ev("after_care_end_time", end, school.get("after_care_as_of"))]
    if value and end < value:
        return _result("after_school_care", PARTIAL, ev, f"Care ends at {end}; you need {value}.")
    as_of = school.get("after_care_as_of")  # care hours have their own date, not the profile's
    age = _age_days(as_of)
    if age is not None and age > FIELD_STALE_DAYS:
        return _result("after_school_care", PARTIAL, ev, f"Care hours are from {as_of[:7]}; confirm them.")
    return _result("after_school_care", CONFIRMED, ev)


def v_transportation(school: dict, value: Any) -> dict:
    t = osp(school, "transportation")
    if "busses" in t:
        return _result("transportation", CONFIRMED, [_ev("osp.transportation", t)], "School-reported.")
    if has_profile(school) and t:
        return _result("transportation", ATTENTION, [_ev("osp.transportation", t)], "No school bus listed.")
    return _result("transportation", MISSING, [], "No transportation information.")


def v_small_classes(school: dict, value: Any) -> dict:
    result = _tier_check(school, "small_classes", "class_size", {"very_small", "small"}, {"average"}, {"large"})
    ratio = school.get("student_teacher_ratio")
    if ratio is not None and ratio <= 40:
        result["evidence"].append(_ev("student_teacher_ratio", ratio))
        if result["status"] == MISSING:
            result["status"] = CONFIRMED if ratio <= 15 else PARTIAL if ratio <= 20 else ATTENTION
            result["note"] = None
    return result


def v_gifted(school: dict, value: Any) -> dict:
    g = school.get("gifted_talented")
    if g is None:
        return _result("gifted", MISSING, [], "No gifted program information.")
    return _result("gifted", CONFIRMED if g else ATTENTION, [_ev("gifted_talented", g)])


def v_special_ed(school: dict, value: Any) -> dict:
    ev, rating = [], school.get("swd_test_scores_rating")
    topic = review_topic(school, "Special Ed / IEP")
    if rating is not None:
        ev.append(_ev("swd_test_scores_rating", rating))
    if topic["recent_pos"] or topic["recent_neg"]:
        ev.append(_ev("reviews: Special Ed / IEP", f"{topic['recent_pos']} positive, {topic['recent_neg']} negative (recent)"))
    if rating is None and not ev:
        return _result("special_ed", MISSING, [], "No special education data or recent reviews.")
    if (rating or 0) >= 7 and topic["recent_neg"] <= topic["recent_pos"]:
        return _result("special_ed", CONFIRMED, ev)
    if rating is not None and rating <= 3 or topic["recent_neg"] > topic["recent_pos"]:
        return _result("special_ed", ATTENTION, ev)
    return _result("special_ed", PARTIAL, ev)


def v_ell_support(school: dict, value: Any) -> dict:
    result = _tier_check(school, "ell_support", "ell", {"high", "above_average"}, {"average"}, {"below_average", "low"})
    langs = [v for v in osp(school, "foreign_language") + osp(school, "family_engagement")
             if v in ("spanish", "in_person_translation", "phone_translation", "digital_translation", "home_lang")]
    if langs:
        result["evidence"].append(_ev("osp (language support)", langs))
        if result["status"] == MISSING:
            result["status"], result["note"] = PARTIAL, "Offers language support; no ELL rating."
    return result


def v_safety(school: dict, value: Any) -> dict:
    t = review_topic(school, "Bullying / Safety")
    recent, old = t["recent_pos"] + t["recent_neg"], t["old_pos"] + t["old_neg"]
    ev = []
    if recent:
        ev.append(_ev("reviews: Bullying / Safety", f"{t['recent_pos']} positive, {t['recent_neg']} negative (recent)"))
    if old:
        ev.append(_ev("reviews: Bullying / Safety (older)", f"{t['old_pos']} positive, {t['old_neg']} negative",
                      t["latest"]))
    if "anti_bullying" in osp(school, "mental_health") + osp(school, "family_engagement"):
        ev.append(_ev("osp", "anti_bullying program"))
    if not recent:
        note = "Only older reviews mention safety, so they may not reflect today." if old else "No reviews mention safety."
        return _result("safety", MISSING if not old else PARTIAL, ev, note)
    if t["recent_neg"] > t["recent_pos"]:
        return _result("safety", ATTENTION, ev, "Recent reviews raise safety concerns.")
    return _result("safety", CONFIRMED, ev)


MENTAL_HEALTH_STAFF = {"school_counselors", "social_workers", "mental_health_specialists"}


def v_mental_health(school: dict, value: Any) -> dict:
    """Counselors or specialists on the school's profile, plus what recent reviews say."""
    listed = osp(school, "mental_health")
    staff = [v for v in listed if v in MENTAL_HEALTH_STAFF]
    t = review_topic(school, "Mental Health")
    ev = [_ev("osp.mental_health", listed, school.get("osp_as_of"))] if listed else []
    if t["recent_pos"] or t["recent_neg"]:
        ev.append(_ev("reviews: Mental Health", f"{t['recent_pos']} positive, {t['recent_neg']} negative (recent)"))
    if staff and not _profile_stale(school):
        return _result("mental_health", CONFIRMED, ev, "School-reported counseling staff.")
    if t["recent_neg"] > t["recent_pos"]:
        return _result("mental_health", ATTENTION, ev, "Recent reviews say counseling support is lacking.")
    if staff:
        return _result("mental_health", PARTIAL, ev, f"Counseling staff listed in {school['osp_as_of'][:7]}; confirm it's current.")
    if listed or t["recent_pos"]:
        return _result("mental_health", PARTIAL, ev, "Some support listed or praised, but no counselors listed.")
    return _result("mental_health", MISSING, ev, "No counseling information. Ask the school.")


def v_attendance(school: dict, value: Any) -> dict:
    result = _tier_check(school, "attendance", "high_attendance", {"good"}, {"concerning"}, {"poor"})
    if school.get("attendance_rate") is not None:
        result["evidence"].append(_ev("attendance_rate", school["attendance_rate"]))
    return result


def _osp_any(need: str, keys: list[str], label: str) -> Callable[[dict, Any], dict]:
    def check(school: dict, value: Any) -> dict:
        found = {k: osp(school, k) for k in keys if osp(school, k)}
        if found:
            return _result(need, CONFIRMED, [_ev(f"osp.{k}", v) for k, v in found.items()], "School-reported.")
        return _result(need, MISSING, [], f"The school profile doesn't list {label}." if has_profile(school)
                       else "No detailed school profile.")
    return check


def v_college_prep(school: dict, value: Any) -> dict:
    ev = []
    if school.get("ap_courses"):
        ev.append(_ev("ap_courses", len(school["ap_courses"])))
    if school.get("college_readiness_rating") is not None:
        ev.append(_ev("college_readiness_rating", school["college_readiness_rating"]))
    if "college_prep" in osp(school, "school_sub_type"):
        ev.append(_ev("osp.school_sub_type", "college_prep"))
    if not ev:
        return _result("college_prep", MISSING, [], "No college prep information.")
    return _result("college_prep", CONFIRMED if len(ev) >= 2 or school.get("ap_courses") else PARTIAL, ev)


def v_cost(school: dict, value: Any) -> dict:
    kind = school.get("entity_type")
    if kind in ("public", "charter"):
        return _result("cost", CONFIRMED, [_ev("entity_type", kind)], "Public and charter schools are tuition-free.")
    tuition = school.get("tuition")
    if tuition is None:
        return _result("cost", MISSING, [_ev("entity_type", kind)], "Private school; tuition not listed.")
    ev = [_ev("tuition", tuition)]
    if value is not None and tuition <= value:
        return _result("cost", CONFIRMED, ev)
    # Over budget (or the parent wants free schools): show what a typical scholarship would leave.
    cost = funding.cost_summary(school)
    if "after_aid_estimate" not in cost:
        return _result("cost", ATTENTION, ev, f"Tuition is about ${tuition:,}/year.")
    after = cost["after_aid_estimate"]
    ev.append(_ev(f"funding.{cost['aid'][0]}.typical_amount", cost["aid_typical_amount"], cost["aid_as_of"]))
    note = (f"Tuition is about ${tuition:,}/year; about ${after:,} after a typical Florida scholarship "
            f"(estimate from the {cost['aid_as_of']} average).")
    fits = value is not None and after <= value
    return _result("cost", PARTIAL if fits else ATTENTION, ev, note)


RULES: dict[str, Callable[[dict, Any], dict]] = {
    "grade_level": v_grade_level,
    "location": v_location,
    "school_type": v_school_type,
    "high_performing": v_high_performing,
    "stem": v_stem,
    "after_school_care": v_after_school_care,
    "transportation": v_transportation,
    "small_classes": v_small_classes,
    "gifted": v_gifted,
    "special_ed": v_special_ed,
    "ell_support": v_ell_support,
    "safety": v_safety,
    "attendance": v_attendance,
    "mental_health": v_mental_health,
    "arts": _osp_any("arts", ["arts_visual", "arts_music", "arts_performing_written"], "arts programs"),
    "sports": _osp_any("sports", ["boys_sports", "girls_sports"], "sports"),
    "college_prep": v_college_prep,
    "cost": v_cost,
}

_INVERT = {CONFIRMED: ATTENTION, ATTENTION: CONFIRMED}

# Needs that only make sense as something wanted. "Avoid bullying" means "want safety",
# so an avoid on these is read as require; inverting it would flag the safest schools.
WANTED_ONLY = {"safety"}


def normalize_mode(need: dict) -> str:
    mode = need.get("mode", "prefer")
    return "require" if mode == "avoid" and need.get("need") in WANTED_ONLY else mode


def verify(school: dict, need: dict) -> dict:
    """Status of one need for one school. `need` is {"need", "mode", "value"}."""
    result = RULES[need["need"]](school, need.get("value"))
    result["mode"] = normalize_mode(need)
    if result["mode"] == "avoid":
        result["status"] = _INVERT.get(result["status"], result["status"])
    return result


# ---------------------------------------------------------------- data quality

def quality_flags(school: dict) -> list[dict]:
    """Values that look wrong. They are shown to parents but not used for ranking."""
    flags = []
    if school.get("enrollment") is not None and school["enrollment"] <= 1:
        flags.append({"field": "enrollment", "value": school["enrollment"],
                      "note": "Enrollment is listed as 0 or 1, so we don't have reliable size data."})
    ratio = school.get("student_teacher_ratio")
    if ratio is not None and ratio > 40:
        flags.append({"field": "student_teacher_ratio", "value": ratio,
                      "note": f"A ratio of {ratio} students per teacher is unlikely; we didn't use it."})
    for t in osp(school, "start_time"):
        if "PM" in t.upper():
            flags.append({"field": "osp.start_time", "value": t, "note": f"Start time '{t}' looks like a typo."})
    rate = school.get("attendance_rate")
    if rate is not None and rate < 50:
        flags.append({"field": "attendance_rate", "value": rate,
                      "note": "Attendance rate is unusually low; check with the school."})
    return flags


# ---------------------------------------------------------------- scoring

STATUS_POINTS = {CONFIRMED: 1.0, PARTIAL: 0.5, MISSING: 0.25, ATTENTION: 0.0}
MODE_WEIGHT = {"require": 3.0, "prefer": 1.0, "avoid": 2.0}


def score(criteria: list[dict]) -> float:
    total = sum(MODE_WEIGHT[c["mode"]] for c in criteria)
    if not total:
        return 0.0
    return sum(MODE_WEIGHT[c["mode"]] * STATUS_POINTS[c["status"]] for c in criteria) / total
