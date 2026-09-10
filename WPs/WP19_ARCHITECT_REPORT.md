# WP19 — Connect the exam-generation frontend — Architect Report

**Repository:** `questions-db` (outer) · **Executor:** Claude Code · **Date:** 2026-09-10
**Outer starting HEAD:** `4cd86d17203d97e1debad5f8adc3efb747740440` (`main`, clean bar the intended
untracked `WPs/WP19_Frontend_Exam_Generation.md`).
**Generator submodule:** `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, `heads/main`, **clean, unchanged,
not staged / committed / pushed.** No gitlink change. `../exam_generator_pre_submodule_backup/` untouched.
**Offline:** no `OPENAI_API_KEY` read, zero provider/network calls. Frontend tests use fake API
fixtures and a `fetch` stub that throws on any un-mocked call.

## 1. Repository boundary

Outer repo only. Backend: 2 source files + 1 new test file. Frontend: `App.jsx` (swap the tab
component + delete the legacy one), 3 new `src/lib` + `src/components` modules, 3 new test files,
a minimal Vitest/Testing-Library setup in `package.json` / `vite.config.js`. No change to the
adapter, readiness, generator boundary, DTO, cost engine, persistence, API routes/verbs, or the
legacy `/api/test/*` path.

## 2. Backend hardening (§1)

**`replace_from_db` concurrency (`backend/src/jobs/service.py`).** The DB swap now acquires the same
process-wide `_RUN_LOCK` (non-blocking) **and** per-job `store.try_acquire_lock` file lock as
`run_job` / `retry_slot` / `replace_via_llm`, released in `finally`. A held lock raises `JobBusy`
before the slot is read or mutated, so a double click or a concurrent `run_job` / retry / LLM
replacement cannot cause a lost update, a duplicate DB selection, or half-written `job.json`
(atomic `os.replace` still applies). `routes/exam_jobs.py::replace_db` now maps `JobBusy → 409`
(it already mapped `JobConflict`/`JobError`).

**Attempt/retry telemetry (`service.ledger_telemetry`).** New pure fold over the append-only
`job.cost_ledger`, surfaced as `result_view()["attempt_telemetry"]` (so `GET /api/exam-jobs/<id>`
carries it). Shape: `by_category` and `by_slot` counters (`attempts`, `failed_attempts`,
`charged_failed_attempts` = failed **and** `cost > 0`, `retries`, `replacements`, `accepted`,
`cost_usd`, `entries`) plus `totals` (+ `ledger_entries`). `by_slot` rows carry `number`,
`instance_id`, current `kind`, and the ordered `outcomes` list. Because it reads the ledger, not
slot state, a **charged failed LLM-replacement attempt stays diagnosable after the slot rollback**
that `replace_via_llm` performs on failure. `by_category` / `by_slot` never partition by current
origin — this is a generation-effort history, not a DB-vs-LLM balance.

**C/A/B stay request provenance only.** No backend change was needed: `CategoryPlan.total/database/
llm` already hold the original request quotas and `progress_view` / `result_view` expose no realised
or current origin tally. The docstrings now say so explicitly, and a new test walks the whole view
tree asserting no key matches `current_*/realised/db_count/composition/...` after origin-flipping
replacements. The per-question `origin` field is the only composition signal.

## 3. Frontend (§2–§6)

New `src/lib/examGen.js` (pure, unit-tested): `parseCount` (empty box = 0; negatives / decimals /
non-numbers are invalid, never clamped), `deriveFromTotal` (C → A=`ceil(C/2)`, B=`floor(C/2)`),
`deriveFromParts` (A|B → C=A+B), `applyRowEdit` (couples the three raw-string boxes, keeps an
invalid entry verbatim), `validateRow` (integer + `A ≤ availability` + `A+B==C`), `llmBlockedReasons`
(readiness blocks **only** when `ΣB > 0`; DB-only always allowed), `pricingWarnings` (stale → warn,
never block), `parseCeiling`, `startBlockers`, `buildCreatePayload` (canonical order preserved,
rows with `total>0` only), `orderQuestions`, `stripJobMetadata` (keeps exactly the seven public
fields, answer order untouched), `retryableSlots`, and `saveActiveJobId` / `loadActiveJobId` /
`syncJobIdToUrl` (localStorage key `examJob.activeId` + `?examJob=<id>` via `history.replaceState`;
URL wins on resume — there is no router, so a query string is safe).

New `src/lib/examApi.js`: thin `fetch` wrappers for `POST/GET /api/exam-jobs*`, `…/slots/<id>/retry`,
`PUT …/cost-ceiling`, `…/questions/<iid>/replace-db|replace-llm`, `…/export.xlsx`, plus
`GET /api/test/categories`, `GET …/readiness`, and the **existing** `POST /api/test/export-docx`
(questions run through `stripJobMetadata` here). Non-2xx throws an `Error` carrying `{status, body}`.

New `src/components/ExamGenerationSection.jsx` replaces `TestGenerationSection` in the "יצירת מבחן"
tab (`App.jsx`); the legacy component — and its synchronous `/api/test/generate` +
`/api/test/replace-question` calls and the single `החלף שאלה` control — is **deleted**. Legacy
backend endpoints are left in place.

- **Builder:** all 20 categories from `/api/test/categories` in canonical order, three
  nonnegative-integer boxes each (`סה"כ` / `מהמאגר` / `בינה`) with the coupling above, inline
  `role="alert"` errors, `A > availability` blocks Start (no clamp), editable `$5.00` ceiling
  default, stale-pricing warning banner, an aggregated "blockers" list, and a Start button disabled
  while any blocker holds or a submit is in flight (`startingRef` + `starting` state ⇒ single
  `POST /api/exam-jobs`).
