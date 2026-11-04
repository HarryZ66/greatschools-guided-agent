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

## 017: Counseling and mental health as a need (Sanchit's next-steps, GreatSchools feedback)

GreatSchools told us mental health is now a top-five parent concern that parents rarely ask about.
`mental_health` is confirmed when the profile lists counselors, social workers or specialists and
isn't stale; partial when only reviews or older listings support it; needs attention when recent
reviews are mostly negative. The prompt offers it as a suggested need when the parent hasn't
raised it: the demo query suggested it in 5 of 5 runs.

## 018: Cost after a typical scholarship

Parents with less money rule out private schools without knowing aid exists. For private schools
with listed tuition, code subtracts the Florida scholarship's average award and shows "about
$8,300 after a typical Florida scholarship (estimate from the 2024-25 average)". The figure is the
FLDOE's latest published statewide average ($8,200, 2024-25); income limits were removed in 2023-24.
We don't claim a priority tier or a 2026-27 amount we couldn't confirm from an official source.
The federal tax-credit scholarship (2027) is listed with no amounts: "details pending".

## 019: Verified profile view (P3)

`GET /api/schools/{id}?session_id=` adds a `profile` built in code: the same checks as the cards
for that parent's needs, review counts by topic split recent/older with dated excerpts, guide
entries for the terms on the page, and the cost estimate. The raw record stays at the top level so
existing callers keep working.

## 020: Programs offered when a parent saves a school

