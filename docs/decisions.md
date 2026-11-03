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

- Agent (criteria extraction, questions and explanations): Claude Sonnet 5.5 on Bedrock
  (`us.anthropic.claude-sonnet-5-5`), set with `MAIN_MODEL`. One model does everything; there is no
  separate extraction model. A smaller model such as Claude Haiku 5.5 could take over extraction later
  if cost or speed matter.
- Embeddings: Amazon Titan Text Embeddings v2 (1024 dimensions), called in us-east-1.
- The `us.` prefix is a cross-region inference profile. Bedrock may run a request in another US region
  (for example us-east-2 or us-west-2) when us-east-1 is busy. Everything else runs in us-east-1. If
  GreatSchools needs model calls kept in us-east-1 only, switch to an in-region model ID where one is
  offered and narrow the IAM policy in `infra/stacks/app_stack.py`.

## 005: Fargate behind CloudFront for the agent API

An agent turn takes 5–12 seconds and makes several model and search calls. API Gateway's
29-second limit leaves little margin, and Lambda would need conversation state moved out of
memory. One ARM64 Fargate task behind an ALB runs the same FastAPI app we use locally, and
CloudFront puts it and the frontend on one HTTPS URL (no CORS, no certificate to manage).
Public subnets and no NAT gateway keep cost and setup time down; production would use
private subnets, several tasks and session state in DynamoDB.
The ALB has a public address but its security group only allows CloudFront's origin-facing
IP ranges (AWS managed prefix list), so the API can't be reached without going through CloudFront.

## 006: Code-only paths where no judgment is needed

Editing a chip, saving, thumbs and metrics never call the model. A chip edit re-runs search
and verification in about a second. Comparison tables are built by the same verify rules as
the cards; the model only writes the one-line summary.

## 007: Needs become one scored OpenSearch query

GreatSchools turns each need into OpenSearch query parameters (for example, "high performing" is a
filter on rating 8–10 plus a boost for 4–5 stars). We do the same in `search.BOOSTS`:

- Required grade level, school type and location are hard filters. Required `high_performing` filters
  out schools rated below 8, but keeps schools with no rating so the parent sees "we don't know"
  rather than losing them.
- Every other need adds weighted boosts. Required needs weigh 3× preferred ones; avoided needs lower
  the score (`boosting` query). The parent's softer wishes add a k-NN similarity clause.
- OpenSearch returns the top 50, and code verifies every need for each one and ranks them:
  85% verified criteria, 15% search score.

Before this, only grade, type and location reached OpenSearch, and the other 50 candidates were
picked arbitrarily. That worked for 105 schools, but at 150,000 the best match could be left out.

## 008: Programs are out of scope

The vision mentions schools *and* programs, and a sample programs file exists. We decided not to
add programs: a second search and a second kind of result card would split the single search box.
When we asked GreatSchools how parents choose between looking for schools and looking for programs
at the start, they said it is an open question and could confuse parents. We left it open and kept
the build to schools. If programs come back, the agent should decide from the parent's words which
kind of result fits, instead of asking the parent to pick a mode.

## 009: Gaps and suggestions come from the model; the app checks them

The model lists parent wishes no need can check (`unmapped`, shown as "can't check" chips) and up to
two needs the parent didn't mention but likely cares about (`suggested`, tap to add). Code drops
suggestions that aren't in the catalog or are already chosen, and never searches with a suggestion
until the parent adds it.

## 010: Guardrails on each agent turn

- At most 6 tool calls per turn. Further calls get an error telling the model to answer.
- If the model fails (Bedrock error, no structured output), the turn falls back to blocks built by
  code: chips, plus results or the comparison table if they were computed this turn, and a short
  apology. Results from an earlier turn are never passed off as the new answer.
- An evidence callout is dropped if it uses a number (rating, time, year, count) that isn't in that
  school's checked data. The contract first said to retry; dropping costs nothing and avoids a
  second 5-second model call.
- Searches are counted for metrics only when a search actually ran, so glossary questions don't
  inflate saves-to-searches.

## 011: Progress is streamed with server-sent events

`POST /api/turn/stream` sends `progress` events while tools run ("Checked 12 schools…") and then one
`result` event with the same body as `/api/turn`. Tools write the progress text in code, so it
can't overstate what was checked. CloudFront and the ALB pass the stream through (caching is off for
`/api/*`). `/api/turn` stays for clients that don't need streaming.

## 012: Term questions are answered from a glossary file

`explain_term` looks up `agent/gs_agent/content/glossary.json` (GreatSchools ratings, school types,
IEP/504, ELL, CTE, ESAs, vouchers, tax-credit scholarships and what our statuses mean). We wrote the
entries for this demo from public sources such as GreatSchools' ratings guide; GreatSchools should
review them or swap in its own content. Answers built from the glossary are labeled with their source.
When a term isn't there, the agent says so and marks its answer as general.
