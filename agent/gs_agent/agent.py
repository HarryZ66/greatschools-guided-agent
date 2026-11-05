"""The guided agent: one Strands agent per parent session.

The model decides which tools to call, which needs the parent has, whether to ask a
question and how to explain. Statuses, evidence, ranking and the result cards come from
code (needs.py, search.py). See docs/contract.md for the block format.
"""

import copy
import json
import logging
import re
import time
import uuid
from functools import lru_cache
from typing import Any, Callable, Literal

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel, CacheConfig

from . import family
from . import fastpath
from . import gateway_client as G
from . import knowledge
from . import needs as N
from . import partners
from . import programs as P
from . import routing
from . import search
from . import turn_cache
from .config import REGION

log = logging.getLogger("gs_agent.agent")

Mode = Literal["require", "prefer", "avoid"]
MAX_TOOL_CALLS = 6  # per turn (docs/contract.md, section 5)

# Needs whose value is a time or an amount the parent gave. On an answer turn the model may only
# change it when the answer itself gives a new one ("Pickup at 5 works"); picking "The library club
# works" still means the parent needs care until 6, so the 6pm stays and the program covers the gap.
KEEP_VALUE_NEEDS = ("after_school_care", "cost")
_NEW_VALUE = re.compile(r"\d|\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon|"
                        r"dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|doce|mediod[ií]a)\b", re.I)


def keep_stated_values(previous: list[dict], new: list[dict], answer: str | None) -> set[str]:
    """Restore times and budgets the parent stated when an answer doesn't give a new one.

    Changes `new` in place and returns the need ids whose value was restored. Only applies on
    answer turns (`answer` is the parent's answer text); a new query may change anything.
    """
    if answer is None or _NEW_VALUE.search(answer):
        return set()
    before = {n["need"]: n.get("value") for n in previous}
    kept = set()
    for n in new:
        old = before.get(n["need"])
        if n["need"] in KEEP_VALUE_NEEDS and old is not None and n.get("value") != old:
            n["value"] = old
            kept.add(n["need"])
    return kept


# ---------------------------------------------------------------- structured decision

class ChipLabel(BaseModel):
    need: str = Field(description="Need id from the catalog")
    label: str = Field(description="Short plain-language chip text, e.g. 'Care until 6pm'")
    source: Literal["stated", "inferred", "answered"] = Field(
        description="stated: parent said it; inferred: you assumed it; answered: from your question")
    mode: Mode = Field(default="prefer", description="require, prefer or avoid")
    value: Any = Field(default=None, description="Value in the catalog's format, if the need has one")


class Question(BaseModel):
    text: str = Field(description="One short question in plain language")
    why: str = Field(description="One short sentence: why the answer changes the results")
    # Code gives each option its id, so the model only writes the words (decision 035)
    options: list[str] = Field(description="2-4 short tappable answers")
    topic: str | None = Field(default=None, description=(
        "Id of the family profile topic this question is about, from the profile note; null for other questions"))


class Callout(BaseModel):
    school_id: str = Field(description="A school_id from the latest find_schools results")
    text: str = Field(description="'I checked this for you: ...' explaining one stale, missing or conflicting fact")


class Suggestion(BaseModel):
    need: str = Field(description="Catalog need id the parent did not mention")
    label: str = Field(description="Short chip text, e.g. 'School bus'")
    why: str = Field(description="One short reason tied to what the parent said, e.g. 'You work until 6pm'")


class Decision(BaseModel):
    chips: list[ChipLabel] = Field(description="Every need you know so far, searched or not")
    unmapped: list[str] = Field(default_factory=list, description=(
        "Wishes the parent stated that no catalog need can check, in their own words (e.g. 'Montessori', "
        "'near my church'). Empty if none."))
    suggestions: list[Suggestion] = Field(default_factory=list, description=(
        "0-2 needs the parent didn't mention but likely cares about, given what they said. Empty if none."))
    question: Question | None = Field(default=None, description="At most one question, or null")
    message: str = Field(description="1-2 short plain sentences for the parent, most important first. No jargon. "
                                     "Don't restate the cards. If you ask a question, don't repeat it here.")
    callouts: list[Callout] = Field(default_factory=list, description="0-2 honest notes about the data")
    sources: list[str] = Field(default_factory=list,
                               description="ids of guide entries from lookup_content that your message relies on")
    offer_visit: bool = Field(default=False, description=(
        "true when the parent asks about visiting or touring schools, talking to someone local, or says "
        "they're ready to decide. The app then offers a visit with a local partner."))


