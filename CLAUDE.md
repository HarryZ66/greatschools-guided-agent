# CLAUDE.md

GreatSchools Guided Agent, built at AWS Breaking Barriers 2026 (Seattle). Python agent (Strands on
Bedrock) behind FastAPI on Fargate, OpenSearch for search, DynamoDB for sessions, CDK for infra.

Read before changing code:

- `README.md`: layout, deploy, data loading, local run, tests
- `docs/contract.md`: needs catalog, status rules, API and UI blocks (source of truth)
- `docs/decisions.md`: why things are the way they are
- `docs/next-steps.md`: what's left to build, in priority order

The parent app is a separate repo. Here, only `frontend/placeholder/` (a test page) lives in `frontend/`.

## Rules

- **The model understands; code decides** (decision 002). Statuses, evidence, scores, `watch_out`,
  program matches and cost estimates come from code in `agent/gs_agent/`. The model writes chips'
  labels, the question, the message and callouts only.
- **No claim without evidence.** Missing data is `missing`, old data is `partial` with a note.
- **Synthetic data only.** No real GreatSchools data, no student data, no secrets. `data/raw/` stays
  out of git.
- **Change the contract with the code.** A new or changed block, field or endpoint updates
  `docs/contract.md` in the same change; a changed decision gets a new numbered entry in
  `docs/decisions.md`.
- Keep code-only paths (chip edits, saves, feedback, profile, programs) free of model calls
  (decision 006).
- Run the offline tests before you finish: `PYTHONPATH=. ../.venv/bin/python -m pytest -q` from `agent/`.

## Commands

- Deploy: `cd infra && cdk deploy --all`
- Generate data: `.venv/bin/python data/generate.py --count 80`
- Load data: `.venv/bin/python data/ingest.py data/raw/schools_sample.json data/generated/schools_generated.json --recreate`
- Run the API locally: `cd agent && PYTHONPATH=. ../.venv/bin/uvicorn gs_agent.api:app --port 8000 --reload`
- Try one turn: `cd agent && PYTHONPATH=. ../.venv/bin/python scripts/try_agent.py "middle school near Miami with STEM, I work until 6"`
