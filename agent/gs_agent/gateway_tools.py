"""MCP tools behind the AgentCore Gateway: one Lambda function (decision 027).

The Gateway lists the tools in gateway_tools.json and calls this handler with the tool's arguments
as the event; the tool name arrives in the client context as "<target>___<tool>". These are the
agent's stateless data lookups, the same code the agent runs in-process when GATEWAY_URL is unset.
Per-conversation work (needs, checks, ranking) stays in the agent.
"""

import json
import logging
from pathlib import Path

from . import programs as P
from . import search

log = logging.getLogger("gs_agent.gateway_tools")
log.setLevel(logging.INFO)

SCHEMAS = json.loads((Path(__file__).with_name("gateway_tools.json")).read_text())
TOOL_NAMES = [t["name"] for t in SCHEMAS]


def run(tool: str, args: dict):
    """Run one tool locally. The Lambda handler and the in-process path both use this."""
    if tool == "lookup_guide":
        return search.lookup_content(args["question"])
    if tool == "search_programs":
        return P.find_programs(args["interest"], args.get("city", ""), args.get("near_school_id", ""),
                               args.get("grades"), args.get("time_from", ""), args.get("time_to", ""))
    if tool == "find_school_by_name":
        return search.find_by_name(args["name"])
    if tool == "get_school":
        return search.get_school(args["school_id"])
    raise ValueError(f"Unknown tool: {tool}")


def handler(event, context):
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    tool = custom.get("bedrockAgentCoreToolName", "").split("___")[-1]
    log.info("tool %s", tool)
    try:
        # Wrapped in an object so lists and empty results come back the same way
        return json.loads(json.dumps({"result": run(tool, event or {})}, default=str))
    except Exception as e:
        log.exception("tool %s failed", tool)
        return {"error": f"{type(e).__name__}: {e}"}
