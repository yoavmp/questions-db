# WP26R — Architect Report

Category semantics, exclusion-workbook hard row limit, and immutable
saved-exam snapshots. Outer `questions-db` only; the generator submodule was
never touched.

## 1. Preflight (confirmed)

- Outer `main` / `origin/main`: `c49036b305c750cbcdc8fb92a5461a871cfb2c1f`
  (`WP26: add named exam history and exclusions`) — matched the expected
  baseline exactly at start, fast-forward-safe, no divergence.
- Generator submodule: `d20c46bbb332e4d40f735e843d31113176b755e5`, working
  tree clean, matches `EXPECTED_GENERATOR_PIN`.
- Untracked owner-owned files present as expected:
  `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`, `WPs/PRE_WP26R_AUDIT.md`. Neither was
  modified, staged, or committed at any point; the audit file's documented
  findings (§5-§7 of that file) were read and used to design the reproduction
  tests below, per the WP's own instruction to inspect existing audit output.
- Zero provider/network calls made. `OPENAI_API_KEY` was read only by the
  pre-existing `llm_ready` test fixture's in-process sentinel value (no real
  key, no network — the same mechanism every prior WP's offline suite uses);
  the complete-suite run itself was executed with `OPENAI_API_KEY` explicitly
  unset. No backend/frontend dev server was started.

## 2. Read-only category-model audit — GATE PASSED

A one-off, strictly read-only script opened `backend/src/database/app.db` via
`sqlite3.connect("file:...?mode=ro", uri=True)` (a connection that raises
`sqlite3.OperationalError` on any write attempt — verified empirically and
also codified as a permanent regression test,
`test_readonly_audit_connection_cannot_write`) and checked every one of the
459 real rows against all five required invariants:

| Invariant | Result |
|---|---|
| `categories` parses to a nonempty ordered list | 459 / 459 pass |
| Every entry is byte-exact canonical (`CATEGORY_ORDER`) | 459 / 459 pass |
| No duplicate entries | 459 / 459 pass |
| Singular `category` is present in the list | 459 / 459 pass |
| Singular `category` equals `categories[0]` | 459 / 459 pass |

**Zero violations found across all 459 rows — no affected IDs to report.**
Per the WP's stop condition, since the gate passed cleanly, implementation
proceeded. `app.db` was opened exactly once, read-only, for this check, and
was never written to at any point in this WP.

## 3. Exact semantics of the three category fields (as implemented)

| Concept | Persisted meaning | Where enforced |
|---|---|---|
| DB `Question.categories` | Complete, ordered, unique, canonical eligibility list — the *only* thing that makes a question eligible for a requested category | `backend/src/utils/category_rules.py::validate_categories` (new shared helper), wired into every write path in `backend/src/routes/upload.py` (Excel import, edit, secondary add/remove, rename); read by `backend/src/jobs/service.py`'s selection/replacement code and `backend/src/jobs/exclusions.py`'s resolution code via exact list membership (`category in q.categories`) — never `Question.category == X OR categories_json LIKE '%X%'` |
| DB `Question.category` / API `primary_category` | Compatibility/display primary; always `== categories[0]`; never independently widens eligibility | Derived by the existing `Question.categories` setter (`category = value[0]`); route-level validation additionally rejects a payload where an explicit singular `category` contradicts the validated list's first entry |
| Job `Slot.category` / result `category` | Fixed exam-slot quota/target category for that position — controls grouping, category history, and DB/LLM replacement context; never inferred from a question's primary category | `backend/src/jobs/model.py::Slot.category` (unchanged field); `replace_from_db` / `replace_via_llm` always target `slot.category`, never the current question's own primary |

## 4. Matching / selection algorithm and failure behavior

