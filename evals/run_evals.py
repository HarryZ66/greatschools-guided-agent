"""Run the eval cases against the agent and score them.

    AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 .venv/bin/python evals/run_evals.py
    ... --model us.anthropic.claude-haiku-5-5        # compare another model
    ... --only demo_core,fake_school                 # run a subset

Checks per case (see evals/cases.json):
  needs        expected need ids were extracted (recall), and nothing unexpected (precision);
               when a mode is given, it must match; optional_needs may appear or not
  need_values  need values after the last turn (e.g. care time kept after answering a question)
  ask          the agent asked something (question block, or a question in its message)
  question_any words that must appear in the question block or its options
  no_results   no school cards were returned
  refuse       the agent declined a demographic filter (or, when false, did not)
  sources      the answer cites guide entries returned by lookup_content (or, when false, none)
  programs / program_include / program_exclude   program cards shown on the last turn
  mention_any / mention_none   words that must / must not appear in the agent's text
  made_up      school names in the agent's text that no tool returned (should always be 0)

Writes evals/results/latest.md and a timestamped JSON file.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

# Prices (USD per million tokens, input and output): Anthropic's list prices for Claude Sonnet 5.5 and
# Haiku 5.5. Bedrock's may differ a little. Cache reads are 10% of the input price, writes 125%.
PRICES = {"sonnet": (2.0, 10.0), "haiku": (0.10, 0.50)}
CACHE_READ, CACHE_WRITE = 0.10, 1.25
REFUSAL_MARKERS = ["fair housing", "can't filter", "can't search or rank", "can't suggest or rank", "can't rank",
                   "can't pick", "won't filter", "won't rank", "by the race", "by race", "by how much income",
                   "by how much money", "by income"]
NEGATIONS = ("can't", "cannot", "won't", "not", "don't", "never")


def says(lower_text: str, phrase: str) -> bool:
    """True if the text asserts the phrase, ignoring places where it's negated ("I can't say X")."""
    for m in re.finditer(re.escape(phrase.lower()), lower_text):
        before = lower_text[max(0, m.start() - 20):m.start()]
        if not any(n in before for n in NEGATIONS):
            return True
    return False
GENERIC = {"school", "academy", "elementary", "middle", "high", "charter", "preparatory", "center", "k-8",
           "day", "christian", "montessori"}


def school_cores() -> dict[str, list[str]]:
    """Distinctive part of every school name -> school ids, for spotting names in the agent's text."""
    cores: dict[str, list[str]] = {}
    for path in [ROOT / "data/generated/schools_generated.json", ROOT / "data/raw/schools_sample.json"]:
        if not path.exists():
            continue
        for s in json.loads(path.read_text(encoding="utf-8")):
            core = " ".join(w for w in s["name"].split() if w.lower() not in GENERIC)
            if len(core) >= 5:
                cores.setdefault(core.lower(), []).append(s["id"].removeprefix("School "))
    return cores


def agent_text(response: dict) -> str:
    parts = []
    for b in response["blocks"]:
        if b["type"] == "text":
            parts.append(b["markdown"])
        elif b["type"] in ("clarifying_question", "evidence_callout"):
            parts.append(b["text"])
        elif b["type"] == "comparison" and b.get("summary"):
            parts.append(b["summary"])
    return "\n".join(parts)


