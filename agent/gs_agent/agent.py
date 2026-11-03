"""The guided agent: one Strands agent per parent session.

The model decides which tools to call, which needs the parent has, whether to ask a
question and how to explain. Statuses, evidence, ranking and the result cards come from
code (needs.py, search.py). See docs/contract.md for the block format.
"""

import copy
import json
import logging
import re
import uuid
from typing import Any, Callable, Literal

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel

from . import glossary
from . import needs as N
from . import search
from .config import MAIN_MODEL, REGION

log = logging.getLogger("gs_agent.agent")

Mode = Literal["require", "prefer", "avoid"]
MAX_TOOL_CALLS = 6  # per turn (docs/contract.md, section 5)


# ---------------------------------------------------------------- structured decision

class ChipLabel(BaseModel):
    need: str = Field(description="Need id from the catalog")
    label: str = Field(description="Short plain-language chip text, e.g. 'Care until 6pm'")
    source: Literal["stated", "inferred", "answered"] = Field(
        description="stated: parent said it; inferred: you assumed it; answered: from your question")


class Option(BaseModel):
    id: str
    label: str


class Question(BaseModel):
    text: str = Field(description="One short question in plain language")
    why: str = Field(description="Why this question changes the results, citing the counts you saw")
    options: list[Option] = Field(description="2-4 tappable answers")


class Callout(BaseModel):
    school_id: str = Field(description="A school_id from the latest find_schools results")
    text: str = Field(description="'I checked this for you: ...' explaining one stale, missing or conflicting fact")


class Suggestion(BaseModel):
    need: str = Field(description="Catalog need id the parent did not mention")
    label: str = Field(description="Short chip text, e.g. 'School bus'")
    why: str = Field(description="One short reason tied to what the parent said, e.g. 'You work until 6pm'")


class Decision(BaseModel):
    chips: list[ChipLabel] = Field(description="One entry per need you searched with")
    question: Question | None = Field(default=None, description="At most one question, or null")
    message: str = Field(description="1-3 plain sentences for the parent. No jargon. Don't restate the cards.")
    callouts: list[Callout] = Field(default_factory=list, description="0-2 honest notes about the data")
    unmapped: list[str] = Field(default_factory=list, description=(
        "Wishes the parent stated that no catalog need can check, in their own words (e.g. 'Montessori', "
        "'near my church'). Empty if none."))
    suggestions: list[Suggestion] = Field(default_factory=list, description=(
        "0-2 needs the parent didn't mention but likely cares about, given what they said. Empty if none."))


SYSTEM_PROMPT = """You are GreatSchools' guided school-search agent. Motto: "We investigate. You decide."
You help parents, many of whom don't know education jargon, find schools that fit their family.

How you work:
1. Turn what the parent says into needs from the catalog below, each with a mode:
   require (must have), prefer (nice to have) or avoid. grade_level and location are always required.
   Infer needs from plain words ("my 6th grader" -> grade_level ["m"]; "I work until 6" -> after_school_care "18:00").
2. If grade level or location is unknown, don't search: ask for it.
3. Otherwise call find_schools with ALL current needs (it replaces the previous search). Pass a short
   semantic_query describing the softer wishes in the parent's words.
4. Read the summary counts. Ask ONE question only if the answer would change the ranking, for example:
   a required need is missing for most schools, needs conflict, or a partial match needs a trade-off
   ("Care at the top schools ends at 5pm. Is that workable?"). Otherwise ask nothing.
5. Spot gaps. If the parent wants something the catalog can't check, put it in unmapped and say plainly
   that we can't check it yet. Suggest at most 2 needs they didn't mention but probably care about
   (a parent who works until 6pm may need a bus). Never search with a suggested need until they add it.
6. Use get_school_profile when the parent asks about one school.
7. When the parent asks what a term means, how GreatSchools rates schools, or how school choice and
   funding work, call explain_term and answer from what it returns. If it finds nothing, say GreatSchools
   doesn't have an explanation for that yet, and give a short general answer you mark as general.
You have at most {max_tools} tool calls per turn.

Honesty rules:
- Never claim a school meets a need unless find_schools says confirmed. Never invent facts, numbers or quotes.
- When data is missing or old, say so plainly and suggest asking the school.
- Don't list the schools in your message; the app shows cards built from the tool results.
- Write at a 6th-grade reading level. Answer in the parent's language.

Need catalog (id: value format):
{catalog}

Glossary topics explain_term knows: {glossary}
"""


