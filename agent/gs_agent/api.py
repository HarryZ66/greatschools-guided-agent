"""HTTP API for the parent app. Endpoints and payloads follow docs/contract.md, section 3.

    cd agent && PYTHONPATH=. uvicorn gs_agent.api:app --port 8000

The same app runs in two places (docs/decisions.md, 025):
- on Fargate as the public API. With AGENT_RUNTIME_ARN set, it runs agent turns, and anything that
  needs a conversation's state, on AgentCore Runtime instead of in this process;
- on Amazon Bedrock AgentCore Runtime (RUNNING_ON=agentcore, port 8080), where `/ping` and
  `/invocations` serve those calls, one AgentCore session per parent's conversation.
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import profile, programs, search, store
from . import runtime_client as rc
from .agent import GuidedSession

log = logging.getLogger("gs_agent.api")
ON_AGENTCORE = os.environ.get("RUNNING_ON") == "agentcore"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="GreatSchools Guided Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Always answer in JSON, so the frontend can show a message instead of failing to parse."""
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={
        "detail": "Something went wrong on our side. Please try again, or start a new search.",
        "error": type(exc).__name__,
    })


# Sessions live in memory: one agent conversation per parent. Fine for a single
# hackathon task; production would persist conversation state (e.g. in DynamoDB).
_sessions: dict[str, GuidedSession] = {}
_locks: dict[str, threading.Lock] = {}


def _session(session_id: str | None) -> GuidedSession:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    session = GuidedSession(session_id)
    if session_id:  # a session we lost (e.g. after a restart): its saves are still in DynamoDB
        try:
            session.saved = {s["school_id"] for s in store.saved_schools(session_id)}
        except Exception:
            log.exception("could not load saved schools for %s", session_id)
    _sessions[session.session_id] = session
    _locks[session.session_id] = threading.Lock()
    return session


class Event(BaseModel):
    type: Literal["query", "answer", "compare", "chip_edit", "new_search"]
    text: str | None = None
    question_id: str | None = None
    option_id: str | None = None
    school_ids: list[str] | None = None
    need: str | None = None
    mode: Literal["require", "prefer", "avoid"] | None = None
    value: Any = None
    removed: bool | None = None


class TurnRequest(BaseModel):
    session_id: str | None = None
    event: Event


class SaveRequest(BaseModel):
    session_id: str
    school_id: str


class FeedbackRequest(BaseModel):
    """A thumbs vote on one agent reply (`turn`, from the response) or on one school (`school_id`)."""
    session_id: str
    vote: Literal["up", "down"]
    turn: int | None = None
    school_id: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "sessions": len(_sessions)}


