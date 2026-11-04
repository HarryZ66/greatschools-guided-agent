# GreatSchools Guided Search — Frontend (mock data)
```
npm install
npm run dev
```
- "How I checked this": `HowIChecked` in `App.jsx` shows a response's top-level `trace` (docs/contract.md, section 4) as a collapsible list under the agent's reply. Until the app calls `/api/turn`, the search reply uses `SAMPLE_TRACE` from `src/data.js`; pass `response.trace` instead once it's connected.
- Mock data: `src/data.js` (swap for backend API later). Logo is a placeholder SVG in `App.jsx` — replace with the official asset.
- Flow: Home → Search → results slide in from the right → school list | draggable divider | chat → Compare modal.
