"""The family profile: what we still need to learn about this child (decision 041).

Parents don't know what to ask (pain point #2), so the agent keeps asking, one question per turn,
until each topic below is known. Code tracks which topics are covered (a need from the topic is
set, or the parent answered a question about it) and which were already asked, and tells the
model which ones are left. When a turn has no model (a chip edit, a save), code asks the next
topic's question in the words below.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    id: str
    label: str  # shown on the profile meter
    needs: frozenset[str]  # a need from this set covers the topic
    question: str
    why: str
    options: tuple[str, ...]


TOPICS = (
    Topic("learning", "How your child learns", frozenset({"special_ed", "ell_support", "gifted"}),
          "Does your child need any of these at school?",
          "Schools differ a lot in the extra help they offer, and it's easy to check.",
          ("Extra help with learning", "Help learning English", "A program for advanced learners", "None of these")),
    Topic("schedule", "Getting there and pickup", frozenset({"after_school_care", "transportation"}),
          "How will your child get to and from school?",
          "Bus routes and after-school care rule some schools in or out.",
          ("A school bus", "Care after school", "We can drive both ways")),
    Topic("wellbeing", "Feeling safe and supported", frozenset({"safety", "mental_health"}),
          "What matters most for how your child feels at school?",
          "Many parents now ask about safety and counseling, and reviews tell us a lot.",
          ("A safe school with little bullying", "Counseling support", "Both matter", "Neither is a worry")),
    Topic("academics", "Classes and learning", frozenset({"high_performing", "small_classes", "college_prep"}),
          "What kind of classes do you want for your child?",
          "This changes which schools rank first.",
          ("Strong test scores", "Small classes", "Getting ready for college", "No preference")),
    Topic("interests", "What your child enjoys", frozenset({"stem", "arts", "sports"}),
          "What does your child love doing?",
          "A school with programs they enjoy helps them want to go.",
          ("Science and building things", "Art or music", "Sports", "Something else")),
    Topic("budget", "Budget and school type", frozenset({"cost", "school_type"}),
          "Should we look at private schools too?",
          "Florida scholarships can pay a large part of private tuition.",
          ("Free public schools only", "Private, if a scholarship helps", "Private is fine")),
)
BY_ID = {t.id: t for t in TOPICS}


def covered(needs: list[dict], answered: set[str]) -> set[str]:
    """Topics we know about: one of their needs is set, or the parent answered a question on it."""
    have = {n["need"] for n in needs}
    return {t.id for t in TOPICS if t.needs & have} | (answered & set(BY_ID))


def remaining(needs: list[dict], answered: set[str], asked: set[str]) -> list[Topic]:
    """Topics still worth a question, in order: not covered and not asked yet."""
    done = covered(needs, answered)
    return [t for t in TOPICS if t.id not in done and t.id not in asked]


def meter(needs: list[dict], answered: set[str]) -> dict:
    """The profile meter on the chips: each topic and whether we know it."""
    done = covered(needs, answered)
    return {"topics": [{"id": t.id, "label": t.label, "done": t.id in done} for t in TOPICS],
            "done": len(done), "total": len(TOPICS)}


def prompt_note(needs: list[dict], answered: set[str], asked: set[str]) -> str:
    """The line code adds to each model turn, so the model keeps building the profile."""
    left = remaining(needs, answered, asked)
    if not left:
        return ("(Family profile: complete. Ask a question only if a choice really depends on it. If the "
                "parent has schools saved or just compared two, set offer_visit to true.)")
    names = ", ".join(f"{t.id} ({t.label.lower()})" for t in left)
    return (f"(Family profile: still unknown: {names}. Unless the parent's message needs a different "
            f"question, end with ONE question about the first of these that fits this family, with 2-4 "
            f"options, and set question.topic to its id.)")
