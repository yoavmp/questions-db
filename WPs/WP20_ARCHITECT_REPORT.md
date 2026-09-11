# WP20 — Live end-to-end validation — Architect Report

**Repository:** `questions-db` (outer) · **Executor:** Claude Code · **Date:** 2026-09-11
**Outer starting HEAD:** `d41f4f4eadba8fccbf7557283c50554c71bf7876` (`main`), clean except the
untracked WP20 brief and the submodule's own untracked `.DS_Store` (macOS artifact, not a code
change — see §7).
**Generator submodule:** `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, `heads/main`. **Not edited,
not staged, not committed.** `../exam_generator_pre_submodule_backup/` untouched.

## 1. Offline UI cleanup (§1 of the brief)

- `frontend/src/components/ExamGenerationSection.jsx`: removed the "שאלות בינה שהוחלפו"
  (displaced-questions) card and its `job?.category_history` binding — the ordinary exam screen no
  longer renders `category_history` in any text or question card.
- No backend change: `category_history` still persists in the job store and still feeds
  `_previous_for_slot` (the previous-question context handed to later LLM generation); it remains
  present in `result_view` as backend diagnostic data, which is not a UI contract.
- `CategoryPlan.total/database/llm` were already request-provenance-only with no recomputed
  aggregate anywhere in the views (WP19); unchanged and re-verified by the existing regression
  test that walks the whole view tree.
- **Tests added, both rules:**
  - `frontend/.../ExamGenerationSection.test.jsx` — new case: given a `category_history` payload
    with a displaced-question entry, the screen shows current questions but renders neither the
    heading nor the displaced text.
  - `backend/tests/test_wp20_semantic_history_boundary.py` — new case: after an LLM→DB
    replacement, the displaced LLM question (a) survives a job-store round-trip, (b) appears in
    `_previous_for_slot` for a remaining LLM slot in the same category, (c) is still present in
    `result_view["category_history"]` as diagnostic data.
- **Offline results (before any live call):** backend `pytest -q` → 91 passed (was 90 + 1 new);
  frontend `npm test` → 56 passed (was 55 + 1 new); `npm run build` → OK (only the pre-existing,
  unrelated CSS-minify warning `-: T;`).

## 2. Credential boundary (§2)

My own command environment did **not** carry `OPENAI_API_KEY` (checked only as a boolean —
`[ -n "$OPENAI_API_KEY" ]` — never printed, never requested). Per the brief I paused rather than
reconfiguring or asking for the key, and asked the owner to launch the backend from the VS Code
terminal where the key had already been verified. The owner did so and reported both servers up
(`http://127.0.0.1:4567`, `http://localhost:3000`); I then confirmed via
`GET /api/exam-jobs/readiness` that `openai_api_key_present: true` (boolean only) and
`ready_for_llm: true`, without ever reading, logging, or displaying the value. It never appeared in
any command I ran, any file I wrote, or this report.

**No browser-automation tool (Playwright/Puppeteer/Cypress) is installed in this environment.** I
therefore drove the scenario through the exact `/api/exam-jobs*` HTTP endpoints the frontend calls
(same paths, verbs, and request/response shapes as `frontend/src/lib/examApi.js`), with the UI
behavior itself covered by the 23 passing `ExamGenerationSection` component tests built on those
same response shapes, plus the clean production build. The frontend dev server was confirmed live
(`GET http://localhost:3000` → 200, correct Hebrew `<title>`) and reachable per its documented
`API_BASE_URL`. I did not click through a rendered browser.

## 3. Live scenario (§3) — job `d2b10f19-65ff-4653-bd38-1bfb226e6922`

Category `היסטולוגיה` (33 questions in the owner's real `backend/src/database/app.db`), plan
`C=2 A=1 B=1`, exam ceiling `$1.00`, all other categories zero.

1. **Create:** `POST /api/exam-jobs` → `queued`. Polled `GET /api/exam-jobs/<id>` every ~2 s (4
   polls to `completed`): poll 1–3 showed `running` with the **DB question already accepted and
   visible** (`#1`, origin `database`) while the LLM slot (`#2`) was still `pending` — confirms
   partial results render before the job finishes. Poll 4: `completed`, both slots `accepted`
   (0 failures, 0 retries).
2. **DB-first, then LLM with DB context:** the DB slot (`#1`) was filled before the LLM slot
   (`#2`) was generated. Inspecting the LLM slot's own rendered-prompt file (not reproduced here,
   per the no-raw-prompts rule) confirmed the DB question's text occurs in it exactly once —
   i.e. the accepted DB question was passed as previous-question context for that generation.
