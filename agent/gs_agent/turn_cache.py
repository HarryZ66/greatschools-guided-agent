"""A shared cache of first-turn answers (decision 036).

On AgentCore Runtime every parent's conversation runs in its own microVM, so a cache has to live
outside the process: it's in the app's DynamoDB table. When a parent's first message matches one
another parent sent today (same words, ignoring case and punctuation), the agent reuses that
checked answer instead of calling the model. Entries last until midnight UTC, so a data refresh
or a program's date never serves a stale answer for long.

Not cached: messages on sensitive topics (routing.sensitive), answers that fell back or needed
the strong model's retry, and anything when TURN_CACHE=off (the evals turn it off so they keep
measuring the model). A cache failure never fails a turn.
"""

import base64
import hashlib
import json
import logging
import os
import re
import zlib
from datetime import datetime, timedelta, timezone

from . import routing, store

log = logging.getLogger("gs_agent.turn_cache")
VERSION = "1"  # bump when the cached shape or the agent's behavior changes
MAX_BYTES = 350_000  # DynamoDB items hold 400 KB


def enabled() -> bool:
    return os.environ.get("TURN_CACHE", "on") != "off" and bool(os.environ.get("TABLE_NAME"))


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", (text or "").lower()))


def key(text: str, now: datetime | None = None) -> str:
    day = (now or datetime.now(timezone.utc)).date().isoformat()
    models = f"{routing.MAIN_MODEL}|{routing.FAST_MODEL}|{routing.STRONG_MODEL}"
    return hashlib.sha256(f"{VERSION}|{day}|{models}|{normalize(text)}".encode()).hexdigest()


def pack(value: dict) -> str:
    return base64.b64encode(zlib.compress(json.dumps(value, default=str).encode(), 9)).decode()


def unpack(data: str) -> dict:
    return json.loads(zlib.decompress(base64.b64decode(data)))


def get(text: str) -> dict | None:
    if not enabled() or routing.sensitive(text):
        return None
    try:
        data = store.cache_get(key(text))
        return unpack(data) if data else None
    except Exception:
        log.exception("turn cache read failed")
        return None


def put(text: str, value: dict) -> None:
    if not enabled() or routing.sensitive(text):
        return
    try:
        data = pack(value)
        if len(data) > MAX_BYTES:
            log.info("turn cache: answer too large to cache (%d bytes)", len(data))
            return
        midnight = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        store.cache_put(key(text), data, int(midnight.timestamp()))
    except Exception:
        log.exception("turn cache write failed")