def _run_turn(session: GuidedSession, event: Event) -> dict:
    started = time.time()
    with _locks[session.session_id]:  # one turn at a time per conversation
        try:
            response = session.handle(event.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    # Count a search only when one ran this turn, so guide questions don't skew saves-to-searches.
    searched = event.type == "chip_edit" or (event.type in ("query", "answer") and session.searched_this_turn)
    if searched and session.last:
        try:
            store.record_search(session.session_id, len(session.needs), len(session.last["results"]))
        except Exception:
            log.exception("could not record search metric")
    if event.type == "new_search":  # the app shows the kept list right away
        try:
            response["saved"] = store.saved_schools(session.session_id)
        except Exception:
            log.exception("could not load saved schools for %s", session.session_id)
            response["saved"] = [{"school_id": i, "name": None, "at": None} for i in sorted(session.saved)]
    response["elapsed_ms"] = int((time.time() - started) * 1000)
    if ON_AGENTCORE and isinstance(response.get("trace"), dict):
        response["trace"]["steps"].insert(0, {
            "tool": "runtime", "service": "Amazon Bedrock AgentCore Runtime",
            "text": "Ran this turn in your own AgentCore Runtime session, which keeps our conversation between turns"})
    # Numbers this session's replies, so the parent can rate a reply (POST /api/feedback with `turn`)
    session.turn_count = getattr(session, "turn_count", 0) + 1
    response["turn"] = session.turn_count
    log.info("turn %s %s %dms", session.session_id, event.type, response["elapsed_ms"])
    return response


# If AgentCore Runtime can't be reached, the API runs the call itself (decision 031): this task has
# the same code and permissions. After a failure it skips the runtime for a while, so parents
# don't each wait for the same timeout; the conversation starts over, the saved list doesn't.
RUNTIME_RETRY_AFTER_S = 120
_runtime_down_until = 0.0
FALLBACK_STEP = {"tool": "fallback", "service": "Amazon ECS on Fargate",
                 "text": "AgentCore Runtime didn't answer, so this turn ran on our Fargate service instead"}


def _use_runtime() -> bool:
    return rc.enabled() and time.time() >= _runtime_down_until


def _runtime_failed(op: str, session_id: str) -> None:
    global _runtime_down_until
    _runtime_down_until = time.time() + RUNTIME_RETRY_AFTER_S
    log.warning("AgentCore Runtime unreachable (%s, session %s); running on Fargate for %ss",
                op, session_id, RUNTIME_RETRY_AFTER_S)


def _with_fallback_step(response: dict) -> dict:
    if isinstance(response.get("trace"), dict):
        response["trace"]["steps"].insert(0, dict(FALLBACK_STEP))
    return response


def _remote(op: str, session_id: str, body: dict) -> dict:
    """Run one operation on the conversation's AgentCore Runtime session.

    Raises rc.RuntimeUnreachable when the runtime didn't answer, so the caller can run it locally;
    errors the runtime returned on purpose (unknown school, bad request) go to the parent app.
    """
    try:
        return rc.invoke(op, session_id, body)
    except rc.RuntimeUnreachable:
        _runtime_failed(op, session_id)
        raise
    except rc.RuntimeCallError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


def _remote_turn_body(request: TurnRequest) -> tuple[str, dict]:
    # The API names new conversations, so the first turn already has an AgentCore session id
    session_id = request.session_id or uuid.uuid4().hex[:12]
    return session_id, {"request": {"session_id": session_id, "event": request.event.model_dump(exclude_none=True)}}


@app.post("/api/turn")
def turn(request: TurnRequest) -> dict:
    if _use_runtime():
        session_id, body = _remote_turn_body(request)
        try:
            return _remote("turn", session_id, body)
        except rc.RuntimeUnreachable:
            return _with_fallback_step(_run_turn(_session(session_id), request.event))
    return _run_turn(_session(request.session_id), request.event)


@app.post("/api/turn/stream")
def turn_stream(request: TurnRequest) -> StreamingResponse:
    """Same as /api/turn, as server-sent events: `progress` events while the agent works
    (the "I checked this for you" trace), then one `result` event, or an `error` event.
    From Sanchit's PR #1."""
    if _use_runtime():
        return _remote_stream(request, *_remote_turn_body(request))
    return StreamingResponse(_local_stream(_session(request.session_id), request.event),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _local_stream(session: GuidedSession, event: Event, fallback: bool = False):
    """Server-sent events for a turn run in this process: progress, then the result or an error."""
    events: queue.Queue = queue.Queue()

    def work() -> None:
        session.on_progress = lambda text: events.put({"type": "progress", "text": text})
        try:
            response = _run_turn(session, event)
            events.put({"type": "result", "response": _with_fallback_step(response) if fallback else response})
        except HTTPException as e:
            events.put({"type": "error", "status": e.status_code, "detail": e.detail})
        except Exception:
            log.exception("streamed turn failed for %s", session.session_id)
            events.put({"type": "error", "status": 500,
                        "detail": "Something went wrong on our side. Please try again, or start a new search."})
        finally:
            session.on_progress = None
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (item := events.get()) is not None:
        yield _sse(item)


def _sse(item: dict) -> str:
    return f"event: {item['type']}\ndata: {json.dumps(item)}\n\n"


def _remote_stream(request: TurnRequest, session_id: str, body: dict) -> StreamingResponse:
    """A streamed turn on AgentCore Runtime: its server-sent events pass through unchanged.

    If the runtime fails before sending anything, the turn runs here instead (decision 031).
    Once events have reached the parent, a failure is reported as an error event.
    """
    def stream():
        sent = False
        try:
            for chunk in rc.invoke_stream(session_id, body):
                sent = True
                yield chunk
        except Exception as e:
            if not sent:
                if not isinstance(e, rc.RuntimeUnreachable):
                    log.exception("streamed AgentCore turn failed for %s", session_id)
                _runtime_failed("turn_stream", session_id)
                yield from _local_stream(_session(session_id), request.event, fallback=True)
            elif isinstance(e, rc.RuntimeCallError):
                yield _sse({"type": "error", "status": e.status, "detail": e.detail})
            else:
                log.exception("streamed AgentCore turn failed for %s", session_id)
                yield _sse({"type": "error", "status": 502,
                            "detail": "Something went wrong on our side. Please try again, or start a new search."})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/saved")
def save(request: SaveRequest) -> dict:
    if _use_runtime():  # programs for this school depend on the conversation's needs
        try:
            return _remote("save", request.session_id, {"request": request.model_dump()})
        except rc.RuntimeUnreachable:
            pass  # save it here; DynamoDB holds the list either way
    school = search.get_school(request.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="Unknown school")
    store.save_school(request.session_id, request.school_id, school.get("name"))
    session = _sessions.get(request.session_id)
    if session:
        session.saved.add(request.school_id)
    # Programs that fill this school's gaps for this parent's needs (code only, no model call)
    pairs = []
    if session and session.needs:
        try:
            pairs = programs.for_saved_school(request.school_id, school, session.needs)
        except Exception:
            log.exception("could not match programs for %s", request.school_id)
    return {"saved": store.saved_schools(request.session_id), "programs": pairs}


@app.get("/api/saved")
def list_saved(session_id: str) -> dict:
    return {"saved": store.saved_schools(session_id)}


@app.delete("/api/saved/{school_id}")
def unsave(school_id: str, session_id: str) -> dict:
    if _use_runtime():
        try:
            return _remote("unsave", session_id, {"school_id": school_id, "session_id": session_id})
        except rc.RuntimeUnreachable:
            pass
    store.unsave_school(session_id, school_id)
    if session_id in _sessions:
        _sessions[session_id].saved.discard(school_id)
    return {"saved": store.saved_schools(session_id)}


@app.post("/api/feedback")
def feedback(request: FeedbackRequest) -> dict:
    if request.turn is None and not request.school_id:
        raise HTTPException(status_code=400, detail="Send the reply's turn or a school_id")
    store.record_feedback(request.session_id, request.vote, school_id=request.school_id, turn=request.turn)
    return {"ok": True}


@app.get("/api/schools/{school_id}")
def school_profile(school_id: str, session_id: str | None = None) -> dict:
    """The school's record plus a verified `profile` (P3), built in code with no model call.

    With a session_id, the profile checks that parent's needs, the same way the cards do.
    """
    if session_id and _use_runtime():
        try:
            return _remote("profile", session_id, {"school_id": school_id, "session_id": session_id})
        except rc.RuntimeUnreachable:
            pass
    school = search.get_school(school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="Unknown school")
    session = _sessions.get(session_id) if session_id else None
    needs = [dict(n) for n in session.needs] if session else []
    return {**school, "profile": profile.build(school, needs)}


@app.get("/api/metrics")
def get_metrics() -> dict:
    return store.metrics()


# ------------------------------------------------ Amazon Bedrock AgentCore Runtime service contract

@app.get("/ping")
def ping() -> dict:
    return {"status": "HealthyBusy" if any(lock.locked() for lock in _locks.values()) else "Healthy"}


@app.post("/invocations")
def invocations(payload: dict):
    """Calls from the public API (runtime_client.py): {"op": ..., ...}.

    Errors come back as {"_error": {status, detail}} so the API can pass them on to the parent app.
    """
    op = payload.get("op")
    try:
        if op == "turn":
            return turn(TurnRequest(**payload["request"]))
        if op == "turn_stream":
            return turn_stream(TurnRequest(**payload["request"]))
        if op == "save":
            return save(SaveRequest(**payload["request"]))
        if op == "unsave":
            return unsave(payload["school_id"], payload["session_id"])
        if op == "profile":
            return school_profile(payload["school_id"], payload["session_id"])
        raise HTTPException(status_code=400, detail=f"Unknown operation: {op}")
    except HTTPException as e:
        return {"_error": {"status": e.status_code, "detail": e.detail}}