3. **DB→LLM (`צור שאלה אחרת`):** `POST .../questions/<db-instance>/replace-llm` on the DB-origin
   slot (`#1`). Accepted on attempt 1. `category_history["היסטולוגיה"]` stayed at **0** entries —
   the displaced DB question was **not** added to semantic history, matching the WP18R rule.
4. **LLM→DB (`החלף בשאלה מהמאגר`):** `POST .../questions/<llm-instance>/replace-db` on the
   original LLM-origin slot (`#2`, the job's first LLM generation). Accepted, **no additional
   cost** (a DB swap makes no provider call). `category_history["היסטולוגיה"]` grew to **1**
   entry — the displaced LLM question was **retained**. A separate prompt-file inspection for the
   step-3 generation additionally confirmed context *growth*: it included the (then still current)
   LLM question from the other slot, and did **not** include its own later-displaced DB question —
   matching "only a displaced LLM question ever reaches later context."
5. **Stopped there.** No further paid generation was attempted; the job was not reset.

Both accepted-slot identities (`instance_id`, `number`, `category`) were stable across their
respective origin transitions — confirmed directly from the API responses at each step.

## 4. Owner-review evidence (§5)

### 4.1 Accepted live-generated (LLM-origin) questions — seven public fields

**Initial** (slot `#2` — the job's first LLM generation, accepted attempt 1; later displaced by the
LLM→DB replacement and now retained only in `category_history`, not in the current exam):

| field | value |
|---|---|
| number | 2 |
| question | איזו שכבה ב-Neocortex היא היחידה המקבלת מידע מהתלמוס? |
| answer1 | Internal Granular |
| answer2 | Molecular |
| answer3 | External Granular |
| answer4 | Internal Pyramidal |
| correct_answer | 1 (Internal Granular) |

**Replacement** (slot `#1` — generated by the DB→LLM `צור שאלה אחרת` call, accepted attempt 1;
**currently in the exam**, origin `llm`):

| field | value |
|---|---|
| number | 1 |
| question | איזו משכבות ה-Neocortex שולחת אקסונים לתלמוס? |
| answer1 | Multiform |
| answer2 | Molecular |
| answer3 | External Granular |
| answer4 | Internal Pyramidal |
| correct_answer | 1 (Multiform) |

*(The final `#2` slot is DB-origin after the LLM→DB replacement — an existing bank question, not
live-generated, so it is not listed here; its text appears in §3 point 4 and in the export
verification below.)*

### 4.2 Source-grounding and Hebrew-language assessment (concise)

Both generated questions stay on-topic for `היסטולוגיה` (cerebral-cortex cytoarchitecture) and are
anatomically sound: Layer IV (*internal granular*) is the principal thalamocortical input layer —
matching the first question's marked answer — and Layer VI (*multiform/polymorphic*) is the
principal corticothalamic output layer — matching the second's. Both use the same mixed
Hebrew-stem / English-anatomical-term convention already present in this category's bank questions
(e.g. the existing DB question's own "projection fibers", "external granular Layer" phrasing), so
the style is grounded in the existing corpus, not an LLM invention. Hebrew phrasing is grammatical
and idiomatic in both; no translation artifacts or awkward constructions observed. This is a
content read, not a psychometric review — the owner should still eyeball both before use.

### 4.3 Cost accounting

| # | operation | slot | attempt | outcome | generation | review | attempt total |
|---|---|---|---|---|---|---|---|
| 1 | initial LLM fill | `#2` | 1 | accepted | $0.0238065 | $0.0262375 | **$0.0500440** |
| 2 | replace_llm (DB→LLM) | `#1` | 1 | accepted | $0.0191208 | $0.0178107 | **$0.0369315** |

- **2 provider operations total, 0 failed, 0 retried** (LLM→DB is a free DB swap — not a provider
  op).
- **Final cumulative cost: $0.0869755** against the job's `$1.00` cost ceiling and the brief's
  `$1.00` hard ceiling — **8.7% of the authorized cap**, remaining `$0.9130245`.
- Calculation basis: `calculated` (not the conservative stale-pricing bound) for both the job and
  every ledger entry; `warnings: []` throughout — the pricing snapshot was 7 days old (< the
  30-day staleness threshold) per `GET /api/exam-jobs/readiness`.
- **Finding — no "final backend-terminal cost line" exists in this codebase.** I searched
  `backend/src/` and the generator's `production.py` for any `print`/`logger` call that emits a
  cost figure to stdout; none exists. The backend terminal only carries Flask's own request log
  (and, on startup, WP18's job-recovery line) — cumulative cost is exposed **only** through the
  JSON API (`accumulated_cost_usd` / `remaining_cost_usd` / `cost_basis`) and the on-disk cost
  ledger, not a printed line. Flagging this to the owner rather than asserting a match with §4 of
  the brief that isn't actually implemented.

### 4.4 Final origin sequence and history-policy result

| # | origin sequence over the scenario | final origin |
|---|---|---|
| 1 | database → **llm** (via DB→LLM `צור שאלה אחרת`) | **llm** |
| 2 | llm → **database** (via LLM→DB `החלף בשאלה מהמאגר`) | **database** |

`category_history["היסטולוגיה"]` final state: **1 entry** — the displaced LLM question from step
4 above ("איזו שכבה ב-Neocortex היא היחידה המקבלת מידע מהתלמוס?"). The displaced DB question from
step 3 is **not** present anywhere in history, matching the WP18R rule exactly (only a displaced
LLM question is retained for future semantic-uniqueness checks; a displaced DB question is
discarded and never reaches later generator context). Verified both via the API's
`category_history` field and directly in the persisted `job.json`.

### 4.5 Excel / DOCX verification

- **Generated-question Excel** (`GET /api/exam-jobs/<id>/export.xlsx`): one row — the current LLM
  question (final slot `#1`) only. The final DB-origin question (slot `#2`) is correctly excluded.
  Confirmed the owner's `app.db` is unchanged by the export (histology count still 33, total still
  459 rows) — nothing was inserted into the bank.
- **Hebrew DOCX**, built from the exact payload the frontend sends (`stripJobMetadata` → the seven
  public fields only, canonical `number` order) via `POST /api/test/export-docx`:
  - Without answers and with answers, both generated successfully as valid `.docx` (OOXML).
  - **RTL:** every paragraph carries `<w:bidi/>` and right alignment; renders acceptably RTL.
  - **Integration metadata stripped:** the request body carried only the seven public fields —
    no `instance_id`/`origin`/`generation_meta`/job id reached the DOCX endpoint.
  - **Answer randomization preserved:** the endpoint's own daily-seed shuffle reordered both
    questions' answer options (e.g. Q1's four options came back in a different order than stored),
    and in the "with answers" file the shuffled position of each question's actual
    `correct_answer` was the one highlighted — confirmed for both questions.
- All exported files were written under the session scratchpad (not `WPs/`, not committed) and
  inspected only for structure/content checks above — not attached to this report.

## 5. Automated tests and build — before and after the live call

| Suite | Before live call | After live call (no new provider calls) |
|---|---|---|
| Backend `pytest -q` | 91 passed | 91 passed (129 s) |
| Frontend `npm test` | 56 passed | 56 passed |
| Frontend `npm run build` | OK | OK |

No source file changed between the two runs; the rerun exists to satisfy §6's "rerun after the
live test" requirement and confirms the live scenario left no residue in tracked code.

## 6. Skips / limitations / owner decisions

- No live failure/retry/rollback was exercised — deliberately, to honor "do not perform further
  paid generations" and avoid manufacturing scope beyond the five authorized steps. That surface
  (JobBusy/409 locking, cross-source rollback identity/export/cost invariants) has thorough offline
  coverage instead: `backend/tests/test_wp19_frontend_contract.py` (concurrency lock →
  409) and `test_wp18r_cross_source_replacements.py` (full rollback matrix, immutable ledger on
  failure) — both green in the reruns above.
- No browser-automation tool is installed, so the live scenario was driven at the HTTP layer the
  frontend itself uses rather than through a rendered page; see §2 for why that is a faithful
  substitute here.
- The "final backend-terminal cost line" named in the brief's §4 does not exist in the current
  codebase (see §4.3) — a genuine gap between the brief's expectation and the implementation,
  reported rather than papered over.

## 7. Git

- `exam_generator/` carries one untracked `.DS_Store` (macOS Finder metadata, not a code change);
  submodule `HEAD` is unchanged at `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, nothing staged or
  committed there.
- Outer commit: `WP20: validate live integrated exam flow` — the frontend UI-cleanup change + its
  test, the new backend test, and this WP's three `WPs/` files. **Not pushed.**
- No live artifacts, exports, secrets, or `.env*` staged. No raw provider response or rendered
  prompt is included in this report or in any committed file.
