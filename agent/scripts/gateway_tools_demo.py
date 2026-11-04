"""Lists the AgentCore Gateway's MCP tools and calls one (decision 027).

    AWS_PROFILE=gs-sandbox python agent/scripts/gateway_tools_demo.py

Reads the Gateway URL from infra/cdk-outputs-app.json and signs MCP requests with your AWS
credentials (the Gateway uses IAM inbound auth).
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_agent import gateway_client as G  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def main() -> None:
    G.GATEWAY_URL = json.loads((REPO / "infra" / "cdk-outputs-app.json").read_text())["GsAppStack"]["GatewayUrl"]
    print(f"Gateway: {G.GATEWAY_URL}\n")
    client = G.MCPClient(G._transport)
    with client:
        tools = client.list_tools_sync()
        print(f"{len(tools)} MCP tools:")
        for t in tools:
            print(f"  - {t.tool_name}")
        result = client.call_tool_sync(tool_use_id=uuid.uuid4().hex, name=f"{G.TARGET}___lookup_guide",
                                       arguments={"question": "What is a charter school?"})
    entries = json.loads(result["content"][0]["text"])["result"]
    print(f"\nCalled {G.TARGET}___lookup_guide('What is a charter school?'): {result['status']}")
    for e in entries[:3]:
        print(f"  - {e['title']}")


if __name__ == "__main__":
    main()
