"""Shows that the agent runtime only answers callers with an OAuth token (decision 026).

    AWS_PROFILE=gs-sandbox python agent/scripts/check_front_door.py

Reads the runtime ARN and OAuth settings from infra/cdk-outputs-app.json and the client secret from
Secrets Manager (never printed). Tries four calls: no token, a made-up token, an IAM-signed call
(SigV4), then a real Cognito token. Only the last one should get through. The test operation is
an unknown one, so no model is called.
"""

import json
import sys
from pathlib import Path

import boto3
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gs_agent import runtime_client as rc  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
REGION = "us-east-1"


def main() -> int:
    out = json.loads((REPO / "infra" / "cdk-outputs-app.json").read_text())["GsAppStack"]
    arn = out["AgentRuntimeArn"]
    url = rc.invocation_url(arn, REGION)
    body = json.dumps({"op": "front-door-check"}).encode()
    session = rc.runtime_session_id("front-door-check-0001")
    http = urllib3.PoolManager()

    def call(label: str, token: str | None) -> int:
        headers = {"Content-Type": "application/json", rc.SESSION_HEADER: session}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = http.request("POST", url, body=body, headers=headers)
        print(f"{label:<34} HTTP {r.status}  {r.data[:160].decode(errors='replace')}")
        return r.status

    print(f"Runtime: {arn}\n")
    results = [call("1. No token", None) in (401, 403),
               call("2. Made-up token", "not-a-real-token") in (401, 403)]

    try:
        boto3.client("bedrock-agentcore", region_name=REGION).invoke_agent_runtime(
            agentRuntimeArn=arn, runtimeSessionId=session, payload=body)
        print(f"{'3. IAM-signed call (SigV4)':<34} accepted")
        results.append(False)
    except Exception as e:  # botocore.exceptions.ClientError
        print(f"{'3. IAM-signed call (SigV4)':<34} rejected: {str(e)[:140]}")
        results.append(True)

    secret = boto3.client("secretsmanager", region_name=REGION).get_secret_value(
        SecretId=out["OAuthClientSecretArn"])["SecretString"]
    rc.OAUTH_TOKEN_URL, rc.OAUTH_CLIENT_ID, rc.OAUTH_SCOPE = out["OAuthTokenUrl"], out["OAuthClientId"], out["OAuthScope"]
    rc.OAUTH_CLIENT_SECRET = secret
    results.append(call("4. Cognito access token", rc.access_token()) == 200)

    print("\nFront door locked: only the call with a valid token got through." if all(results)
          else "\nUnexpected result: check the runtime's authorizer configuration.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
