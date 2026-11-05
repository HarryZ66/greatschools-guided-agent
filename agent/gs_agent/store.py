"""DynamoDB persistence for saved schools, feedback and the metrics GreatSchools tracks.

Single table (see infra/stacks/data_stack.py):
    pk = SESSION#<id>   sk = SAVED#<school_id> | FEEDBACK#TURN#<n> or FEEDBACK#<school_id> | SEARCH#<iso time>
                        | VISIT#<request id> (a visit or call request to a local partner, decision 042)
    pk = CACHE#<key>    sk = TURN (a cached first-turn answer, with `expires`)
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Key

from .config import REGION, REPO_ROOT


def table_name() -> str:
    if os.environ.get("TABLE_NAME"):
        return os.environ["TABLE_NAME"]
    outputs = json.loads((REPO_ROOT / "infra" / "cdk-outputs.json").read_text())
    return outputs["GsDataStack"]["TableName"]


@lru_cache(maxsize=1)
def _table():
    return boto3.Session(region_name=REGION).resource("dynamodb").Table(table_name())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _pk(session_id: str) -> str:
    return f"SESSION#{session_id}"


def save_school(session_id: str, school_id: str, name: str | None = None) -> None:
    _table().put_item(Item={"pk": _pk(session_id), "sk": f"SAVED#{school_id}", "school_id": school_id,
                            "name": name or school_id, "at": _now()})


def unsave_school(session_id: str, school_id: str) -> None:
    _table().delete_item(Key={"pk": _pk(session_id), "sk": f"SAVED#{school_id}"})


def saved_schools(session_id: str) -> list[dict]:
    items = _table().query(KeyConditionExpression=Key("pk").eq(_pk(session_id)) & Key("sk").begins_with("SAVED#"))
    return [{"school_id": i["school_id"], "name": i.get("name"), "at": i["at"]} for i in items["Items"]]


def save_visit(session_id: str, request: dict) -> None:
    _table().put_item(Item={"pk": _pk(session_id), "sk": f"VISIT#{request['request_id']}", **request, "at": _now()})


def visits(session_id: str) -> list[dict]:
    items = _table().query(KeyConditionExpression=Key("pk").eq(_pk(session_id)) & Key("sk").begins_with("VISIT#"))
    keep = ("request_id", "partner_id", "partner_name", "way", "way_label", "when", "language", "schools", "note",
            "status", "reply_by", "sample", "at")
    return sorted(({k: i[k] for k in keep if k in i} for i in items["Items"]), key=lambda v: v.get("at", ""))


def record_feedback(session_id: str, vote: str, school_id: str | None = None, turn: int | None = None) -> None:
    """One vote per reply (or per school) per session; a new vote replaces the old one."""
    target = {"turn": turn} if turn is not None else {"school_id": school_id}
    key = f"TURN#{turn}" if turn is not None else school_id
    _table().put_item(Item={"pk": _pk(session_id), "sk": f"FEEDBACK#{key}", **target, "vote": vote, "at": _now()})


def record_search(session_id: str, criteria_count: int, result_count: int) -> None:
    _table().put_item(Item={"pk": _pk(session_id), "sk": f"SEARCH#{_now()}",
                            "criteria_count": criteria_count, "result_count": result_count})


def metrics() -> dict:
    """GreatSchools' metrics: saves-to-searches (primary), thumbs relevance, criteria per search, visit requests.

    A full scan is fine at hackathon scale; production would aggregate with streams.
    """
    searches = saves = up = down = criteria = visits_ = 0
    kwargs: dict = {}
    while True:
        page = _table().scan(**kwargs)
        for item in page["Items"]:
            sk = item["sk"]
            if sk.startswith("SEARCH#"):
                searches += 1
                criteria += int(item.get("criteria_count", Decimal(0)))
            elif sk.startswith("SAVED#"):
                saves += 1
            elif sk.startswith("VISIT#"):
                visits_ += 1
            elif sk.startswith("FEEDBACK#"):
                up += item.get("vote") == "up"
                down += item.get("vote") == "down"
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return {
        "searches": searches,
        "saves": saves,
        "saves_to_searches": round(saves / searches, 3) if searches else None,
        "thumbs_up": up,
        "thumbs_down": down,
        "relevance": round(up / (up + down), 3) if up + down else None,
        "criteria_per_search": round(criteria / searches, 2) if searches else None,
        "visit_requests": visits_,  # the step after saving: a visit or call with a local partner
    }


# ---------------------------------------------------------------- first-turn answer cache (decision 036)
# pk = CACHE#<sha256 of the normalized message, day and models>, sk = TURN. `expires` is epoch
# seconds: reads ignore expired items, and the table's TTL deletes them.

def cache_get(key: str) -> str | None:
    item = _table().get_item(Key={"pk": f"CACHE#{key}", "sk": "TURN"}).get("Item")
    if not item or int(item.get("expires", 0)) <= int(datetime.now(timezone.utc).timestamp()):
        return None
    return item["data"]


def cache_put(key: str, data: str, expires: int) -> None:
    _table().put_item(Item={"pk": f"CACHE#{key}", "sk": "TURN", "data": data, "expires": expires})
