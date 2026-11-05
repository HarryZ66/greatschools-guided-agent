# Technical guide

How the GreatSchools Guided Agent is built, deployed, tested and secured. For what it does for
parents, see [`features.md`](features.md). For why things are the way they are, see
[`decisions.md`](decisions.md). The API and UI blocks are defined in [`contract.md`](contract.md).

## In short

A Python agent (Strands Agents on Amazon Bedrock) runs on Amazon Bedrock AgentCore Runtime behind a
FastAPI service on Fargate. It searches schools in Amazon OpenSearch Service and stores saves,
feedback and metrics in DynamoDB. A React app is served from S3 through CloudFront. AWS CDK
(Python) defines every resource, and merging to `main` deploys through GitHub Actions.

> **The model understands; code decides** (decision 002). The model reads the parent's words, picks
> tools and writes the chips, the question and the message. Code decides every status, score,
> trade-off, piece of evidence and cost estimate.

## Repository layout

| Path | What's there |
|---|---|
| `infra/` | AWS CDK app (Python) that defines every AWS resource |
| `agent/` | Python agent (Strands Agents on Amazon Bedrock), its tools and the FastAPI service |
| `frontend/` | React app for parents, connected to the agent API (see [`frontend/README.md`](../frontend/README.md)) |
| `data/` | Synthetic data generators, ingestion scripts and the parent guide |
| `evals/` | Test queries and evaluation scripts |
| `docs/` | This guide, features, pain points, contract, decisions and next steps |

## Choices we made

GreatSchools left these open (see the tech brief). Reasons are in [`decisions.md`](decisions.md).

| Area | Our choice |
|---|---|
| Language | Python for the agent, API, data scripts and infrastructure; React for the parent app |
| Model | Claude Sonnet 5.5 on Bedrock for every turn (decision 040), with prompt caching. Set `MAIN_MODEL` to an empty string for the cheaper tiers: Haiku 5.5 for most turns, Sonnet 5.5 for sensitive or failed ones (decision 034). Titan Text Embeddings v2 for semantic search |
| How agentic | A guided agent. The model picks its tools (school search, school profile, find by name, parent guide, programs), asks at most one question per turn, spots gaps and suggests needs. Code decides every status, score, trade-off and piece of evidence. At most 6 tool calls per turn |
| Agent framework | Strands Agents |
| Compute | The agent runs on Amazon Bedrock AgentCore Runtime, one session per conversation (decision 025). The public API is one ARM64 Fargate task behind an ALB, reached only through CloudFront and AWS WAF. If AgentCore Runtime is down, Fargate runs the turn itself (decision 038) |
| Infrastructure as code | AWS CDK (Python) |
| Frontend | React + Vite single-page app served from S3 through CloudFront |
| Scope | Schools, plus library and community programs that fill a school's gaps (decision 010) |

## AWS services

| Service | Role |
|---|---|
| Amazon Bedrock | Claude models for the agent, Titan Text Embeddings v2 for semantic search |
| Amazon OpenSearch Service | Keyword and vector search over school, program and guide documents |
| Amazon DynamoDB | Session state, saved schools, thumbs up/down feedback, visit requests and metrics |
| Amazon S3 | Data files and the frontend site |
| Amazon Bedrock AgentCore Runtime | Runs the agent: each parent's conversation in its own warm session |
| Amazon Bedrock AgentCore Memory | Short-term memory: each conversation's state after every turn, so a new session picks it up after an idle timeout or a deploy (decision 037) |
| Amazon ECS on AWS Fargate (ARM64) | Runs the public API, which passes agent turns to AgentCore Runtime |
| Elastic Load Balancing (ALB) | Routes traffic to the API task |
| Amazon CloudFront | One HTTPS URL: `/api/*` goes to the API, everything else to the frontend |
| Amazon ECR | Stores the agent image (created by CDK) |
| AWS WAF | Rate limit on agent turns and IP reputation blocking at CloudFront |
| Amazon Cognito + AgentCore Identity | OAuth front door on the agent runtime: only the API's access tokens get in (decision 026) |
| AWS Secrets Manager | The API's OAuth client secret |
| Amazon Bedrock AgentCore Gateway + AWS Lambda | The agent's data lookups as 4 MCP tools (guide, programs, school by name, school record), IAM-protected (decision 027) |
| Amazon Bedrock Knowledge Bases + Amazon S3 Vectors | The parent guide as one S3 document per entry; guide answers cite the document they came from (decision 028) |
| Amazon CloudWatch | Container logs (14 days), WAF metrics, and AgentCore Observability: agent traces, spans and logs through Transaction Search |

All resources are in `us-east-1`.

