"""OpenSearch retrieval plus code-side verification and ranking."""

import json
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Callable

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from . import badges, funding
from . import knowledge
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


def _center_of(query: dict) -> dict | None:
    hits = client().search(index=SCHOOLS_INDEX, body={"size": 50, "_source": ["location"], "query": query})["hits"]["hits"]
    points = [h["_source"]["location"] for h in hits if h["_source"].get("location")]
    if not points:
        return None
    return {"lat": sum(p["lat"] for p in points) / len(points), "lon": sum(p["lon"] for p in points) / len(points)}


def resolve_location(value: dict) -> dict | None:
    """Center point for a city or a ZIP code, from the schools we have there. None if we have none.

    A ZIP is matched from our own data (exact, then the same 4- and 3-digit area), never from
    the model's memory, so a ZIP outside our data gets "no schools there" instead of a guess.
    """
    zipcode = "".join(ch for ch in str(value.get("zip") or "") if ch.isdigit())[:5]
    if len(zipcode) == 5:
        for prefix in (zipcode, zipcode[:4], zipcode[:3]):
            q = {"term": {"zipcode": prefix}} if prefix == zipcode else {"prefix": {"zipcode": prefix}}
            if (center := _center_of(q)):
                return center
    city = str(value.get("city", "")).strip()
    if not city:
        return None
    return _center_of({"bool": {"should": [{"term": {"city": city}}, {"term": {"city": city.title()}}],
                                "minimum_should_match": 1}})


DATA_PROBLEM_PENALTY = 0.02  # score taken off per data problem (quality_flags), up to 3: a tie-breaker
CANDIDATES = 50  # schools pulled from OpenSearch per search; code verifies and re-ranks these
MODE_BOOST = {"require": 3.0, "prefer": 1.0, "avoid": 1.0}
SEMANTIC_BOOST = 2.0


def _reviews_positive(topic: str) -> dict:
    """Schools where at least one review speaks well of a topic (counts from sentiment_stats)."""
    return {"range": {f"sentiment_stats.sentiment_by_topic.{topic}.positive": {"gte": 1}}}


def _exists(*fields: str) -> list[dict]:
    return [{"exists": {"field": f}} for f in fields]


# Each need becomes OpenSearch clauses, the way GreatSchools maps needs to query parameters
# today ("top school" -> high performing -> rating 8-10). A clause is (query, weight). These
# decide which schools come back and in what order; the status parents see still comes from
# needs.verify(). Ported from Sanchit Arora's PR #1.
BOOSTS: dict[str, Callable[[Any], list[tuple[dict, float]]]] = {
    "grade_level": lambda v: [({"terms": {"level_codes": list(v)}}, 2.0)] if v else [],
    "location": lambda v: [],  # handled as a geo filter
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
    "mental_health": lambda v: [({"terms": {"osp.mental_health": sorted(N.MENTAL_HEALTH_STAFF)}}, 2.0),
                                (_reviews_positive("Mental Health"), 0.5)],
    "arts": lambda v: [(q, 1.0) for q in _exists("osp.arts_visual", "osp.arts_music", "osp.arts_performing_written")],
    "sports": lambda v: [(q, 1.0) for q in _exists("osp.boys_sports", "osp.girls_sports")],
    "college_prep": lambda v: [({"exists": {"field": "ap_courses"}}, 1.5),
                               ({"range": {"college_readiness_rating": {"gte": 7}}}, 1.5)],
    "cost": lambda v: [({"terms": {"entity_type": ["public", "charter"]}}, 2.0)]
                      + ([({"range": {"tuition": {"lte": v}}}, 2.0)] if v else []),
}