SYSTEM_PROMPT = """You are GreatSchools' guided school-search agent. Motto: "We investigate. You decide."
You help parents, many of whom don't know education jargon, find schools that fit their family.

How you work:
1. Turn what the parent says into needs from the catalog below, each with a mode:
   require (must have), prefer (nice to have) or avoid. grade_level and location are always required.
   Infer needs from plain words ("my 6th grader" -> grade_level ["m"]; "I work until 6" -> after_school_care "18:00").
   If the parent gives only a ZIP code for where they live, put it in location as "zip" and leave out
   city: never guess the city from a ZIP. Code finds the area from our own data.
2. If grade level or location is unknown, don't search: ask for it, and still return chips for the
   needs you already know. If find_schools says a city isn't in our data, describe where we do have
   schools from its cities_with_data list (name the areas with the most schools), never from memory.
3. Otherwise call find_schools with ALL current needs (it replaces the previous search). Pass a short
   semantic_query describing the softer wishes in the parent's words.
4. Read the summary counts and question_hints. If question_hints is not empty, ask ONE question about
   the most important hint, naming the school and the trade-off, e.g. "Tamarind Cove has the STEM
   program you want, but care ends at 5pm. Could someone pick him up at 5, or do you need 6?".
   Otherwise ask only if the answer would clearly change the ranking (e.g. cost: free vs private).
   If private schools fall short only on cost and a result's cost has an after_aid_estimate, the
   question may offer to include schools a Florida scholarship could help pay for. Always call that
   figure an estimate, based on a typical award; for details, lookup_content has the guide entries.
   If a program you found could cover the gap, still ask: name the school and the program, and let
   the parent choose (e.g. "Tamarind Cove's care ends at 5pm. Would the library robotics club from
   5 to 6:30 work, or do you need care at the school until 6?"). Only the parent can decide that.
   If they pick the program, keep their time (after_school_care stays "18:00") and only change the
   mode to prefer. Change a time or budget only when the parent gives a new one.
   Help the parent find what matters: if they gave little beyond grade and location (e.g. "a good
   elementary school in Miami") and there are no question_hints, still search, then ask ONE question
   about what their child needs, because parents often don't know these can be checked. Offer the
   3-4 options most likely for this family from: extra help with learning, after-school care,
   a school bus, counseling support, strong academics, small classes. If grade or location is
   missing, ask for that first (rule 2) and offer 1-2 of these as suggestions instead.
5. When the parent asks about one school, use get_school_profile with its school_id. If the school
   isn't in your latest results, first call find_school_by_name, then get_school_profile. If several
   schools match, say which one you checked. If none match, say the school isn't in our data.
6. Use search_programs when the parent wants clubs, tutoring, classes or help outside school hours,
   or when a good school leaves a time gap (a question_hint will say so): search near that school
   with time_from/time_to set to the gap. Mention only programs the tool returned, say they're run by
   a library or community center (not the school), and note if registration is needed. Programs with
   only past sessions are excluded; say so if the parent asks about one. Classes for the parent or the
   whole family (English classes, computer classes) are programs too: call search_programs with the
   city right away, without asking for a child's grade.
7. When the parent asks what a term means, how ratings work, how school choice works, or what the
   app's labels mean, call lookup_content and explain using only what it returns, in plain words,
   and list the entry ids in sources. If it returns nothing, say you don't have a guide entry for
   that yet and suggest asking the school or district; don't explain it from memory.
8. Spot gaps. If the parent wants something the catalog can't check, put it in unmapped and say
   plainly that we can't check it yet. Suggest at most 2 needs they didn't mention but probably care
   about (a parent who works until 6pm may need a bus). GreatSchools says counseling and mental
   health support is now a top concern that parents rarely ask about: unless the parent already
   mentioned it, mental_health is a good suggestion, with a why like "Many parents now ask about
   counseling support." Never search with a suggested need until they add it.
9. Keep building the family profile: parents don't know what to ask, so asking is how you help.
   Each turn ends with a note from code listing the profile topics still unknown. Once schools are
   shown, every reply ends with ONE question, with 2-4 tappable options: a trade-off from
   question_hints first, otherwise the first unknown topic, in words that fit this family (set
   question.topic to its id). After a comparison, ask about what would settle the choice between
   the two schools. Only skip the question when the profile is complete and nothing is left to decide.
   Topics are filled by asking, never by assuming: don't add a need the parent didn't state just
   because its topic is unknown (offer it as an option or a suggestion instead).
10. Visiting schools: GreatSchools works with local partners (nonprofits and parent guides) who
   visit schools with families or talk a list through with them, for free. When the parent asks
   about visiting, touring, seeing a school in person or talking to someone local, or says they're
   ready to decide, set offer_visit to true and say in one sentence that a local partner can help.
   Don't name partners or promise times; the app shows who serves their schools.
You have at most {max_tools} tool calls per turn.

Honesty rules:
- Never claim a school meets a need unless find_schools says confirmed. Never invent facts, numbers or quotes.
- When data is missing or old, say so plainly and suggest asking the school.
- Don't list the schools in your message; the app shows cards built from the tool results.
- Write at a 6th-grade reading level. Answer in the parent's language.

Plain words (many parents don't know school terms; this is a core goal of the app):
- Chip labels, suggestions, questions, why text and answer options use everyday words only. No
  acronyms or school-system terms: say "extra help with learning", not "IEP", "504" or "special ed";
  "help learning English", not "ELL"; "a state scholarship", not "FES-EO" or "ESA".
- In messages, use the everyday words too. Use a term only if the parent used it or asked about it,
  and then explain it in the same sentence ("a written plan for extra help, called an IEP").
- Say distances in miles, as the data notes do, and ratings as "4 out of 10".

Fairness rule (fair housing):
- Never filter, rank or recommend schools or neighborhoods by the race, ethnicity, national origin,
  religion, disability or income of the students or residents, even if asked, and even if the data
  had it. Don't point the parent to other sources for that either.
- Say so in one kind sentence, without lecturing, then offer to search by what their child needs
  (programs, safety reviews, class size, ratings, support for English learners or special needs).
- Subgroup ratings (e.g. how a school does for low-income or English-learner students) may be
  shared when a parent asks how well a school serves a group their own child belongs to.
- A parent describing their own family ("we're low-income", "my son is learning English") is telling
  you what their child needs, not asking you to sort by who the students are. Just help; don't say
  what you can't filter by.

Need catalog (id: value format):
{catalog}
"""


def _catalog_text() -> str:
    return "\n".join(f"- {k}: value = {v['value']}" for k, v in N.CATALOG.items())


@lru_cache(maxsize=8)
def bedrock_model(model_id: str) -> BedrockModel:
    """One client per model, shared by every session: it holds settings, not conversation state."""
    # Claude 5.x models on Bedrock reject `temperature`, so it's left at the default.
    # Prompt caching: the system prompt, tool specs and earlier turns repeat on every call.
    return BedrockModel(model_id=model_id, boto_session=boto3.Session(region_name=REGION),
                        max_tokens=4000, cache_config=CacheConfig(strategy="auto"))


# ---------------------------------------------------------------- session

