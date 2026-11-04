"""End-to-end check of every API endpoint against a running deployment.

    python3 evals/smoke_api.py https://<cloudfront-domain>
    python3 evals/smoke_api.py http://localhost:8000

Walks one parent session through query -> answer -> compare -> chip edit -> guide question ->
program search, then saves, thumbs, profile and metrics, plus the error paths. Uses only the
standard library so anyone can run it.
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
results: list[tuple[str, bool, str, float]] = []


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(BASE + path, method=method, headers={"content-type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:200].decode(errors="replace")}


def check(name: str, ok: bool, detail: str = "", started: float | None = None) -> None:
    results.append((name, bool(ok), detail, time.time() - started if started else 0.0))


def blocks(resp: dict, kind: str) -> list[dict]:
    return [b for b in resp.get("blocks", []) if b["type"] == kind]


def turn(sid: str | None, event: dict) -> tuple[int, dict, float]:
    t = time.time()
    code, resp = call("POST", "/api/turn", {"session_id": sid, "event": event})
    return code, resp, t


# Health
t = time.time(); code, r = call("GET", "/api/health")
check("GET /api/health", code == 200 and r.get("ok"), str(r), t)

# 1. Query: chips, question, results with evidence, program cards
code, r, t = turn(None, {"type": "query", "text": "Middle school near Miami for my son who loves robotics. I work until 6pm."})
sid = r.get("session_id")
schools = (blocks(r, "school_results") or [{"results": []}])[0]["results"]
question = (blocks(r, "clarifying_question") or [None])[0]
check("turn: query returns 200 + session", code == 200 and sid, f"session {sid}", t)
check("turn: criteria chips", bool(blocks(r, "criteria_chips")), str([c["label"] for b in blocks(r, "criteria_chips") for c in b["chips"]]))
check("turn: clarifying question", question is not None, (question or {}).get("text", "")[:90])
check("turn: ranked school cards", len(schools) >= 3, f"{len(schools)} cards")
check("turn: every criterion has a status", all(c["status"] in ("confirmed", "partial", "needs_attention", "missing")
                                                  for s in schools for c in s["criteria"]))
check("turn: evidence on confirmed criteria", all(c["evidence"] for s in schools for c in s["criteria"] if c["status"] == "confirmed"))
check("turn: data problems flagged", any(s["quality_flags"] for s in schools), "quality_flags present on some card")
check("turn: program cards", bool(blocks(r, "program_results")), str([p["name"] for b in blocks(r, "program_results") for p in b["programs"]]))

# 2. Answer the question
if question:
    code, r2, t = turn(sid, {"type": "answer", "question_id": question["question_id"], "option_id": question["options"][0]["id"]})
    check("turn: answer", code == 200 and blocks(r2, "school_results"), f"{len(blocks(r2, 'school_results'))} result block", t)

# 3. Compare two schools (P2)
if len(schools) >= 2:
    a, b = schools[0]["school_id"], schools[1]["school_id"]
    code, r3, t = turn(sid, {"type": "compare", "school_ids": [a, b]})
    comp = (blocks(r3, "comparison") or [None])[0]
    check("turn: compare (P2)", code == 200 and comp and comp["rows"], f"{len(comp['rows']) if comp else 0} rows; summary: {(comp or {}).get('summary', '')[:60]}", t)

# 4. Chip edit: code-only re-rank
code, r4, t = turn(sid, {"type": "chip_edit", "need": "small_classes", "mode": "prefer"})
check("turn: chip_edit (no LLM)", code == 200 and r4.get("elapsed_ms", 99999) < 3000, f"{r4.get('elapsed_ms')} ms", t)

# 5. Guide question (P4) with sources
code, r5, t = turn(sid, {"type": "query", "text": "What does CTE mean?"})
srcs = [s["title"] for b in blocks(r5, "text") for s in b.get("sources", [])]
check("turn: guide answer with sources (P4)", code == 200 and srcs, str(srcs), t)

# 6. Named school (P3)
code, r6, t = turn(sid, {"type": "query", "text": "Is Lanternfish K-8 still running its STEM program?"})
text6 = " ".join(b["markdown"] for b in blocks(r6, "text"))
check("turn: named school detail (P3)", code == 200 and "2024" in text6, text6[:90], t)

# Streaming: progress events, then one result (through CloudFront when BASE is the deployment)
t = time.time()
req = urllib.request.Request(BASE + "/api/turn/stream", method="POST", headers={"content-type": "application/json"},
                             data=json.dumps({"session_id": sid, "event": {"type": "query", "text": "What does IEP mean?"}}).encode())
kinds, result = [], None
with urllib.request.urlopen(req, timeout=120) as resp:
    for raw in resp:
        line = raw.decode().strip()
        if line.startswith("data: "):
            msg = json.loads(line[6:])
            kinds.append(msg["type"])
            result = msg.get("response", result)
check("turn/stream: progress then result", "progress" in kinds and kinds[-1] == "result" and result and result.get("blocks"),
      f"events: {' > '.join(kinds)}", t)

# Saved list
target =schools[0]["school_id"] if schools else "fl-000000"
t = time.time(); code, r = call("POST", "/api/saved", {"session_id": sid, "school_id": target})
check("POST /api/saved", code == 200 and any(s["school_id"] == target for s in r.get("saved", [])), "", t)
t = time.time(); code, r = call("GET", f"/api/saved?session_id={sid}")
check("GET /api/saved", code == 200 and len(r.get("saved", [])) == 1, str([s["name"] for s in r.get("saved", [])]), t)
t = time.time(); code, r = call("DELETE", f"/api/saved/{target}?session_id={sid}")
check("DELETE /api/saved/{id}", code == 200 and not r.get("saved"), "", t)

# Feedback, profile, metrics
t = time.time(); code, r = call("POST", "/api/feedback", {"session_id": sid, "school_id": target, "vote": "up"})
check("POST /api/feedback", code == 200 and r.get("ok"), "", t)
t = time.time(); code, r = call("GET", f"/api/schools/{target}")
check("GET /api/schools/{id} (P3)", code == 200 and r.get("name") and "profile_vector" not in r, r.get("name", ""), t)
t = time.time(); code, r = call("GET", "/api/metrics")
check("GET /api/metrics", code == 200 and r.get("searches", 0) > 0 and "saves_to_searches" in r,
      f"saves/searches {r.get('saves_to_searches')}, relevance {r.get('relevance')}, criteria/search {r.get('criteria_per_search')}", t)

# Error paths: clear JSON errors, never a crash
code, r = call("GET", "/api/schools/does-not-exist")
check("error: unknown school -> 404 JSON", code == 404 and "detail" in r, str(r))
code, r = call("POST", "/api/turn", {"session_id": sid, "event": {"type": "compare", "school_ids": ["nope", target]}})
check("error: bad compare -> 400 JSON", code == 400 and "detail" in r, str(r)[:80])
code, r = call("POST", "/api/turn", {"event": {"type": "dance"}})
check("error: unknown event type -> 422 JSON", code == 422, str(r)[:80])
code, r = call("POST", "/api/feedback", {"session_id": sid, "school_id": target, "vote": "maybe"})
check("error: bad vote -> 422 JSON", code == 422, "")

width = max(len(n) for n, *_ in results)
for name, ok, detail, secs in results:
    print(f"{'✅' if ok else '❌'} {name:<{width}}  {f'{secs:4.1f}s' if secs else '     '}  {detail}")
passed = sum(ok for _, ok, *_ in results)
print(f"\n{passed}/{len(results)} checks passed against {BASE}")
sys.exit(0 if passed == len(results) else 1)
