# GreatSchools Guided Search: parent app

React + Vite app for parents, connected to the agent API (`docs/contract.md`).

```
npm install
npm run dev                                         # agent API running locally on :8000
API_URL=https://<cloudfront-domain> npm run dev     # or use the deployed API
npm run build                                       # writes dist/, which `cdk deploy GsAppStack` ships
```

In development, Vite proxies `/api` to `API_URL` (default `http://localhost:8000`). In production,
CloudFront serves the app and `/api/*` from one URL, so the app calls relative paths.

Flow: Home → search → results slide in from the right → school list | draggable divider | chat →
Compare modal.

## How it uses the API

- `src/api.js`: every agent turn goes through `POST /api/turn/stream`. Progress events show in the
  chat while the agent works; the `result` event carries the same body as `/api/turn`. Saves,
  unsaves and thumbs call `/api/saved` and `/api/feedback` directly (no model call).
- `src/App.jsx` applies each response's blocks:
  - `criteria_chips`: chips above the list. Inferred chips are highlighted; × sends a `chip_edit`
    remove (not offered for grade level and location). Unmapped wishes show greyed; suggested
    needs are "+" chips that send a `chip_edit` with mode `prefer`.
  - `school_results`: the cards, with each criterion's status, note and evidence (on hover),
    `watch_out`, cost (after-aid amounts always marked as estimates), Save and 👍/👎. A turn without
    results keeps the current cards.
  - `program_results`: program cards under the schools, plus the names of programs skipped for
    having only past sessions.
  - `text`, `evidence_callout` and `clarifying_question`: one chat reply. Question options are
    buttons that send an `answer`; typing while a question is open answers it too.
  - `comparison`: the Compare modal (pick 2 schools, then "Compare schools").
  - `trace`: "How I checked this" under the reply.
- Saving a school shows the nearby programs `/api/saved` returns for that school's gaps.
- "New search" starts a new session.

The logo is in `src/assets/`; replace it with the official asset.