def build_query(needs: list[dict], filters: list[dict], vector: list[float] | None = None) -> dict:
    """One scored query: hard filters, a boost per need, and optional semantic similarity.

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


@lru_cache(maxsize=1)
def covered_cities() -> dict:
    """Where we actually have schools, so the agent can say so accurately instead of guessing."""
    aggs = client().search(index=SCHOOLS_INDEX, body={
        "size": 0,
        "aggs": {"states": {"terms": {"field": "state", "size": 10},
                            "aggs": {"cities": {"terms": {"field": "city", "size": 60}}}}},
    })["aggregations"]["states"]["buckets"]
    return {s["key"]: {c["key"]: c["doc_count"] for c in s["cities"]["buckets"]} for s in aggs}


def _filters(needs: list[dict]) -> tuple[list[dict], dict]:
    """Hard filters for required grade, type and location. Returns (filters, notes)."""
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
            # GreatSchools' "high performing" need is a hard filter on rating 8-10. Schools with
            # no rating stay, so the parent sees "we don't know" instead of losing them.
            filters.append({"bool": {"should": [{"range": {"summary_rating": {"gte": 8}}},
                                                {"bool": {"must_not": {"exists": {"field": "summary_rating"}}}}],
                                     "minimum_should_match": 1}})
        elif need["need"] == "location" and value:
            center = resolve_location(value)
            if center is None:
                notes["location"] = f"We have no schools in '{N.place(value)}' in our data."
                notes["cities_with_data"] = covered_cities()
                filters.append({"term": {"city": "__none__"}})
            else:
                value["_center"] = center
                radius = value.get("radius_km", 20)
                filters.append({"geo_distance": {"distance": f"{radius}km", "location": center}})
    return filters, notes


def find(needs: list[dict], semantic_query: str | None = None, size: int = 8) -> dict:
    """Search, verify every need for every candidate, and rank. Pure code apart from the embedding."""
    needs = [n for n in needs if n.get("need") in N.RULES]
    for n in needs:  # in place, like the location center, so chips show the mode actually used
        n["mode"] = N.normalize_mode(n)
    filters, notes = _filters(needs)
    vector = embed(semantic_query) if semantic_query else None

    hits = client().search(index=SCHOOLS_INDEX, body={
        "size": CANDIDATES, "query": build_query(needs, filters, vector),
        "sort": ["_score", {"name.raw": "asc"}], "track_scores": True,
        "_source": {"excludes": SOURCE_EXCLUDES},
    })["hits"]["hits"]

    max_retrieval = max((h["_score"] or 0 for h in hits), default=0.0) or 1.0
    results, docs = [], {}
    for hit in hits:
        school = docs[hit["_id"]] = hit["_source"]
        criteria = [N.verify(school, n) for n in needs]
        flags = N.quality_flags(school)
        # Verified criteria decide most of the rank; the search score breaks near-ties.
        final = 0.85 * N.score(criteria) + 0.15 * ((hit["_score"] or 0) / max_retrieval)
        # A "yes" read from data with obvious problems is less certain. Each problem takes a little
        # off (at most 3), enough that a clean school with the same checks comes first, but never
        # enough to drop a school below ones that meet fewer of the parent's needs.
        final -= DATA_PROBLEM_PENALTY * min(len(flags), 3)
        results.append({
            "school_id": hit["_id"],
            "name": school.get("name"),
            "entity_type": school.get("entity_type"),
            "city": school.get("city"),
            "level_codes": school.get("level_codes"),
            "score": round(final, 3),
            "criteria": criteria,
            "quality_flags": flags,
            "cost": funding.cost_summary(school),
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    for rank, r in enumerate(results, 1):
        r["rank"] = rank
    # Trade-offs are found across every candidate; a hinted school outside the top cards is
    # added as an extra card so the agent never talks about a school the parent can't see.
    hints, hinted_ids = question_hints(needs, results)
    shown = results[:size]
    shown += [r for r in results[size:] if r["school_id"] in hinted_ids]
    for r in shown:
        r["watch_out"] = watch_out(r)
    badges.assign(needs, shown, docs)

    return {"results": shown, "summary": summarize(needs, shown), "notes": notes,
            "question_hints": hints, "total_candidates": len(hits)}


FILTER_NEEDS = {"grade_level", "location", "school_type"}  # already enforced by the search itself


def question_hints(needs: list[dict], results: list[dict]) -> tuple[list[str], set[str]]:
    """Trade-offs worth asking about, found in code so the agent asks them reliably.

    1. A top school meets every other must-have but only partly meets one (e.g. care ends at 5,
       parent needs 6): ask whether that is workable.
    2. No result confirms a must-have: ask whether it's truly a must, or what to relax.
    """
    hints = []
    required = [n["need"] for n in needs if n.get("mode") == "require" and n["need"] not in FILTER_NEEDS]
    valued = {n["need"] for n in needs if n.get("value")}  # needs with a time or price: concrete trade-offs
    candidates = []
    for r in results:
        by_need = {c["need"]: c for c in r["criteria"]}
        partial = [n for n in required if by_need[n]["status"] == N.PARTIAL]
        others_ok = all(by_need[n]["status"] == N.CONFIRMED for n in required if n not in partial)
        if len(partial) == 1 and others_ok:
            confirmed = sum(c["status"] == N.CONFIRMED for c in r["criteria"] if c["need"] not in FILTER_NEEDS)
            candidates.append((partial[0] in valued, confirmed, -r["rank"], r, by_need[partial[0]]))
    candidates.sort(key=lambda t: t[:3], reverse=True)
    hinted_ids = set()
    wanted = {n["need"]: n.get("value") for n in needs}
    for _, _, _, r, c in candidates[:2]:
        hinted_ids.add(r["school_id"])
        hint = (f"Trade-off: {r['name']} meets every other must-have, but "
                f"{N.CATALOG[c['need']]['label']} is only partial: {(c['note'] or '').rstrip('.')}. "
                "Ask if that is workable.")
        ends = next((e["value"] for e in c["evidence"] if e["field"] == "after_care_end_time"), None)
        if c["need"] == "after_school_care" and ends and wanted.get("after_school_care"):
            hint += (f" Also call search_programs with near_school_id='{r['school_id']}', time_from='{ends}', "
                     f"time_to='{wanted['after_school_care']}' to look for a nearby program that covers the gap.")
        hints.append(hint)
    for need in required:
        if results and not any(c["need"] == need and c["status"] == N.CONFIRMED for r in results for c in r["criteria"]):
            hints.append(f"No result confirms the must-have '{N.CATALOG[need]['label']}'. Ask if it is a must, "
                         "or what they could relax.")
    return hints[:3], hinted_ids


def watch_out(result: dict) -> str | None:
    """One honest line about the downsides, built only from statuses and flags."""
    def reason(c: dict) -> str:
        if c["note"]:
            return c["note"]
        shown = N.plain_evidence(c["evidence"][:2])  # "Class size: large", not "class_size.tier is large"
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


GENERIC_NAME_WORDS = {"school", "schools", "academy", "elementary", "middle", "high", "charter", "preparatory",
                      "prep", "center", "k-8", "k8", "day", "christian", "montessori", "the", "of"}


def find_by_name(name: str, size: int = 3) -> list[dict]:
    """Schools whose name matches what the parent typed, tolerating typos and partial names.

    Loose matching uses only the distinctive words, so "Hogwarts Academy" doesn't match
    every school with "Academy" in its name.
    """
    core = " ".join(w for w in name.split() if w.lower().strip(".,") not in GENERIC_NAME_WORDS)
    if not core:
        return []
    hits = client().search(index=SCHOOLS_INDEX, body={
        "size": size,
        "_source": ["name", "city", "entity_type", "level_codes"],
        "query": {"bool": {
            "must": [{"match": {"name": {"query": core, "fuzziness": "AUTO", "operator": "and"}}}],
            "should": [{"match_phrase": {"name": {"query": name, "boost": 3}}}],
        }},
    })["hits"]["hits"]
    return [{"school_id": h["_id"], **h["_source"], "match_score": round(h["_score"], 2)} for h in hits]


CONTENT_INDEX = "content"


MIN_SIMILARITY = 0.35  # below this, a vector-only match is treated as "no guide entry"
# Words too common in school questions to count as a term match on their own
EVERYDAY_WORDS = {"school", "schools", "need", "needs", "mean", "means", "meaning", "work", "works", "kid", "kids",
                  "child", "son", "daughter", "class", "classes", "program", "programs", "good", "best", "high",
                  "what", "whats", "what's", "does", "do", "how", "why", "which", "who", "when", "where", "can",
                  "tell", "you", "me", "my", "i", "we", "our"}


def lookup_content(question: str, k: int = 3) -> list[dict]:
    """Relevant guide entries for a question about terms, ratings or the app.

    An entry is relevant if its title or an alias matches the question's words (exact terms
    like "CTE"), or its meaning is close enough by vector similarity (paraphrases and other
    languages). Unrelated questions return nothing, so the agent says it has no guide entry.
    With KNOWLEDGE_BASE_ID set, the entries come from the Bedrock Knowledge Base instead (decision 028).
    """
    if knowledge.enabled():
        return knowledge.lookup(question, k, frozenset(EVERYDAY_WORDS))
    fields = ["id", "kind", "title", "body", "source"]
    terms = " ".join(w for w in re.findall(r"[\w'-]+", question) if w.lower() not in EVERYDAY_WORDS)
    keyword = client().search(index=CONTENT_INDEX, body={
        "size": k, "_source": fields,
        "query": {"multi_match": {"query": terms, "fields": ["title^2", "aliases"]}},
    })["hits"]["hits"] if terms else []
    vector = client().search(index=CONTENT_INDEX, body={
        "size": 8, "_source": fields,
        "query": {"knn": {"vector": {"vector": embed(question), "k": 8}}},
    })["hits"]["hits"]

    merged: dict[str, dict] = {}
    for h in vector:
        # Lucene cosine scores are (1 + cos) / 2; convert back to cosine similarity
        merged[h["_id"]] = {**h["_source"], "similarity": round(2 * h["_score"] - 1, 3), "term_match": False}
    for h in keyword:
        merged.setdefault(h["_id"], {**h["_source"], "similarity": 0.0})["term_match"] = True
    relevant = [e for e in merged.values() if e["term_match"] or e["similarity"] >= MIN_SIMILARITY]
    relevant.sort(key=lambda e: e["similarity"] + (0.5 if e["term_match"] else 0), reverse=True)
    return relevant[:k]


def get_school(school_id: str) -> dict | None:
    try:
        doc = client().get(index=SCHOOLS_INDEX, id=school_id, _source_excludes=["profile_vector"])
    except Exception:
        return None
    return doc["_source"]
