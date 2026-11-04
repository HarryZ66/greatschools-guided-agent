# Next steps: closing the gaps for judging

**Status (Tue Nov 3, evening): tasks 1–4 are done and deployed; 5 and 6 are open stretch goals.**
Original plan by Sanchit; statuses updated as work lands.
This file lists what's left, in priority order, in the terms of `docs/contract.md` and
`docs/decisions.md`. When a task changes a block or an endpoint, update `docs/contract.md` in the
same PR. When it changes a decision, add a new numbered entry to `docs/decisions.md`.

## Where we stand

| GreatSchools requirement | Status in this repo |
|---|---|
| P1: one box, criteria chips (require / prefer / avoid), clarifying question, gap-spotting, ranked results with evidence | Done (`/api/turn`, `criteria_chips`, `clarifying_question`, `school_results`, `suggested`, `unmapped`) |
| Confirmed / partial / needs attention per criterion, with evidence | Done (`needs.verify`, decision 002) |
| Flag missing or stale data instead of guessing | Done (`missing` status, freshness rules, `quality_flags`, `evidence_callout`) |
| P2: compare two schools | Done (`compare` event, `comparison` block) |
| P3: detail from a school profile | Done (`GET /api/schools/{id}?session_id=` adds a verified `profile`, decision 019) |
| P4: define terms, explain the framework | Done (`lookup_content` over the parent guide in OpenSearch, with sources, decision 008) |
| Save to a list, thumbs up/down, metrics | Done (`/api/saved`, `/api/feedback`, `/api/metrics`) |
| Infrastructure as code | Done (CDK: `GsDataStack`, `GsAppStack`) |
| Parent-facing app | React app in `frontend/` on mock data; next step is wiring it to `docs/contract.md`. A test page is live meanwhile |

Pain points we lead with, in priority order: parents don't know what to ask (#2), don't know about
cost help (#4), don't know the jargon (#1), have no time (#10), can't tell what to trust (#8).
#1, #8 and #10 are already covered by the work above. #2 and #4 need the tasks below.

## Tasks, in priority order

### 1. Pain point #2: a mental health need, suggested when the parent doesn't mention it (done, decision 017)

GreatSchools told us mental health moved into parents' top five concerns, and parents rarely ask
about it themselves.

- `needs.CATALOG`: add `mental_health` ("Counseling and mental health support").
- `needs.RULES`: `v_mental_health` reads `osp.mental_health` (school_counselors,
  social_workers, mental_health_specialists, positive_intervention, anti_bullying) and the
  `Mental Health` review topic with the existing recent/older split. Confirmed when the profile
  lists counselors or specialists and the profile isn't stale; partial when only reviews support it
  or the profile is stale; missing when neither exists.
- `search.BOOSTS`: boost on `osp.mental_health` present.
- Prompt: when the parent hasn't mentioned it, `mental_health` is a good candidate for one of the
  two `suggested` needs, with a `why` such as "Many parents now ask about counseling support."
- Tests: rule cases (counselors listed / reviews only / stale profile / nothing), and a suggestion test.

### 2. Pain point #4: show cost after typical scholarship help (done, decision 018)

Built with the official FLDOE figure: $8,200 average FES-EO award in 2024-25 (income limits removed in
2023-24). The 185% poverty-level priority and an "about $8,000" 2026-27 figure below could not be
confirmed from an official source, so they are not shown to parents.

Today `v_cost` marks a private school above the parent's budget as `needs_attention` and stops.
Parents with less money rule out schools without knowing help exists.

- Add `agent/gs_agent/content/funding.json`:
  - `fl_fes_eo_ftc`: Florida scholarships (FES-EO / FTC). Any Florida K–12 student eligible for
    public school can apply; priority for families up to 185% of the federal poverty level;
    average award about $8,000; applications usually open in February. Status `available`.
  - `federal_tax_credit_sgo`: federal tax-credit scholarships starting 2027; may cover tutoring and
    other services for public-school students and tuition for private. Status `coming_soon`.
    No amounts, no rules: always say "details pending".
- `v_cost` for private schools with `tuition`: add evidence
  `{"field": "funding.fl_fes_eo_ftc.typical_amount", "value": 8000}` and a note such as
  "About $8,500/year after a typical Florida scholarship (estimate)." Status stays code-decided:
  `partial` when tuition minus the typical award fits the parent's budget (or no budget was given),
  `needs_attention` when it still doesn't.
- `school_results`: add an optional `cost` object per result:
  `{"tuition": 16500, "after_aid_estimate": 8500, "aid": ["fl_fes_eo_ftc"]}`. Public and charter
  schools: `{"tuition": 0}`. Update `docs/contract.md`.
- Prompt: if private schools were excluded only by cost, the clarifying question may offer to
  include schools a scholarship could help pay for.
- Demo case: Brightwater Preparatory School ($16,500) should show the estimate.
- Tests: estimate math, status with and without a budget, public/charter unchanged.

### 3. P3: a verified profile view (done, decision 019; the record stays at the top level)

- `GET /api/schools/{school_id}?session_id=…` returns, in addition to today's record (move it
  under `record`), a `profile` object:
  - `criteria`: `needs.verify` for every need in the session (same rules as the cards).
  - `quality_flags`: as on the card.
  - `reviews`: per topic, recent and older positive/negative counts (reuse `review_topic`),
    plus up to 3 short excerpts with their dates, marked "older review" when over 3 years old.
  - `terms`: plain meanings for fields on the page (rating types, school type, IEP, AP/IB),
    looked up from the glossary.
