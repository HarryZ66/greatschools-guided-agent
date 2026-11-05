"""One "Best for ..." badge per school card, decided in code (decision 031).

A school earns "Best for X" only when its status for X is confirmed and it is the single
strongest of the schools shown, measured by a value in the data (latest care pickup, fewest
students per teacher, most counseling staff listed...). A tie earns nobody the badge, so the
card never says "best" when it isn't. Each school gets at most one badge and each need goes to
at most one school.

The parent's own needs come first, in their order (must-haves before nice-to-haves). Then a short
list of extra needs, so a school can stand out for something the parent didn't ask about. The
extras leave out needs tied to a child's language or disability (decision 007): those badges
appear only when the parent asked for that need.
"""

from typing import Any, Callable

from . import funding
from . import needs as N

FILTER_NEEDS = {"grade_level", "location", "school_type"}  # every shown school already meets these

# Needs a school can be "best for" without the parent asking. No special_ed / ell_support (decision 007).
EXTRA_NEEDS = ["mental_health", "stem", "arts", "sports", "small_classes", "after_school_care",
               "safety", "gifted", "college_prep", "transportation", "high_performing"]

WORDS = {
    "stem": "STEM", "after_school_care": "after-school care", "small_classes": "small classes",
    "transportation": "bus service", "gifted": "advanced learners", "special_ed": "extra help with learning",
    "ell_support": "help learning English", "safety": "safety", "attendance": "attendance",
    "mental_health": "counseling", "arts": "the arts", "sports": "sports", "college_prep": "college prep",
    "high_performing": "ratings", "cost": "low cost",
}
TIER_RANK = {"very_small": 3, "small": 2, "high": 3, "above_average": 2, "average": 1}
STAFF_WORDS = {"school_counselors": "counselors", "social_workers": "social workers",
               "mental_health_specialists": "mental health specialists"}


def _clock(hhmm: str) -> str:
    """'18:30' -> '6:30pm' (parents read 12-hour times)."""
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{h % 12 or 12}{':%02d' % m if m else ''}{'pm' if h >= 12 else 'am'}"


def _join(items: list[str]) -> str:
    return " and ".join([", ".join(items[:-1]), items[-1]] if len(items) > 1 else items)


# need -> (strength(school) -> sortable key, or None when too thin to call best;
#          fact(school) -> short phrase; superlative)
def _mental_health(s):
    staff = [v for v in N.osp(s, "mental_health") if v in N.MENTAL_HEALTH_STAFF]
    t = N.review_topic(s, "Mental Health")
    return (len(staff), len(N.osp(s, "mental_health")), t["recent_pos"] - t["recent_neg"])


def _stem(s):
    clubs = [c for c in N.osp(s, "student_clubs") if c in ("science_club", "math_club")]
    return (len(clubs), N.review_topic(s, "STEM / Coding")["recent_pos"])


def _stem_fact(s):
    clubs = [c.replace("_", " ") for c in N.osp(s, "student_clubs") if c in ("science_club", "math_club")]
    return "a STEM program" + (f" plus a {_join(clubs)}" if clubs else "")


def _arts(s):
    return [v for k in ("arts_visual", "arts_music", "arts_performing_written") for v in N.osp(s, k)]


def _sports(s):
    return sorted(set(N.osp(s, "boys_sports") + N.osp(s, "girls_sports")))


def _ratio(s):
    r = s.get("student_teacher_ratio")
    return r if r is not None and r <= 40 else None  # over 40 is a data quality flag, never "best"


def _small_classes_fact(s):
    r = _ratio(s)
    return f"{r} students per teacher" if r is not None else f"{s['class_size']['tier'].replace('_', ' ')} classes"


def _safety(s):
    t = N.review_topic(s, "Bullying / Safety")
    if t["recent_pos"] <= t["recent_neg"]:
        return None  # mixed reviews can be "confirmed" (no concerns), but not "best"
    return (t["recent_pos"] - t["recent_neg"], t["recent_pos"])


def _safety_fact(s):
    t = N.review_topic(s, "Bullying / Safety")
    return f"{t['recent_pos']} good and {t['recent_neg']} bad recent reviews about safety"


def _yearly_cost(s):
    c = funding.cost_summary(s)
    return c.get("after_aid_estimate", c.get("tuition"))