GreatSchools reps liked programs as a companion to schools. Programs still appear in search turns
when they fill a time gap (decision 010); in addition, saving a school returns up to 3 programs
within 8 km that cover a need that school doesn't fully meet, with a `why` written by code
("Care at Tamarind Cove ends at 5:00 PM. After-School Homework Help … runs until 6:00 PM, 1.0 km
away"). A care gap is only filled by a program whose session covers the whole gap.

## 004: Models

- Agent (understanding needs, choosing tools, writing messages): Claude Sonnet 5.5 on Bedrock
  (`us.anthropic.claude-sonnet-5-5`), one model for the whole turn. Set `MAIN_MODEL` to change it.
- Embeddings: Amazon Titan Text Embeddings v2 (1024 dimensions)
- Claude Haiku 5.5 (`us.anthropic.claude-haiku-5-5`) was evaluated as a cheaper option: about a third
  of the cost per turn, but it failed more eval cases, so Sonnet stays the default (see README, Evaluation).

## 021: Answering a question keeps the parent's time and budget

When a parent answered "The library club works" to the trade-off question, the model sometimes
changed "care until 6pm" to 5pm. Schools whose care ends at 5 then showed as confirmed, and saving
one no longer offered the program that covers the gap. Now, on an answer turn, code restores a
time or budget the parent gave unless the answer itself names a new one ("Pickup at 5 works");
the mode may still change (require to prefer). The prompt says the same, and the eval case
`answer_keeps_care_time` checks it.

## 022: Show what the agent really did (`trace`)

Judges and parents ask whether this is an agent or a chatbot that writes everything. Every
response carries a `trace` built by code as each tool returns: which service ran (Claude on
Bedrock, OpenSearch, Titan embeddings, or plain code), what it found, and how long it took, plus
the code-only steps (verifying needs, spotting trade-offs, keeping the parent's stated values,
dropping notes the data doesn't back). The model never writes the trace, so it can't claim a
check that didn't happen. It's a top-level field, not a block, so existing renderers are unaffected.

## 023: Help parents find what matters

GreatSchools' core problem is that parents don't know what to ask. When a parent gives little
beyond grade and location ("a good elementary school in Miami") and code found no trade-off,
the agent still searches, then asks one question about what the child needs, offering the
likeliest of extra help with learning, after-school care, a bus, counseling, strong
academics and small classes. If grade or location is missing it asks for that first and offers
these as suggested chips. Eval cases `discovery_vague` (English) and `discovery_vague_es` check it.

## 024: Plain words on every label, and feedback on replies

Walking through the app as a parent of a 6th grader with ADHD showed jargon in the places parents
read most: the chip "Extra help for ADHD (IEP/504)", answer options with "(IEP or 504)" (the prompt
itself suggested that wording), a comparison cell showing `level_codes: ['e', 'm', 'p']`, and
distances in kilometres. The Vision doc lists "don't know the jargon" as a core pain point.

- The prompt has a plain-words section: labels, suggestions, questions and options use everyday words
  ("extra help with learning", "help learning English"); a term appears in a message only if the
  parent used or asked about it, explained in the same sentence. Distances in miles, ratings as
  "4 out of 10".
- Code backs it up: `plain_label` drops "(IEP/504)"-style asides from chips, suggestions and options,
  and a chip that still uses a term falls back to the catalog's plain label. Catalog labels, notes
  (including the extra-help rule, which now says what the data shows) and comparison cells
  (`plain_evidence`) are written in plain words. Evidence field names don't change.
- Thumbs moved from each school card to each agent reply ("Helpful?"). A thumbs-down on one school
  out of eight told us little; a vote on the reply rates the whole answer, results and question
  included. `/api/feedback` takes the reply's `turn` (new top-level field on every response) or a
  `school_id` as before, so `relevance` in `/api/metrics` keeps working.

## 025: Agent turns run on Amazon Bedrock AgentCore Runtime

Until now the agent ran inside the API process on one Fargate task, with conversations in memory.
That works for a demo but can't scale out: a second task wouldn't know the first one's
conversations. AgentCore Runtime fixes this the way agents are meant to be hosted on AWS: each
session gets its own isolated, warm environment, kept between turns, paid per use.

- The same ARM64 image runs in both places. On AgentCore (`RUNNING_ON=agentcore`, port 8080) the
  app also serves AgentCore's service contract: `GET /ping` and `POST /invocations`.
- The Fargate API stays the public front door behind CloudFront and WAF. With `AGENT_RUNTIME_ARN`
  set, it sends agent turns (`/api/turn`, `/api/turn/stream`) and the calls that need the
  conversation's needs (`POST`/`DELETE /api/saved`, `/api/schools/{id}?session_id=…`) to
  `InvokeAgentRuntime`, with the AgentCore session id `greatschools-guided-search-session-<session_id>`.
  The API names new conversations so the first turn already has a session. Streamed turns pass
  AgentCore's server-sent events through unchanged. Feedback, saved-list reads, school details
  without a session, and metrics stay on the API: they need no conversation state.
- Sessions stay warm for 30 idle minutes (8 hours at most); after that a parent's next turn starts
  a new conversation, and saved schools still come back from DynamoDB.
- The browser can't call AgentCore directly (it needs SigV4 or a JWT), which is why the API proxies.
  The API and the frontend contract don't change.
- "How I checked this" gains a first step, "Amazon Bedrock AgentCore Runtime", recorded by code on
  the runtime, so a parent (and a judge) can see where the turn ran.
- Without `AGENT_RUNTIME_ARN` (local runs, tests) everything runs in-process as before.

## 026: OAuth on the agent runtime, and AgentCore Observability

**Front door.** Anyone with IAM access to the account could call the runtime directly and skip the
API's WAF rate limit. The runtime now has inbound auth through AgentCore Identity: a JWT authorizer
that accepts only access tokens from our Cognito user pool, issued to the API's app client
(`allowedClients`). Calls without a token, with a made-up token, or signed with IAM (SigV4) are
rejected before they reach the container.

- Machine to machine: the API gets tokens with the OAuth client-credentials grant (scope
  `greatschools-agent/invoke`), caches each one until a minute before it expires, and calls the
  runtime's HTTPS endpoint (`/runtimes/<arn>/invocations?qualifier=DEFAULT`) with it. Parents still
  don't sign in; this guards the agent, not the app.
- The client secret lives in Secrets Manager and reaches the task as an ECS secret, never as a plain
  environment variable or a CDK output. The task role no longer needs `InvokeAgentRuntime`.
- A rejected token is dropped so the next call fetches a new one; the parent sees "not reachable".
- `agent/scripts/check_front_door.py` shows it: no token, a made-up token and a SigV4 call are
  rejected; a Cognito token gets through.

**Observability.** The runtime container runs under `opentelemetry-instrument` (AWS Distro for
OpenTelemetry), so every turn's Strands agent spans, model calls and tool calls go to CloudWatch.
CDK turns on CloudWatch Transaction Search (spans stored in CloudWatch Logs, 100% indexed, since a
demo sends few) and delivers the runtime's own application logs and traces. The CloudWatch GenAI
Observability dashboard shows sessions, traces, latency and token use per agent. Transaction
Search is an account setting: deleting the stack turns it off again. Fargate runs without the
instrumentation; it only passes calls through.

## 027: The agent's data lookups are MCP tools behind an AgentCore Gateway

The agent's stateless lookups (the parent guide, programs, finding a school by name, a school's
record) are the kind of tools other agents could reuse, so they now sit behind an Amazon Bedrock
AgentCore Gateway as MCP tools: `lookup_guide`, `search_programs`, `find_school_by_name` and
`get_school`, served by one Lambda function (`gs_agent/gateway_tools.py`, image
`agent/Dockerfile.tools`) built from the same code.

- The model's tools don't change. `lookup_content`, `search_programs`, `find_school_by_name` and
  `get_school_profile` keep their names, docstrings and session bookkeeping; only where their data
  comes from changes. With `GATEWAY_URL` set (on AgentCore Runtime), each one calls the Gateway's
  MCP tool through Strands' `MCPClient` over streamable HTTP; without it, the same function runs
  in-process. Prompts and evals stay the same.
- `find_schools` stays in the agent: it records the conversation's needs, checks and ranking, which
  the Gateway's stateless tools shouldn't hold.
- The Gateway uses IAM inbound auth. The runtime's role has `bedrock-agentcore:InvokeGateway` on
  this Gateway only, and the MCP client signs every request with SigV4. The Gateway invokes the
  Lambda with its own role; the Lambda can only read OpenSearch and call Titan embeddings.
- Both sides of each permission are set. The caller side: the runtime role's identity policy
  allows `InvokeGateway`, and the Gateway's resource-based policy names the runtime role as an
  allowed caller. The Gateway's own role: its trust policy lets `bedrock-agentcore.amazonaws.com`
  assume it only from this account *and* from a `greatschools-tools-*` gateway ARN
  (`aws:SourceArn`, AWS's confused-deputy guidance), and its permissions policy allows invoking
  the tools Lambda only.
- The Gateway delivers its application logs to CloudWatch Logs and its traces to X-Ray, like the
  runtime (decision 026), so tool calls show up in AgentCore Observability.
- "How I checked this" names the hop: "AgentCore Gateway (MCP) → AWS Lambda → Amazon OpenSearch".
- A failed Gateway call is recorded in the trace and returned to the model as "the lookup failed",
  never as made-up data.
- `agent/scripts/gateway_tools_demo.py` lists the tools and calls `lookup_guide`.

## 028: The parent guide is also an Amazon Bedrock Knowledge Base

The parent guide (`data/content/guide.json`, 35 entries the team wrote) was only an OpenSearch
index. It now also lives in an Amazon Bedrock Knowledge Base, so guide answers come from our own
documents through a managed retrieval service, and each answer names the document it came from.

- **Documents.** `GsKnowledgeStack` (`infra/stacks/knowledge_stack.py`) writes one markdown file
  per entry (`guide/<id>.md`: title, aliases, body) with a `.metadata.json` sidecar (id, title,
  kind, source) and uploads them with a CDK `BucketDeployment`. The files are built from
  `guide.json` at synth time, so the guide stays the one source and a deploy reproduces them.
  They go up as one folder asset: 70 separate inline sources made the deployment's response too
  long for CloudFormation.
- **Vector store: Amazon S3 Vectors.** It is the cheapest store a knowledge base can use: pay per
  GB stored and per query, nothing while idle. OpenSearch Serverless would cost hundreds of
  dollars a month for its minimum capacity. One index, Titan Text Embeddings v2, 1024 dimensions,
  float32, cosine. Bedrock's own text and metadata fields are non-filterable, so they don't count
  against S3 Vectors' small filterable-metadata limit.
- **One chunk per entry** (chunking `NONE`): entries are a few sentences, so a hit is a whole entry.
- **Ingestion.** A custom resource calls `StartIngestionJob` on every deploy that changes the
  guide (its id is a hash of the entries). The job takes under a minute;
  `agent/scripts/kb_demo.py` shows its status, and `--sync` runs one and waits.
- **Connecting it.** With `KNOWLEDGE_BASE_ID` set, `search.lookup_content` calls the Bedrock Agent
  Runtime `Retrieve` API (`gs_agent/knowledge.py`) instead of OpenSearch. Both paths use it: the
  Gateway's Lambda on AgentCore and the in-process lookup locally. Code maps each hit back to the
  entry through its metadata and keeps the S3 document name. It keeps OpenSearch's relevance rule:
  a hit counts if its cosine similarity is at least 0.35 or its title or an alias is in the
  question. Retrieve's score on this index is (1 + cosine) / 2; we checked that against Titan
  embeddings computed directly. So an unrelated question still gets "no guide entry": "best pizza
  near me" scores cosine 0.07 at best, and "What is a Waldorf school?" 0.26. Without
  `KNOWLEDGE_BASE_ID` (tests, local runs) the guide stays on OpenSearch, unchanged. School profiles
  still read guide terms from OpenSearch by id.
- The 6 guide eval cases (P4) pass with the knowledge base turned on.
- **Citing the document.** The model still only lists entry ids in `sources`; code keeps the ids
  `lookup_content` returned and adds each one's `document` (for example `charter-school.md`) to
  the `text` block. The trace step's service is "Amazon Bedrock Knowledge Base" (behind the
  Gateway on AgentCore) and names the documents. The prompt doesn't change.
- **Separate stack.** `GsKnowledgeStack` exports nothing and needs nothing from the other stacks,
  so it deploys and `cdk destroy GsKnowledgeStack` removes it on its own. The app stack takes the
  id as context (`cdk deploy GsAppStack -c knowledge_base_id=<id>`), which adds the env var and
  `bedrock:Retrieve` on that knowledge base to the Gateway tools Lambda and the runtime role.
- Retrieval on S3 Vectors is vector-only (no hybrid keyword search), so exact short terms like
  "CTE" rely on the title and aliases being in each document's text.

## 029: The saved list outlives a refresh and a new search

The Vision doc ends the core journey with "save schools to a list", and login is out of scope
("assume the user is signed in"). The session id stands in for the signed-in parent: the app keeps
it in `localStorage` and loads `GET /api/saved` on start. A `new_search` event forgets the
conversation (needs, results, chat history) but keeps the session id and its saves, so starting
over never empties My list. Saves are in DynamoDB, so they also survive a server restart.

## 030: ZIP codes from our data, "3 of 4 confirmed", and clock times

- **ZIP codes.** The ZIP box is gone; parents say where they live in the one search box. When they
  give only a ZIP, the agent stores it as `location.zip` and never guesses the city. Code finds the
  area from our own schools (exact ZIP, then the same 4- and 3-digit area); a ZIP outside our data
  gets "no schools there yet" with the areas we do cover. Eval cases `zip_only`, `zip_not_in_data`.
- **"3 of 4 confirmed" instead of "% fit".** The percentage mixed verified checks with search
  relevance, so a school whose data was plainly wrong (enrollment 1, 52 students per teacher)
  showed "100% fit". The card now counts the confirmed checks listed under it, and turns amber with
  "⚠ check data" when the school has data problems. Each problem also takes 0.02 off the score (at
  most 3): enough that a clean school with the same checks ranks first, never enough to drop a
  school below ones that meet fewer needs. The school stays visible, with the reason shown.
- **Clock times.** Notes read "Care ends at 5:00 PM; you need 6:00 PM" and "Runs 5:00 PM–6:30 PM,
  covers 5:00 PM–6:00 PM"; program cards show "Next: Tue, Nov 3 · 5:00 PM–6:30 PM". Evidence keeps
  the raw "17:00", so grounding checks are unchanged.
- **My list for returning parents.** The app stores the session id, starts a fresh conversation on
  load with `new_search` (decision 029) and shows "My list (n)" on the home page.

## 031: If AgentCore Runtime is down, Fargate runs the turn

Every agent turn, save and profile call goes through AgentCore Runtime (decision 025) behind OAuth
(026). One failure there (a token, throttling, a cold start that times out) used to show the parent
"Our assistant is not reachable" with no way forward. The Fargate API has the same code and the same
permissions, so when the runtime can't be reached it now runs the call itself, and the trace's first
step says so ("AgentCore Runtime didn't answer, so this turn ran on our Fargate service instead").
After a failure it skips the runtime for 2 minutes, so later parents don't each wait for the same
timeout. Errors the runtime returns on purpose (an unknown school, a bad request) still go to the
parent. A turn that falls back starts a fresh conversation on Fargate; the saved list stays,
because it lives in DynamoDB. A streamed turn falls back only if the runtime fails before sending
anything; once progress has reached the parent, a failure is reported as an error.
