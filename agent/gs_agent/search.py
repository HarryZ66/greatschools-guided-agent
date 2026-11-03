"""OpenSearch retrieval plus code-side verification and ranking."""

import json
from collections import Counter
from functools import lru_cache

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


def find(needs: list[dict], semantic_query: str | None = None, size: int = 8) -> dict:
    """Search, verify every need for every candidate, and rank. Pure code apart from the embedding."""
    needs = [n for n in needs if n.get("need") in N.RULES]
    filters, notes = _filters(needs)

    if semantic_query:
        query = {"knn": {"profile_vector": {"vector": embed(semantic_query), "k": 50,
                                             "filter": {"bool": {"filter": filters}}}}}
    else:
        query = {"bool": {"filter": filters}}
    hits = client().search(index=SCHOOLS_INDEX, body={
        "size": 50, "query": query, "_source": {"excludes": SOURCE_EXCLUDES},
    })["hits"]["hits"]

    max_semantic = max((h["_score"] for h in hits), default=1.0) or 1.0
    results = []
    for hit in hits:
        school = hit["_source"]
        criteria = [N.verify(school, n) for n in needs]
        semantic = hit["_score"] / max_semantic if semantic_query else 0.0
        final = 0.85 * N.score(criteria) + 0.15 * semantic if semantic_query else N.score(criteria)
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
