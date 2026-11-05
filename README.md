# GreatSchools Guided Agent

A Level 2 "Guided Agent" for GreatSchools, built at AWS Breaking Barriers 2026 (Seattle).
A parent describes what they need in plain language. The agent pulls out their criteria,
asks a clarifying question, checks every criterion against the data and returns ranked
schools with evidence. It says so when data is missing or stale instead of guessing.

> **We investigate. You decide.**

## Repository layout

| Path | What's there |
|---|---|
| `infra/` | AWS CDK app (Python) that defines every AWS resource |
| `agent/` | Python agent (Strands Agents on Amazon Bedrock) and its tools |
| `frontend/` | React app for parents, connected to the agent API (see `frontend/README.md`) |
| `data/` | Synthetic data generator and OpenSearch ingestion scripts |
| `evals/` | Test queries and evaluation scripts |
| `docs/` | Architecture notes and decision records |

## Choices we made

GreatSchools left these open (see the tech brief). Reasons are in [`docs/decisions.md`](docs/decisions.md).

| Area | Our choice |
|---|---|
| Language | Python for the agent, API, data scripts and infrastructure; React for the parent app |
| Model | Claude Sonnet 5.5 on Bedrock for the agent, with prompt caching; Titan Text Embeddings v2 for semantic search. Haiku 5.5 was evaluated as a cheaper option (see Evaluation) |
| How agentic | A guided agent. The model picks its tools (school search, school profile, find by name, parent guide, programs), asks at most one question per turn, spots gaps and suggests needs. Code decides every status, score, trade-off and piece of evidence. At most 6 tool calls per turn |
| Agent framework | Strands Agents |
| Compute | The agent runs on Amazon Bedrock AgentCore Runtime, one session per conversation (decision 025). The public API is one ARM64 Fargate task behind an ALB, reached only through CloudFront and AWS WAF |
| Infrastructure as code | AWS CDK (Python) |
| Frontend | Single-page app served from S3 through CloudFront (a test page until the React app is built) |
| Scope | Schools, plus library and community programs that fill a school's gaps (decision 010) |

## AWS services

| Service | Role |
|---|---|
| Amazon Bedrock | Claude models for the agent, Titan Text Embeddings v2 for semantic search |
| Amazon OpenSearch Service | Keyword and vector search over school documents |
| Amazon DynamoDB | Session state, saved schools and thumbs up/down feedback |
| Amazon S3 | Data files and the frontend site |
| Amazon Bedrock AgentCore Runtime | Runs the agent: each parent's conversation in its own warm session |
| Amazon ECS on AWS Fargate (ARM64) | Runs the public API, which passes agent turns to AgentCore Runtime |
| Elastic Load Balancing (ALB) | Routes traffic to the agent task |
| Amazon CloudFront | One HTTPS URL: `/api/*` goes to the agent, everything else to the frontend |
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
                                                       ├──▶ OpenSearch (schools index)
                                                       └──▶ DynamoDB (saves, feedback, metrics)
```

## Deploy

Prerequisites: Python 3.12+, Node.js 22+, AWS CLI v2, AWS CDK CLI, a Docker-compatible
runtime (Docker Desktop, Finch or Colima) and AWS credentials for the target account.

```bash
cd infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap        # once per account and region
cdk deploy --all     # GsDataStack (search, table, bucket) then GsAppStack (agent + site)
```

The app URL is printed as `GsAppStack.AppUrl`. To ship a frontend build, run
`npm run build` in `frontend/` (it writes `frontend/dist`) and run `cdk deploy GsAppStack` again;
without a build, a small API test page from `frontend/placeholder/` is served.

To tear everything down:

```bash
cdk destroy --all
```

## Load data

```bash
python3 -m venv .venv
.venv/bin/pip install -r agent/requirements.txt
.venv/bin/python data/generate.py --count 80            # synthetic Miami-area schools
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 \
  .venv/bin/python data/ingest.py data/generated/schools_generated.json --recreate
```

All generated schools are fictional. Records carry `"synthetic_generated": true`.

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

## Run the agent API locally

```bash
cd agent
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 PYTHONPATH=. ../.venv/bin/uvicorn gs_agent.api:app --port 8000 --reload
```

| Endpoint | Purpose |
|---|---|
| `POST /api/turn` | Query, answer a question, compare two schools, or edit a chip (see `docs/contract.md`). Every response includes a `trace` of the tools and AWS services that really ran |
| `POST /api/turn/stream` | Same, as server-sent events: progress while the agent works, then the result |
| `POST /api/saved`, `GET /api/saved?session_id=`, `DELETE /api/saved/{school_id}?session_id=` | Saved list; saving returns programs that fill that school's gaps |
| `POST /api/feedback` | Thumbs up/down on a result |
| `GET /api/schools/{school_id}?session_id=` | School record plus a verified profile: fit checks, programs for gaps, review counts, guide terms, cost after aid |
| `GET /api/metrics` | Saves-to-searches, thumbs relevance, criteria per search |
| `GET /api/health` | Health check |

Try it from the command line without the API: `PYTHONPATH=. ../.venv/bin/python scripts/try_agent.py "middle school near Miami with STEM, I work until 6"`

## Evaluation

`evals/cases.json` holds 38 parent queries across core searches, missing information, honesty,
different family needs, fairness, guide questions (P4), programs and edge cases. `evals/run_evals.py` runs them and checks needs
extraction, questions, refusals, and that every school the agent names was returned by a tool.

```bash
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 .venv/bin/python evals/run_evals.py
```

Latest run on Claude Sonnet 5.5 (full table in [`evals/results/latest.md`](evals/results/latest.md)):

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
cd agent && ../.venv/bin/pytest -q tests                  # 107 offline tests, including AgentCore, Gateway, school fit and program matching
python3 evals/smoke_api.py https://<cloudfront-domain>    # 26 end-to-end API checks against a deployment, including streaming
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
- The agent's task role can only use its OpenSearch domain, its DynamoDB table and Bedrock model
  invocation. OpenSearch requires IAM-signed requests over HTTPS, with encryption at rest and
  between nodes. Logs are kept for 14 days.
- No login, by design (out of scope). Saved lists are keyed by an anonymous session id.

## Decisions

See [`docs/decisions.md`](docs/decisions.md).
