"""Plain searches skip the model (decision 036).

A first message that is only a grade and a place we have schools in ("elementary schools in
Hialeah", "middle school near 33012"), optionally with public / charter / private, "free" or
"top", is a classic filter search. Code reads it, runs the same search and checks, and asks the
same "what matters most?" question the agent asks for a search this plain (prompt rule 4). Any
word it doesn't know sends the message to the model instead, so this only ever handles what it
fully understood. It's English only; other languages go to the model, which answers in kind.
"""

import re
from functools import lru_cache

from . import needs as N
from . import search

# Grade words -> level codes ("p", "e", "m", "h"), checked longest first
GRADES = [
    (r"pre-?k(?:indergarten)?|preschool", ["p"]),
    (r"k-?8", ["e", "m"]),
    (r"elementary|primary|grade school|kindergarten", ["e"]),
    (r"middle|junior high", ["m"]),
    (r"high", ["h"]),
]
ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)[ -]grad(?:e|er)s?\b")
TYPES = {"public": "public", "charter": "charter", "private": "private"}
TOP = re.compile(r"\b(top[- ]rated|top|best|highly[- ]rated|high[- ]performing)\b")
FREE = re.compile(r"\b(free|no tuition|tuition[- ]free)\b")
ZIP = re.compile(r"\b(\d{5})\b")
FILLER = set("""a an the school schools in near around close to by at for my our me i i'm im we want need
looking look find show please good nice any some options list of area zip code fl florida kid kids child
children son daughter grader""".split())

# Answers a plain search is most often missing (the agent's own list in prompt rule 4)
OPTIONS = ["Extra help with learning", "After-school care", "A school bus", "Counseling support"]
QUESTION = "What matters most for your child?"
WHY = "Each of these changes which schools fit, and we can check them for you."


@lru_cache(maxsize=1)
def _cities() -> dict[str, str]:
    """Cities we have schools in, lowercased -> (name, state). Read once per process."""
    return {city.lower(): (city, state) for state, cities in search.covered_cities().items() for city in cities}


def _level(grade: int) -> str:
    return "e" if grade <= 5 else "m" if grade <= 8 else "h"


def parse(text: str) -> list[dict] | None:
    """The needs in a plain search, or None if the message asks for anything else."""
    rest = " " + re.sub(r"[^\w\s'-]", " ", (text or "").lower()) + " "
    needs: list[dict] = []

    def take(pattern: str) -> str | None:
        nonlocal rest
        m = re.search(pattern, rest)
        if not m:
            return None
        rest = rest[:m.start()] + " " + rest[m.end():]
        return m.group(1) if m.groups() else m.group(0)

    # Place: a ZIP code, or a city we cover (longest names first, so "North Miami" beats "Miami")
    if (zipcode := take(ZIP.pattern)):
        location = {"zip": zipcode, "radius_km": 20}
    else:
        location = None
        for city in sorted(_cities(), key=len, reverse=True):
            if take(rf"\b{re.escape(city)}\b"):
                name, state = _cities()[city]
                location = {"city": name, "state": state, "radius_km": 20}
                break
    if location is None:
        return None

    # "top" / "high performing" first, so its "high" isn't read as high school
    top = bool(take(TOP.pattern))

    # Grade: words like "middle", or "6th grade" / "3rd grader"
    codes: list[str] = []
    while (n := take(ORDINAL.pattern)):
        codes.append(_level(int(n)))
    for pattern, level in GRADES:
        if take(rf"\b(?:{pattern})\b"):
            codes += level
    if not codes:
        return None
    needs.append({"need": "grade_level", "mode": "require", "value": sorted(set(codes), key="pemh".index)})
    needs.append({"need": "location", "mode": "require", "value": location})

    types = [TYPES[w] for w in TYPES if take(rf"\b{w}\b")]
    if types:
        needs.append({"need": "school_type", "mode": "require", "value": types})
    if take(FREE.pattern):
        needs.append({"need": "cost", "mode": "require", "value": None})

    if top:
        needs.append({"need": "high_performing", "mode": "prefer", "value": None})

    leftover = [w for w in rest.split() if w not in FILLER]
    return None if leftover else needs


def label(need: dict) -> str:
    """Chip text for a need this module parsed."""
    v = need.get("value")
    if need["need"] == "grade_level":
        return N.grades_text(v).capitalize() + " school"
    if need["need"] == "location":
        return f"Near {N.place(v)}"
    if need["need"] == "school_type":
        return " or ".join(TYPES[t].capitalize() for t in v)
    if need["need"] == "cost":
        return "Free"
    return N.CATALOG[need["need"]]["label"]


def message(needs: list[dict], found: dict) -> str:
    grade = next(n for n in needs if n["need"] == "grade_level")
    where = next(n for n in needs if n["need"] == "location")
    count = len(found["results"])
    return (f"Here {'are' if count != 1 else 'is'} {count} {N.grades_text(grade['value'])} school{'s' if count != 1 else ''} "
            f"near {N.place(where['value'])}, checked against our data.")
