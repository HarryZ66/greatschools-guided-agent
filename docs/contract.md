# Contract: needs catalog and UI blocks

**Status: draft for team review.** Everything else (extraction prompt, search queries, verify
rules, frontend components) is built on this file, so agree on it first and change it by PR.

## 1. Needs catalog

A **need** is one thing a parent cares about. The LLM maps the parent's words to needs from
this list. It never invents a need outside the list; anything it can't map goes into an
`unmapped` list that the agent can ask about.

Each need is used as `require`, `prefer` or `avoid`.

| id | Example parent words | Search (OpenSearch) | Evidence field(s) checked by code | Notes |
|---|---|---|---|---|
| `grade_level` | "middle school", "my 6th grader" | filter `level_codes` (p, e, m, h) | `level_codes` | Always required. Ask if missing. |
| `location` | "in Miami", "near 33101" | filter `city` / `zipcode`, or geo distance on `latlon` | `city`, `zipcode`, `latlon` | Always required. Ask if missing or ambiguous. |
| `school_type` | "public", "charter", "private" | filter `entity_type` | `entity_type` | |
| `high_performing` | "top school", "good ratings" | filter `summary_rating` 8–10, boost `avg_review_rating` 4–5 | `summary_rating`, `avg_review_rating` | Mirrors GreatSchools' existing need. `summary_rating` is missing for 12 of 25 schools. |
| `stem` | "STEM", "science", "coding" | boost `osp.school_sub_type: STEM`, `osp.student_clubs: science_club / math_club` | `osp.school_sub_type`, `osp.student_clubs`, review topic `STEM / Coding` | |
| `after_school_care` | "after-school care", "until 6pm" | boost on care field | `osp.end_time`, **`after_care_end_time` (synthetic, to add)** | Not in sample data; the generator must add it. Has a value (end time). |
| `transportation` | "needs a bus", "can't drive" | boost `osp.transportation: busses` | `osp.transportation` | |
| `small_classes` | "small classes", "more attention" | boost `class_size.tier` small / very_small | `class_size.tier`, `student_teacher_ratio` | Ratio over 40 is flagged as a data quality issue. |
| `gifted` | "gifted program", "advanced" | boost `gifted_talented: true` | `gifted_talented`, `osp.student_clubs: advanced_courses` | |
| `special_ed` | "IEP", "special needs" | boost review topic `Special Ed / IEP` positive | `swd_test_scores_rating`, review topic `Special Ed / IEP` | |
| `ell_support` | "English learner", "Spanish speaking" | boost `ell.tier` high / above_average | `ell.tier`, `osp.foreign_language`, `osp` translation values | |
| `safety` | "safe", "no bullying" | penalize high negative share for topic `Bullying / Safety` | review topic `Bullying / Safety`, `osp` anti_bullying | Usually `avoid` (avoid bullying). |
| `attendance` | "kids actually show up" | boost `high_attendance.tier: good` | `high_attendance.tier`, `attendance_rate` | 10 of 16 schools are under 70%: confirm what the field means before ranking on it. |
| `arts` | "art", "music", "drama" | boost `osp.arts_*` present | `osp.arts_visual`, `osp.arts_music`, `osp.arts_performing_written` | |
| `sports` | "soccer", "sports" | boost `osp.boys_sports` / `osp.girls_sports` | same | |
| `college_prep` | "college prep", "AP classes" | boost `ap_courses`, `college_readiness_rating` | `ap_courses`, `college_readiness_rating`, `career_prep.tier` | High schools only. |
| `cost` | "free", "affordable", "under $X" | filter public/charter, or tuition range | **`tuition` (synthetic, to add)** | Not in sample data. |

## 2. Status rules (decided by code, never by the model)

For every school × need, `verify_criteria` returns one status:

| Status | When | UI |
|---|---|---|
| `confirmed` | The evidence field has a value that meets the need, and it's fresh | ✅ |
| `partial` | Meets it partly (e.g. care ends at 5, parent needs 6), or only reviews support it, or the evidence is stale | ◐ |
| `needs_attention` | Evidence says the school doesn't meet it, or there's a data quality flag | ⚠️ |
| `missing` | No data for this need | ❔ "We don't know: ask the school" |

**Freshness**
- Fields with `source_generated_at`: fresh if under 18 months old.
- Reviews (`reviews_full[].created_date`): reviews over 3 years old don't count toward
  `confirmed`, and the UI labels them "older review".

**Data quality flags** (the value is shown but not used for ranking)
- `enrollment` of 0 or 1
- `student_teacher_ratio` over 40
- A school `start_time` in the PM, or an `end_time` in the AM
- City and ZIP code that don't match (programs)
- Program instances with `status: past` are never recommended

Every status carries its evidence:

