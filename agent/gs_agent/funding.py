"""Cost after typical aid, computed in code from content/funding.json (never by the model)."""

import json
from functools import lru_cache
from pathlib import Path

FUNDING_FILE = Path(__file__).parent / "content" / "funding.json"
STATE_AID = {"FL": "fl_fes_eo_ftc"}  # state -> scholarship that can pay private tuition


@lru_cache(maxsize=1)
def programs() -> dict[str, dict]:
    return {p["id"]: p for p in json.loads(FUNDING_FILE.read_text())["programs"]}


def cost_summary(school: dict) -> dict:
    """Tuition and an after-aid estimate for one school.

    Public and charter schools are tuition-free. For a private school with listed tuition, the
    estimate subtracts the state scholarship's typical award (an average, not a promise).
    """
    if school.get("entity_type") in ("public", "charter"):
        return {"tuition": 0}
    tuition = school.get("tuition")
    if tuition is None:
        return {"tuition": None}
    aid_id = STATE_AID.get(school.get("state", ""))
    aid = programs().get(aid_id) if aid_id else None
    if not aid or not aid.get("typical_amount"):
        return {"tuition": tuition}
    return {"tuition": tuition, "after_aid_estimate": max(tuition - aid["typical_amount"], 0), "aid": [aid_id],
            "aid_typical_amount": aid["typical_amount"], "aid_as_of": aid["as_of"]}