```
Browser ──HTTPS──▶ CloudFront ──/api/*──▶ ALB ──▶ Fargate task (FastAPI)
                       │                               │  InvokeAgentRuntime
                       └──/*──▶ S3 (frontend)          ▼
                                     AgentCore Runtime session (FastAPI + Strands agent)
                                                       ├──▶ Bedrock (Claude, Titan embeddings)
                                                       ├──▶ OpenSearch (schools, programs, guide)
                                                       ├──▶ AgentCore Gateway ──▶ Lambda tools
                                                       └──▶ DynamoDB (saves, feedback, metrics)
```

### Stacks

| Stack | What it holds |
|---|---|
| `GsDataStack` | OpenSearch domain, DynamoDB table, data bucket |
| `GsAppStack` | VPC, Fargate API, ALB, CloudFront, WAF, site bucket, AgentCore Runtime, Memory, Gateway, Cognito |
| `GsKnowledgeStack` | Bedrock Knowledge Base for the parent guide, on S3 Vectors |
| `GsCiStack` | GitHub OIDC trust and the deploy and evals roles |

## Deploy

Prerequisites: Python 3.12+, Node.js 22+, AWS CLI v2, AWS CDK CLI, a Docker-compatible
runtime (Docker Desktop, Finch or Colima) and AWS credentials for the target account.