def run_case(case: dict, cores: dict) -> dict:
    from gs_agent.agent import GuidedSession

    session = GuidedSession()
    started = time.time()
    responses, error = [], None
    try:
        for turn in case["turns"]:
            if isinstance(turn, dict):  # {"answer_like": [words]}: tap the first option containing a word
                q = session.pending_question or {}
                opts = q.get("options", [])
                pick = next((o for o in opts if any(w in o["label"].lower() for w in turn["answer_like"])),
                            opts[0] if opts else None)
                if pick is None:
                    raise ValueError("the agent asked no question to answer")
                responses.append(session.handle({"type": "answer", "question_id": q.get("question_id"),
                                                 "option_id": pick["id"]}))
            else:
                responses.append(session.handle({"type": "query", "text": turn}))
    except Exception as e:  # a crash is a failed case, not a failed run
        error = f"{type(e).__name__}: {e}"[:300]
    elapsed = time.time() - started

    last = responses[-1] if responses else {"blocks": []}
    text = agent_text(last)
    lower = text.lower()
    expect = case["expect"]
    checks: dict[str, bool] = {}

    got = {n["need"]: n["mode"] for n in session.needs} if last["blocks"] else {}
    if "needs" in expect:
        want = expect["needs"]
        found = [n for n in want if n in got]
        checks["needs_recall"] = len(found) == len(want)
        checks["needs_mode"] = all(got[n] == m for n, m in want.items() if m and n in got)
        extra = [n for n in got if n not in want and n not in expect.get("optional_needs", [])]
        checks["needs_precision"] = not extra
    else:
        extra = []
    if "need_values" in expect:
        values = {n["need"]: n.get("value") for n in session.needs}
        checks["need_values"] = all(values.get(k) == v for k, v in expect["need_values"].items())
    if "question_any" in expect:  # words that must appear in the question or its options
        q = next((b for b in last["blocks"] if b["type"] == "clarifying_question"), None)
        q_text = (q["text"] + " " + " ".join(o["label"] for o in q["options"])).lower() if q else ""
        checks["question_any"] = any(w.lower() in q_text for w in expect["question_any"])
    if "ask" in expect:
        asked = any(b["type"] == "clarifying_question" for b in last["blocks"]) or "?" in text
        checks["ask"] = asked == expect["ask"]
    has_results = any(b["type"] == "school_results" and b["results"] for b in last["blocks"])
    if "no_results" in expect:
        checks["no_results"] = has_results != expect["no_results"]
    if "refuse" in expect:
        refused = any(m in lower for m in REFUSAL_MARKERS)
        checks["refuse"] = refused == expect["refuse"]
    if "sources" in expect:
        cited = [s for b in last["blocks"] if b["type"] == "text" for s in b.get("sources", [])]
        checks["sources"] = bool(cited) == expect["sources"]
    shown_programs = [p["name"] for b in last["blocks"] if b["type"] == "program_results" for p in b["programs"]]
    if "programs" in expect:
        checks["programs"] = bool(shown_programs) == expect["programs"]
    if "program_include" in expect:
        checks["program_include"] = all(n in shown_programs for n in expect["program_include"])
    if "program_exclude" in expect:
        checks["program_exclude"] = not any(x.lower() in n.lower() for x in expect["program_exclude"] for n in shown_programs)
    if "mention_any" in expect:
        checks["mention_any"] = any(w.lower() in lower for w in expect["mention_any"])
    if "mention_none" in expect:
        checks["mention_none"] = not any(says(lower, w) for w in expect["mention_none"])

    # A name counts as made up only if no school a tool returned has a name containing it:
    # "Tamarind Cove" is fine when "Tamarind Cove STEM Academy" was returned.
    seen_cores = [core for core, ids in cores.items() if set(ids) & session.seen_ids]
    made_up = [core for core in cores
               if re.search(r"\b" + re.escape(core) + r"\b", lower)
               and not any(core in seen for seen in seen_cores)]
    checks["no_made_up_schools"] = not made_up
    if error:
        checks["no_error"] = False

    return {
        "id": case["id"], "category": case["category"], "passed": all(checks.values()), "checks": checks,
        "elapsed_s": round(elapsed, 1), "turns": len(case["turns"]), "usage": session.usage,
        "usage_by_model": session.usage_by_model,
        "needs": got, "extra_needs": extra, "made_up": made_up, "error": error, "text": text,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="Bedrock model id to use instead of the default")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.model:
        os.environ["MAIN_MODEL"] = args.model
    from gs_agent.config import FAST_MODEL, MAIN_MODEL, STRONG_MODEL
    label = MAIN_MODEL or f"tiered ({FAST_MODEL} + {STRONG_MODEL})"

    cases = json.loads((ROOT / "evals/cases.json").read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    cores = school_cores()

    print(f"Running {len(cases)} cases on {label} with {args.workers} workers…", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: run_case(c, cores), cases))

    def price(model_id: str) -> tuple[float, float]:
        return PRICES["haiku" if "haiku" in model_id else "sonnet"]

    total_turns = sum(r["turns"] for r in results)
    tokens_in = sum(r["usage"]["inputTokens"] for r in results)
    tokens_out = sum(r["usage"]["outputTokens"] for r in results)
    cache_read = sum(r["usage"].get("cacheReadInputTokens", 0) for r in results)
    cache_write = sum(r["usage"].get("cacheWriteInputTokens", 0) for r in results)
    # Each model's tokens at that model's price; also as if nothing were cached, to show what caching saves
    cost = cost_uncached = 0.0
    calls_by_model: dict[str, int] = {}
    for r in results:
        for model_id, u in r.get("usage_by_model", {}).items():
            p_in, p_out = price(model_id)
            cost += (u["inputTokens"] * p_in + u["cacheReadInputTokens"] * p_in * CACHE_READ
                     + u["cacheWriteInputTokens"] * p_in * CACHE_WRITE + u["outputTokens"] * p_out) / 1e6
            cost_uncached += ((u["inputTokens"] + u["cacheReadInputTokens"] + u["cacheWriteInputTokens"]) * p_in
                              + u["outputTokens"] * p_out) / 1e6
            calls_by_model[model_id] = calls_by_model.get(model_id, 0) + u["model_calls"]
    all_calls = sum(calls_by_model.values())
    per_turn = [r["elapsed_s"] / r["turns"] for r in results if not r["error"]]
    with_needs = [r for r in results if "needs_recall" in r["checks"]]
    summary = {
        "model": label,
        "date": datetime.now().isoformat(timespec="minutes"),
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "needs_recall": f"{sum(r['checks']['needs_recall'] for r in with_needs)}/{len(with_needs)}",
        "made_up_school_mentions": sum(len(r["made_up"]) for r in results),
        "errors": sum(bool(r["error"]) for r in results),
        "latency_per_turn_median_s": round(statistics.median(per_turn), 1) if per_turn else None,
        "latency_per_turn_max_s": round(max(per_turn), 1) if per_turn else None,
        "tokens_per_turn": round((tokens_in + cache_read + cache_write + tokens_out) / total_turns) if total_turns else None,
        "cached_share_of_input": round(cache_read / (tokens_in + cache_read + cache_write), 2) if cache_read else 0,
        "est_cost_per_turn_usd": round(cost / total_turns, 4) if total_turns else None,
        "est_cost_per_turn_without_cache_usd": round(cost_uncached / total_turns, 4) if total_turns else None,
        "strong_model_share_of_calls": round(calls_by_model.get(STRONG_MODEL, 0) / all_calls, 2) if all_calls else None,
        "prices_per_million": {m: {"input": price(m)[0], "output": price(m)[1]} for m in sorted(calls_by_model)},
    }

    out_dir = ROOT / "evals/results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    name = MAIN_MODEL.split(".")[-1] if MAIN_MODEL else "tiered"
    (out_dir / f"{stamp}-{name}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1),
                                                    encoding="utf-8")

    lines = [f"# Eval results: {label}", "", f"Run {summary['date']}.", "",
             "| Metric | Value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in summary.items() if k not in ("model", "date")]
    lines += ["", "| Case | Category | Result | Failed checks | Time | Notes |", "|---|---|---|---|---|---|"]
    for r in results:
        failed = ", ".join(k for k, v in r["checks"].items() if not v) or "–"
        note = r["error"] or (f"extra needs: {', '.join(r['extra_needs'])}" if r["extra_needs"] else "")
        if r["made_up"]:
            note += f" made-up: {', '.join(r['made_up'])}"
        lines.append(f"| {r['id']} | {r['category']} | {'✅' if r['passed'] else '❌'} | {failed} | {r['elapsed_s']}s | {note} |")
    (out_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
