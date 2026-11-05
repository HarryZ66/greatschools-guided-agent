"""Local partners who visit schools with parents (decision 041). Code only, no model call.

GreatSchools works with nonprofits and local partners who know the schools first-hand. This
closes the parent's journey: from a saved list to a visit, or a call, with someone local.
The partners in content/partners.json are made-up samples for the demo.
"""

import json
import uuid
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

PARTNERS_FILE = Path(__file__).parent / "content" / "partners.json"
WAYS = {"visit": "Visit schools with a guide", "call": "Talk with a guide first"}
TIMES = ("Weekday mornings", "Weekday afternoons", "Evenings", "Saturdays")
NOTE_LIMIT = 300


@lru_cache(maxsize=1)
def partners() -> dict[str, dict]:
    return {p["partner_id"]: p for p in json.loads(PARTNERS_FILE.read_text(encoding="utf-8"))["partners"]}


def for_schools(schools: list[dict]) -> list[dict]:
    """Partners who serve the cities of these schools, each with the schools it covers.

    `schools` are dicts with school_id, name and city. Partners covering more of them come first.
    """
    found = []
    for p in partners().values():
        covers = [{"school_id": s["school_id"], "name": s.get("name") or s["school_id"]}
                  for s in schools if s.get("city") in p["cities"]]
        if covers:
            found.append({**{k: p[k] for k in ("partner_id", "name", "kind", "what", "cities", "languages",
                                               "ways", "reply_days", "cost")},
                          "schools": covers, "sample": True})
    return sorted(found, key=lambda p: -len(p["schools"]))


def _business_days_from(start: date, days: int) -> date:
    d = start
    while days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


def build_request(partner_id: str, schools: list[dict], way: str, when: str, language: str,
                  note: str | None = None, today: date | None = None) -> dict:
    """Check a visit request against the partner and return the record to store.

    Raises ValueError with a message for the parent when something doesn't fit.
    """
    p = partners().get(partner_id)
    if p is None:
        raise ValueError("We don't know that partner.")
    covered = [s for s in schools if s.get("city") in p["cities"]]
    if not covered:
        raise ValueError(f"{p['name']} doesn't serve the schools you picked.")
    if way not in p["ways"]:
        raise ValueError(f"{p['name']} doesn't offer that.")
    if when not in TIMES:
        raise ValueError("Please pick when you're free.")
    if language not in p["languages"]:
        raise ValueError(f"{p['name']} works in {', '.join(p['languages'])}.")
    reply_by = _business_days_from(today or date.today(), p["reply_days"])
    return {"request_id": "v-" + uuid.uuid4().hex[:8], "partner_id": partner_id, "partner_name": p["name"],
            "way": way, "way_label": WAYS[way], "when": when, "language": language,
            "schools": [{"school_id": s["school_id"], "name": s.get("name") or s["school_id"]} for s in covered],
            "note": (note or "").strip()[:NOTE_LIMIT], "status": "sent", "reply_by": reply_by.isoformat(),
            "sample": True}
