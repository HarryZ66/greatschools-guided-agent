"""Run one or more parent turns through the agent and print the UI blocks.

    PYTHONPATH=. python scripts/try_agent.py "elementary school near Miami with STEM, I work until 6"
    PYTHONPATH=. python scripts/try_agent.py "..." --answer need_6pm     # answer the agent's question
"""

import argparse
import json
import time

from gs_agent.agent import GuidedSession


def show(response: dict) -> None:
    for block in response["blocks"]:
        kind = block["type"]
        if kind == "criteria_chips":
            print("CHIPS:", ", ".join(f"[{c['mode']}] {c['label']} ({c['source']})" for c in block["chips"]))
        elif kind == "text":
            print("MESSAGE:", block["markdown"])
            for src in block.get("sources", []):
                print(f"   source: {src['title']} [{src['id']}]" + (f", document {src['document']}" if src.get("document") else ""))
        elif kind == "clarifying_question":
            print("QUESTION:", block["text"], "| why:", block["why"])
            print("   options:", [(o["id"], o["label"]) for o in block["options"]])
        elif kind == "evidence_callout":
            print(f"CALLOUT [{block['school_id']}]:", block["text"])
        elif kind == "school_results":
            for r in block["results"][:5]:
                marks = " ".join(f"{c['need']}:{c['status']}" for c in r["criteria"])
                print(f"  #{r['rank']} {r['name']} ({r['city']}) {r['score']} | {marks}")
                if r["watch_out"]:
                    print("      watch out:", r["watch_out"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--answer", help="option id (or free text) to answer the agent's question with")
    parser.add_argument("--json", action="store_true", help="print the raw response JSON")
    args = parser.parse_args()

    session = GuidedSession()
    events = [{"type": "query", "text": args.query}]
    if args.answer:
        events.append({"type": "answer", "option_id": args.answer})
    for event in events:
        print(f"\n=== {event}")
        if event["type"] == "answer" and session.pending_question:
            ids = [o["id"] for o in session.pending_question["options"]]
            if args.answer not in ids:
                event = {"type": "answer", "text": args.answer}
        start = time.time()
        response = session.handle(event)
        print(f"({time.time() - start:.1f}s)")
        print(json.dumps(response, indent=1)[:6000] if args.json else "", end="")
        show(response)
        for step in response.get("trace", {}).get("steps", []):
            print(f"   trace: {step['tool']} | {step['service']} | {step['text']}")


if __name__ == "__main__":
    main()
