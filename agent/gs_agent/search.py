"""OpenSearch retrieval plus code-side verification and ranking."""

import json
from collections import Counter
from functools import lru_cache
from typing import Any, Callable

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from . import needs as N
from .config import EMBED_DIMS, EMBED_MODEL, REGION, SCHOOLS_INDEX, search_endpoint

SOURCE_EXCLUDES = ["profile_vector", "profile_text", "reviews_text", "reviews_positive", "reviews_negative"]


@lru_cache(maxsize=1)
def _session() -> boto3.Session:
    return boto3.Session(region_name=REGION)


@lru_cache(maxsize=1)
def client() -> OpenSearch:
    host = search_endpoint().removeprefix("https://")
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=AWSV4SignerAuth(_session().get_credentials(), REGION, "es"),
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def embed(text: str) -> list[float]:
    body = json.dumps({"inputText": text[:8000], "dimensions": EMBED_DIMS, "normalize": True})
    response = _session().client("bedrock-runtime").invoke_model(modelId=EMBED_MODEL, body=body)
    return json.loads(response["body"].read())["embedding"]


def resolve_location(value: dict) -> dict | None:
    """Center point for a city, from the schools we have there. None if we have none."""
    city = str(value.get("city", "")).strip()
    if not city:
        return None
    hits = client().search(index=SCHOOLS_INDEX, body={
        "size": 50, "_source": ["location"],
        "query": {"bool": {"should": [{"term": {"city": city}}, {"term": {"city": city.title()}}],
                           "minimum_should_match": 1}},
    })["hits"]["hits"]
    points = [h["_source"]["location"] for h in hits if h["_source"].get("location")]
    if not points:
        return None
    return {"lat": sum(p["lat"] for p in points) / len(points), "lon": sum(p["lon"] for p in points) / len(points)}


CANDIDATES = 50  # schools pulled from OpenSearch per search; code verifies and re-ranks these
MODE_BOOST = {"require": 3.0, "prefer": 1.0, "avoid": 1.0}
SEMANTIC_BOOST = 2.0


def _reviews_positive(topic: str) -> dict:
    """Schools where at least one review speaks well of a topic (counts from sentiment_stats)."""
    return {"range": {f"sentiment_stats.sentiment_by_topic.{topic}.positive": {"gte": 1}}}


def _exists(*fields: str) -> list[dict]:
    return [{"exists": {"field": f}} for f in fields]


# Each need becomes OpenSearch clauses, the same way GreatSchools maps needs to query
# parameters today. A clause is (query, weight). These only decide which schools come
# back and in what order; the status shown to parents still comes from needs.verify().
BOOSTS: dict[str, Callable[[Any], list[tuple[dict, float]]]] = {
    "grade_level": lambda v: [({"terms": {"level_codes": list(v)}}, 2.0)] if v else [],
    "school_type": lambda v: [({"terms": {"entity_type": list(v)}}, 2.0)] if v else [],
    "high_performing": lambda v: [({"range": {"summary_rating": {"gte": 8}}}, 2.0),
                                  ({"range": {"avg_review_rating": {"gte": 4}}}, 1.0)],
    "stem": lambda v: [({"term": {"osp.school_sub_type": "STEM"}}, 2.0),
                       ({"terms": {"osp.student_clubs": ["science_club", "math_club"]}}, 1.0),
                       (_reviews_positive("STEM / Coding"), 0.5)],
    "after_school_care": lambda v: [({"range": {"after_care_end_time": {"gte": v}}} if v
                                     else {"exists": {"field": "after_care_end_time"}}, 2.0)],
    "transportation": lambda v: [({"term": {"osp.transportation": "busses"}}, 2.0)],
    "small_classes": lambda v: [({"terms": {"class_size.tier": ["very_small", "small"]}}, 2.0),
                                ({"range": {"student_teacher_ratio": {"lte": 15}}}, 1.0)],
    "gifted": lambda v: [({"term": {"gifted_talented": True}}, 2.0)],
    "special_ed": lambda v: [({"range": {"swd_test_scores_rating": {"gte": 7}}}, 1.5),
                             (_reviews_positive("Special Ed / IEP"), 1.0)],
    "ell_support": lambda v: [({"terms": {"ell.tier": ["high", "above_average"]}}, 2.0),
                              ({"terms": {"osp.foreign_language": ["spanish"]}}, 0.5)],
    "safety": lambda v: [(_reviews_positive("Bullying / Safety"), 1.0),
                         ({"terms": {"osp.mental_health": ["anti_bullying"]}}, 0.5)],
    "attendance": lambda v: [({"term": {"high_attendance.tier": "good"}}, 2.0)],
    "arts": lambda v: [(q, 1.0) for q in _exists("osp.arts_visual", "osp.arts_music", "osp.arts_performing_written")],
    "sports": lambda v: [(q, 1.0) for q in _exists("osp.boys_sports", "osp.girls_sports")],
    "college_prep": lambda v: [({"exists": {"field": "ap_courses"}}, 1.5),
                               ({"range": {"college_readiness_rating": {"gte": 7}}}, 1.5)],
    "cost": lambda v: [({"terms": {"entity_type": ["public", "charter"]}}, 2.0)]
                      + ([({"range": {"tuition": {"lte": v}}}, 2.0)] if v else []),
}


