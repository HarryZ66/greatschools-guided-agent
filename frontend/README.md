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

Animation uses [Motion](https://motion.dev) (`motion/react`), the library MagicUI's components are
built on. MagicUI itself needs Tailwind, and this app uses plain CSS. Motion is used where it shows
what changed after a parent acts:
- cards come in one after another, and slide to their new place when a chip edit changes the results
- chips grow in and shrink out
- the heart pops when a school is saved
- the drawer, the compare window and My list animate both open and closed
- chat replies slide in
- the phone tabs' highlight slides between Schools and Chat

The one effect that isn't a reply to an action is a single shine across each "Best for" ribbon when
results land. `MotionConfig reducedMotion="user"` turns movement off for anyone whose device asks
for reduced motion.

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
  - `school_results`: short cards in a grid that fits as many columns as the list pane allows (one
    on a phone). Each card has a school-type tag (Public / Charter / Private), a heart to save, the
    name (opens the details panel), city and cost (after-aid amounts always marked as estimates),
    the school's one `badge` ("Best for ...", if it has one), "Good to know" (`watch_out`, two
    lines) and Compare. No rank numbers and no "% fit": the per-need checklist (Yes / Partly /
    Watch out / Not known) is in the details panel, with the badge's reason. A turn without
    results keeps the current cards.
  - `program_results`: program cards under the schools, in miles, plus the names of programs
    skipped because their sessions already ended.
  - `text`, `evidence_callout` and `clarifying_question`: one chat reply. Question options are
    buttons that send an `answer`; typing while a question is open answers it too. Each reply
    shows its first sentence and the question; "View more" opens the rest of the text, the data
    notes (`evidence_callout`), the question's `why` and guide sources. A collapsed reply with data
    notes shows "⚠️ 1 data note" (decision 033).
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