RULES: dict[str, tuple[Callable[[dict], Any], Callable[[dict], str], str]] = {
    "after_school_care": (lambda s: s["after_care_end_time"],
                          lambda s: f"care until {_clock(s['after_care_end_time'])}", "Latest after-school care"),
    "small_classes": (lambda s: (TIER_RANK.get((s.get("class_size") or {}).get("tier"), 0), -(_ratio(s) or 99)),
                      _small_classes_fact, "Smallest classes"),
    "high_performing": (lambda s: (s["summary_rating"], s.get("avg_review_rating") or 0),
                        lambda s: f"a GreatSchools rating of {s['summary_rating']} out of 10", "Highest rating"),
    "stem": (_stem, _stem_fact, "Most STEM on offer"),
    "mental_health": (_mental_health,
                      lambda s: _join([STAFF_WORDS[v] for v in N.osp(s, "mental_health") if v in STAFF_WORDS]) + " on staff",
                      "Most counseling support"),
    "safety": (_safety, _safety_fact, "Best safety reviews"),
    "special_ed": (lambda s: (s.get("swd_test_scores_rating") or 0,),
                   lambda s: f"a {s.get('swd_test_scores_rating')} out of 10 for test results of students who get extra help",
                   "Strongest results for students who get extra help"),
    "ell_support": (lambda s: (TIER_RANK.get((s.get("ell") or {}).get("tier"), 0),),
                    lambda s: f"{s['ell']['tier'].replace('_', ' ')} results for students learning English",
                    "Strongest support for students learning English"),
    "attendance": (lambda s: (s.get("attendance_rate") or 0,),
                   lambda s: f"an attendance rate of {s.get('attendance_rate')}%", "Best attendance"),
    "arts": (lambda s: len(_arts(s)), lambda s: f"{len(_arts(s))} arts programs listed", "Most arts programs"),
    "sports": (lambda s: len(_sports(s)), lambda s: f"{len(_sports(s))} sports listed", "Most sports"),
    "college_prep": (lambda s: (len(s.get("ap_courses") or []), s.get("college_readiness_rating") or 0),
                     lambda s: f"{len(s.get('ap_courses') or [])} AP courses", "Strongest college prep"),
    "gifted": (lambda s: 1, lambda s: "a program for advanced learners", "Advanced-learner program"),
    "transportation": (lambda s: 1, lambda s: "a school bus listed", "School bus"),
    "cost": (lambda s: -(_yearly_cost(s) or 0),
             lambda s: "no tuition" if not _yearly_cost(s) else f"about ${_yearly_cost(s):,} a year", "Lowest cost"),
}


def _winner(need: dict, results: list[dict], docs: dict[str, dict]) -> tuple[dict, str] | None:
    """The single strongest confirmed school for one need, and why, or None on a tie or no data."""
    rule = RULES.get(need["need"])
    if not rule:
        return None
    strength, fact, superlative = rule
    confirmed = []
    for r in results:
        c = next((c for c in r["criteria"] if c["need"] == need["need"]), None)
        if c is None:  # an extra need the parent didn't ask about: check it with the same rules
            c = N.verify(docs[r["school_id"]], {"need": need["need"], "mode": "prefer", "value": need.get("value")})
        key = strength(docs[r["school_id"]]) if c["status"] == N.CONFIRMED else None
        if key is not None:
            confirmed.append((key, r))
    if not confirmed:
        return None
    best = max(k for k, _ in confirmed)
    top = [r for k, r in confirmed if k == best]
    if len(top) != 1:
        return None
    school, n = top[0], len(results)
    why = (f"The only one of these {n} schools that has {fact(docs[school['school_id']])}." if len(confirmed) == 1
           else f"{superlative} of these {n} schools: {fact(docs[school['school_id']])}.")
    return school, why


def assign(asked: list[dict], results: list[dict], docs: dict[str, dict]) -> None:
    """Set results[i]["badge"] to {need, label, why, asked} or None. Pure code, no model."""
    for r in results:
        r["badge"] = None
    if len(results) < 2:  # "best of one" means nothing
        return
    mine = [n for n in asked if n["need"] not in FILTER_NEEDS and n.get("mode") != "avoid"]
    mine.sort(key=lambda n: n.get("mode") != "require")  # stable: must-haves first, parent's order kept
    taken = {n["need"] for n in asked}
    order = [(n, True) for n in mine] + [({"need": x}, False) for x in EXTRA_NEEDS if x not in taken]
    for need, was_asked in order:
        found = _winner(need, results, docs)  # best among every school shown
        if not found:
            continue
        school, why = found
        if school["badge"] is None:
            school["badge"] = {"need": need["need"], "label": f"Best for {WORDS[need['need']]}",
                               "why": why, "asked": was_asked}
