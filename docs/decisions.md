# Decision log

Short records of the choices we made and why, so GreatSchools can follow the reasoning.

## 001: Python and AWS CDK for infrastructure

The agent is written in Python, so the infrastructure is too. One language for the whole
backend means anyone on the team can read and change any part of it.

## 002: The model understands; code decides

The LLM extracts needs from the parent's words and writes explanations. Whether a school
meets a need (confirmed / partial / needs attention / missing) is decided by plain code that
reads the data fields and their dates. Evidence shown to parents comes only from tool
results, never from model text. This keeps results reproducible and stops the model from
inventing a match.

## 003: Single-node OpenSearch domain for the hackathon

One `t3.medium.search` data node with a public HTTPS endpoint and an IAM-based access
policy. It's cheap (well under the $500 sandbox cap for three days) and supports k-NN
vector search. Production would use a multi-AZ domain inside a VPC.

## 005: Fargate behind CloudFront for the agent API

An agent turn takes 5–12 seconds and makes several model and search calls. API Gateway's
29-second limit leaves little margin, and Lambda would need conversation state moved out of
memory. One ARM64 Fargate task behind an ALB runs the same FastAPI app we use locally, and
CloudFront puts it and the frontend on one HTTPS URL (no CORS, no certificate to manage).
Public subnets and no NAT gateway keep cost and setup time down; production would use
private subnets, several tasks and session state in DynamoDB.

## 006: Code-only paths where no judgment is needed

Editing a chip, saving, thumbs and metrics never call the model. A chip edit re-runs search
and verification in about a second. Comparison tables are built by the same verify rules as
the cards; the model only writes the one-line summary.

## 007: Fairness rule in the agent

The agent never filters, ranks or recommends schools or neighborhoods by the race, ethnicity,
national origin, religion, disability or income of students or residents, and doesn't point
parents elsewhere for it. Steering families by demographics is a fair-housing risk. It declines
in one sentence and offers to search by what the child needs. Subgroup ratings can still be
shared when a parent asks how a school serves a group their own child belongs to. The
`fairness` cases in `evals/cases.json` check this.

## 004: Models

- Main agent: Claude Sonnet 5.5 on Bedrock (`us.anthropic.claude-sonnet-5-5`)
- Criteria extraction: Claude Haiku 5.5 (`us.anthropic.claude-haiku-5-5`)
- Embeddings: Amazon Titan Text Embeddings v2 (1024 dimensions)
