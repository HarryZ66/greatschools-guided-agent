"""Glossary lookup for term and framework questions (P4).

The agent answers "what is CTE?" from this file instead of from memory, so answers can
be reviewed and replaced with GreatSchools' own content. See content/glossary.json.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

GLOSSARY_PATH = Path(__file__).parent / "content" / "glossary.json"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@lru_cache(maxsize=1)
def entries() -> list[dict]:
    return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))["terms"]


def titles() -> list[str]:
    return [t["title"] for t in entries()]


def lookup(term: str, limit: int = 2) -> list[dict]:
    """Best matches for a term: exact title or alias first, then partial word matches."""
    q = _norm(term)
    if not q:
        return []
    exact, partial = [], []
    for entry in entries():
        names = [_norm(entry["title"]), _norm(entry["id"])] + [_norm(a) for a in entry["aliases"]]
        if q in names:
            exact.append(entry)
        elif any(re.search(rf"\b{re.escape(n)}\b", q) or re.search(rf"\b{re.escape(q)}\b", n)
                 for n in names if len(n) > 2):
            partial.append(entry)
    return (exact + partial)[:limit]