def _filters(needs: list[dict]) -> tuple[list[dict], dict]:
    """Hard filters for required grade, type, location and ratings. Returns (filters, notes)."""
    filters, notes = [], {}
    for need in needs:
        if need.get("mode") != "require":
            continue
        value = need.get("value")
        if need["need"] == "grade_level" and value:
            filters.append({"terms": {"level_codes": list(value)}})
        elif need["need"] == "school_type" and value:
            filters.append({"terms": {"entity_type": list(value)}})
        elif need["need"] == "high_performing":
            # GreatSchools' "high performing" need is a hard filter on rating 8-10. We also keep
            # schools with no rating, so the parent sees "we don't know" instead of losing them.
            filters.append({"bool": {"should": [{"range": {"summary_rating": {"gte": 8}}},
                                                {"bool": {"must_not": {"exists": {"field": "summary_rating"}}}}],
                                     "minimum_should_match": 1}})
        elif need["need"] == "location" and value:
            center = resolve_location(value)
            if center is None:
                notes["location"] = f"We have no schools in '{value.get('city')}' in our data."
                filters.append({"term": {"city": "__none__"}})
            else:
                value["_center"] = center
                radius = value.get("radius_km", 20)
                filters.append({"geo_distance": {"distance": f"{radius}km", "location": center}})
    return filters, notes


def build_query(needs: list[dict], filters: list[dict], vector: list[float] | None = None) -> dict:
    """One scored query: filters, a boost per need, and optional semantic similarity.

    require and prefer boosts raise a school's score; avoid boosts lower it.
    """
    positive, negative = [], []
    for need in needs:
        weight = MODE_BOOST.get(need.get("mode", "prefer"), 1.0)
        clauses = [{"constant_score": {"filter": q, "boost": w * weight}}
                   for q, w in BOOSTS[need["need"]](need.get("value"))]
        (negative if need.get("mode") == "avoid" else positive).extend(clauses)
    if vector is not None:
        positive.append({"knn": {"profile_vector": {"vector": vector, "k": CANDIDATES,
                                                    "filter": {"bool": {"filter": filters}},
                                                    "boost": SEMANTIC_BOOST}}})
    query: dict = {"bool": {"filter": filters, "should": positive}}
    if negative:
        query = {"boosting": {"positive": query, "negative": {"bool": {"should": negative}}, "negative_boost": 0.5}}
    return query


def find(needs: list[dict], semantic_query: str | None = None, size: int = 8) -> dict:
    """Search, verify every need for every candidate, and rank. Pure code apart from the embedding."""
    needs = [n for n in needs if n.get("need") in N.RULES]
    for n in needs:  # in place, like the location center below, so chips show the mode we used
        n["mode"] = N.normalize_mode(n)
    filters, notes = _filters(needs)
    vector = embed(semantic_query) if semantic_query else None

    hits = client().search(index=SCHOOLS_INDEX, body={
        "size": CANDIDATES, "query": build_query(needs, filters, vector),
        "sort": ["_score", {"name.raw": "asc"}], "track_scores": True,
        "_source": {"excludes": SOURCE_EXCLUDES},
    })["hits"]["hits"]

    max_retrieval = max((h["_score"] or 0 for h in hits), default=0.0) or 1.0
    results = []
    for hit in hits:
        school = hit["_source"]
        criteria = [N.verify(school, n) for n in needs]
        # The verified criteria decide most of the rank; the search score breaks near-ties.
        final = 0.85 * N.score(criteria) + 0.15 * ((hit["_score"] or 0) / max_retrieval)
        results.append({
            "school_id": hit["_id"],
            "name": school.get("name"),
            "entity_type": school.get("entity_type"),
            "city": school.get("city"),
            "level_codes": school.get("level_codes"),
            "score": round(final, 3),
            "criteria": criteria,
            "quality_flags": N.quality_flags(school),
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:size]
    for rank, r in enumerate(results, 1):
        r["rank"] = rank
        r["watch_out"] = watch_out(r)

    return {"results": results, "summary": summarize(needs, results), "notes": notes, "total_candidates": len(hits)}


def watch_out(result: dict) -> str | None:
    """One honest line about the downsides, built only from statuses and flags."""
    def reason(c: dict) -> str:
        if c["note"]:
            return c["note"]
        shown = ", ".join(f"{e['field']} is {e['value']}" for e in c["evidence"][:2])
        return f"not met ({shown})" if shown else "not met"

    parts = [f"{N.CATALOG[c['need']]['label']}: {reason(c)}"
             for c in result["criteria"] if c["status"] == N.ATTENTION]
    parts += [f["note"] for f in result["quality_flags"]]
    return " ".join(parts[:3]) or None


def summarize(needs: list[dict], results: list[dict]) -> dict:
    """Per-need status counts across the results. The agent uses this to pick its question."""
    summary = {}
    for need in needs:
        counts = Counter(c["status"] for r in results for c in r["criteria"] if c["need"] == need["need"])
        summary[need["need"]] = dict(counts)
    return summary


def get_school(school_id: str) -> dict | None:
    try:
        doc = client().get(index=SCHOOLS_INDEX, id=school_id, _source_excludes=["profile_vector"])
    except Exception:
        return None
    return doc["_source"]
