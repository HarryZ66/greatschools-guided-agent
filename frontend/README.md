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
  "Helpful?" votes and school details call `/api/saved`, `/api/feedback` and `/api/schools/{id}`
  directly (no model call).
- `src/App.jsx` applies each response's blocks:
  - `criteria_chips`: chips above the list ("Must" marks a must-have). Inferred chips are
    highlighted; × sends a `chip_edit` remove (not offered for grade level and location). Unmapped
    wishes show greyed; suggested needs sit under "Also worth checking?" as "+" chips that send a
    `chip_edit` with mode `prefer`.
  - `school_results`: compact cards: a small rank badge, "% fit", a heart to save, and one line per
    criterion with its status (Yes / Partly / Watch out / Not known) and the plain-language note.
    Then "Good to know" (`watch_out`), cost (after-aid amounts always marked as estimates), "See
    details and reviews" and Compare. A turn without results keeps the current cards.
  - `program_results`: program cards under the schools, in miles, plus the names of programs
    skipped because their sessions already ended.
  - `text`, `evidence_callout` and `clarifying_question`: one chat reply. Question options are
    buttons that send an `answer`; typing while a question is open answers it too.
  - `comparison`: the Compare modal (pick 2 schools, then "Compare schools"). The reply in the chat
    carries the summary and an "Open the comparison table" link.
  - `trace` and `turn`: under each reply, "How I checked this" and "Helpful? 👍 👎" (rates that reply).
- "See details and reviews" opens a side panel with the verified profile (P3): ratings, the same
  checks as the card, dated parent quotes (older ones marked), data problems and plain meanings of
  terms on the page.
- The heart saves a school; "♥ My list" in the header lists saved schools. Saving shows the nearby
  programs `/api/saved` returns for that school's gaps.
- The home page offers three example searches for parents who don't know what to ask.
- "New search" starts a new session.

The logo is in `src/assets/`; replace it with the official asset.
