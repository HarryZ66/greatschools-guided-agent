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
| `frontend/` | React app for parents |
| `data/` | Synthetic data generator and OpenSearch ingestion scripts |
| `evals/` | Test queries and evaluation scripts |
| `docs/` | Architecture notes and decision records |

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

All resources are in `us-east-1`.

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

## Run the agent API locally

```bash
cd agent
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 PYTHONPATH=. ../.venv/bin/uvicorn gs_agent.api:app --port 8000 --reload
```

| Endpoint | Purpose |
|---|---|
| `POST /api/turn` | Query, answer a question, compare two schools, or edit a chip (see `docs/contract.md`) |
| `POST /api/saved`, `GET /api/saved?session_id=`, `DELETE /api/saved/{school_id}?session_id=` | Saved list |
| `POST /api/feedback` | Thumbs up/down on a result |
| `GET /api/schools/{school_id}` | Full school record for the profile view |
| `GET /api/metrics` | Saves-to-searches, thumbs relevance, criteria per search |
| `GET /api/health` | Health check |

Try it from the command line without the API: `PYTHONPATH=. ../.venv/bin/python scripts/try_agent.py "middle school near Miami with STEM, I work until 6"`

## Evaluation

`evals/cases.json` holds 31 parent queries across core searches, missing information, honesty,
different family needs, fairness, guide questions (P4), programs and edge cases. `evals/run_evals.py` runs them and checks needs
extraction, questions, refusals, and that every school the agent names was returned by a tool.

```bash
AWS_PROFILE=<profile> AWS_DEFAULT_REGION=us-east-1 .venv/bin/python evals/run_evals.py
```

Latest run on Claude Sonnet 5.5 (full table in [`evals/results/latest.md`](evals/results/latest.md)):

| Metric | Result |
|---|---|
| Cases passed | 31 / 31 |
| Needs extracted correctly | 14 / 14 |
| Made-up school mentions | 0 |
| Guide answers citing a guide entry | 5 / 5 (and none for a term the guide lacks) |
| Program cases (fill a gap, interest match, past-only excluded, nothing found) | 5 / 5 |
| Errors | 0 |
| Latency per turn | median 6.2 s, max 16.1 s |
| Tokens per turn | ~11,400 |
| Estimated cost per turn | ~$0.044 (assuming $3 / $15 per million input / output tokens) |

In 5 of 5 runs, the demo query found the library robotics club that covers Tamarind Cove's
5–6pm care gap and asked the parent whether that works.

Load test against the deployed URL: 8 parents searching at the same moment all got answers
(median 7.7 s, max 12.2 s).

## Decisions

See [`docs/decisions.md`](docs/decisions.md).
