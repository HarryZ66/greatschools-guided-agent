# CLAUDE.md

GreatSchools Guided Agent, built at AWS Breaking Barriers 2026 (Seattle). Python agent (Strands on
Bedrock) behind FastAPI on Fargate, OpenSearch for search, DynamoDB for saves and metrics, CDK for infra.

Read before changing code:

- `README.md`: layout, deploy, data loading, local run, tests
- `docs/contract.md`: needs catalog, status rules, API and UI blocks (source of truth)
- `docs/decisions.md`: why things are the way they are
- `docs/next-steps.md`: what's left to build, in priority order

`frontend/` holds the React parent app (`src/`, which calls the API through `src/api.js`) and
`frontend/placeholder/`, a test page that CDK serves until `frontend/dist` is built. A change to
blocks or endpoints in `docs/contract.md` needs the matching change in `frontend/src/App.jsx`.

## Rules

- **The model understands; code decides** (decision 002). Statuses, evidence, scores, `watch_out`,
  program matches, trade-off hints and cost estimates come from code in `agent/gs_agent/`. The model
  writes chip labels, the question, the message, callouts and suggestions only.
- **No claim without evidence.** Missing data is `missing`, old data is `partial` with a note.
  Callouts may only use numbers found in the data; guide answers cite `lookup_content` entries.
- **Synthetic data only.** No real GreatSchools data, no student data, no secrets. `data/raw/` stays
  out of git. Funding facts come from official sources, with the source and year in `funding.json`.
- **Fairness.** Never filter, rank or steer by race, ethnicity, national origin, religion,
  disability or income (decision 007).
- **Change the contract with the code.** A new or changed block, field or endpoint updates
  `docs/contract.md` in the same change; a changed decision gets a new numbered entry in
  `docs/decisions.md`.
- Keep code-only paths (chip edits, saves, feedback, profile, metrics) free of model calls (decision 006).
- `agent.py`, `search.py` and `needs.py` change often: branch from the latest `main` and keep PRs small.
- Before you finish: run the unit tests, and the evals for any prompt or agent change (commands below).

## Commands

- Unit tests (offline): `cd agent && ../.venv/bin/pytest -q tests`
- Evals: `AWS_PROFILE=gs-sandbox AWS_DEFAULT_REGION=us-east-1 .venv/bin/python evals/run_evals.py`
- Live API checks: `python3 evals/smoke_api.py https://<cloudfront-domain>`
- Deploy: `cd infra && cdk deploy --all` (run `aws sts get-caller-identity --profile gs-sandbox` first to refresh credentials)
- Generate data: `.venv/bin/python data/generate.py --count 80` and `.venv/bin/python data/generate_programs.py`
- Load data: `data/ingest.py`, `data/ingest_programs.py`, `data/ingest_content.py` (each with `--recreate`)
- Run the API locally: `cd agent && PYTHONPATH=. ../.venv/bin/uvicorn gs_agent.api:app --port 8000 --reload`
- Try one turn: `cd agent && PYTHONPATH=. ../.venv/bin/python scripts/try_agent.py "middle school near Miami with STEM, I work until 6"`
- Before a demo: `.venv/bin/python data/reset_metrics.py --yes`
