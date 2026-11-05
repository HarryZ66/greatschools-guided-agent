"""Which model answers a turn (decision 033).

Most turns run on the fast model (Claude Haiku 5.5). Code sends a turn to the strong model
(Claude Sonnet 5.5) when the parent's words touch a topic where a careless reply does real harm:
sorting schools by who the students are (fair housing, decision 007), or a child's disability.
The choice is made in code, before any model reads the turn, so it costs nothing and can't be
talked out of by the message itself. A turn the fast model fails is retried on the strong one
(agent.py). Setting MAIN_MODEL pins every turn to one model, which is how the evals compare models.
"""

import re

from .config import FAST_MODEL, MAIN_MODEL, STRONG_MODEL

NAMES = {
    "us.anthropic.claude-sonnet-5-5": "Claude Sonnet 5.5",
    "us.anthropic.claude-haiku-5-5": "Claude Haiku 5.5",
}


def name(model_id: str) -> str:
    return NAMES.get(model_id, model_id)


# English and Spanish words for race and ethnicity, national origin, religion, income and
# disability. Matching too much only costs a few cents; missing one risks a hurtful answer.
SENSITIVE = re.compile(
    r"\b("
    r"race|races|racial\w*|ethnic\w*|hispanics?|latin[oax]s?|african[- ]americans?|asians?|minorit\w+|divers\w+"
    r"|(black|white|brown)\s+(kids|students|families|people|children|neighborhoods?|areas?)"
    r"|immigra\w+|undocumented|nationalit\w+|foreigners?"
    r"|religio\w*|church\w*|mosques?|synagogues?|temples?|muslims?|jewish|jews|christians?|catholics?|hindus?"
    r"|income|low-income|poor|poverty|rich|wealthy|welfare"
    r"|disab\w+|adhd|autis\w+|ieps?|504|special\s+(ed|education|needs)|dyslexi\w+|down\s+syndrome|wheelchairs?|deaf|blind"
    r"|raza|étnic\w+|etnic\w+|hispanos?|latinos?|inmigra\w+|religi[oó]n\w*|iglesias?|ingresos|pobre\w*|ricos?"
    r"|discapacidad\w*|necesidades\s+especiales|autismo|tdah"
    r")\b",
    re.I,
)


def sensitive(text: str) -> bool:
    return bool(SENSITIVE.search(text or ""))


def choose(text: str, strong_already: bool = False) -> tuple[str, str | None]:
    """The model for this turn and why, as (model_id, reason). reason is None on the fast model.

    A conversation that has touched a sensitive topic stays on the strong model: its follow-up
    turns ("yes, the bus works") still carry that context, and the strong model's cache is warm.
    """
    if MAIN_MODEL:
        return MAIN_MODEL, None
    if strong_already:
        return STRONG_MODEL, "earlier in this conversation"
    if sensitive(text):
        return STRONG_MODEL, "sensitive topic"
    return FAST_MODEL, None