`backend/src/jobs/service.py::_match_db_slots` — a dependency-free
augmenting-path (Kuhn's algorithm) bipartite matcher, replacing the old
independent-per-category-precheck-plus-greedy-selection approach:

- One fixed-order DB slot per requested `{category, count}` pair, built in
  canonical `CATEGORY_ORDER` (never shuffled — only candidate order is).
- A DB question is a candidate for a slot only via exact membership of that
  slot's category in the question's `categories` list, computed once per
  `create_job` call (`_candidate_map`) — no LIKE/substring matching anywhere.
- Every listed category of a question is equally eligible; no preference for
  a question's primary category.
- Candidate order (never slot order) is shuffled per augmenting-path attempt
  using the existing injectable `random.Random(seed)`, so a fixed seed gives
  a fully deterministic assignment and an unseeded call still gives a valid
  (possibly different) one each time.
- The whole match is computed, and must fully succeed, **before** `Job(...)`
  is constructed or `store.save` runs — a failure raises `JobError` with zero
  side effects (no job object, no partial slots, no provider call reachable).
- On infeasibility, the raised message includes each category's independent
  availability count for diagnostics but does not claim those counts prove
  joint feasibility (`"לא ניתן להקצות... גם אם כל קטגוריה בנפרד נראית
  זמינה בנפרד"`).
- Reproduces and correctly rejects the exact overlapping-category
  counterexample documented in `WPs/PRE_WP26R_AUDIT.md` §6 (three questions,
  two requested categories sharing one question, independent-per-category
  checks both pass, no joint assignment actually exists) —
  `test_audit_counterexample_correctly_rejected_atomically`.
- Also proven to *succeed*, every time, on a feasible overlap that a naive
  non-backtracking greedy selector can miss depending on random draw order
  (20 different seeds, always finds the one valid assignment) —
  `test_feasible_overlap_always_found_regardless_of_random_draw`.
- DB replacement (`replace_from_db`) targets `slot.category` alone, accepts a
  candidate via any (not only primary) category-list membership, excludes
  every DB id currently in the exam plus persisted workbook exclusions, and
  leaves the slot completely unchanged (`JobConflict`, no mutation) on
  exhaustion.

**Scoping note:** the legacy, frontend-confirmed-unused endpoints
(`/api/test/generate`, `/api/generate-test`, `/api/test/replace-question`,
`/api/categories-summary`) still use the old `category == X OR LIKE '%X%'`
pattern. They are unreachable from the current UI (already flagged as
"unused by the UI" in the WP26 handoff and confirmed again by grepping
`frontend/src` for any caller) and were left untouched as out-of-scope dead
code — fixing dead code risked exceeding the two-repair-pass budget for no
functional benefit and no test coverage exists for them.

## 5. Exclusion workbook: 100-row hard rejection

`backend/src/jobs/exclusions.py`: `MAX_ROWS` lowered from `5000` to `100`.
The loop now raises `ExclusionParseError` the instant the 101st **non-blank**
data row is seen (the header row and blank physical rows never increment the
counter), so `parse_and_resolve` returns nothing at all for an oversized
file — the previous silent-truncation-with-warning behavior (200 OK,
`counts["rows_total"] == 5000`, one generic warning appended) is gone
entirely. The preview route (`POST /api/exam-jobs/exclusions/preview`) now
returns a plain 400 with no `resolved_db_ids`/`counts`/`warnings` keys at all
for this case (verified directly against the Flask test client). The
frontend's existing `handleExclusionFile` already cleared `exclusionPreview`
(set to `null`) *before* awaiting the new upload's result, so a failed
replacement upload was already guaranteed to drop stale accepted ids — this
WP adds the first regression test proving it end-to-end
(`ExamGenerationSection.test.jsx`).

## 6. Snapshot and legacy fallback contracts

- `Slot` (`backend/src/jobs/model.py`) gained two new optional fields,
  `primary_category` and `categories`, populated at selection time
  (`create_job`) and at every replacement (`_apply_db_origin` /
  `_apply_llm_origin`). Always `None`/absent on a slot loaded from a
  pre-WP26R file — never backfilled onto disk.
- `service._db_slot_dto` no longer queries `Question` at all — every field
  (question text, four answers, correct answer, primary category, full
  category list, analytics) now comes entirely from the persisted `Slot`.
  This closes a gap `WPs/PRE_WP26R_AUDIT.md` §7 documented empirically: the
  WP26 architect report had claimed `result_view` was already
  snapshot-isolated for these fields, but the audit proved `question`,
  `answer1-4`, `correct_answer`, `primary_category`, and `categories` were
  all live-re-read from the DB whenever the row still existed (only
  `accuracy`/`distinction` were genuinely frozen before this WP).
  `export_full_xlsx` / `export_llm_xlsx` were already snapshot-only and
  needed no change; DOCX input is built from the same `result_view` question
  dicts, so it is fixed transitively.
- A pre-WP26R job (no `primary_category`/`categories` keys in its JSON at
  all, not merely `null`-valued) falls back deterministically at *read* time
  to `primary_category = Slot.category`, `categories = [Slot.category]` —
  the file itself is never rewritten (proven by a byte-identical
  before/after-read comparison test).
- `branch_job` deep-copies the snapshot fields as-is (including a `None` on a
  legacy parent, which the child then renders via the identical fallback) —
  never refreshed from the live DB.

## 7. Files changed

```
SETUP.md                                                  (docs)
WPs/ARCHITECT_HANDOFF.md                                  (docs)
backend/src/jobs/exclusions.py                            (100-row hard reject; exact category-list membership)
backend/src/jobs/model.py                                 (Slot.primary_category / Slot.categories)
backend/src/jobs/service.py                               (bipartite matching; exact membership; snapshot wiring; _db_slot_dto rewrite)
backend/src/routes/upload.py                              (category_rules wired into create/edit/import/rename; one incidental fix, see below)
backend/src/utils/category_rules.py                       (new: shared category-list validator)
backend/tests/test_wp26_exclusions.py                     (+5 tests: 100-row limit)
backend/tests/test_wp26r_category_invariants.py           (new: 24 tests)
backend/tests/test_wp26r_joint_selection.py               (new: 10 tests)
backend/tests/test_wp26r_snapshot_immutability.py         (new: 8 tests)
frontend/src/components/ExamGenerationSection.test.jsx    (+1 test: exclusion-preview clearing)
```

No change to the generator, `app.db`, real job artifacts, `.env*`,
dependencies, or prompts.

**Incidental fix (not a category-semantics change):** `update_question`
(PUT `/api/questions/<id>`) unconditionally assigned to `question.accuracy`
and `question.distinction`, which are read-only computed properties with no
setter — every call to this route raised `AttributeError` → 500,
unconditionally, regardless of payload, both before and independent of this
WP. This pre-existing bug sat directly adjacent to the category-validation
code being added and made it impossible to prove that a *successful*
category edit actually persists (required to test WP26R §3 meaningfully).
Fixed minimally: only replace `accuracy_list`/`distinction_list` when the
caller supplies an explicit new single value, mirroring the existing
`add_performance_data` settable-property pattern already used elsewhere in
the same file.

## 8. Exact backend/frontend/build results

| Suite | Result |
|---|---|
| Complete outer backend suite (`cd backend && python -m pytest -q`, `OPENAI_API_KEY` unset, correct venv with generator editable-installed) | **243 passed, 0 failed** (279.56s) |
| Complete frontend suite (`cd frontend && npm test -- --run`) | **108 passed, 0 failed** (107 pre-existing + 1 new) |
| Frontend production build (`cd frontend && npm run build`) | **succeeded** (1261 modules, `dist/` emitted, no errors) |
| Generator suite | **not run** — submodule must remain unchanged, per instruction |

Repair passes used: **1 of the allotted 2** — a wrong assumption in one of
my own new tests (`test_db_replacement_accepts_secondary_category_candidate`)
about which of two equally-eligible questions the random matcher would pick
first during initial selection; not a product defect. Fixed by asserting on
the pair of possible outcomes instead of one fixed one; the full suite has
since run twice more, clean both times.

## 9. Zero-provider / leakage confirmation

- No `OPENAI_API_KEY` read outside the pre-existing offline `llm_ready` test
  fixture's in-process sentinel; the full-suite run itself had
  `OPENAI_API_KEY` explicitly unset. No network call (the WP18+ socket-block
  fixture is active for every relevant test). No backend/frontend dev server
  was started at any point.
- No real workbook bytes, real question text, or real job artifacts were
  written anywhere in the repository outside `artifacts/` (git-ignored, and
  `git status` confirms nothing under it is tracked/staged); every new test
  uses a temporary SQLite DB and a temporary job store (`tmp_path`), matching
  the existing fixture conventions exactly.
- `backend/src/database/app.db` was opened exactly once, read-only, for the
  §2 audit; its mtime is unchanged from before this WP began.
- `git diff` was scanned for API keys/secrets/`.env` content before staging;
  the only match was the pre-existing literal string `OPENAI_API_KEY` inside
  prose documentation (never a value).

## 10. PRE files

Both `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md` and `WPs/PRE_WP26R_AUDIT.md` remain
untracked and were not modified, staged, or committed at any point —
confirmed via `git status` immediately before staging: both still appear
only under "Untracked files".

## 11. Architect summary

The three WP26 issues this WP set out to fix are implemented and covered by
new, passing, targeted tests: (1) the exclusion workbook now hard-rejects
past 100 non-blank rows instead of silently truncating at 5,000; (2) DB
selection eligibility is now exact `categories`-list membership only, proven
jointly feasible for the *entire* exam via bipartite matching before any job
is persisted or provider code is reachable, closing both the double-counting
false-positive and the greedy false-negative the pre-WP26R audit
documented; (3) every saved-exam field is now a true selection-time
snapshot, closing the live-re-read gap the audit found in `result_view` for
question text, answers, correct answer, and category fields. The real-DB
category audit gate passed cleanly (459/459 rows, zero violations), so no
data-repair stop condition was ever triggered — no question row was read for
its text/answer content beyond what the audit's own aggregate counts
required, and none was modified. All required tests pass, the complete
backend and frontend suites pass, and the frontend production build
succeeds.

## 12. Final Git checkpoint and push outcome

Committed as `5f31a530ee0057a8ed6b1f18ad981e3afc1fc939`
(`WP26R: harden categories exclusions and snapshots`), containing exactly the
14 intended files listed in §7 — no `app.db`, no real job artifacts, no
`.env*`, no generator/gitlink change, and neither PRE file. `git fetch origin`
proved fast-forward safety before push; pushed normally (no force, no
rebase/merge through divergence) — outer `main` and `origin/main` both sit at
this SHA. `git diff --check` against the previous commit (`c49036b..5f31a53`)
reported no whitespace errors. Generator remains clean and pinned at
`d20c46bbb332e4d40f735e843d31113176b755e5`. Final working tree carries no
modified files and exactly the two expected untracked owner-owned files
(`WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`, `WPs/PRE_WP26R_AUDIT.md`), both
unmodified throughout.