Merging to `main` deploys `GsDataStack` and `GsAppStack` through GitHub Actions (see
[CI/CD](#cicd)). To deploy by hand:

```bash
cd infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap        # once per account and region
cdk deploy --all     # GsDataStack (search, table, bucket) then GsAppStack (agent + site)
```

The app URL is printed as `GsAppStack.AppUrl`. Build the frontend first (`npm run build` in
`frontend/`, which writes `frontend/dist`); without a build, a small API test page from
`frontend/placeholder/` is served.

To tear everything down:

```bash
cdk destroy --all
```

## Load data

All schools, programs and partners are made up. Records carry `"synthetic_generated": true`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r agent/requirements.txt
.venv/bin/python data/generate.py --count 80            # synthetic Miami-area schools
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 \
  .venv/bin/python data/ingest.py data/generated/schools_generated.json --recreate
```

Programs (library and community events) follow the sample's program format:

```bash
.venv/bin/python data/generate_programs.py --count 36          # synthetic Miami-area programs
cd data && AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 \
  ../.venv/bin/python ingest_programs.py generated/programs_generated.json --recreate
```

The parent guide (terms, how GreatSchools ratings work, what the app's labels mean) lives in
`data/content/guide.json`. Entries are short summaries written by the team for this demo;
GreatSchools would review them before real use.

```bash
cd data && AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 ../.venv/bin/python ingest_content.py content/guide.json --recreate
```

The same guide also goes into an Amazon Bedrock Knowledge Base (decision 028). `cdk deploy
GsKnowledgeStack` uploads one markdown file per entry (with a `.metadata.json` sidecar) to S3,
creates the knowledge base on S3 Vectors and starts an ingestion job. Turn it on for the agent with
`cdk deploy GsAppStack -c knowledge_base_id=<GsKnowledgeStack.KnowledgeBaseId>`, or locally with
`KNOWLEDGE_BASE_ID=<id>`. Check it with one live Retrieve (`--sync` re-ingests first):

```bash
(cd infra && cdk deploy GsKnowledgeStack --outputs-file cdk-outputs-knowledge.json)
AWS_PROFILE=<profile> AWS_REGION=us-east-1 .venv/bin/python agent/scripts/kb_demo.py "What is a charter school?"
```

Scholarship figures come from official sources, with the source and year in
`agent/gs_agent/content/funding.json`.

## Run the agent API locally

```bash
cd agent
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 PYTHONPATH=. ../.venv/bin/uvicorn gs_agent.api:app --port 8000 --reload
```

Then run the parent app against it: `cd frontend && npm install && npm run dev`.

| Endpoint | Purpose |
|---|---|
| `POST /api/turn` | Query, answer a question, compare two schools, or edit a chip (see `contract.md`). Every response includes a `trace` of the tools and AWS services that really ran |
| `POST /api/turn/stream` | Same, as server-sent events: progress while the agent works, then the result |
| `POST /api/saved`, `GET /api/saved?session_id=`, `DELETE /api/saved/{school_id}?session_id=` | Saved list; saving returns programs that fill that school's gaps, and the agent's next question or a visit offer |
| `POST /api/visits` | Request a school visit with a local partner (checked in code, stored in DynamoDB) |
| `POST /api/feedback` | Thumbs up/down on a result |
| `GET /api/schools/{school_id}?session_id=` | School record plus a verified profile: fit checks, programs for gaps, review counts, guide terms, cost after aid |
| `GET /api/metrics` | Saves-to-searches, thumbs relevance, criteria per search, visit requests |
| `GET /api/health` | Health check |

Try it from the command line without the API:

```bash
cd agent && PYTHONPATH=. ../.venv/bin/python scripts/try_agent.py "middle school near Miami with STEM, I work until 6"
```

## CI/CD

GitHub Actions (decision 039). No AWS keys are stored in GitHub; workflows sign in with OIDC.

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every pull request | agent unit tests, frontend build, `cdk synth` |
| `evals.yml` | pull requests that change `agent/` or `evals/` | the 38 evals on Bedrock; results posted on the PR; fails below 36 passes |
| `deploy.yml` | every merge to `main`, or "Run workflow" | CI, then `cdk deploy GsDataStack GsAppStack`, then the live smoke test |

One-time setup, from `infra/`: `cdk deploy GsCiStack` creates the GitHub OIDC trust and the two
roles. To deploy to another account, deploy GsCiStack there and change `AWS_ROLE` (and
`KNOWLEDGE_BASE_ID`) in the workflows.

## Evaluation

`evals/cases.json` holds 38 parent queries across core searches, missing information, honesty,
different family needs, fairness, guide questions (P4), programs and edge cases. `evals/run_evals.py`
runs them and checks needs extraction, questions, refusals, and that every school the agent names
was returned by a tool.

```bash
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 .venv/bin/python evals/run_evals.py
```

Run with the tiers, Haiku 5.5 with Sonnet 5.5 for sensitive and failed turns (decision 034; the app
now uses Sonnet 5.5 for every turn, decision 040, and CI posts each PR's run; table in
[`evals/results/latest.md`](../evals/results/latest.md)):

| Metric | Result |
|---|---|
| Cases passed | 38 / 38 (one run) |
| Model calls on Sonnet 5.5 | 11% (the eval set is heavy on fairness and special-needs cases) |
| Estimated cost per turn | ~$0.0033, vs ~$0.017 with Sonnet 5.5 on every turn (list prices: Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10 per million input / output tokens; cache reads 10%, writes 125% of input) |

The earlier all-Sonnet run, for comparison:

| Metric | Result |
|---|---|
| Cases passed | 37 / 38. The miss: in one run of `subgroup_help_ok` the agent helped but added a needless "I can't pick schools by family income"; 3 of 3 reruns passed |
| Needs extracted correctly | 20 / 20 |
| Made-up school mentions | 0 |
| Guide answers citing a guide entry | 5 / 5 (and none for a term the guide lacks) |
| Program cases (fill a gap, interest match, past-only excluded, nothing found) | 5 / 5 |
| Errors | 0 |
| Latency per turn | median 8.1 s, max 17.2 s |
| Tokens per turn | ~14,800, 84% of input served from the prompt cache |
| Estimated cost per turn | ~$0.025 with prompt caching, vs ~$0.055 without (assuming $3 / $15 per million input / output tokens, cache reads at 10% and writes at 125% of the input price) |

Vague requests ("a good elementary school in Miami", in English and Spanish) get one question about
what the child needs: learning support, after-school care, a bus or counseling.

In 5 of 5 runs, the demo query found the library robotics club that covers Tamarind Cove's
5–6pm care gap and asked the parent whether that works.

Load test against the deployed URL: 8 parents searching at the same moment all got answers
(median 7.7 s, max 12.2 s).

Other tests:

```bash
cd agent && ../.venv/bin/pytest -q tests                  # offline unit tests (178), including AgentCore, Gateway, Memory, model routing, the fast path, the cache and the Fargate fallback
python3 evals/smoke_api.py https://<cloudfront-domain>    # end-to-end API checks against a deployment, including streaming
python3 agent/scripts/check_front_door.py                # the agent runtime rejects calls without an OAuth token
python3 agent/scripts/gateway_tools_demo.py              # lists the Gateway's MCP tools and calls one
```

Before a demo, clear test traffic from `/api/metrics`:

```bash
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 .venv/bin/python data/reset_metrics.py --yes
```

## Security

- The load balancer only accepts traffic from CloudFront (AWS-managed prefix list), so the WAF
  can't be bypassed.
- AWS WAF on CloudFront limits each IP to 300 agent turns per 5 minutes (each turn calls
  Bedrock) and blocks addresses on Amazon's IP reputation list.
- The agent runtime accepts only the API's OAuth tokens (Cognito + AgentCore Identity), and the
  Gateway's tools are IAM-protected.
- The agent's task role can only use its OpenSearch domain, its DynamoDB table and Bedrock model
  invocation. OpenSearch requires IAM-signed requests over HTTPS, with encryption at rest and
  between nodes. Logs are kept for 14 days.
- No login, by design (out of scope). Saved lists are keyed by an anonymous session id.
- Synthetic data only: no real GreatSchools data, no student data, no secrets in the repo.