- **Persistence / resume:** on create, id is saved to localStorage + URL; on mount an existing id
  is fetched once; a stale id is forgotten.
- **Polling:** `GET /api/exam-jobs/<id>` every 1.5 s while `queued`/`running`; stops at every
  terminal state. Accepted partial questions render on each poll.
- **Progress:** overall (accepted / requested, LLM accepted / requested, cumulative cost / ceiling,
  basis, remaining), per-category (`ביקשו` provenance + accepted/failed/pending), per-slot chips
  (kind, status, attempts `נ`, retries `ח`, `⚠` on `safe_error`). `completed` / `partial` /
  `interrupted` / `cost_ceiling` / `failed` each get a clear status badge. Retry button on every
  eligible LLM slot → `…/retry`. Raise-ceiling input → `PUT …/cost-ceiling`, then retry.
- **Results:** questions in canonical/global-number order; **every** accepted question shows an
  origin badge **and both** `החלף בשאלה מהמאגר` (→ `replace-db`) and `צור שאלה אחרת` (→
  `replace-llm`), wired to the WP18R endpoints; the view is refreshed from the server response so
  the badge follows the new origin for all four transitions. Any in-flight mutation disables every
  replacement/retry control; on failure `job` is not replaced, so the current question stays
  visible and unchanged with an error line. Displaced-LLM `category_history` is shown; no
  displaced-DB retention. The per-question badges are the **only** composition indicator — no
  recomputed current DB/LLM count; the per-category line shows only the original request quotas.
- **Telemetry / cost:** cumulative LLM cost, `cost_basis`, `job.warnings`, and `attempt_telemetry`
  totals + per-category rows shown verbatim — no invented precision.
- **Outputs:** one-click Hebrew DOCX (± answers) via `POST /api/test/export-docx` from the current
  set, job metadata stripped, answer randomisation left to that endpoint; generated-question Excel
  via `GET /api/exam-jobs/<id>/export.xlsx`; a note states generated questions are session-only.
- **Quality:** same `Card`/`Button`/`Badge`/`Input` primitives, `hebrew-text` RTL classes,
  `aria-label` on every input, `role="alert"` errors, responsive grid; `App.jsx` otherwise untouched.

## 4. Test setup

`package.json`: `test` → `vitest run`; devDeps `vitest@^1.6`, `@testing-library/react@^16`,
`@testing-library/dom@^10`, `@testing-library/user-event@^14`, `@testing-library/jest-dom@^6`,
`jsdom@^24` (RTL 16 + dom 10 chosen so `user-event` and RTL share one `@testing-library/dom`
copy — a 14/9 + 10 split otherwise leaves `fireEvent` outside `act`). `vite.config.js` gains a
`test` block (`jsdom`, `globals`, `setupFiles`, `include: src/**/*.{test,spec}`). `src/test/setup.js`
loads `jest-dom`, clears `localStorage` after each test, and stubs `fetch` to throw.