class GuidedSession:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.needs: list[dict] = []
        self.semantic_query: str | None = None
        self.last: dict | None = None
        self.saved: set[str] = set()
        self.pending_question: dict | None = None
        self.comparison: dict | None = None
        self.chip_labels: dict[str, ChipLabel] = {}  # the agent's wording, kept across chip edits
        self.seen_ids: set[str] = set()  # every school a tool returned; evals check the model stays inside it
        self.seen_content: dict[str, str] = {}  # guide entry id -> title, for sources the model may cite
        self.seen_documents: dict[str, str] = {}  # guide entry id -> knowledge base document it came from
        self.last_programs: dict | None = None
        self.programs_fresh = False  # show program cards only on the turn they were searched
        self.seen_programs: set[str] = set()
        self.usage = {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0,
                      "model_calls": 0}
        self.usage_by_model: dict[str, dict[str, int]] = {}  # the same counts per model id, for cost
        self._strong = False  # this conversation touched a sensitive topic, so it stays on the strong model
        self._usage_agent, self._usage_seen = None, {}
        self.unmapped: list[str] = []
        self.suggestions: list[dict] = []
        self.asked_topics: set[str] = set()  # family profile topics we asked about (family.py)
        self.answered_topics: set[str] = set()  # ... and the ones the parent answered
        self.visit_offered = False  # the visit offer appears on its own once; asking or comparing brings it back
        self.on_progress: Callable[[str], None] | None = None  # set by the streaming endpoint
        self._tool_calls = 0
        self.searched_this_turn = False  # find_schools ran during the current turn
        self._needs_recap_pending = False  # the conversation restarted after a failed turn
        self._answer_text: str | None = None  # the parent's answer, on an answer turn
        self._kept_values: set[str] = set()  # needs whose stated value keep_stated_values restored this turn
        self._trace: list[dict] = []  # what really ran this turn, recorded by code (contract: `trace`)
        self._turn_started = 0.0
        self.agent = self._new_agent()

    def progress(self, text: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(text)
            except Exception:
                log.exception("progress callback failed")

    def _step(self, tool: str, service: str, text: str, started: float | None = None) -> None:
        """Record one step of this turn. Written by code from what actually ran, never by the model."""
        step = {"tool": tool, "service": service, "text": text}
        if started is not None:
            step["ms"] = round((time.perf_counter() - started) * 1000)
        self._trace.append(step)

    def _trace_search(self, needs: list[dict], started: float, kept: set[str]) -> None:
        """Steps for one school search: OpenSearch retrieval, then the code checks on the results."""
        r = self.last or {}
        results, total = r.get("results", []), r.get("total_candidates", 0)
        vector = bool(self.semantic_query)
        self._step("find_schools", "Amazon OpenSearch" + (" + Titan Embeddings" if vector else ""),
                   (f"Found {total} candidate schools for your grade and area, scored by your "
                    f"{len(needs)} needs" + (" and your own words (vector match)" if vector else ""))
                   if total else "No schools in our data for that grade and area", started)
        if not results:
            return
        counts: dict[str, int] = {}
        for res in results:
            for c in res["criteria"]:
                counts[c["status"]] = counts.get(c["status"], 0) + 1
        words = {N.CONFIRMED: "confirmed", N.PARTIAL: "partial", N.ATTENTION: "need attention", N.MISSING: "missing"}
        tally = ", ".join(f"{counts[k]} {w}" for k, w in words.items() if counts.get(k))
        flagged = sum(1 for res in results if res["quality_flags"])
        self._step("verify", "Code (no model)",
                   f"Checked {len(needs)} needs on the top {len(results)} schools against the data: {tally}"
                   + (f". Flagged data problems at {flagged} school{'s' if flagged != 1 else ''} and ranked "
                      f"{'them' if flagged != 1 else 'it'} lower" if flagged else ""))
        hints = r.get("question_hints") or []
        if hints:
            self._step("trade_offs", "Code (no model)",
                       f"Spotted {len(hints)} trade-off{'s' if len(hints) != 1 else ''} worth asking you about")
        if kept:
            names = ", ".join(N.CATALOG[k]["label"].lower() for k in sorted(kept))
            self._step("keep_values", "Code (no model)", f"Kept the time or budget you gave for {names}")

    def _over_budget(self) -> str | None:
        self._tool_calls += 1
        if self._tool_calls > MAX_TOOL_CALLS:
            return json.dumps({"error": f"Tool limit of {MAX_TOOL_CALLS} per turn reached. "
                                        "Answer now with what you already have."})
        return None

    def _new_agent(self, messages: list | None = None, model_id: str | None = None) -> Agent:
        return Agent(
            # The model is set again at the start of each turn (routing.choose)
            model=bedrock_model(model_id or routing.MAIN_MODEL or routing.FAST_MODEL),
            tools=self._tools(),
            system_prompt=SYSTEM_PROMPT.format(catalog=_catalog_text(), max_tools=MAX_TOOL_CALLS),
            conversation_manager=SlidingWindowConversationManager(window_size=60),
            messages=messages,
            callback_handler=None,
        )

    # Tools are closures so each session keeps its own last search.
    def _tools(self) -> list:
        session = self

        def service(backend: str) -> str:
            # Data lookups go through the AgentCore Gateway's MCP tools when it is configured (decision 027)
            return f"{G.SERVICE} → {backend}" if G.enabled() else backend

        def lookup(tool_name: str, args: dict, backend: str, started: float):
            """Run a data tool; on a Gateway failure, record it and return None."""
            try:
                return G.call(tool_name, args)
            except G.GatewayError:
                session._step(tool_name, service(backend), "The lookup failed, so I didn't use it", started)
                return None

        @tool
        def find_schools(needs: list[dict], semantic_query: str = "") -> str:
            """Search schools and check every need against the data.

            Args:
                needs: All current needs, each {"need": <catalog id>, "mode": "require"|"prefer"|"avoid", "value": ...}.
                semantic_query: Short description of softer wishes, in the parent's words.
            """
            if (stop := session._over_budget()):
                session._step("find_schools", "Agent", "Stopped: tool limit for this turn reached")
                return stop
            started = time.perf_counter()
            clean = copy.deepcopy([n for n in needs if isinstance(n, dict) and n.get("need") in N.RULES])
            kept = keep_stated_values(session.needs, clean, session._answer_text)
            if kept:
                log.info("session %s: kept the parent's stated value for %s", session.session_id, sorted(kept))
            session._kept_values |= kept
            session.semantic_query = semantic_query or None
            session.progress(f"Searching schools and checking {len(clean)} of your needs…")
            # find() adds the resolved location center to the needs; keep it for compare and edits
            session.last = search.find(clean, session.semantic_query)
            session.needs = clean
            session.searched_this_turn = True
            session.seen_ids.update(r["school_id"] for r in session.last["results"])
            session.progress(f"Checked {session.last['total_candidates']} schools; "
                             f"ranking the top {len(session.last['results'])}.")
            session._trace_search(clean, started, kept)
            return json.dumps(_compact(session.last))

        @tool
        def get_school_profile(school_id: str) -> str:
            """Full data for one school, for questions about a specific school.

            Args:
                school_id: e.g. "fl-95390"
            """
            if (stop := session._over_budget()):
                session._step("get_school_profile", "Agent", "Stopped: tool limit for this turn reached")
                return stop
            started = time.perf_counter()
            school = lookup("get_school", {"school_id": school_id}, "Amazon OpenSearch", started)
            if school is None:
                session._step("get_school_profile", service("Amazon OpenSearch"), f"No school with id {school_id}", started)
                return json.dumps({"error": f"No school with id {school_id}"})
            session.progress(f"Reading the profile for {school.get('name', school_id)}…")
            session.seen_ids.add(school_id)
            criteria = [N.verify(school, n) for n in copy.deepcopy(session.needs)]
            session._step("get_school_profile", service("Amazon OpenSearch"),
                          f"Read the profile for {school.get('name', school_id)} and checked "
                          f"{len(criteria)} of your needs against its data", started)
            keep = {k: v for k, v in school.items() if k not in ("reviews_full", "reviews_text", "profile_text")}
            return json.dumps({"school": keep, "criteria": criteria, "quality_flags": N.quality_flags(school)})[:12000]

        @tool
        def find_school_by_name(name: str) -> str:
            """Look up schools by name, for when the parent names a school that may not be in the results.

            Args:
                name: The school name as the parent wrote it, e.g. "Lanternfish K-8".
            """
            if (stop := session._over_budget()):
                session._step("find_school_by_name", "Agent", "Stopped: tool limit for this turn reached")
                return stop
            started = time.perf_counter()
            session.progress(f"Looking up '{name}'…")
            matches = lookup("find_school_by_name", {"name": name}, "Amazon OpenSearch", started)
            if matches is None:
                return json.dumps({"matches": [], "note": "The lookup failed; ask the parent to try again."})
            session._step("find_school_by_name", service("Amazon OpenSearch"),
                          f"Looked up '{name}': {len(matches)} school{'s' if len(matches) != 1 else ''} with that name"
                          if matches else f"Looked up '{name}': no school with that name in our data", started)
            session.seen_ids.update(m["school_id"] for m in matches)
            if not matches:
                return json.dumps({"matches": [], "note": f"No school named like '{name}' in our data."})
            return json.dumps({"matches": matches,
                               "next": "Call get_school_profile with the best match's school_id."})

        @tool
        def lookup_content(question: str) -> str:
            """Look up GreatSchools guide entries: terms (charter, IEP, CTE...), how ratings work,
            how school choice works, and what the app's labels mean.

            Args:
                question: The parent's question, in their words.
            """
            if (stop := session._over_budget()):
                session._step("lookup_content", "Agent", "Stopped: tool limit for this turn reached")
                return stop
            started = time.perf_counter()
            session.progress("Checking the parent guide…")
            # The guide is a Bedrock Knowledge Base when KNOWLEDGE_BASE_ID is set (decision 028)
            backend = knowledge.SERVICE if knowledge.enabled() else "Amazon OpenSearch + Titan Embeddings"
            entries = lookup("lookup_guide", {"question": question}, backend, started)
            if entries is None:
                return json.dumps({"entries": [], "note": "The guide lookup failed; don't answer from memory."})

            def named(e: dict) -> str:
                return f"{e['title']} ({e['document']})" if e.get("document") else e["title"]

            session._step("lookup_content", service(backend),
                          "Searched the parent guide: " + (", ".join(named(e) for e in entries) if entries
                                                           else "no entry covers this, so I won't answer from memory"),
                          started)
            session.seen_content.update({e["id"]: e["title"] for e in entries})
            session.seen_documents.update({e["id"]: e["document"] for e in entries if e.get("document")})
            if not entries:
                return json.dumps({"entries": [], "note": "No guide entry covers this."})
            return json.dumps({"entries": [{k: e[k] for k in ("id", "title", "body", "source", "document") if k in e}
                                           for e in entries]})

        @tool
        def search_programs(interest: str, city: str = "", near_school_id: str = "", grades: list[str] | None = None,
                            time_from: str = "", time_to: str = "") -> str:
            """Find library and community programs (clubs, tutoring, after-school help, classes) with
            upcoming sessions, near a city or near one school.

            Args:
                interest: What the parent wants, e.g. "robotics club" or "after-school homework help".
                city: City to search around, if not searching near a school.
                near_school_id: A school_id from find_schools, to look within about 8 km of that school.
                grades: Level codes to match, e.g. ["m"].
                time_from: Start of a time gap to cover, "HH:MM" 24h (e.g. care ends "17:00").
                time_to: End of the gap, "HH:MM" (e.g. parent needs "18:00").
            """
            if (stop := session._over_budget()):
                session._step("search_programs", "Agent", "Stopped: tool limit for this turn reached")
                return stop
            started = time.perf_counter()
            session.progress(f"Looking for nearby programs: {interest}…")
            found = lookup("search_programs", {"interest": interest, "city": city, "near_school_id": near_school_id,
                                               "grades": grades, "time_from": time_from, "time_to": time_to},
                           "Amazon OpenSearch + Titan Embeddings", started)
            if found is None:
                return json.dumps({"programs": [], "note": "The program search failed."})
            n, past = len(found["programs"]), found["excluded_past"]
            where = "near the school" if near_school_id else f"in {city}" if city else "nearby"
            gap = f", covering {time_from}–{time_to}" if time_from and time_to else ""
            session._step("search_programs", service("Amazon OpenSearch + Titan Embeddings"),
                          f"Searched programs for '{interest}' {where}{gap}: {n} with upcoming sessions"
                          + (f"; skipped {len(past)} with only past sessions" if past else ""), started)
            session.last_programs, session.programs_fresh = found, True
            session.seen_programs.update(p["program_id"] for p in found["programs"])
            return json.dumps({
                "programs": [{k: p[k] for k in ("program_id", "name", "organization", "city", "distance_km", "distance_miles", "near",
                                                "meets_on", "next_sessions", "ages", "cost", "registration_open", "time_fit",
                                                "quality_flags")} for p in found["programs"]],
                "excluded_past": found["excluded_past"], "notes": found["notes"],
            })

        return [find_schools, get_school_profile, find_school_by_name, lookup_content, search_programs]

    # ---------------------------------------------------------------- turns

    def handle(self, event: dict) -> dict:
        self._answer_text, self._kept_values = None, set()
        self._trace, self._turn_started = [], time.perf_counter()
        response = self._handle(event)
        response["trace"] = {"steps": self._trace,
                             "elapsed_ms": round((time.perf_counter() - self._turn_started) * 1000)}
        return response

    def _handle(self, event: dict) -> dict:
        kind = event.get("type")
        if kind == "query":
            text = event["text"]
            first = not self.needs and not self.agent.messages
            if first and (response := self._fast_turn(text)):
                return response
            if first and (cached := turn_cache.get(text)):
                return self._replay(cached)
            response = self._agent_turn(text)
            if first and not response.get("fallback") and not any(st["tool"] == "escalate" for st in self._trace):
                turn_cache.put(text, {"state": self.snapshot(), "response": response, "steps": list(self._trace)})
            return response
        if kind == "answer":
            label = event.get("text") or self._option_label(event.get("option_id"))
            question = (self.pending_question or {}).get("text", "")
            self._answer_text = label
            if topic := (self.pending_question or {}).get("topic"):
                self.answered_topics.add(topic)
            return self._agent_turn(f'(Answer to your question "{question}"): {label}')
        if kind == "compare":
            self.comparison = self._comparison(event.get("school_ids", [])[:2])
            if self.comparison is None:
                raise ValueError("Both school ids must exist")
            names = " and ".join(self.comparison["names"])
            self._step("compare", "Code (no model)",
                       f"Built the side-by-side table for {names} from the same checks as the cards")
            return self._agent_turn(
                f"Compare {names} for my needs. Here is the side-by-side check (already shown to me as a table): "
                f"{json.dumps(self.comparison['rows'])}. Don't call tools. In the message, say in 1-2 sentences "
                "what the real difference is for my family. Then ask ONE question whose answer would settle the "
                "choice between them (or about the next unknown profile topic), with 2-4 options.")
        if kind == "chip_edit":
            return self._chip_edit(event)
        if kind == "new_search":
            return self._new_search()
        raise ValueError(f"Unknown event type: {kind}")

    def _fast_turn(self, text: str) -> dict | None:
        """A plain grade-and-place search, answered in code without the model (decision 036).

        Returns None to hand the message to the model: when it asks for anything else, when we
        have no schools there (the model explains where we do), or when code spots a trade-off
        (the model words that question best).
        """
        try:
            needs = fastpath.parse(text)
        except Exception:
            log.exception("fast path parse failed; using the model")
            return None
        if not needs:
            return None
        started = time.perf_counter()
        clean = copy.deepcopy(needs)
        found = search.find(clean, None)
        if not found["results"] or found["question_hints"]:
            return None
        self.needs, self.last, self.semantic_query = clean, found, None
        self.searched_this_turn = True
        self.seen_ids.update(r["school_id"] for r in found["results"])
        self._step("fast_path", "Code (no model)",
                   "Your search was a plain grade and place, so I ran it without calling the AI model")
        self._trace_search(clean, started, set())
        self.chip_labels = {n["need"]: ChipLabel(need=n["need"], label=fastpath.label(n), source="stated",
                                                 mode=n["mode"], value=n.get("value")) for n in needs}
        decision = Decision(chips=list(self.chip_labels.values()), message=fastpath.message(needs, found),
                            question=Question(text=fastpath.QUESTION, why=fastpath.WHY, options=fastpath.OPTIONS))
        response = self._blocks(decision)
        # The next turn goes to the model: give it what happened here, like a chip edit does
        self.agent.messages.append({"role": "user", "content": [{"text": text}]})
        self.agent.messages.append({"role": "assistant", "content": [
            {"text": f"{decision.message} {fastpath.QUESTION} (Options: {', '.join(fastpath.OPTIONS)})"}]})
        self._needs_recap_pending = True
        return response

    def _replay(self, cached: dict) -> dict:
        """Answer with another parent's identical first turn from today (decision 036)."""
        self.restore(cached["state"])
        self._step("cache", "Amazon DynamoDB",
                   "Another parent asked exactly this today, so I reused that checked answer without calling "
                   "the AI model. The steps below ran for that answer")
        self._trace += cached.get("steps", [])
        response = copy.deepcopy(cached["response"])
        response["session_id"] = self.session_id
        for block in response["blocks"]:
            if block["type"] == "school_results":
                for r in block["results"]:
                    r["saved"] = r["school_id"] in self.saved
        response.pop("trace", None)
        return response

    # ---------------------------------------------------------------- saving and restoring

    _STATE = ("needs", "semantic_query", "last", "pending_question", "seen_content", "seen_documents",
              "last_programs", "unmapped", "suggestions", "_strong", "_needs_recap_pending", "visit_offered")
    _SETS = ("seen_ids", "seen_programs", "asked_topics", "answered_topics")

    def snapshot(self) -> dict:
        """The conversation as plain JSON, to restore in another process (decisions 036 and 037).

        Holds the needs, the last results, the open question and the model's history (without
        thinking, which is bound to the turn that wrote it). Not the parent's identity or saves.
        """
        state = {k: getattr(self, k) for k in self._STATE}
        state.update({k: sorted(getattr(self, k)) for k in self._SETS})
        state["chip_labels"] = {k: v.model_dump() for k, v in self.chip_labels.items()}
        state["messages"] = _without_thinking(self.agent.messages)
        return json.loads(json.dumps(state, default=str))

    def restore(self, state: dict) -> None:
        for k in self._STATE:
            if k in state:
                setattr(self, k, copy.deepcopy(state[k]))
        for k in self._SETS:
            setattr(self, k, set(state.get(k, [])))
        self.chip_labels = {k: ChipLabel(**v) for k, v in state.get("chip_labels", {}).items()}
        self.agent = self._new_agent(messages=copy.deepcopy(state.get("messages") or []))

    def _new_search(self) -> dict:
        """Start over with the same parent: forget the conversation, keep the session and saved list.

        The app stores session_id in the browser, so a parent's list survives a page refresh and a
        "New search" (login is out of scope; the session id stands in for the signed-in parent).
        """
        self.needs, self.semantic_query, self.last = [], None, None
        self.pending_question, self.comparison, self.chip_labels = None, None, {}
        self.seen_ids, self.seen_content, self.seen_programs = set(), {}, set()
        self.seen_documents = {}
        self.last_programs, self.programs_fresh = None, False
        self.unmapped, self.suggestions = [], []
        self.asked_topics, self.answered_topics, self.visit_offered = set(), set(), False
        self._needs_recap_pending = False
        self._strong = False
        self.agent = self._new_agent()
        self._step("new_search", "Code (no model)", "Started a new search; your saved list is kept")
        return {"session_id": self.session_id, "blocks": []}

    def _agent_turn(self, text: str) -> dict:
        self._drop_old_thinking()
        self._tool_calls, self.searched_this_turn = 0, False
        if self._needs_recap_pending:
            self._needs_recap_pending = False
            if self.needs:
                text = f"{self._recap()}\n\n{text}"
        text = f"{text}\n\n{family.prompt_note(self.needs, self.answered_topics, self.asked_topics)}"
        model_id, reason = routing.choose(text, self._strong)
        self._strong = self._strong or reason is not None
        history = copy.deepcopy(self.agent.messages)  # to retry this turn on the strong model
        try:
            decision, calls = self._run(text, model_id)
        except Exception:
            self._count_failed_attempt(model_id)
            if model_id == routing.STRONG_MODEL or routing.MAIN_MODEL:
                log.exception("agent turn failed for session %s; answering from code", self.session_id)
                return self._fallback()
            # The fast model couldn't finish (no structured reply, a Bedrock error). Give the same
            # turn, from the same history, to the strong model before falling back to code.
            log.warning("fast model failed for session %s; retrying on the strong model", self.session_id,
                        exc_info=True)
            strong = routing.STRONG_MODEL
            self._step("escalate", f"{routing.name(strong)} on Amazon Bedrock",
                       f"{routing.name(model_id)} couldn't finish this turn, so {routing.name(strong)} took it over")
            model_id, reason = strong, "retry"
            self.agent = self._new_agent(messages=history, model_id=model_id)
            self._tool_calls = 0
            try:
                decision, calls = self._run(text, model_id)
            except Exception:
                self._count_failed_attempt(model_id)
                log.exception("agent turn failed for session %s; answering from code", self.session_id)
                return self._fallback()
        why = {"sensitive topic": " I used the stronger model because this touches a sensitive topic.",
               "earlier in this conversation": " I kept the stronger model from earlier in this conversation."}
        self._trace.insert(0, {"tool": "understand", "service": f"{routing.name(model_id)} on Amazon Bedrock",
                               "text": f"Read your message, chose which tools to call ({calls} model "
                                       f"call{'s' if calls != 1 else ''}) and wrote the reply." + why.get(reason, "")})
        return self._blocks(decision)

    def _run(self, text: str, model_id: str) -> tuple["Decision", int]:
        """One model turn on `model_id`: tools, then the structured reply. Returns it and the call count."""
        self.agent.model = bedrock_model(model_id)
        calls_before = self.usage["model_calls"]
        try:
            result = self.agent(text, structured_output_model=Decision)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ValidationException":
                raise
            # Bedrock rejected the stored history. Start a fresh conversation that keeps
            # what the parent has told us so far, and try once more.
            self.agent = self._new_agent(model_id=model_id)
            self._tool_calls = 0
            result = self.agent(f"{self._recap()}\n\n{text}", structured_output_model=Decision)
        self._add_usage(result.metrics, model_id)
        decision: Decision | None = result.structured_output
        if decision is None:
            raise ValueError("model returned no structured output")
        return decision, self.usage["model_calls"] - calls_before

    def _count_failed_attempt(self, model_id: str) -> None:
        """A failed attempt still used tokens; count what the agent recorded, if anything."""
        metrics = getattr(self.agent, "event_loop_metrics", None)
        if metrics is not None:
            try:
                self._add_usage(metrics, model_id)
            except Exception:
                log.debug("no usage recorded for the failed attempt", exc_info=True)

    def _recap(self) -> str:
        return (f"(Context from earlier in this conversation: the parent's current needs are "
                f"{json.dumps(self._needs_for_prompt())}.)")

    def _fallback(self) -> dict:
        """Contract section 5: when the model can't answer, show what code already knows.

        Cards (or the comparison table) are built by code, so they're still right. Search
        results are shown only if a search ran during this turn, so old results never pass
        as the answer to a new question. The conversation restarts, since its history may
        be broken; the next turn gets a recap of the parent's needs. (From Sanchit's PR #1.)
        """
        self.agent = self._new_agent()
        self._needs_recap_pending = True
        has_answer = bool(self.comparison) or (self.searched_this_turn and bool((self.last or {}).get("results")))
        response = self._blocks(None, show_results=self.searched_this_turn)
        note = ("I checked the data, but I couldn't write my explanation this time. "
                "The checks shown come straight from the data." if has_answer
                else "Sorry, I couldn't finish that. Please try again, or say it another way.")
        blocks = response["blocks"]
        at = 1 if blocks and blocks[0]["type"] == "criteria_chips" else 0
        blocks.insert(at, {"type": "text", "markdown": note})
        response["fallback"] = True
        self._step("fallback", "Code (no model)", "The model didn't finish, so the cards come straight from the data")
        return response

    def _add_usage(self, metrics, model_id: str) -> None:
        """Strands' counters are running totals for the agent, so add only what this turn used."""
        now = {**metrics.accumulated_usage, "model_calls": metrics.cycle_count}
        if self.agent is not self._usage_agent:  # a fresh agent after a fallback starts from zero
            self._usage_agent, self._usage_seen = self.agent, {}
        per_model = self.usage_by_model.setdefault(model_id, dict.fromkeys(self.usage, 0))
        for key in self.usage:
            delta = now.get(key, 0) - self._usage_seen.get(key, 0)
            self.usage[key] += delta
            per_model[key] += delta
        self._usage_seen = now

    def _drop_old_thinking(self) -> None:
        """Remove thinking blocks from finished turns.

        Each thinking block is bound to the exact history before it. Once the sliding window
        trims old messages, those blocks no longer match and Bedrock rejects the request.
        The model doesn't need its old thinking, so strip it before every new turn.
        """
        self.agent.messages[:] = _without_thinking(self.agent.messages)

    def _needs_for_prompt(self) -> list[dict]:
        return [{k: ({kk: vv for kk, vv in v.items() if not kk.startswith("_")} if isinstance(v, dict) else v)
                 for k, v in n.items()} for n in self.needs]

    def _chip_edit(self, event: dict) -> dict:
        """Editing a chip re-runs search and verify in code; no model call."""
        need_id = event["need"]
        known_before = family.covered(self.needs, self.answered_topics)
        self.needs = [n for n in self.needs if n["need"] != need_id]
        if not event.get("removed"):
            self.needs.append({"need": need_id, "mode": event.get("mode", "prefer"), "value": event.get("value")})
        started = time.perf_counter()
        self.last = search.find(self.needs, self.semantic_query)
        self._trace_search(self.needs, started, set())
        self._step("rerank", "Code (no model)", "Re-ranked in code without calling the model")
        # Keep asking (decision 041): the open question stays unless this edit answered it; else the next topic
        question = self.pending_question
        answered_now = family.covered(self.needs, self.answered_topics) - known_before
        if question and question.get("topic") in answered_now:
            question = None
        question = question or self.next_question()
        self.agent.messages.append({"role": "user", "content": [{"text": f"(I changed my criteria: {json.dumps(event)})"}]})
        self.agent.messages.append({"role": "assistant", "content": [
            {"text": "Updated the results." + (f" {question['text']}" if question else "")}]})
        return self._blocks(None, question=question)

    def next_question(self) -> dict | None:
        """The next family profile question, in code's words, once there are schools to refine."""
        if not (self.last or {}).get("results"):
            return None
        left = family.remaining(self.needs, self.answered_topics, self.asked_topics)
        if not left:
            return None
        t = left[0]
        return {"question_id": "q-" + uuid.uuid4().hex[:6], "text": t.question, "why": t.why,
                "options": [{"id": f"o{i + 1}", "label": o} for i, o in enumerate(t.options)],
                "allow_text": True, "topic": t.id}

    def after_save(self) -> list[dict]:
        """What the agent says after a save (code only): the next profile question, or the visit offer."""
        if self.pending_question:  # one open question at a time
            return []
        if question := self.next_question():
            self.pending_question = question
            self.asked_topics.add(question["topic"])
            return [{"type": "clarifying_question", **question}]
        offer = self._visit_offer(force=False)
        return [offer] if offer else []

    def _visit_offer(self, force: bool, school_ids: list[str] | None = None) -> dict | None:
        """A visit or call with a local partner, for the schools the parent is weighing (decision 041).

        Shown when asked for (`force`), or once on its own when the profile is complete and the
        parent has saved schools. The partners and their schools come from code, never the model.
        """
        complete = not family.remaining(self.needs, self.answered_topics, self.asked_topics)
        if not force and (self.visit_offered or not complete or not self.saved):
            return None
        results = {r["school_id"]: r for r in (self.last or {}).get("results", [])}
        ids = school_ids or sorted(self.saved) or list(results)[:3]
        schools = []
        for sid in ids[:6]:
            school = results.get(sid)
            if school is None:
                try:
                    school = search.get_school(sid)
                except Exception:
                    log.exception("could not look up %s for the visit offer", sid)
            if school:
                schools.append({"school_id": sid, "name": school.get("name"), "city": school.get("city")})
        found = partners.for_schools(schools)
        if not found:
            return None
        self.visit_offered = True
        self._step("visit_offer", "Code (no model)",
                   f"Found {len(found)} local partner{'s' if len(found) != 1 else ''} who can visit "
                   f"{'these schools' if len(schools) != 1 else 'this school'} with you")
        names = [s["name"] for s in schools if s["name"]]
        what = names[0] if len(names) == 1 else " and ".join(names) if len(names) == 2 else "these schools"
        return {"type": "visit_offer", "text": f"Ready to see {what} in person? A local partner can visit with you "
                                               "or talk your list through, for free.",
                "schools": [{"school_id": s["school_id"], "name": s["name"]} for s in schools], "partners": found}

    def _comparison(self, school_ids: list[str]) -> dict | None:
        """Side-by-side table built in code from the same verify rules as the cards."""
        schools = [search.get_school(i) for i in school_ids]
        if len(schools) != 2 or None in schools:
            return None
        rows = []
        for need in self.needs:
            cells = []
            for school in schools:
                c = N.verify(school, copy.deepcopy(need))
                shown = c["note"] or N.plain_evidence(c["evidence"][:1])
                cells.append({"status": c["status"], "text": shown})
            rows.append({"need": need["need"], "label": N.CATALOG[need["need"]]["label"], "cells": cells})
        rows.append({"need": "data_quality", "label": "Problems in our data",
                     "cells": [{"status": N.ATTENTION if N.quality_flags(s) else N.CONFIRMED,
                                "text": " ".join(f["note"] for f in N.quality_flags(s)) or "None found"}
                               for s in schools]})
        return {"school_ids": school_ids, "names": [s["name"] for s in schools], "rows": rows}

    def _option_label(self, option_id: str | None) -> str:
        for o in (self.pending_question or {}).get("options", []):
            if o["id"] == option_id:
                return o["label"]
        return option_id or ""

    # ---------------------------------------------------------------- blocks

    def _blocks(self, decision: Decision | None, show_results: bool = True, question: dict | None = None) -> dict:
        blocks: list[dict[str, Any]] = []
        # A restored value keeps its earlier label ("Care until 6pm"), not the model's new one
        self.chip_labels.update({c.need: c for c in (decision.chips if decision else [])
                                 if not (c.need in self._kept_values and c.need in self.chip_labels)})
        labels = self.chip_labels
        if decision and not self.needs:
            # No search yet (e.g. the agent asked for a location first): still show what it
            # understood, and keep it so the next search starts from these needs.
            self.needs = [{"need": c.need, "mode": c.mode, "value": c.value}
                          for c in decision.chips if c.need in N.RULES]
        current = {n["need"] for n in self.needs}
        if decision:  # gaps are kept across chip edits until the agent's next answer
            self.unmapped = [u for u in decision.unmapped if u.strip()][:5]
            self.suggestions = [{"need": g.need, "label": plain_label(g.label, N.CATALOG.get(g.need, {}).get("label")),
                                 "why": g.why} for g in decision.suggestions
                                if g.need in N.CATALOG and g.need not in current][:2]
        else:
            self.suggestions = [g for g in self.suggestions if g["need"] not in current]
        chips = []
        for n in self.needs:
            c = labels.get(n["need"])
            value = n.get("value")
            if isinstance(value, dict):
                value = {k: v for k, v in value.items() if not k.startswith("_")}
            chips.append({"need": n["need"], "mode": n["mode"], "value": value,
                          "label": plain_label(c.label, N.CATALOG[n["need"]]["label"]) if c else N.CATALOG[n["need"]]["label"],
                          "source": c.source if c else "stated"})
        if chips or self.unmapped or self.suggestions:
            blocks.append({"type": "criteria_chips", "chips": chips, "unmapped": self.unmapped,
                           "suggested": self.suggestions,
                           "profile": family.meter(self.needs, self.answered_topics)})

        if decision and decision.message and not self.comparison:  # a comparison carries it as its summary
            # Only entries lookup_content actually returned can be cited
            # and each names the knowledge base document it came from, when it came from one
            sources = [{"id": s, "title": self.seen_content[s],
                        **({"document": self.seen_documents[s]} if s in self.seen_documents else {})}
                       for s in decision.sources if s in self.seen_content]
            blocks.append({"type": "text", "markdown": decision.message, **({"sources": sources} if sources else {})})

        self.pending_question = question
        if decision and decision.question:
            q = decision.question
            self.pending_question = {"question_id": "q-" + uuid.uuid4().hex[:6], "text": q.text, "why": q.why,
                                     "options": [{"id": f"o{i + 1}", "label": plain_label(label)}
                                                 for i, label in enumerate(q.options)],
                                     "allow_text": True,
                                     **({"topic": q.topic} if q.topic in family.BY_ID else {})}
        if self.pending_question:
            if topic := self.pending_question.get("topic"):
                self.asked_topics.add(topic)
            blocks.append({"type": "clarifying_question", **self.pending_question})

        # The step after saving: see the schools in person with a local partner
        compared = self.comparison["school_ids"] if self.comparison else None
        offer = None
        if decision or compared:
            try:
                offer = self._visit_offer(force=bool(compared or (decision and decision.offer_visit)),
                                          school_ids=compared)
            except Exception:
                log.exception("could not build the visit offer")
        if offer:
            blocks.append(offer)

        if self.comparison:
            blocks.append({"type": "comparison", "school_ids": self.comparison["school_ids"],
                           "names": self.comparison["names"], "rows": self.comparison["rows"],
                           "summary": decision.message if decision else None})
            self.comparison = None
            return {"session_id": self.session_id, "blocks": blocks}

        results = (self.last or {}).get("results", []) if show_results else []
        by_id = {r["school_id"]: r for r in results}
        programs = self.last_programs["programs"] if self.programs_fresh and self.last_programs else []
        notes = decision.callouts if decision else []
        dropped = 0
        for callout in notes:
            r = by_id.get(callout.school_id)
            if r is None:  # the model may only point at schools the tool returned
                dropped += 1
                continue
            evidence = [e for c in r["criteria"] if c["status"] != N.CONFIRMED for e in c["evidence"]]
            evidence += [{"field": f["field"], "value": f["value"]} for f in r["quality_flags"]]
            if not evidence or not _grounded(callout.text, r, programs):
                log.info("dropped ungrounded callout for %s: %s", r["school_id"], callout.text)
                dropped += 1
                continue
            blocks.append({"type": "evidence_callout", "school_id": r["school_id"], "text": callout.text,
                           "evidence": evidence})

        if notes:
            kept_notes = len(notes) - dropped
            self._step("ground", "Code (no model)",
                       f"Checked the agent's {len(notes)} note{'s' if len(notes) != 1 else ''} against the data: "
                       f"{kept_notes} kept" + (f", {dropped} dropped (not backed by the data)" if dropped else ""))

        if self.programs_fresh and self.last_programs and self.last_programs["programs"]:
            blocks.append({"type": "program_results", "programs": self.last_programs["programs"],
                           "excluded_past": self.last_programs["excluded_past"]})
        self.programs_fresh = False

        if results:
            blocks.append({"type": "school_results", "results": [
                {**{k: r.get(k) for k in ("school_id", "name", "entity_type", "city", "rank", "score", "criteria",
                                           "watch_out", "quality_flags", "cost", "badge")},
                 "saved": r["school_id"] in self.saved}
                for r in results]})
        return {"session_id": self.session_id, "blocks": blocks}


def _without_thinking(messages: list[dict]) -> list[dict]:
    """The same messages without thinking blocks (an emptied message keeps a placeholder)."""
    out = []
    for message in messages:
        content = message.get("content", [])
        kept = [block for block in content if "reasoningContent" not in block]
        out.append({**message, "content": kept or [{"text": "(thinking)"}]} if len(kept) != len(content) else message)
    return out


_NUMBER = re.compile(r"\d+(?:[.:,]\d+)*")

# School-system terms parents often don't know (Vision doc: parents "don't know the jargon").
JARGON = re.compile(r"\b(IEPs?|504s?|ELLs?|ESL|ESOL|ESAs?|SWD|FES(?:-EO|-UA)?|FTC|OSP|CTE|LEP)\b")
_JARGON_ASIDE = re.compile(r"\s*[(\[][^)\]]*\b(?:IEPs?|504s?|ELLs?|ESL|ESOL|ESAs?|SWD|FES(?:-EO|-UA)?|FTC|OSP|CTE|LEP)\b[^)\]]*[)\]]")


def plain_label(text: str, fallback: str | None = None) -> str:
    """Short UI text without school-system terms: "Extra help for ADHD (IEP/504)" -> "Extra help for ADHD"."""
    cleaned = _JARGON_ASIDE.sub("", text or "").strip()
    if JARGON.search(cleaned) and fallback:
        return fallback
    return cleaned or (fallback or text)


def _grounded(text: str, result: dict, programs: list[dict] | None = None) -> bool:
    """A callout may only use numbers (ratings, times, years, counts, distances) found in the data.

    The facts are that school's criteria and flags, plus any programs shown this turn (a callout
    may point at the library club that fills a gap). Cards come from code; this keeps the model's
    own sentence from adding numbers the data doesn't contain. Based on Sanchit's PR #1.
    """
    facts = json.dumps({"criteria": result["criteria"], "flags": result["quality_flags"], "name": result["name"],
                        "cost": result.get("cost"), "programs": programs or []})
    known = set(_NUMBER.findall(facts))
    known |= {d[:4] for d in re.findall(r"\d{4}-\d{2}", facts)}  # "2023" from "2023-05-01"
    known |= {d[:7] for d in re.findall(r"\d{4}-\d{2}", facts)}
    for n in list(known):
        if re.fullmatch(r"\d+\.\d+", n):  # "1.6" km can be written "1.6" or rounded to "2"
            known |= {n.split(".")[0], str(round(float(n)))}
    for hh, mm in re.findall(r"\b(\d{1,2}):(\d{2})\b", facts):  # "18:30" can be written "6:30" or "6pm"
        hour = str(int(hh) % 12 or 12)
        known |= {hour, f"{hour}:{mm}"}
    return all(n.replace(",", "") in known or n in known for n in _NUMBER.findall(text))


def _compact(found: dict) -> dict:
    """What the model sees from a search: statuses and short notes, not raw documents."""
    return {
        "total_candidates": found["total_candidates"],
        "notes": found["notes"],
        "summary_counts": found["summary"],
        "question_hints": found["question_hints"],
        "results": [{
            "school_id": r["school_id"], "name": r["name"], "type": r["entity_type"], "city": r["city"],
            "rank": r["rank"], "score": r["score"],
            "criteria": {c["need"]: {"status": c["status"], "note": c["note"],
                                     "evidence": [f"{e['field']}={e['value']}" + (f" (as of {e['as_of']})" if e.get("as_of") else "")
                                                  for e in c["evidence"]]}
                         for c in r["criteria"]},
            "data_quality": [f["note"] for f in r["quality_flags"]],
            "cost": r.get("cost"),
            "badge": (r.get("badge") or {}).get("label"),
        } for r in found["results"]],
    }
