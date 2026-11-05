"""Conversations that outlive their process, in AgentCore Memory (decision 036).

Each parent's conversation runs in its own AgentCore Runtime microVM, which ends after 30 idle
minutes, 8 hours, or a deploy. After every turn the API saves the conversation's state
(GuidedSession.snapshot: needs, results, the open question, the model's history) as one
short-term memory event. When a turn arrives for a conversation this process doesn't have, it
loads the newest event and carries on where the parent left off.

The memory has no extraction strategies: it summarizes nothing and keeps nothing past the
conversation, and events expire after 7 days. actorId stands for the parent (the session id,
since login is out of scope) and sessionId for the conversation. A memory failure never fails
a turn: the parent just starts a fresh conversation, with their saved list (DynamoDB) intact.
"""

import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

import boto3

from .config import REGION
from .turn_cache import pack, unpack

log = logging.getLogger("gs_agent.memory")
SERVICE = "Amazon Bedrock AgentCore Memory"
# The blob is a plain string: an object comes back from the service as a Java-style map string
# ("{v=1, z=...}"), which loses its JSON. A version prefix leaves room to change the format.
PREFIX = "v1:"


def memory_id() -> str | None:
    return os.environ.get("MEMORY_ID") or None


def enabled() -> bool:
    return bool(memory_id()) and os.environ.get("SESSION_MEMORY", "on") != "off"


@lru_cache(maxsize=1)
def _client():
    return boto3.Session(region_name=REGION).client("bedrock-agentcore")


def _ids(session_id: str) -> dict:
    return {"memoryId": memory_id(), "actorId": f"parent-{session_id}", "sessionId": session_id}


def save(session_id: str, state: dict) -> None:
    if not enabled():
        return
    try:
        _client().create_event(**_ids(session_id), eventTimestamp=datetime.now(timezone.utc),
                               payload=[{"blob": PREFIX + pack(state)}])
    except Exception:
        log.exception("could not save conversation %s to memory", session_id)


def load(session_id: str) -> dict | None:
    """The newest saved state of this conversation, or None."""
    if not enabled():
        return None
    try:
        ids, newest, token = _ids(session_id), None, None
        while True:  # the API doesn't promise an order, so find the newest event ourselves
            page = _client().list_events(**ids, includePayloads=False, maxResults=100,
                                         **({"nextToken": token} if token else {}))
            for event in page.get("events", []):
                if newest is None or event["eventTimestamp"] >= newest["eventTimestamp"]:
                    newest = event
            token = page.get("nextToken")
            if not token:
                break
        if newest is None:
            return None
        blob = _client().get_event(**ids, eventId=newest["eventId"])["event"]["payload"][0]["blob"]
        if not isinstance(blob, str) or not blob.startswith(PREFIX):
            log.warning("conversation %s has a saved state in an unknown format; starting fresh", session_id)
            return None
        return unpack(blob[len(PREFIX):])
    except Exception:
        log.exception("could not load conversation %s from memory", session_id)
        return None