- No model call (same reasoning as decision 006).
- Tests: profile criteria match the card's criteria for the same session.

### 4. Programs that pair well with a saved school (done, decision 020)

Programs were already built into search turns (decision 010), indexed in OpenSearch with 65
records; saving a school now also returns gap-matched programs.

Decision 008 kept programs out to avoid splitting the search box. GreatSchools reps were positive
about programs as a companion, so we add them **only after a parent saves a school**, matched to
that school's gaps. The search box stays schools-only.

- New decision 013 in `docs/decisions.md` recording this.
- `data/generate_programs.py`: about 15 fictional Miami-area programs (library and community):
  coding club, robotics, math tutoring, homework help, after-school care until 6–6:30 PM,
  a teen counseling or support group, arts. Each has `program_id`, `name`, `organization`,
  `program_type`, `tag_names`, `location` (lat/lon), `cost`, `instances` with `start_date`,
  `start_time` and `status`. Give most an upcoming session after 2026-11-04 and give 2–3 only
  past sessions. `"synthetic_generated": true`.
- `agent/gs_agent/programs.py`: load the JSON in memory (15 records don't need an index; a
  `programs` OpenSearch index is a later step). `NEED_TAGS` maps needs to program tags
  (stem → STEM/Coding/Robotics, after_school_care → Afterschool/Homework Help,
  mental_health → Counseling/Teen Support, arts → Arts, college_prep → Tutoring).
- `POST /api/saved` adds `programs` (at most 3) to its response: candidates whose tags match a
  need that is `partial`, `needs_attention` or `missing` at the saved school **and** that have an
  upcoming session. Order by tag match, distance to the school, free first, soonest session.
  Each has a `why` written by code from the facts, for example
  "Care at Tamarind Cove ends at 5:00 PM. This homework club runs until 6:00 PM, 2 km away."
  No model call.
- Demo cases: Tamarind Cove (care ends 17:00, parent needs 18:00) → after-school program;
  Kestrel Point (no STEM program) → coding club.
- Tests: past-only programs never appear; a school with every need confirmed gets no programs.

### 5. Stretch: "answer first, then context"

GreatSchools asked us to answer the question asked and add context as support, not redirect.
Add an optional `context` field (one sentence) to the model's decision and render it as a muted
`text` block after the answer. Example: a ratings question gets "Ratings compare schools within
Florida only; a lower score can hide strong growth."

### 6. Stretch: how you get in

Add `entry_type` to generated schools (`zoned`, `open_enrollment`, `lottery`, `application`) and
show it on the card. Low priority.

## Cut order if time runs short

6 → 5 → programs fall back to "nearby programs" without gap matching → profile shows only criteria
and reviews. Never cut tasks 1, 2 and 3.

## Not in scope

The parent app (separate repo), the day-in-the-life timeline, family voting, voice input, real routing, real attendance boundaries,
"if we move" lens, login, real GreatSchools data, student data.
