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
| `agent/` | Python agent (Strands Agents on Amazon Bedrock), its tools, glossary content and offline tests |
| `frontend/` | `placeholder/`: a one-page test client, served until the parent app is built |
| `data/` | Synthetic data generator and OpenSearch ingestion scripts |
| `docs/` | API contract (`contract.md`) and decision records (`decisions.md`) |

## Choices we made

GreatSchools left these open (see the tech brief). Reasons are in [`docs/decisions.md`](docs/decisions.md).

| Area | Our choice |
|---|---|
| Language | Python for the agent, API, data scripts and infrastructure |
| Model | Claude Sonnet 5.5 on Bedrock for the agent; Titan Text Embeddings v2 for semantic search |
| How agentic | A guided agent. The model picks its tools (search, school profile, glossary), asks at most one question per turn and spots gaps. Code decides every status, score and piece of evidence. At most 6 tool calls per turn. |
| Agent framework | Strands Agents |
| Compute | One ARM64 Fargate task behind an ALB and CloudFront |
| Infrastructure as code | AWS CDK (Python) |
| Frontend | Single-page web app served from S3 through CloudFront; a placeholder page for now |
| Scope | Schools only. Programs are out of scope (decision 008). |

## AWS services

| Service | Role |
|---|---|
| Amazon Bedrock | Claude models for the agent, Titan Text Embeddings v2 for semantic search |
| Amazon OpenSearch Service | Keyword and vector search over school documents |
| Amazon DynamoDB | Session state, saved schools and thumbs up/down feedback |
| Amazon S3 | Data files and the frontend site |
| Amazon ECS on AWS Fargate (ARM64) | Runs the agent API container |
| Elastic Load Balancing (ALB) | Routes traffic to the agent task |
| Amazon CloudFront | One HTTPS URL: `/api/*` goes to the agent, everything else to the frontend |
| Amazon ECR | Stores the agent image (created by CDK) |

All resources are in `us-east-1`. The `us.` Claude model ID is a cross-region inference profile, so
Bedrock may run some model requests in another US region (decision 004).

```
Browser ──HTTPS──▶ CloudFront ──/api/*──▶ ALB ──▶ Fargate task (FastAPI + Strands agent)
                       │                               │
                       └──/*──▶ S3 (frontend)          ├──▶ Bedrock (Claude, Titan embeddings)
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

We load GreatSchools' 25 sample schools and 80 generated Miami-area schools into one index. The
sample file isn't committed (`data/raw/` is ignored), so copy it in first.

```bash
python3 -m venv .venv
.venv/bin/pip install -r agent/requirements.txt
mkdir -p data/raw && cp "../Sample Data/schools_sample.json" data/raw/   # GreatSchools' sample
.venv/bin/python data/generate.py --count 80            # synthetic Miami-area schools
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 \
  .venv/bin/python data/ingest.py data/raw/schools_sample.json data/generated/schools_generated.json --recreate
```

All generated schools are fictional. Records carry `"synthetic_generated": true`. The sample has
no after-school care hours, tuition or profile dates, so those needs show as "missing" for sample
schools. That's expected.

## Run the agent API locally

```bash
cd agent
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 PYTHONPATH=. ../.venv/bin/uvicorn gs_agent.api:app --port 8000 --reload
```

| Endpoint | Purpose |
|---|---|
| `POST /api/turn` | Query, answer a question, compare two schools, or edit a chip (see `docs/contract.md`) |
| `POST /api/turn/stream` | Same as `/api/turn`, as server-sent events: progress while the agent works, then the result |
| `POST /api/saved`, `GET /api/saved?session_id=`, `DELETE /api/saved/{school_id}?session_id=` | Saved list |
| `POST /api/feedback` | Thumbs up/down on a result |
| `GET /api/schools/{school_id}` | Full school record for the profile view |
| `GET /api/metrics` | Saves-to-searches, thumbs relevance, criteria per search |
| `GET /api/health` | Health check |

Run the offline tests (no AWS needed):

```bash
../.venv/bin/pip install pytest httpx
PYTHONPATH=. ../.venv/bin/python -m pytest -q      # from agent/
```

Try it from the command line without the API: `PYTHONPATH=. ../.venv/bin/python scripts/try_agent.py "middle school near Miami with STEM, I work until 6"`

## Decisions

See [`docs/decisions.md`](docs/decisions.md).
