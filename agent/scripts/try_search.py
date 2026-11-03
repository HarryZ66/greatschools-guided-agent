"""Run the search + verify pipeline without the LLM, for debugging rules."""
import json

from gs_agent import search

NEEDS = [
    {"need": "grade_level", "mode": "require", "value": ["e"]},
    {"need": "location", "mode": "require", "value": {"city": "Miami", "state": "FL", "radius_km": 40}},
    {"need": "stem", "mode": "prefer"},
    {"need": "small_classes", "mode": "prefer"},
    {"need": "safety", "mode": "prefer"},
    {"need": "after_school_care", "mode": "require", "value": "18:00"},
]

out = search.find(NEEDS, "STEM science and small classes")
print("candidates:", out["total_candidates"], "notes:", out["notes"])
print("summary:", json.dumps(out["summary"]))
for r in out["results"][:4]:
    print(f"#{r['rank']} {r['name']} ({r['city']}, {r['entity_type']}) score={r['score']}")
    for c in r["criteria"]:
        print("    ", c["need"], c["status"], "|", c["note"], "|", json.dumps(c["evidence"])[:110])
    print("     watch_out:", r["watch_out"])
