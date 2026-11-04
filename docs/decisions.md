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

## 008: Guide answers come only from the guide (P4)

Questions about terms, ratings and how school choice works are answered from a small guide
index in OpenSearch (`content`), found by keyword match on titles and aliases or by vector
similarity (which also handles Spanish). Unrelated questions find nothing, and the agent then
says it has no guide entry instead of answering from the model's memory. Answers list their
sources, and code drops any source the tool didn't return. GreatSchools can replace the
team-written entries with its own articles without code changes.

## 009: Trade-off questions are found by code

Leaving the trade-off question to the model made it appear in some runs and not others. Code
now looks across all candidates for a school that meets every must-have except one partial
match, preferring concrete gaps in time or price, and passes these as `question_hints`. The
agent asks about the most important one; a hinted school outside the top cards is added as a
card so the parent can see it.

## 010: Programs fill the gaps schools leave

Programs are searched near a school or a city, and code decides fit: whether the sessions
cover a time gap, distance from the school, ages and cost. Programs with only past sessions are
never listed, and ZIP codes that don't match the state are flagged. When a school's care ends
before the parent needs it, the trade-off hint tells the agent to look for programs near that
school covering the gap, then still let the parent choose. The sample programs were all in
other states, so we generated Miami-area programs in the same format.

## 011: Rate limit and lock the origin

The public URL calls Bedrock on every agent turn, so anyone could run up the bill. AWS WAF on
CloudFront allows 300 turns per IP per 5 minutes (a busy parent uses a few a minute; a whole
demo room behind one NAT address stays well under it) and blocks Amazon's IP reputation list.
The load balancer's security group only admits CloudFront's managed prefix list, so nobody can
skip the WAF by calling the load balancer directly.

## 012: Prompt caching

The system prompt, tool definitions and earlier turns are resent on every model call. Bedrock
prompt caching (Strands `CacheConfig(strategy="auto")`) serves about 83% of input tokens from the
cache, roughly halving the estimated cost per turn ($0.041 to $0.020) with no change in latency
or eval results. At GreatSchools' scale this is the single biggest cost lever.

## 013: Every need shapes the OpenSearch query (from Sanchit Arora's PR #1)

Before, only grade, type and location reached OpenSearch, so for broad searches the 50 candidates
were arbitrary. Now each need becomes filters or weighted boosts (`search.BOOSTS`), the way
GreatSchools maps needs to query parameters today; require weighs 3x prefer, avoid lowers the
score, and the parent's softer wishes add a k-NN clause. A required "high performing" filters to
ratings 8-10 but keeps unrated schools so they show as missing. Statuses still come from
`needs.verify()`; OpenSearch only decides which schools come back and breaks near-ties.

## 014: Answer from code when the model fails (from PR #1)

A failed model turn returns blocks built by code with `"fallback": true` instead of a 500: the
cards from a search that ran this turn, or the comparison table, plus a short note. Results from
an earlier turn are never reused as the answer to a new question. Each turn is capped at 6 tool
calls, and callouts that use numbers not found in the data are dropped.

## 015: Stream progress while the agent works (from PR #1)

A turn takes 6-12 seconds. `POST /api/turn/stream` sends server-sent `progress` events
("Checked 10 schools; ranking the top 8.") and then the result, so the parent sees the agent
investigating instead of a spinner. It passes through CloudFront and the ALB unchanged.

## 016: Show gaps the agent can't check, and needs the parent didn't mention (from PR #1)

`criteria_chips` carries `unmapped` (wishes no need can check yet, such as a robotics club at
the school) and up to 2 `suggested` needs (a parent who works until 6pm may need a bus). Being
explicit about what we can't check is part of the honesty rule.

PR #1's own glossary tool was not ported: the guide (decision 008) already answers term questions
from OpenSearch with sources. Its five extra topics (microschools, chronic absence, ESAs, vouchers,
tax-credit scholarships) were added to `data/content/guide.json`. PR #1 also proposed leaving
programs out of scope; we kept them (decision 010) because the Vision doc lists program cards in scope.

## 004: Models

- Main agent: Claude Sonnet 5.5 on Bedrock (`us.anthropic.claude-sonnet-5-5`)
- Criteria extraction: Claude Haiku 5.5 (`us.anthropic.claude-haiku-5-5`)
- Embeddings: Amazon Titan Text Embeddings v2 (1024 dimensions)