def _catalog_text() -> str:
    return "\n".join(f"- {k}: value = {v['value']}" for k, v in N.CATALOG.items())


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
        self.unmapped: list[str] = []
        self.suggestions: list[dict] = []
        self.on_progress: Callable[[str], None] | None = None  # set by the streaming endpoint
        self._tool_calls = 0
        self.searched_this_turn = False  # find_schools ran during the current turn
        self._glossary_used: list[dict] = []
        self._needs_recap_pending = False  # the conversation restarted after a failed turn
        self.agent = self._new_agent()

    def progress(self, text: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(text)
            except Exception:
                log.exception("progress callback failed")

    def _over_budget(self) -> str | None:
        self._tool_calls += 1
        if self._tool_calls > MAX_TOOL_CALLS:
            return json.dumps({"error": f"Tool limit of {MAX_TOOL_CALLS} per turn reached. "
                                        "Answer now with what you already have."})
        return None

    def _new_agent(self, messages: list | None = None) -> Agent:
        return Agent(
            # Claude 5.x models on Bedrock reject `temperature`, so it's left at the default.
            model=BedrockModel(model_id=MAIN_MODEL, boto_session=boto3.Session(region_name=REGION),
                               max_tokens=4000),
            tools=self._tools(),
            system_prompt=SYSTEM_PROMPT.format(catalog=_catalog_text(), max_tools=MAX_TOOL_CALLS,
                                               glossary="; ".join(glossary.titles())),
            conversation_manager=SlidingWindowConversationManager(window_size=60),
            messages=messages,
            callback_handler=None,
        )

    # Tools are closures so each session keeps its own last search.
    def _tools(self) -> list:
        session = self

        @tool
        def find_schools(needs: list[dict], semantic_query: str = "") -> str:
            """Search schools and check every need against the data.

            Args:
                needs: All current needs, each {"need": <catalog id>, "mode": "require"|"prefer"|"avoid", "value": ...}.
                semantic_query: Short description of softer wishes, in the parent's words.
            """
            if (stop := session._over_budget()):
                return stop
            clean = copy.deepcopy([n for n in needs if isinstance(n, dict) and n.get("need") in N.RULES])
            session.semantic_query = semantic_query or None
            session.progress(f"Searching schools and checking {len(clean)} of your needs…")
            # find() adds the resolved location center to the needs; keep it for compare and edits
            session.last = search.find(clean, session.semantic_query)
            session.needs = clean
            session.searched_this_turn = True
            session.progress(f"Checked {session.last['total_candidates']} schools; "
                             f"ranking the top {len(session.last['results'])}.")
            return json.dumps(_compact(session.last))

        @tool
        def get_school_profile(school_id: str) -> str:
            """Full data for one school, for questions about a specific school.

            Args:
                school_id: e.g. "fl-95390"
            """
            if (stop := session._over_budget()):
                return stop
            school = search.get_school(school_id)
            if school is None:
                return json.dumps({"error": f"No school with id {school_id}"})
            session.progress(f"Reading the profile for {school.get('name', school_id)}…")
            criteria = [N.verify(school, n) for n in copy.deepcopy(session.needs)]
            keep = {k: v for k, v in school.items() if k not in ("reviews_full", "reviews_text", "profile_text")}
            return json.dumps({"school": keep, "criteria": criteria, "quality_flags": N.quality_flags(school)})[:12000]

        @tool
        def explain_term(term: str) -> str:
            """Look up a school term or GreatSchools rating in the glossary (e.g. "CTE", "charter", "summary rating").

            Args:
                term: The word or phrase the parent asked about.
            """
            if (stop := session._over_budget()):
                return stop
            session.progress(f"Looking up '{term}' in the GreatSchools glossary…")
            found = glossary.lookup(term)
            session._glossary_used += [e for e in found if e not in session._glossary_used]
            if not found:
                return json.dumps({"found": False, "known_topics": glossary.titles()})
            return json.dumps({"found": True, "entries": [{k: e[k] for k in ("title", "text", "source")} for e in found]})

        return [find_schools, get_school_profile, explain_term]

    # ---------------------------------------------------------------- turns

    def handle(self, event: dict) -> dict:
        kind = event.get("type")
        if kind == "query":
            return self._agent_turn(event["text"])
        if kind == "answer":
            label = event.get("text") or self._option_label(event.get("option_id"))
            question = (self.pending_question or {}).get("text", "")
            return self._agent_turn(f'(Answer to your question "{question}"): {label}')
        if kind == "compare":
            self.comparison = self._comparison(event.get("school_ids", [])[:2])
            if self.comparison is None:
                raise ValueError("Both school ids must exist")
            names = " and ".join(self.comparison["names"])
            return self._agent_turn(
                f"Compare {names} for my needs. Here is the side-by-side check (already shown to me as a table): "
                f"{json.dumps(self.comparison['rows'])}. Don't call tools. In the message, say in 1-2 sentences "
                "what the real difference is for my family. No question unless a choice really depends on it.")
        if kind == "chip_edit":
            return self._chip_edit(event)
        raise ValueError(f"Unknown event type: {kind}")

    def _agent_turn(self, text: str) -> dict:
        self._drop_old_thinking()
        self._tool_calls, self.searched_this_turn, self._glossary_used = 0, False, []
        if self._needs_recap_pending:
            self._needs_recap_pending = False
            if self.needs:
                text = f"{self._recap()}\n\n{text}"
        try:
            try:
                result = self.agent(text, structured_output_model=Decision)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") != "ValidationException":
                    raise
                # Bedrock rejected the stored history. Start a fresh conversation that keeps
                # what the parent has told us so far, and try once more.
                self.agent = self._new_agent()
                self._tool_calls = 0
                result = self.agent(f"{self._recap()}\n\n{text}", structured_output_model=Decision)
            decision: Decision | None = result.structured_output
            if decision is None:
                raise ValueError("model returned no structured output")
        except Exception:
            log.exception("agent turn failed for session %s; answering from code", self.session_id)
            return self._fallback()
        return self._blocks(decision)

    def _recap(self) -> str:
        return (f"(Context from earlier in this conversation: the parent's current needs are "
                f"{json.dumps(self._needs_for_prompt())}.)")

    def _fallback(self) -> dict:
        """Contract section 5: when the model can't answer, show what code already knows.

        Cards (or the comparison table) are built by code, so they're still right. Search
        results are shown only if a search ran during this turn, so old results never pass
        as the answer to a new question. The conversation restarts, since its history may
        be broken; the next turn gets a recap of the parent's needs.
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
        return response

    def _drop_old_thinking(self) -> None:
        """Remove thinking blocks from finished turns.

        Each thinking block is bound to the exact history before it. Once the sliding window
        trims old messages, those blocks no longer match and Bedrock rejects the request.
        The model doesn't need its old thinking, so strip it before every new turn.
        """
        for message in self.agent.messages:
            content = message.get("content", [])
            kept = [block for block in content if "reasoningContent" not in block]
            if len(kept) != len(content):
                message["content"] = kept or [{"text": "(thinking)"}]

    def _needs_for_prompt(self) -> list[dict]:
        return [{k: ({kk: vv for kk, vv in v.items() if not kk.startswith("_")} if isinstance(v, dict) else v)
                 for k, v in n.items()} for n in self.needs]

    def _chip_edit(self, event: dict) -> dict:
        """Editing a chip re-runs search and verify in code; no model call."""
        need_id = event["need"]
        self.needs = [n for n in self.needs if n["need"] != need_id]
        if not event.get("removed"):
            self.needs.append({"need": need_id, "mode": event.get("mode", "prefer"), "value": event.get("value")})
        self.last = search.find(self.needs, self.semantic_query)
        self.agent.messages.append({"role": "user", "content": [{"text": f"(I changed my criteria: {json.dumps(event)})"}]})
        self.agent.messages.append({"role": "assistant", "content": [{"text": "Updated the results."}]})
        return self._blocks(None)

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
                shown = c["note"] or ", ".join(f"{e['field']}: {e['value']}" for e in c["evidence"][:1]) or ""
                cells.append({"status": c["status"], "text": shown})
            rows.append({"need": need["need"], "label": N.CATALOG[need["need"]]["label"], "cells": cells})
        rows.append({"need": "data_quality", "label": "Data problems",
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

    def _blocks(self, decision: Decision | None, show_results: bool = True) -> dict:
        blocks: list[dict[str, Any]] = []
        self.chip_labels.update({c.need: c for c in (decision.chips if decision else [])})
        if decision:  # gaps are kept across chip edits until the agent's next answer
            self.unmapped = [u for u in decision.unmapped if u.strip()][:5]
            current = {n["need"] for n in self.needs}
            self.suggestions = [{"need": g.need, "label": g.label, "why": g.why} for g in decision.suggestions
                                if g.need in N.CATALOG and g.need not in current][:2]
        else:
            current = {n["need"] for n in self.needs}
            self.suggestions = [g for g in self.suggestions if g["need"] not in current]
        labels = self.chip_labels
        chips = []
        for n in self.needs:
            c = labels.get(n["need"])
            value = n.get("value")
            if isinstance(value, dict):
                value = {k: v for k, v in value.items() if not k.startswith("_")}
            chips.append({"need": n["need"], "mode": n["mode"], "value": value,
                          "label": c.label if c else N.CATALOG[n["need"]]["label"],
                          "source": c.source if c else "stated"})
        if chips or self.unmapped or self.suggestions:
            blocks.append({"type": "criteria_chips", "chips": chips, "unmapped": self.unmapped,
                           "suggested": self.suggestions})

        if decision and decision.message and not self.comparison:  # a comparison carries it as its summary
            text = decision.message
            if self._glossary_used:  # cite the glossary entries the answer was built from
                sources = ", ".join(sorted({e["source"] for e in self._glossary_used if e["source"].startswith("http")}))
                text += "\n\n_From the GreatSchools glossary (demo draft)" + (f": {sources}" if sources else "") + "._"
            blocks.append({"type": "text", "markdown": text})

        self.pending_question = None
        if decision and decision.question:
            q = decision.question
            self.pending_question = {"question_id": "q-" + uuid.uuid4().hex[:6], "text": q.text, "why": q.why,
                                     "options": [o.model_dump() for o in q.options], "allow_text": True}
            blocks.append({"type": "clarifying_question", **self.pending_question})

        if self.comparison:
            blocks.append({"type": "comparison", "school_ids": self.comparison["school_ids"],
                           "names": self.comparison["names"], "rows": self.comparison["rows"],
                           "summary": decision.message if decision else None})
            self.comparison = None
            return {"session_id": self.session_id, "blocks": blocks}

        results = (self.last or {}).get("results", []) if show_results else []
        by_id = {r["school_id"]: r for r in results}
        for callout in (decision.callouts if decision else []):
            r = by_id.get(callout.school_id)
            if r is None:  # the model may only point at schools the tool returned
                continue
            evidence = [e for c in r["criteria"] if c["status"] != N.CONFIRMED for e in c["evidence"]]
            evidence += [{"field": f["field"], "value": f["value"]} for f in r["quality_flags"]]
            if not evidence or not _grounded(callout.text, r):
                log.info("dropped ungrounded callout for %s: %s", r["school_id"], callout.text)
                continue
            blocks.append({"type": "evidence_callout", "school_id": r["school_id"], "text": callout.text,
                           "evidence": evidence})

        if results:
            blocks.append({"type": "school_results", "results": [
                {**{k: r[k] for k in ("school_id", "name", "entity_type", "city", "rank", "score", "criteria",
                                       "watch_out", "quality_flags")},
                 "saved": r["school_id"] in self.saved}
                for r in results]})
        return {"session_id": self.session_id, "blocks": blocks}


_NUMBER = re.compile(r"\d+(?:[.:,]\d+)*")


def _grounded(text: str, result: dict) -> bool:
    """A callout may only use numbers (ratings, times, years, counts) found in that school's data.

    The cards' statuses and evidence come from code; this check keeps the model's own
    sentence about a school from adding numbers the data doesn't contain.
    """
    facts = json.dumps({"criteria": result["criteria"], "flags": result["quality_flags"], "name": result["name"]})
    known = set(_NUMBER.findall(facts))
    known |= {d[:4] for d in re.findall(r"\d{4}-\d{2}", facts)}  # "2023" from "2023-05-01"
    known |= {d[:7] for d in re.findall(r"\d{4}-\d{2}", facts)}
    for value in re.findall(r"\b(\d{1,2}):00\b", facts):  # "17:00" can be written "5pm" or "5:00"
        hour = str(int(value) % 12 or 12)
        known |= {hour, f"{hour}:00"}
    return all(n.replace(",", "") in known or n in known for n in _NUMBER.findall(text))


def _compact(found: dict) -> dict:
    """What the model sees from a search: statuses and short notes, not raw documents."""
    return {
        "total_candidates": found["total_candidates"],
        "notes": found["notes"],
        "summary_counts": found["summary"],
        "results": [{
            "school_id": r["school_id"], "name": r["name"], "type": r["entity_type"], "city": r["city"],
            "rank": r["rank"], "score": r["score"],
            "criteria": {c["need"]: {"status": c["status"], "note": c["note"],
                                     "evidence": [f"{e['field']}={e['value']}" + (f" (as of {e['as_of']})" if e.get("as_of") else "")
                                                  for e in c["evidence"]]}
                         for c in r["criteria"]},
            "data_quality": [f["note"] for f in r["quality_flags"]],
        } for r in found["results"]],
    }
