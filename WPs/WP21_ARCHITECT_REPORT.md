# WP21 — Restore exam analytics and complete exports — Architect Report

**Repository:** `questions-db` (outer) · **Executor:** Claude Code · **Date:** 2026-09-11
**Outer starting HEAD:** `4c0a7df1b551bca8bf55dd56ddea3e1d0f7aeabe`, clean bar the untracked brief.
**Generator submodule:** `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, clean, untouched.
**Offline throughout:** no `OPENAI_API_KEY` read, zero provider/network calls (fake providers only).

## 1. Recovered legacy contract (§1)

Source: `git show 4cd86d1:frontend/src/App.jsx` (the `TestGenerationSection`/`QuestionCard`
components WP19 deleted) and `git show 4cd86d1:backend/src/routes/test_generation.py`
(`/test/export-excel`, also removed — its only caller was the deleted frontend).

- **Category headings:** grouped by `categories[0] || category`, one `<h5>` per group, groups in
  the order the (already category-sorted) question list was built — i.e. canonical order, never
  repeated within a group.
- **Per-question display:** `דיוק:`/`הבחנה:` — every raw value from `accuracy_list`/
  `distinction_list` joined with `', '` when there is more than one (accuracy gets a `%` suffix,
  distinction does not); the single average as a fallback; **`'N/A'`** — a string — when there is
  no data. **Correction to the brief:** no legacy code path ever renders the literal text `"NaN"`;
  the only `NaN` occurrences are JS `isNaN()` calls used to *exclude* missing values from the
  overall calculation below. `'N/A'` is the recovered, followed convention throughout.
- **Overall stats:** `avgAccuracy` = mean of each question's own average `accuracy` (not raw
  history), excluding `null`/non-numeric, `'N/A'` if none. `highDistinctionCount` = count of
  questions whose own average `distinction` is **strictly `>` threshold** (not `≥`), among only
  questions with *some* distinction value; denominator is that count, not the total question
  count. Threshold: a `0–1` step-`0.1` slider, default **`0.3`**, client-side only (legacy never
  sent it to the backend).
- **Full Excel schema (`/test/export-excel`):** 12 columns, exact order/labels: `מספר_שאלה,
  מזהה_שאלה, נושא, שאלה, תשובה1..4, תשובה_נכונה, דיוק, הבחנה, תאריך_יצירה`. Missing-value
  convention: a single historical value → `"[v]"`; several → `json.dumps(list)`; none → `""`
  (never `0`, never `"NaN"`). `תאריך_יצירה` is the **export's own timestamp**, identical for every
  row (never the question's own upload date — that was already the legacy behavior).

## 2–4. Implementation

**Persisted analytics (§3).** `Slot` gains `analytics: {accuracy, distinction, accuracy_list,
distinction_list}` (`model.missing_analytics()`), snapshotted at the moment a DB question enters a
slot (`service._db_analytics`) — in `create_job`, `_apply_db_origin` (DB replacement), and reset to
missing by `_apply_llm_origin` (LLM replacement). **Never re-fetched live** on every view (the prior
behavior — WP17's `_db_slot_dto` re-querying the row on each `result_view()` call — silently lost
accuracy whenever no app context was available or the row was later deleted/edited; that gap is
closed). `_db_slot_dto` now overlays `slot.analytics` onto the DTO in both its row-found and
fallback branches. Analytics never touches `Slot.question` (the seven public fields), so it can
never reach `_previous_for_slot`'s generator context — proven by a new test that walks every
context-building path over an analytics-bearing job and asserts each entry's keys are exactly
`SEVEN`. All four replacement transitions tested: DB→DB snapshots the **newly selected row's own**
data (not a copy of the old); DB→LLM and LLM→LLM reset to missing; LLM→DB snapshots the selected
row. A failed `replace_via_llm` leaves analytics exactly as it was (`_SLOT_STATE_FIELDS` now
includes `"analytics"`, restored on rollback like `question`).

**Overall analytics (§4)** is computed **client-side**, from `result_view()["questions"]`'s
existing `accuracy`/`distinction` fields — matching the legacy architecture (this was never a
backend computation) and trivially satisfying "recalculate after success, unchanged after failure"
(it is a pure render-time function over `job.questions`, and `job` is only replaced on a successful
mutation). `examGen.overallAnalytics(questions, threshold)` reproduces the exact legacy formula.

**Grouped presentation (§2)** groups the (already canonically ordered) question list into
consecutive same-category runs — equivalent to, and simpler than, legacy's object-key grouping,
since global numbering is always contiguous per category. `category_history` stays hidden (WP20,
unchanged); no current DB/LLM aggregate is computed anywhere (WP19 rule, unchanged).

**Two Excel exports (§5).** New `service.export_full_xlsx` / route `GET .../export-full.xlsx`:
every current accepted question (DB + LLM, post-replacement), full 12-column legacy schema; LLM
rows use the same columns with id/accuracy/distinction rendered by the identical missing-value
convention — never fabricated. `service.export_llm_xlsx` / `GET .../export.xlsx` is **unchanged**
(WP18's 7-column upload-compatible schema); verified against the real `upload_excel()` ingestion
route — `דיוק`/`הבחנה`/`נושא2/3` are optional there, so no schema change was needed (documented,
not just asserted). Two distinct routes/buttons on purpose: `ייצוא שאלות בינה בלבד (Excel)` vs.
`ייצוא מבחן מלא (Excel)` — one label never means two things.

**Ledger-derived counts (§6).** `SlotChips` and `ResultQuestion` now read
`attempt_telemetry.by_slot` (via new `examGen.slotAttemptCounts`/`slotAttemptCountsByInstance`)
instead of the mutable `slot.attempts`/`slot.retries`/`generation_meta.attempts`. This actually
**fixes a real bug** found during the WP20 failure-analysis task: `replace_via_llm`'s failure path
restores `attempts`/`retries` to their pre-attempt snapshot, so a failed paid replacement was
previously **invisible** in the UI's own counters even though it was charged. Label:
`ניסיונות: 3 · חזרות: 1` (`חזרות` folds job-level retries **and** LLM-replacement attempts on that
slot — either kind of "try again"). No backend change to `ledger_telemetry` itself (still WP19).

**Audit-overwrite prevention (§7).** This is the second concrete fix from that same WP20 finding:
`_generate_one` now builds a **fresh, never-reused invocation directory** per top-level call —
`slots/<slot_id>/<kind>_<seq>` where `seq` is that call's own eventual `cost_ledger` position
(computed as `len(job.cost_ledger)+1` immediately before the call; nothing else appends between
that read and `_record_cost`'s append, since the run lock keeps the worker sequential — exact,
monotonic, collision-resistant). `store.invocation_audit_dir` validates the token and never touches
an existing directory. Every `cost_ledger` row now carries its own `audit_ref` (safe relative path,
e.g. `slots/…/replace_llm_0003`); `slot.audit_ref` still tracks the *current* invocation. A new
test forces an initial failure then a successful retry on the same slot and asserts: distinct
directories, the first one's files byte-identical before/after, and every ledger row's `audit_ref`
resolvable and unique. Audit paths are still never shown on the ordinary exam screen (unchanged).

## 5. Files changed

Backend: `src/jobs/model.py` (+`analytics`), `store.py` (+`invocation_audit_dir`), `service.py`
(analytics helpers/wiring, invocation dirs, `export_full_xlsx`), `routes/exam_jobs.py`
(+`export-full.xlsx`), `tests/test_wp21_analytics_and_exports.py` (new, 16 tests).
Frontend: `lib/examGen.js` (+6 pure helpers), `lib/examApi.js` (+`downloadFullExamXlsx`),
`components/ExamGenerationSection.jsx` (headings, per-question/overall analytics, ledger-derived
labels, two export buttons), plus matching test files (`examGen.test.js` +13,
`examApi.test.js` +1, `ExamGenerationSection.test.jsx` +9, 1 renamed for the new button label).

## 6. Tests / build

- Backend `pytest -q`, serial, temp DB, sockets blocked: **113 passed** (97 prior + 16 new).
- Frontend `npm test`: **79 passed** (56 prior + 23 new). `npm run build`: OK (pre-existing,
  unrelated CSS-minify warning only).
- Generator-boundary tests: not run — no adapter/generator-interface change.

## 7. Limitations / owner decisions

- Overall analytics/threshold stay **frontend-only**, exactly like the legacy screen (never a
  backend field, never persisted) — flagged as a deliberate architectural match, not an oversight.
- "LLM rows' missing id" has no literal legacy precedent (history never had an idless question); it
  reuses the accuracy/distinction missing convention (blank cell) — reasonable and documented, not
  fabricated, but not literally "recovered."
- `progress_view`'s per-slot `attempts`/`retries` remain mutable/diagnostic (unchanged); only the
  **displayed** counts moved to the ledger. No owner decision is blocked.

## 8. Git

- Outer commit: `WP21: restore exam analytics and complete exports` — the files in §5 plus this
  report and the refreshed `ARCHITECT_HANDOFF.md`. **Not pushed.**
- Generator submodule untouched, pinned at `ea59cd857e5618b0260d2bb146dd5573c9ca2309`. Backup
  untouched. Zero provider calls, zero key access, no runtime artifact (`artifacts/exam_jobs/…`)
  committed.
