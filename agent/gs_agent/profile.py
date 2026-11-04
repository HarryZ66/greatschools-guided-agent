"""Verified school profile (P3): built in code from the record, the same rules as the cards, and the guide."""

from . import funding
from . import needs as N
from .search import CONTENT_INDEX, client

TOPICS = ["Teachers / Staff", "Bullying / Safety", "STEM / Coding", "Special Ed / IEP", "ELL", "Mental Health",
          "Homework / Assignments", "Leadership", "Sports", "Belonging / Inclusion", "Gifted / Advanced Learning"]


def _terms_for(school: dict) -> list[str]:
    """Guide entries that explain what's on this school's page."""
    ids = {"public": "public-school", "charter": "charter-school", "private": "private-school"}
    terms = [ids[school["entity_type"]]] if school.get("entity_type") in ids else []
    sub = school.get("osp", {}).get("school_sub_type", [])
    terms += [t for s, t in (("magnet", "magnet-school"), ("montessori", "montessori"), ("STEM", "stem")) if s in sub]
    for field, term in (("summary_rating", "gs-summary-rating"), ("test_scores_rating", "gs-test-score-rating"),
                        ("student_progress_rating", "gs-student-progress-rating"),
                        ("college_readiness_rating", "gs-college-readiness"), ("swd_test_scores_rating", "iep"),
                        ("ell", "ell"), ("ap_courses", "ap"), ("gifted_talented", "gifted"),
                        ("after_care_end_time", "after-school-care"), ("student_teacher_ratio", "student-teacher-ratio"),
                        ("tuition", "tax-credit-scholarship")):
        if school.get(field) is not None:
            terms.append(term)
    return terms + ["app-statuses"]


def _guide(ids: list[str]) -> list[dict]:
    docs = client().mget(index=CONTENT_INDEX, body={"ids": ids}, _source=["title", "body"])["docs"]
    return [{"id": d["_id"], "title": d["_source"]["title"], "body": d["_source"]["body"]} for d in docs if d.get("found")]


def _reviews(school: dict) -> dict:
    topics = {}
    for topic in TOPICS:
        t = N.review_topic(school, topic)
        if any(t[k] for k in ("recent_pos", "recent_neg", "old_pos", "old_neg")):
            topics[topic] = {k: t[k] for k in ("recent_pos", "recent_neg", "old_pos", "old_neg")}
    excerpts = []
    for r in sorted(school.get("reviews_full", []), key=lambda r: r.get("created_date", ""), reverse=True)[:3]:
        age = N._age_days(r.get("created_date"))
        sentence = r["text"].split(". ")[1] if ". " in r["text"] else r["text"]  # skip the stock opener
        excerpts.append({"text": sentence.strip().rstrip(".") + ".", "date": r.get("created_date", "")[:10],
                         "older": age is not None and age > N.REVIEW_STALE_DAYS,
                         "topics": [s["topic"] for s in r.get("sentiments", [])]})
    return {"by_topic": topics, "excerpts": excerpts, "total": len(school.get("reviews_full", []))}


def build(school: dict, needs: list[dict]) -> dict:
    return {
        "criteria": [N.verify(school, dict(n)) for n in needs],
        "quality_flags": N.quality_flags(school),
        "reviews": _reviews(school),
        "terms": _guide(_terms_for(school)),
        "cost": funding.cost_summary(school),
    }