```json
{
  "need": "small_classes",
  "status": "confirmed",
  "evidence": [
    {"field": "class_size.tier", "value": "very_small", "as_of": "2026-07-15", "confidence": "high"},
    {"field": "student_teacher_ratio", "value": 14}
  ],
  "note": null
}
```

## 3. API

One endpoint for everything that needs the agent:

`POST /api/turn`

```json
{
  "session_id": "abc123",
  "event": {"type": "query", "text": "middle school in Miami with STEM and after-school care until 6"}
}
```

Event types:

| type | Payload | Goes through the agent? |
|---|---|---|
| `query` | `text` | Yes |
| `answer` | `question_id`, `option_id` or `text` | Yes |
| `compare` | `school_ids` (2) | Yes |
| `chip_edit` | `need`, `mode` (require/prefer/avoid) or `removed: true` | No: code re-runs search and verify |

Omit `session_id` on the first turn; every response returns the `session_id` to send next time.

Saving and feedback skip the agent entirely:

- `POST /api/saved`: `{session_id, school_id}` → `{saved: [...]}`
- `GET /api/saved?session_id=…` → `{saved: [{school_id, name, at}]}`
- `DELETE /api/saved/{school_id}?session_id=…` → `{saved: [...]}`
- `POST /api/feedback`: `{session_id, school_id, vote: "up" | "down"}`
- `GET /api/schools/{school_id}`: full school record (profile view)
- `GET /api/metrics`: `{searches, saves, saves_to_searches, thumbs_up, thumbs_down, relevance, criteria_per_search}`

A `compare` turn returns `criteria_chips` and a `comparison` block (no `school_results`);
the comparison's `summary` is the agent's one-line take.

## 4. Response: UI blocks

The agent answers with an ordered list of blocks. The frontend has one component per block
type and renders them in order. The agent chooses which blocks to send.

```json
{
  "session_id": "abc123",
  "blocks": [ ... ]
}
```

### `criteria_chips`

```json
{
  "type": "criteria_chips",
  "chips": [
    {"need": "grade_level", "mode": "require", "label": "Middle school", "value": "m", "source": "stated"},
    {"need": "location", "mode": "require", "label": "Miami, FL", "value": {"city": "Miami", "state": "FL"}, "source": "inferred"},
    {"need": "after_school_care", "mode": "require", "label": "Care until 6pm", "value": "18:00", "source": "stated"},
    {"need": "stem", "mode": "prefer", "label": "STEM", "source": "stated"}
  ],
  "unmapped": []
}
```

`source` is `stated`, `inferred` (the agent assumed it: show it editable and highlighted) or
`answered` (from a clarifying question).

### `clarifying_question`

At most one per turn.

```json
{
  "type": "clarifying_question",
  "question_id": "q1",
  "text": "Care at the top 3 schools ends at 5pm. Is that workable?",
  "why": "3 of 5 matches end care at 5pm; your answer changes the ranking.",
  "options": [
    {"id": "ok_5pm", "label": "5pm is fine"},
    {"id": "need_6pm", "label": "I need until 6pm"}
  ],
  "allow_text": true
}
```

### `progress`

Streamed while the agent works (the "I checked this for you" trace).

```json
{"type": "progress", "text": "Checking after-school hours for 9 schools…"}
```

### `school_results`

```json
{
  "type": "school_results",
  "results": [
    {
      "school_id": "fl-95390",
      "name": "Bayside Middle School",
      "entity_type": "public",
      "city": "Miami",
      "rank": 1,
      "score": 0.82,
      "criteria": [ {"need": "...", "status": "...", "evidence": [], "note": "..."} ],
      "watch_out": "Attendance tier is 'poor', and two recent reviews mention understaffing.",
      "saved": false
    }
  ]
}
```

### `evidence_callout`

```json
{
  "type": "evidence_callout",
  "school_id": "fl-95390",
  "text": "I checked this for you: the STEM listing is from 2023, so I treated it as a nice-to-have.",
  "evidence": [ {"field": "osp.school_sub_type", "value": "STEM", "as_of": "2023-05-01"} ]
}
```

### `comparison`

```json
{
  "type": "comparison",
  "school_ids": ["fl-95390", "fl-10421"],
  "rows": [
    {"need": "after_school_care", "cells": [ {"status": "partial", "text": "Until 5pm"}, {"status": "confirmed", "text": "Until 6pm"} ]}
  ],
  "summary": "Coral Cove covers your 6pm need; Bayside has smaller classes."
}
```

### `text`

Plain answer, e.g. a term definition.

```json
{"type": "text", "markdown": "**Charter school**: a free public school run independently, often entered by lottery."}
```

## 5. Rules the backend enforces

- Every `evidence` item must point to a field that `verify_criteria` actually returned.
  Responses that cite anything else are rejected and retried once.
- The response must match this schema; on a second failure the backend falls back to
  `school_results` built directly from code.
- At most about 6 tool calls per turn.
