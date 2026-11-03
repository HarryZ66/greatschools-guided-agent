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

## 004: Models

- Main agent: Claude Sonnet 5.5 on Bedrock (`us.anthropic.claude-sonnet-5-5`)
- Criteria extraction: Claude Haiku 5.5 (`us.anthropic.claude-haiku-5-5`)
- Embeddings: Amazon Titan Text Embeddings v2 (1024 dimensions)
