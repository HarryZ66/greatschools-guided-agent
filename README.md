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
| Amazon S3 | Data files |

All resources are in `us-east-1`.

## Deploy

Prerequisites: Python 3.12+, Node.js 20+, AWS CLI v2, AWS CDK CLI, and AWS credentials
for the target account.

```bash
cd infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap   # once per account and region
cdk deploy GsDataStack
```

To tear everything down:

```bash
cdk destroy --all
```

## Decisions

See [`docs/decisions.md`](docs/decisions.md).
