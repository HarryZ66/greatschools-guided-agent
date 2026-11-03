"""Program search: library and community events that can fill what a school doesn't offer.

As with schools, fit (time window, distance, ages) and data problems are decided in code;
the model only chooses when to search and how to explain the results.
"""

from datetime import datetime

from . import needs as N
from .search import EVERYDAY_WORDS, client, embed, get_school, resolve_location

PROGRAMS_INDEX = "programs"
MIN_SIMILARITY = 0.3
WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _hhmm(iso_time: str) -> str:
    return iso_time[11:16]  # "2000-01-01T17:00:00-05:00" -> "17:00"


def _sessions(program: dict, limit: int = 3) -> list[dict]:
    upcoming = [i for i in program.get("instances", []) if i.get("status") in ("upcoming", "current")]
    upcoming.sort(key=lambda i: i["start_date"])
    return [{"date": i["start_date"], "day": WEEKDAY[datetime.fromisoformat(i["start_date"]).weekday()],
             "start": _hhmm(i["start_time"]), "end": _hhmm(i["end_time"])} for i in upcoming[:limit]]


def _weekdays(program: dict) -> list[str]:
    """Days the program meets, from its upcoming sessions (not just the next few)."""
    days = {datetime.fromisoformat(i["start_date"]).weekday() for i in program.get("instances", [])
            if i.get("status") in ("upcoming", "current")}
    return [WEEKDAY[d] for d in sorted(days)]


def _time_fit(sessions: list[dict], time_from: str | None, time_to: str | None) -> dict | None:
    if not (time_from and time_to) or not sessions:
        return None
    start, end = sessions[0]["start"], sessions[0]["end"]
    if start <= time_from and end >= time_to:
        return {"status": N.CONFIRMED, "note": f"Runs {start}-{end}, covering {time_from}-{time_to}."}
    if start < time_to and end > time_from:
        return {"status": N.PARTIAL, "note": f"Runs {start}-{end}; only part of {time_from}-{time_to}."}
    return {"status": N.ATTENTION, "note": f"Runs {start}-{end}, outside {time_from}-{time_to}."}


def _flags(program: dict) -> list[dict]:
    flags = []
    zipcode = str(program.get("zipcode", ""))
    if program.get("state") == "FL" and not zipcode.startswith(("32", "33", "34")):
        flags.append({"field": "zipcode", "value": zipcode,
                      "note": f"ZIP code {zipcode} isn't a Florida ZIP, so check the address."})
    for i in program.get("instances", [])[:5]:
        if _hhmm(i["end_time"]) < _hhmm(i["start_time"]):
            flags.append({"field": "instances.end_time", "value": _hhmm(i["end_time"]),
                          "note": "Listed end time is before the start time; check the schedule."})
            break
    return flags


def find_programs(interest: str = "", city: str = "", near_school_id: str = "", grades: list[str] | None = None,
                  time_from: str = "", time_to: str = "", size: int = 5) -> dict:
    """Programs with upcoming sessions near a city or a school, best match first."""
    school = get_school(near_school_id) if near_school_id else None
    if school and school.get("location"):
        center, radius, anchor = school["location"], 8, school["name"]
    else:
        center, radius, anchor = resolve_location({"city": city}) if city else None, 20, city
    if center is None:
        return {"programs": [], "excluded_past": [], "notes": {"location": f"No programs found near '{anchor or 'that place'}'."}}

    filters = [{"geo_distance": {"distance": f"{radius}km", "location": center}}]
    if grades:
        filters.append({"terms": {"level_code": list(grades)}})
    body = {"size": 40, "_source": {"excludes": ["vector"]}}
    keyword_ids: set[str] = set()
    if interest:
        # Relevant = the words appear in the name/description, or the meaning is close enough.
        # Short queries ("robotics") score low on vectors alone, so both signals count.
        terms = " ".join(w for w in interest.split() if w.lower() not in EVERYDAY_WORDS)
        if terms:
            keyword_ids = {h["_id"] for h in client().search(index=PROGRAMS_INDEX, body={
                **body, "_source": False,
                "query": {"bool": {"filter": filters,
                                   "must": {"multi_match": {"query": terms, "fields": ["name^3", "description"]}}}},
            })["hits"]["hits"]}
        query = {"knn": {"vector": {"vector": embed(interest), "k": 40, "filter": {"bool": {"filter": filters}}}}}
    else:
        query = {"bool": {"filter": filters}}
    hits = client().search(index=PROGRAMS_INDEX, body={**body, "query": query})["hits"]["hits"]

    programs, past_only, seen = [], [], set()
    for h in hits:
        p = h["_source"]
        # Lucene cosine scores are (1 + cos) / 2
        if interest and h["_id"] not in keyword_ids and 2 * h["_score"] - 1 < MIN_SIMILARITY:
            continue
        org = (p.get("organizations") or [{}])[0]
        key = (p["name"], org.get("name"))
        if key in seen:  # the same program listed twice
            continue
        seen.add(key)
        sessions = _sessions(p)
        if not sessions:  # only past sessions: never recommend as available
            past_only.append({"name": p["name"], "organization": org.get("name"), "city": p.get("city")})
            continue
        fit = _time_fit(sessions, time_from or None, time_to or None)
        programs.append({
            "program_id": h["_id"], "name": p["name"], "organization": org.get("name"), "city": p.get("city"),
            "distance_km": round(N.haversine_km(center, p["location"]), 1),
            "near": anchor, "meets_on": _weekdays(p), "next_sessions": sessions, "ages": p.get("age_display"),
            "cost": p.get("cost_display") or "Not listed", "registration_open": p.get("has_available_registration"),
            "tags": p.get("tag_names", []), "description": p.get("description", "")[:300],
            "url": org.get("home_page_url"), "time_fit": fit, "quality_flags": _flags(p),
            "match": h["_score"],
        })
    # Programs that cover the time window first, then by search match
    order = {N.CONFIRMED: 0, N.PARTIAL: 1, N.ATTENTION: 2, None: 1}
    programs.sort(key=lambda r: (order[(r["time_fit"] or {}).get("status")], -r["match"]))
    for r in programs:
        r.pop("match")
    return {"programs": programs[:size], "excluded_past": past_only[:5], "notes": {}}