## 5. Test commands & results

- **Backend, serial, temp DB, sockets blocked, zero provider calls:**
  `cd backend && python -m pytest -q` → **90 passed** (84 prior + 6 new
  `tests/test_wp19_frontend_contract.py`), ~121 s, one process.
  New tests: `replace_from_db` refuses while `_RUN_LOCK` held (and route → 409); sequential DB
  replacements never duplicate a row / lose an update / break `db_selected_ids`; `ledger_telemetry`
  folds by category + slot and matches `result_view`; a charged failed LLM-replacement attempt is
  still in the telemetry after the slot rollback; no `current/realised` DB-vs-LLM key anywhere in
  `result_view` / `progress_view` after flipping both origins.
- **Frontend:** `cd frontend && npm test` → **55 passed** (3 files), ~2 s, 0 React `act()` warnings.
  `examGen.test.js` (27) pure logic; `examApi.test.js` (6) endpoint paths/verbs + error shape +
  DOCX body carries only the seven fields; `ExamGenerationSection.test.jsx` (22) drives the screen
  through every §Verification bullet — canonical render, in-UI C/A/B, availability error + Start
  block, LLM-not-ready blocks B>0 only, stale-warn non-blocking, `$5.00` default, double-submit,
  persistence + resume, polling with immediate partials, interrupted + retry, cap raise via PUT,
  per-category/per-slot progress, both controls on both origins, all four transitions with badge
  flip, failure-keeps-question, mutation locking, no recomputed aggregate, telemetry + warnings,
  Excel via job endpoint, DOCX via legacy path in canonical order.
- **Frontend production build:** `npm run build` → OK, 1261 modules, `dist/` written (pre-existing
  unrelated CSS-minify warning `-: T;` only).
- **Generator-boundary tests:** not run — no adapter/generator-interface change (WP18R precedent);
  the submodule tree stays clean, nothing committed there.

## 6. Files changed

| File | Change |
|---|---|
| `backend/src/jobs/service.py` | `replace_from_db` takes `_RUN_LOCK` + `job.lock`; new `ledger_telemetry`; `result_view` adds `attempt_telemetry`; provenance-only docstrings |
| `backend/src/routes/exam_jobs.py` | `replace_db` maps `JobBusy → 409`; docstrings |
| `backend/tests/test_wp19_frontend_contract.py` | new — 6 tests |
| `frontend/src/App.jsx` | import + render `ExamGenerationSection`; delete legacy `TestGenerationSection` |
| `frontend/src/lib/examGen.js`, `examApi.js` | new — pure logic + API client |
| `frontend/src/components/ExamGenerationSection.jsx` | new — the job-API screen |
| `frontend/src/lib/examGen.test.js`, `examApi.test.js`, `src/components/ExamGenerationSection.test.jsx` | new |
| `frontend/src/test/setup.js` | new — Vitest setup |
| `frontend/package.json`, `package-lock.json`, `vite.config.js` | Vitest/Testing-Library setup + `test` script |
| `WPs/WP19_Frontend_Exam_Generation.md`, `WP19_ARCHITECT_REPORT.md`, `ARCHITECT_HANDOFF.md` | brief + report + refreshed handoff |

## 7. Skips / limitations / owner decisions

- The in-process daemon-thread worker is unchanged (single-user desktop tool). `replace_from_db`
  now also serialises through `_RUN_LOCK`; concurrent job mutations return `409` rather than
  queueing — the frontend surfaces the backend reason and the user retries.
- Progress polling is a fixed 1.5 s interval (no backoff, no websockets) — adequate for a
  sequential single-user job.
- `attempt_telemetry.by_slot` is keyed by `slot_id`; the UI shows `by_category` + `totals` only
  (per-slot attempt/retry counts are already on the progress chips).
- No owner decision is blocked. Open item for a future WP: if a "realised origin" count is ever
  wanted it must be a **separate** field, never a rewrite of the request quotas (WP18R §5).

## 8. Git

- Commit (outer only): `WP19: connect exam generation frontend` — the files in §6.
- **Not pushed.** Generator submodule not staged/committed/pushed. Backup untouched. No live API
  call, no secret read.
