"""HTTP API for the parent app. Endpoints and payloads follow docs/contract.md, section 3.

    cd agent && PYTHONPATH=. uvicorn gs_agent.api:app --port 8000
"""

import logging
import os
import threading
import time
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import search, store
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
    session_id: str
    school_id: str
    vote: Literal["up", "down"]


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "sessions": len(_sessions)}


@app.post("/api/turn")
def turn(request: TurnRequest) -> dict:
    session = _session(request.session_id)
    started = time.time()
    with _locks[session.session_id]:  # one turn at a time per conversation
        try:
            response = session.handle(request.event.model_dump(exclude_none=True))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if request.event.type in ("query", "answer", "chip_edit") and session.last:
        try:
            store.record_search(session.session_id, len(session.needs), len(session.last["results"]))
        except Exception:
            log.exception("could not record search metric")
    response["elapsed_ms"] = int((time.time() - started) * 1000)
    log.info("turn %s %s %dms", session.session_id, request.event.type, response["elapsed_ms"])
    return response


@app.post("/api/saved")
def save(request: SaveRequest) -> dict:
    school = search.get_school(request.school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="Unknown school")
    store.save_school(request.session_id, request.school_id, school.get("name"))
    if request.session_id in _sessions:
        _sessions[request.session_id].saved.add(request.school_id)
    return {"saved": store.saved_schools(request.session_id)}


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
    store.record_feedback(request.session_id, request.school_id, request.vote)
    return {"ok": True}


@app.get("/api/schools/{school_id}")
def school_profile(school_id: str) -> dict:
    """Full record for the profile view (P3), without the embedding."""
    school = search.get_school(school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="Unknown school")
    return school


@app.get("/api/metrics")
def get_metrics() -> dict:
    return store.metrics()
