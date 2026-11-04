"""HTTP API for the parent app. Endpoints and payloads follow docs/contract.md, section 3.

    cd agent && PYTHONPATH=. uvicorn gs_agent.api:app --port 8000
"""

import json
import logging
import os
import queue
import threading
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import profile, programs, search, store
from .agent import GuidedSession

log = logging.getLogger("gs_agent.api")
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
    type: Literal["query", "answer", "compare", "chip_edit"]
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
    response["elapsed_ms"] = int((time.time() - started) * 1000)
    # Numbers this session's replies, so the parent can rate a reply (POST /api/feedback with `turn`)
    session.turn_count = getattr(session, "turn_count", 0) + 1
    response["turn"] = session.turn_count
    log.info("turn %s %s %dms", session.session_id, event.type, response["elapsed_ms"])
    return response


@app.post("/api/turn")
def turn(request: TurnRequest) -> dict:
    return _run_turn(_session(request.session_id), request.event)


@app.post("/api/turn/stream")
def turn_stream(request: TurnRequest) -> StreamingResponse:
    """Same as /api/turn, as server-sent events: `progress` events while the agent works
    (the "I checked this for you" trace), then one `result` event, or an `error` event.
    From Sanchit's PR #1."""
    session = _session(request.session_id)
    events: queue.Queue = queue.Queue()

    def work() -> None:
        session.on_progress = lambda text: events.put({"type": "progress", "text": text})
        try:
            events.put({"type": "result", "response": _run_turn(session, request.event)})
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

    def stream():
        while (item := events.get()) is not None:
            yield f"event: {item['type']}\ndata: {json.dumps(item)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/saved")
def save(request: SaveRequest) -> dict:
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
    school = search.get_school(school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="Unknown school")
    session = _sessions.get(session_id) if session_id else None
    needs = [dict(n) for n in session.needs] if session else []
    return {**school, "profile": profile.build(school, needs)}


@app.get("/api/metrics")
def get_metrics() -> dict:
    return store.metrics()
