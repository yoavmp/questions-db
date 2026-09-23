# questions-db — Architect Handoff

**Repository:** `questions-db` (outer) — Hebrew exam question bank + test builder
(Flask backend, React/Vite frontend) integrating the Hebrew neuroanatomy
question **generator** as a Git submodule.
**Updated:** 2026-09-23 · **Latest completed WP:** WP28 (warning acceptance,
persistent manual editing, hard-rejection failure memory, failed-replacement
retention, and RTL/LTR numeric-ratio isolation — spans both repositories;
offline only, no live/provider call, `OPENAI_API_KEY` never accessed). See
`WPs/WP28_ARCHITECT_REPORT.md` and the generator-side
`exam_generator/WPs/WP28G_ARCHITECT_REPORT.md`.

Triggered by the read-only audit `WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md`
against exam job `258ffef8-…`. Generator submodule re-pinned to
`5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d` (WP28G); the outer integration:

- **Warning acceptance is now a first-class slot outcome.** The generator
  adapter (`backend/src/integration/generator_adapter.py`) forwards the
  generator's `review_quality`/`review_warnings` (remapping the generator's
  internal `distractor_1..3`/`correct_answer` naming onto the public
  `answer2..4`/`answer1` fields the outer app already uses everywhere), and
  `_generate_one` (`backend/src/jobs/service.py`) persists them on the
  `Slot` (`review_quality`, `review_warnings` — each with its own
  `warning_id`/`resolved`/`resolved_by`/`resolved_at`) fresh on every new
  acceptance. Exposed to the frontend via `GenerationMeta`
  (`backend/src/integration/exam_question_dto.py`), never inside the
  seven-field public question, and never in DOCX output (`GenerationMeta`
  was already excluded from `docx_view()`).
- **Bounded, per-category hard-rejection failure memory**
  (`Job.hard_rejection_feedback`) is threaded into every generator call
  (`_generate_one` reads the last `MAX_HARD_REJECTION_FEEDBACK_PER_CALL = 8`
  records for that slot's category, stripping the store's own `recorded_at`
  bookkeeping before handing them to the generator's strict
  `HardRejectionFeedback` model) and grows from whatever new records that
  same call's own failed attempts produced
  (`_record_hard_rejection_feedback`, deduplicated by
  `(bad_field, bad_value, failure_code)`). Never written for a warning or
  clean acceptance; never folded into `category_history`.
- **Persistent manual editing**: `PATCH /api/exam-jobs/<job_id>/questions/<instance_id>`
  (`service.edit_llm_question`) edits the six public fields of the *current*
  LLM-origin question in one slot, no provider call, no API key. Rejects a
  database-origin slot, a missing slot, or a job mid-generation
  (`job.status == "running"`); deterministic structural validation only
  (non-empty trimmed text, four distinct answers, `correct_answer` a
  strict `1..4` int). On success: appends an immutable
  `Slot.edit_history` entry (before/after seven fields, affected warning
  ids), updates `Slot.question` in place (identity/number/origin
  untouched), sets `manually_edited = True`, and resolves exactly the
  unresolved warning(s) whose own declared field was among the changed
  ones. `branch_job` copies `review_quality`/`review_warnings`/
  `manually_edited`/`edit_history` per slot and the whole
  `hard_rejection_feedback` store, the same way `category_history` already
  was.
- **Export confirmation and edited text**: both XLSX exports
  (`export_llm_xlsx`/`export_full_xlsx`) already read `slot.question`
  directly, so a manual edit is reflected with no export-side change;
  neither schema gained a `manually_edited` column (no safe extension
  point — schema compatibility with the existing DB-upload/legacy contract
  took priority, per the owner's explicit WP28 ruling). The DOCX path is
  unaffected the same way (the frontend already strips job-only metadata
  before that call). The frontend (`ExamGenerationSection.jsx`) gates every
  export action behind a Hebrew confirmation dialog
  (`unresolvedWarningCount()` in `examGen.js`) whenever any current
  question still carries an unresolved warning; cancelling makes no
  download request.
- **Failed-replacement retention is now explicit**: a failed
  `replace_via_llm` sets `slot.safe_error` to a fixed Hebrew sentence
  ("לא נוצרה שאלה חלופית. השאלה המקורית נשמרה.") with the attempt
  count/cost appended when available, instead of an ad hoc failure string —
  `category_history` is still untouched on failure (unchanged from before
  WP28), and the hard-rejection feedback from the failed attempts is still
  persisted for later calls.
- **RTL/LTR**: every "X / Y" numeric ratio on the exam-generation screen
  (accepted count, LLM-accepted count, accumulated-vs-ceiling cost, the
  distinction-threshold count) is now wrapped in one reusable `<Ratio>`
  component rendering `<bdi dir="ltr">…</bdi>` — the surrounding Hebrew
  layout is untouched; only the digits/operator are isolated.

Full generator suite (submodule): 1025 collected, 0 failures. Outer backend
suite: 310 passed. Outer frontend suite: 155 passed. Frontend production
build: succeeds. See `WPs/WP28_ARCHITECT_REPORT.md` §7 for the exact counts
and commands.

---

WP27R (below) remains the most recent prior outer-repo change — persisted
workflow phase, atomic Continue claim, and recovery; outer-only, offline
only, no live/provider call, `OPENAI_API_KEY` never accessed, generator
untouched. See `WPs/WP27R_ARCHITECT_REPORT.md`.
Supersedes the never-executed `WP25_Named_Exam_History_Branches_And_UI_Polish.md`.

WP27R corrects, backward-compatibly, on top of the WP27 job model (WP27's
description below is otherwise unchanged and still accurate — read it for
everything WP27R does not modify):

- **`workflow_phase` is now a persisted `Job` field, not derived.** WP27's
  original design recomputed `db_review`/`llm_generation`/`complete` fresh
  from `status` on every read. That had two real gaps: (1) an async
  Continue's `202` could be followed by an immediate `GET` that still saw
  the pre-claim `queued` state, since nothing was persisted synchronously
  yet, causing the frontend to stop polling while generation quietly ran in
  the background; (2) retrying one `interrupted` slot while later planned
  slots stayed `queued` recomputed the derived phase as `complete` (status
  alone doesn't distinguish "never attempted" from "genuinely done"),
  hiding Continue and stranding real planned work. `workflow_phase` (see
  `backend/src/jobs/model.py::WORKFLOW_PHASES`) is validated on save,
  inferred once (never rewritten-on-read) for any legacy job.json that
  predates the field via `model._infer_legacy_workflow_phase`, and updated
  at every mutation site that can change it (`create_job`, `run_job`,
  `_finalise`, `branch_job`'s child).
- **`_finalise` now derives phase from whether any planned slot is still
  untouched** (`status` in `queued`/`running`/`interrupted`) rather than
  from the terminal-vs-not shape of `job.status` — so `partial` and
  `cost_ceiling` correctly coexist with `llm_generation` whenever real
  planned work remains, while a fully-traversed batch is `complete` even if
  one of its slots individually stayed rejected/retryable (`status ==
  "failed"`/`"cost_ceiling"` after being attempted, not merely never tried).
- **Continuation split into an atomic claim + a claimed worker**
  (`service.claim_llm_continuation` / `run_claimed_llm_generation`, plus a
  thin `continue_llm_generation` convenience wrapper combining both for
  direct/test callers). The claim — `workflow_phase="llm_generation"`,
  `status="running"`, persisted — now always happens **synchronously**
  inside the `POST /exam-jobs/<id>/continue-llm` request, in both sync and
  async mode; only the actual multi-question generation work is deferred to
  a background worker in async/production mode. `abort_claim_as_interrupted`
  handles the one new edge case this split introduces (the worker thread
  itself fails to start): the job is marked recoverably `interrupted`
  (`workflow_phase` stays `llm_generation`) instead of being left a
  permanently fake `running` job that nothing will ever finish.
- **Resume reuses the exact same claim**, no separate mechanism: a job left
  `partial`/`interrupted`/`cost_ceiling` with real planned (`queued`) work
  remaining is eligible for another `claim_llm_continuation` call exactly
  like a fresh `db_review` job is — an already-`interrupted` individual slot
  still needs its own explicit retry (unchanged, pre-existing rule); the
  automatic batch only ever touches genuinely `queued` slots.
- **Branching now requires both `status == "completed"` and
  `workflow_phase == "complete"`** (`branch_job`, `list_jobs`, `result_view`)
  — belt-and-braces on top of the pre-existing status-only guard, which
  already agreed with it in every normally-reachable state.
- **Frontend polling considers status AND phase together**
  (`examGen.isPollingStatus(status, phase)`) — `"queued"` never polls
  regardless of phase; only an actively `"running"` `llm_generation` batch
  does. `handleContinue` applies the claim response's real `status`/
  `workflow_phase` to local state immediately (so polling starts without
  depending on a follow-up `GET` winning any race), then fetches the full
  result; a `409` (another request already won the claim, or it already
  finished) loads the current job instead of showing a fatal error. A new
  "יצירת השאלות בבינה מלאכותית הופסקה" banner (distinct from the db_review
  one) offers the same Continue action to resume a paused batch with real
  planned work remaining.

Full detail, the exact phase/status transition table, claim/worker locking,
and test results are in `WPs/WP27R_ARCHITECT_REPORT.md`. **Next:** none
scheduled.

WP27 changes, backward-compatibly, on top of the WP18-WP26R job model:

- **Two explicit phases instead of one automatic run**
  (`backend/src/jobs/service.py`): `POST /api/exam-jobs` now performs DB
  selection ONLY — it never imports/checks `OPENAI_API_KEY`, never runs a
  pricing-readiness check, and never calls the generator. A job with any
  planned AI (LLM) question is persisted `queued`/`db_review` and simply sits
  there, saved and reopenable indefinitely, until a new explicit
  `POST /api/exam-jobs/<id>/continue-llm` claims and runs exactly that
  originally-planned batch. A job with zero planned AI questions is finalised
  `completed` immediately inside `create_job` itself — there is nothing to
  continue, and no Continue control is ever shown for it.
- **`workflow_phase` — a derived, not persisted, three-value field**
  (`service.workflow_phase`, `model.py` docstring): `"db_review"` /
  `"llm_generation"` / `"complete"`, computed purely from the existing
  `status` field (`queued`+any LLM slot → `db_review`; `running`/
  `interrupted` → `llm_generation`; everything else → `complete`) rather than
  a new field kept in lockstep with `status` at every mutation site — a
  deliberate choice to make desync between the two structurally impossible.
  Exposed on `GET /exam-jobs`, `GET /exam-jobs/<id>` and both job-creating
  routes' response bodies. A legacy (pre-WP27) `job.json` — which never had
  and still doesn't need this field — maps through the exact same rule with
  no migration and no rewrite-on-read.
- **Exactly-once continuation** (`service.continue_llm_generation`): claims
  the transition (`status="running"`, persisted) under the same process-wide
  run lock + per-job file lock every other generating operation already
  used, so a double-click or a genuinely concurrent request can never start
  two batches; a request after the batch has already started/finished gets a
  safe `409`. Readiness (API key/pricing/generator data) is checked once, up
  front, and a failure there leaves the job completely untouched in
  `db_review` — Continue stays safely retryable once the environment is
  fixed. A backend restart mid-batch leaves it `interrupted` exactly like any
  other WP18 job; calling Continue again resumes the same batch (only
  still-`queued` slots run — an already-accepted slot is never regenerated),
  reusing the existing interrupted/retry model rather than inventing a new
  resume mechanism.
- **Manual replacements keep working unchanged during `db_review`**
  (`replace_from_db`/`replace_via_llm`, both already phase-agnostic — no
  guard added): both "החלף בשאלה מהמאגר" and "צור שאלה אחרת" remain available
  on every accepted question. A manual `replace_via_llm` call is charged
  normally and never reduces the count Continue will later generate. One
  real bug this WP found and fixed in the same function: it used to call the
  shared `_finalise` helper unconditionally, which — now that other planned
  LLM slots can legitimately still be `queued` while a manual replacement
  runs — misread that as an in-progress/partial batch and flipped the job
  out of `db_review` as a side effect. Fixed by skipping `_finalise`'s
  status recomputation (keeping only its cost/telemetry summary refresh)
  whenever the job was in `db_review` before the call.
- **Interim vs. final numbering** (`service.result_view`/
  `export_full_xlsx`): during `db_review`, displayed/exported question
  numbers are a compact `1..N` over only the currently accepted questions
  (never the persisted final number, which can have gaps wherever a later
  category's AI slots are still pending) — no empty placeholder rows are
  ever shown or exported. The real final number — assigned once, for every
  slot, at creation time, in canonical category order — is stable and
  unaffected; it is simply what gets shown again the moment `db_review`
  ends, exactly as before WP27.
- **Semantic context needed no code change**: `_previous_for_slot` already
  only ever scanned *accepted* slots plus retained displaced-LLM history, so
  a still-`queued` planned slot was already structurally invisible to it,
  and a slot generated earlier in the same continuation batch is already
  persisted `accepted` before the next slot's context is built — both WP27
  requirements the existing WP18 sequential loop already satisfied.
- **Frontend** (`ExamGenerationSection.jsx`, `examGen.js`, `examApi.js`): a
  new "ממתין לאישור שאלות המאגר" banner (shown whenever
  `workflow_phase === "db_review"`) with the planned AI-question count,
  current AI cost, and the "המשך ליצירת שאלות חדשות באמצעות בינה מלאכותית"
  button (double-click-protected, hidden for a read-only/historical view).
  `isPollingStatus` no longer polls on `status === "queued"` (that status is
  now a long-lived resting state, not a transient one) — only an actively
  `"running"` batch is polled. Branching is unavailable during `db_review`/
  `llm_generation` with an inline explanation of when it returns (unchanged
  backend guard: only `status === "completed"`).

Full detail, the exact legacy-phase mapping, idempotency/concurrency
mechanism, and test results are in `WPs/WP27_ARCHITECT_REPORT.md`.
**Next:** none scheduled.

WP26R corrects, backward-compatibly, on top of the WP26 job model:

- **Exclusion workbook hard row limit** (`backend/src/jobs/exclusions.py`):
  `MAX_ROWS` lowered from a silent 5,000-row truncation to a hard 100-row
  cap — the 101st non-blank data row now rejects the **entire** workbook
  (`ExclusionParseError`, safe Hebrew message); no partial preview/resolved-id
  set is ever returned. The header row and blank physical rows never count.
- **One authoritative category list** (`backend/src/utils/category_rules.py`,
  new): a single shared validator enforces `categories = nonempty, ordered,
  unique, canonical list` and `category = categories[0]` across every
  question create (Excel import), edit, secondary-category add/remove, and
  category-rename write path in `backend/src/routes/upload.py`. Selection
  eligibility (`backend/src/jobs/service.py`) now checks exact membership in
  a question's full `categories` list only — the old `Question.category == X
  OR categories_json LIKE '%X%'` fallback (which let the singular primary
  independently widen eligibility, and which matched on an unanchored JSON
  substring rather than exact list membership) is removed everywhere in the
  active job-creation/selection/replacement/exclusion-resolution path.
- **Globally feasible DB selection** (`service.py::_match_db_slots`): the old
  independent per-category availability precheck plus greedy sequential
  selection is replaced by one dependency-free bipartite-matching (Kuhn's
  algorithm) pass over every requested DB slot at once, proving a complete,
  globally-unique assignment exists **before** the job is persisted or any
  provider code is reachable. Fixes a genuine false-negative/false-positive
  pair the WP26R audit found: a shared-category question could be
  double-counted by the old independent precheck (false "OK"), and — the
  inverse — a feasible overlapping-category request could be incorrectly
  rejected by naive greedy selection depending on random draw order, even
  though a valid joint assignment existed. Candidate order (never slot order)
  is randomized through the existing injectable RNG.
- **Immutable saved-exam snapshots** (`jobs/model.py::Slot.primary_category` /
  `.categories`, new fields): every accepted slot now snapshots its selecting
  question's primary category and full category list at selection/replacement
  time. `service._db_slot_dto` / `result_view` build every field — including
  `primary_category`/`categories`, previously live-re-read from `Question` on
  every view — entirely from persisted slot data; a DB row edited or deleted
  after exam creation can no longer change a reopened exam, its DOCX/Excel
  exports, or a branch. A pre-WP26R job with no snapshot fields falls back
  deterministically to `primary_category = Slot.category` /
  `categories = [Slot.category]` at read time and is never rewritten.

Full detail (including the real-DB category audit that gated this WP) in
`WPs/WP26R_ARCHITECT_REPORT.md`. **Next:** none scheduled.

WP26 adds, backward-compatibly, on top of the existing `/api/exam-jobs*` job
model (WP18-WP25G, unchanged):

- **Naming** (`backend/src/jobs/naming.py`): structured (`קורס`/`שנה`/`סוג`/`מועד`)
  or custom exam names, a normalized `display_name` + filesystem-safe `slug`,
  and a calculated (never persisted) fallback label for any job with no
  identity -- every pre-WP26 job included.
- **History** (`GET /api/exam-jobs`, `service.list_jobs`): every persisted job,
  newest-first, safe list fields only (no question bodies/prompts/audits).
- **Immutable branching** (`POST /api/exam-jobs/<id>/branch`,
  `service.branch_job`): a new job id/slot ids/instance ids, copies current
  question snapshots + `category_history` + `excluded_db_ids`, starts with an
  empty cost ledger and the parent's ceiling as its new default -- the parent
  `job.json` is only ever read, never written, so it stays byte-for-byte
  unchanged on both success and failure. Only a `completed` job may be
  branched (a typed `JobConflict` otherwise -- no invented partial-branch
  semantics).
- **Optional DB exclusion workbook** (`backend/src/jobs/exclusions.py`,
  `POST /api/exam-jobs/exclusions/preview`): local, non-provider `.xlsx`
  parsing/resolution (id-authoritative, then text+category, then text-only;
  ambiguous fallbacks are excluded conservatively and warned, never guessed)
  feeding a normalized, deduplicated `excluded_db_ids` set that both initial
  DB selection and every later DB replacement enforce, with an atomic,
  Hebrew, category-specific pre-flight failure if a category can no longer be
  satisfied -- before any paid LLM call.
- **Retry/replacement telemetry correction** (`service.py`): an intentional
  `replace_llm` no longer bumps the mutable per-slot retry counter, and
  `terminal_summary`'s `retries`/`replacements` are now derived from the
  immutable `cost_ledger`'s operation `kind` (already how `ledger_telemetry`/
  `attempt_telemetry` worked since WP21R) -- so even an old job whose
  persisted counter was already conflated reports correctly, without
  rewriting its file.
- **Frontend** (`ExamGenerationSection.jsx`, `App.jsx`): a setup step with the
  identity fields + exclusion-workbook preview; a saved-exam selector; separate
  active-editable-job vs. viewed-job local state (survives navigation/restart);
  a visibly read-only historical view with mutation controls hidden and
  "יצירת גרסה חדשה" prominent; the exam slug used in DOCX/Excel filenames; the
  required brand title, About-tab content, RTL tab order
  (`אודות המערכת` far right / `עיון בשאלות` far left), non-wrapping export
  button text, and a question-browser topic bar now sourced from
  `GET /api/test/categories` (the same authoritative `CATEGORY_ORDER` the
  backend uses) instead of question-insertion order.

Full detail, contracts, and the exact ambiguous-match interpretation in
`WPs/WP26_ARCHITECT_REPORT.md`. **Next:** none scheduled.

Prior state (WP25G and earlier, carried forward, untouched by WP26 beyond the
items listed above): generator complete suite (pre-WP26) 999 collected/825
passed/174 skipped/0 failed, outer backend complete suite 122/122 passed
pre-WP26 + 74 new WP26 tests (196/196 total), frontend complete suite 95/95
passed pre-WP26 + 12 new WP26 tests (107/107 total), frontend production build
succeeded. The "יצירת מבחן" screen uses `/api/exam-jobs*` end to end, has been
validated against a real local backend + real OpenAI generation (WP20: one
small mixed job, $0.087 of a $1.00 authorized ceiling; WP22: one integrated
job + two reviewer-only replays, $0.1624 of a $0.50 authorized ceiling), and
carries the analytics/export/audit surface WP21 restored, WP21R's
telemetry-clarity and crash-safety hardening, and WP25G's inverse-duplicate
guard. WP26 made no live/provider call, so none of that live-validated state
changed. The legacy synchronous `/api/test/generate` + `/api/test/replace-
question` endpoints are **still present** (nothing on the current screen
calls them) and may be retired by a later WP.

## 1. Repository SHAs

| Repo | Path | SHA | State |
|---|---|---|---|
| Outer `questions-db` | `.` | Before WP27R: `53177b87ab2d3f914f83a3a22bc3fa0c7ed74c45` (`WP27R: record final commit SHA and push outcome in architect report` — this commit's own subject names WP27R by the same historical labeling convention as `8302c43`'s, but it in fact closed out **WP27**, one commit past the `a13b60d` baseline WP27R's own brief expected; see `WPs/WP27R_ARCHITECT_REPORT.md` §0 for the reconciliation). WP27R committed as `WP27R: harden staged continuation recovery` — exact SHA in this WP's closing terminal response / `WPs/WP27R_ARCHITECT_REPORT.md` | branch `main`; pushed after WP27R (if fast-forward-safe), `HEAD == origin/main` |
| Generator `exam-generator` | `exam_generator/` (submodule) | `d20c46bbb332e4d40f735e843d31113176b755e5` (`WP25G: reject inverse semantic duplicates` — **unchanged since WP26**: outer's recorded `EXPECTED_GENERATOR_PIN` still matches exactly) | `heads/main`, **fully clean**, **do not commit/push here** |

Generator remote: `https://github.com/yoavmp/exam-generator.git` — `origin/main`
contains `d20c46b` (WP25G). Pre-submodule snapshot preserved at
`../exam_generator_pre_submodule_backup/` (untouched).

## 2. Submodule update / re-pin procedure

```bash
git submodule update --init --recursive          # fresh clone / missing submodule
```

To **re-pin** to a newer generator commit:

```bash
git -C exam_generator fetch origin
git -C exam_generator checkout <new_sha>          # detached, exact commit
git add exam_generator                            # stages ONLY the gitlink
# update the recorded pin so readiness stops flagging drift:
#   backend/src/integration/generator_pin.py  ->  EXPECTED_GENERATOR_PIN
# then re-verify:
cd backend && python -m pytest -q                 # WP17 + WP18 suites
python -c "from src.integration.category_map import verify_against_generator_catalog as v; \
           print(v('../exam_generator/config/categories.json'))"
```

Rules: the outer repo tracks **only** `.gitmodules` and the `exam_generator`
gitlink. Never `git add exam_generator/<file>`. Never commit or push inside
`exam_generator/`. Course source data and its derived index
(`exam_generator/Data/index/`, `exam_generator/Data/Course_Material_Summary.pdf`) are local, Git-ignored
(`exam_generator/.gitignore`), and never committed by either repository — `git clone
--recurse-submodules` does not download them. This installation's copy already exists locally, so it is
LLM-generation-ready on that axis (subject to `OPENAI_API_KEY` and the other `readiness_report()`
checks); a **fresh clone is DB-only** until the owner restores or rebuilds that exact `Data/` tree out
of band. See `SETUP.md` § "Local course data required for LLM generation" for the procedure and the
readiness check.

## 3. Integration surface (outer repo)

| Area | Location |
|---|---|
| Canonical categories (spelling + display order) | `backend/src/utils/category_order.py::CATEGORY_ORDER` |
| Shared category-list invariants (nonempty/ordered/unique/canonical; WP26R) | `backend/src/utils/category_rules.py::validate_categories/dedupe_and_validate` |
| Canonical ↔ generator context binding, aliases, strict resolver | `backend/src/integration/category_map.py` |
| Owner policy (attempts, $5 cap, arithmetic, DB ownership) | `backend/src/integration/owner_policy.py` |
| Per-category `{total,database,llm}` request contract | `backend/src/integration/request_contract.py` |
| Exam-question DTO (7 fields + meta, `docx_view()`) | `backend/src/integration/exam_question_dto.py` |
| **Thin** generator adapter over `production.generate_exam_question` | `backend/src/integration/generator_adapter.py` |
| Recorded generator pin (readiness drift check) | `backend/src/integration/generator_pin.py` |
| Non-network LLM readiness service | `backend/src/integration/readiness.py` |
| Persistent sequential job model / store / worker | `backend/src/jobs/{model,store,service}.py` |
| Cross-source replacement (DB↔LLM, both endpoints, any accepted slot) | `backend/src/jobs/service.py::replace_from_db` / `replace_via_llm` (WP18R) |
| Job + readiness API blueprint | `backend/src/routes/exam_jobs.py` (`/api/exam-jobs*`, incl. `POST …/continue-llm`, WP27) |
| Staged DB review / explicit LLM continuation (WP27, hardened WP27R) | `backend/src/jobs/service.py::create_job` (DB selection only), `claim_llm_continuation` / `run_claimed_llm_generation` / `abort_claim_as_interrupted` (WP27R split), `continue_llm_generation` (thin claim+run wrapper), `run_job` (legacy direct-driver), `_run_llm_slots`, `workflow_phase` (validating accessor over the persisted `Job.workflow_phase`, WP27R), `pending_llm_slots` |
| Ledger-derived attempt/retry/replacement telemetry (WP19, separated WP21R) | `backend/src/jobs/service.py::ledger_telemetry` → `result_view()["attempt_telemetry"]`; frontend split via `examGen.slotAttemptCounts`/`slotAttemptCountsByInstance` |
| Job-API exam screen (WP19) | `frontend/src/components/ExamGenerationSection.jsx` + `frontend/src/lib/examGen.js` (pure) + `examApi.js` (client) |
| Root install / start flow | `scripts/dev_install.sh`, `SETUP.md` |
| Per-question/DB analytics snapshot, full export (WP21) | `backend/src/jobs/model.py::missing_analytics`, `service.py::_db_analytics/export_full_xlsx` |
| Crash-safe, UUID-authoritative per-invocation audit dirs + pre-call manifest (WP21R) | `backend/src/jobs/store.py::new_invocation_uuid/invocation_dir_name/invocation_audit_dir/write_invocation_manifest`, `service.py::_generate_one` |
| Contract + job tests (temp DB, fake provider, sockets blocked) | `backend/tests/test_wp17_*.py`, `test_wp18_*.py`, `test_wp18r_*.py`, `test_wp19_frontend_contract.py`, `test_wp20_semantic_history_boundary.py`, `test_wp20_terminal_cost_log.py`, `test_wp21_analytics_and_exports.py`, `test_wp21r_audit_hardening.py`, `test_wp25g_inverse_duplicate_guard.py`, `test_wp26_*.py`, `test_wp26r_category_invariants.py`, `test_wp26r_joint_selection.py`, `test_wp26r_snapshot_immutability.py`, `test_wp27_two_phase_db_review.py`, `test_wp27r_persisted_phase_and_recovery.py` |
| Frontend tests (Vitest + Testing Library, fake API fixtures) | `frontend/src/**/*.test.{js,jsx}`; `cd frontend && npm test`; WP27 adds `ExamGenerationSection.wp27.test.jsx`, WP27R adds `ExamGenerationSection.wp27r.test.jsx` |

- `/api/test/categories` still returns all 20 canonical categories in
  `CATEGORY_ORDER` with live DB availability (incl. a zero-count category). The
  WP19 job UI should use it; WP18 adds no parallel categories route.
- **Cross-source replacement (WP18R):** `POST …/replace-db` and `…/replace-llm`
  each accept **any** accepted slot (DB→DB, LLM→DB, DB→LLM, LLM→LLM). `instance_id`,
  `slot_id`, `category`, `order_in_category`, public `number` are stable; the
  slot's `kind`/`db_id`/metadata and DTO `origin` switch to the new origin on
  success. Only a displaced **LLM** question enters `category_history`
  (post-success); a displaced DB question never does and never reaches a later
  generator context. Cross-source failure is a full rollback (slot + Excel/DOCX
  identical); a failed LLM attempt is still ledgered. Export = current
  `kind == "llm"` only. `CategoryPlan.total/database/llm` stay at the original
  request quotas (request provenance only — no realised/current DB-vs-LLM
  balance is computed or exposed anywhere; per-question `origin` is the only
  composition signal).
- **WP19:** `replace_from_db` now takes the same `_RUN_LOCK` + `job.lock` as
  every other job mutation (`JobBusy → 409` on a double click / concurrent op).
  `GET /api/exam-jobs/<id>` adds `attempt_telemetry` — attempt/retry/charged-
  failure counters folded from the immutable `cost_ledger`, by category and slot,
  so a charged failed attempt stays diagnosable after a rollback. No route/verb
  or generator-boundary change.
- **WP20 (UI only — no backend change):** `frontend/src/components/ExamGenerationSection.jsx` no
  longer renders `category_history` anywhere (the "שאלות בינה שהוחלפו" card was removed). The field
  still round-trips through backend persistence and still feeds `_previous_for_slot` for later LLM
  generation, and it still appears in `result_view` as backend diagnostic data — only the
  user-facing screen stopped showing it. New tests on both sides prove this
  (`ExamGenerationSection.test.jsx`, `backend/tests/test_wp20_semantic_history_boundary.py`).
- **WP20 live validation:** one real job against the owner's local backend + real OpenAI calls —
  `היסטולוגיה`, `C=2/A=1/B=1`, $1.00 ceiling, **2 provider ops, $0.0869755 total (8.7% of cap)**,
  0 failures/retries. Confirmed live: DB-first selection with the DB question in the LLM's
  previous-question context; DB→LLM via `צור שאלה אחרת` does **not** add the displaced DB question
  to `category_history`; LLM→DB via `החלף בשאלה מהמאגר` **does** retain the displaced LLM question
  there (and it then appears in the next generation's context); stable `instance_id`/`number`/
  `category` across both transitions; Excel export = current LLM question only, no DB insert;
  Hebrew DOCX (± answers) strips job metadata, keeps the endpoint's own answer-shuffle, renders
  RTL. Full detail, per-operation costs, and the two accepted questions' seven fields are in
  `WPs/WP20_ARCHITECT_REPORT.md`.
- **WP20 follow-up — backend-terminal cost line, corrected.** WP20's live-validation report
  originally claimed no cost line is ever printed to the backend terminal; that was a **search
  error in that session**, not a real gap — `service._print_terminal_summary` has printed one
  since WP18 (`d793a9f`), after the initial run and after every LLM retry/replacement (accepted or
  failed alike), never for a DB-only replacement. The owner's follow-up asked for two fields it was
  missing; both are now in: `_print_terminal_summary(job, *, operation)` (was `header=`) prints
  `job=<id> operation=<initial|retry|replace_llm> status=<...> llm_cost=$<...> basis=<...>
  remaining=$<...> accepted=<n>/<n> failed=<n> retries=<n> pricing_warnings=<...>` — never a
  prompt, response, question, or secret. 6 new offline tests
  (`backend/tests/test_wp20_terminal_cost_log.py`) prove: one well-formed line per initial run;
  one line on a retry's acceptance *and* on its charged failure; one line on an LLM replacement's
  acceptance *and* on its charged failure; **no** line (and no cost movement) for
  `replace_from_db`; and the printed `remaining=$` matches `ceiling − accumulated` exactly. Full
  detail in `WPs/WP20_ARCHITECT_REPORT.md` §8.
- **WP21 — restored analytics/exports, and two fixes the WP20 failure-analysis task surfaced.**
  `Slot.analytics` ({`accuracy`,`distinction`,`accuracy_list`,`distinction_list`}) is now
  **persisted**, snapshotted at DB selection/replacement time, never re-fetched live (closes a real
  gap: the old live re-query silently dropped accuracy whenever no app context was available or the
  row was later edited/deleted) — set by `service._db_analytics`/`_apply_db_origin`, reset to
  missing by `_apply_llm_origin`, restored on a failed `replace_via_llm` like `question` is. Never
  reaches `Slot.question` or generator context. The exam screen groups results by category again
  (one heading per group), shows every historical accuracy/distinction value per question (`'N/A'`
  when there is none — the legacy convention; **not** the literal text `"NaN"`, contra the brief's
  phrasing — see `WPs/WP21_ARCHITECT_REPORT.md` §1), and recomputes the legacy mean-accuracy /
  distinction-threshold stats client-side (threshold slider, default `0.3`, never sent to the
  backend — matching the legacy architecture exactly). **Fix 1:** `GET …/export-full.xlsx`
  (`service.export_full_xlsx`) — every current DB+LLM question, the complete 12-column legacy
  schema — alongside the unchanged 7-column `GET …/export.xlsx` (LLM-only, upload-compatible,
  verified against the real `upload_excel()` contract, not just assumed). **Fix 2 (the WP20 bug):**
  question cards and slot chips now read attempt/retry counts from `attempt_telemetry.by_slot`
  instead of the mutable `slot.attempts/retries` — a failed paid `replace_llm` rolls those back to
  their pre-attempt value (WP18R), so it was previously **invisible** in the UI even though charged;
  the ledger-derived label (`ניסיונות: N · חזרות: N`, **folding retries and replacements together —
  superseded by WP21R, see below**) fixes that. **Fix 3 (the other WP20 bug, hardened further by
  WP21R):** `_generate_one` now writes every top-level LLM call into its **own** invocation directory
  (`slots/<slot_id>/<kind>_<seq>`, `seq` = that call's own `cost_ledger` position) instead of a
  shared per-slot directory — a later call can no longer silently overwrite an earlier one's audit
  evidence; every ledger row carries a safe relative `audit_ref`. Full detail in
  `WPs/WP21_ARCHITECT_REPORT.md`.
- **WP21R — clarified telemetry display, closed the WP21 crash-collision gap.** Two owner-directed
  fixes, both display/storage-only (retry eligibility, cost accounting, semantic history, and
  replacement behavior are all untouched):
  1. **Retry vs. replacement, never folded.** WP21's `חזרות` label silently combined failure retries
     and intentional `replace_llm` calls into one number — an intentional replacement could look like
     a failure. `examGen.slotAttemptCounts`/`slotAttemptCountsByInstance` now return four **separate**
     fields (`attempts`, `retries`, `replacements`, `failedAttempts`); `SlotChips` and `ResultQuestion`
     render up to four distinct labels, each only when non-zero: `ניסיונות: N` ·
     `ניסיונות חוזרים לאחר כשל: N` · `החלפות LLM: N` · `נכשלו: N`. Source is unchanged —
     still exclusively `attempt_telemetry.by_slot`, the immutable ledger-derived view, never the
     mutable `slot.attempts/retries`.
  2. **Crash-safe invocation directories.** WP21's `<kind>_<seq>` naming computed `seq` from
     `len(cost_ledger) + 1` *before* the provider call but only persisted it *after* — a crash inside
     the call left the ledger unchanged, so the next invocation recomputed the **same** `seq` and (with
     the old `exist_ok=True`) silently **reused the crashed call's directory**. Fixed: every invocation
     now gets a fresh `uuid.uuid4()` (`store.new_invocation_uuid`) that is the *sole* authoritative
     identity — directory name is `<operation>_<seq>_<uuid>`, `invocation_audit_dir` now uses
     `exist_ok=False` (a collision is a loud error, never silent reuse), and a small atomic,
     secret-free manifest (`job_id`, `slot_id`, `operation`, `sequence`, `invocation_uuid`,
     `created_at` — nothing else) is written via `store.write_invocation_manifest` **before** the
     provider call, so an orphaned crash directory is diagnosable without any prompt/response/
     credential content. `cost_ledger` rows gained an `invocation_uuid` field alongside the existing
     `audit_ref`. Old-style `audit_ref` values (pre-WP21R, no UUID) still load and display fine —
     nothing validates an *already-persisted* reference's format. Full detail, including the exact
     crash simulation, in `WPs/WP21R_ARCHITECT_REPORT.md`.
- **WP22 — targeted live evidence validation (validation only, no code change).** Three paid
  operations under a hard $0.50 shared ceiling, real cost **$0.1624412** total, none refused for
  budget. **Op 1:** one integrated production job (`אמבריולוגיה`, `C=2/A=1/B=1`) via the normal
  `/api/exam-jobs` path — confirmed the DB-selected question is auto-supplied as the LLM slot's
  previous-question context with no manual wiring, confirmed the WP21R invocation-manifest stayed
  byte-identical and the audit directory collision-free, real cost $0.0932765, one real attempt,
  `question_rejected` (a reviewer patch was mislabeled with the wrong `term_id` and correctly refused
  by the deterministic patch validator — looks like a reviewer-prompt defect, not an evidence gap).
  **Ops 2–3:** since no safe interface exists for a reviewer-only replay without `OPENAI_API_KEY`, a
  new git-ignored one-shot script (`exam_generator/artifacts/wp22/reviewer_replay.py`, untracked, not
  part of this repo's tracked tree) replayed the two preserved WP21G/WP21GR candidates
  (`chapter_01_q001`, `chapter_03_emb_001`) through the **unmodified** production orchestrator
  (`generate_one_question`) with their current WP21GR candidate-aware evidence pack, budget-guarded
  before each real call, run once by the owner from their own terminal. Neither flipped to accepted;
  `chapter_03_emb_001` gained 2 of 4 previously-failing criteria (`exactly_one_correct_answer`,
  `grounded_in_context`); both remain blocked on the same root cause — the reviewer requires an
  *explicit* source disproof per distractor and won't infer implausibility from a unit that only
  describes the distractor's own role, even though the (WP21GR-fixed) evidence pack now surfaces
  that unit correctly. This is a reviewer-strictness issue, not a retrieval gap. Full detail,
  exact costs, criterion-by-criterion diffs, and both replayed public questions in
  `WPs/WP22_ARCHITECT_REPORT.md`.
- **WP25G — the displaced question now reaches its own replacement's context.**
  `service.replace_via_llm` builds `previous = _previous_for_slot(job, slot)` *before* the paid call;
  that helper always excludes the target slot's own current question (it scans "other slots" by
  `instance_id`), and `category_history` cannot supply it either — it is appended there only *after*
  this exact call succeeds. Net effect (the WP25G incident): the one question being displaced was the
  one question never shown to the generator/reviewer judging its own replacement. Fixed with a one-line
  ephemeral append — `previous = _previous_for_slot(job, slot) + [old_question]` — scoped to that one
  call; `category_history` mutation timing is unchanged (still post-success only, still gated on
  `was_llm`). New regression `backend/tests/test_wp25g_inverse_duplicate_guard.py` proves it with the
  real incident pair (a capturing fake provider records exactly what
  `request.previous_questions` would send to the real paid call). Generator-side, `exam_generator`
  independently strengthens its own prompts and adds a deterministic public-text backstop
  (`duplicate_guard.semantic_duplicate_cross_role_problems`) as a final safety net — detail in
  `exam_generator/WPs/WP25G_GENERATOR_REPORT.md`. No outer route, DTO, schema, or seven-field contract
  change. Full detail in `WPs/WP25G_ARCHITECT_REPORT.md`.
- Backend entrypoint `backend/run.py`, **port 4567**. `src/main.py` runs
  `store.recover_on_start()` at import (running jobs → `interrupted`).
- Job state lives under git-ignored `artifacts/exam_jobs/<job_id>/` — JSON only,
  never in `app.db`, never in Git. Per-slot generator audits under
  `.../slots/<slot_id>/<operation>_<seq>_<uuid>/` (WP21R) — one directory per
  top-level LLM call, never reused, `invocation_manifest.json` written before
  the provider call. `EXAM_JOBS_ROOT` overrides the location (tests do).

## 4. WP17 blockers — both resolved

1. **Generator production API** — done (WP17G/WP17GR): `exam_generator.production.
   generate_exam_question(*, category_name, number, previous_public_questions,
   cost_ceiling_usd, audit_dir, max_attempts=2, provider=None,
   pricing_stale_after_days=30, <path overrides>) -> ProductionGenerationResult`.
   The WP18 adapter is a thin wrapper over it — no re-implemented assembly.
2. **Generator cross-platform test hygiene** — done (WP17G): LF fixtures,
   `.gitattributes`, self-set sentinel key in the stub-runner tests,
   `constraints.txt` + `docs/DEPENDENCY_LOCK.md`. The pinned generator's full
   suite is green (886→900 collected, 726 passed, 174 Data/font skips) and the
   targeted production tests pass network-blocked from this repo's env.

**Open items (post-WP22, corrected post-release by WP24D)**

*(WP24D correction: the two items WP22 surfaced here as not-yet-implemented were both resolved by
generator-side WPs before WP24's own release and are removed from this list, not carried forward as
open.)* Resolved: (1) a reviewer-proposed repair patch carrying a `term_id` that doesn't match its own
replacement text — **resolved in WP23** (`exam_generator`'s `TermSurfaceIndex` /
`repair.resolve_reviewer_patch_term_id`); (2) the reviewer's requirement of an *explicit* source
disproof to mark a distractor `distractors_incorrect_and_plausible` — **retired in WP23** (review-prompt
criterion 4 rewrite), and further sharpened by a new general distractor answer-type-alignment
requirement **added in WP23R**. Detail in `exam_generator/WPs/WP23_ARCHITECT_REPORT.md` and
`exam_generator/WPs/WP23R_ARCHITECT_REPORT.md`.

- Overall analytics (mean accuracy, distinction-threshold count) is deliberately **frontend-only**
  and unpersisted — matches the legacy architecture exactly, not an oversight. If it's ever wanted
  server-side, it needs a new WP.
- A generated (LLM-origin) row's "missing id" in the full export has no literal legacy precedent
  (history never had an idless question) — it reuses the accuracy/distinction blank-cell convention.
  Reasonable and documented, not fabricated, but flagged as an extension rather than a recovery.
- No live failure/retry/rollback was exercised in WP20 (by design, to stay inside the one
  authorized paid job) — that surface keeps relying on the offline fake-provider suites
  (`test_wp18r_cross_source_replacements.py`, `test_wp19_frontend_contract.py`,
  `test_wp21_analytics_and_exports.py`).
- No browser-automation tool (Playwright/Puppeteer/Cypress) is installed in this environment; a
  future live UI validation would need one added first if a literal click-through is required.

- The in-process daemon-thread worker is unchanged (single-user desktop tool);
  `replace_from_db` now also serialises through `_RUN_LOCK` (WP19). Concurrent
  job mutations return `409` and the frontend surfaces the reason. A real
  queue/process is only needed for multi-user/multi-process.
- **Realised origin count:** WP19 deliberately does **not** compute or display a
  current DB-vs-LLM balance (owner ruling). If one is ever wanted it must be a
  *separate* field, never a rewrite of `CategoryPlan.total/database/llm`.
- Progress polling is a fixed 1.5 s interval (no backoff / websockets) — fine for
  a sequential single-user job.
- Two dependency-pin conflicts between `backend/requirements.txt` and
  `exam_generator/constraints.txt` (`pytest` 7.4.2 vs 9.1.1; `MarkupSafe` 2.1.3
  vs 3.0.3) are documented in `scripts/dev_install.sh` and the WP18 report, not
  resolved. A unified lockfile for the integrated env is optional.
- Legacy `/api/test/generate` + `/api/test/replace-question` are unused by the UI
  but still mounted; a later WP may retire them (`/api/test/categories` and
  `/api/test/export-docx` stay — WP19 uses both).
- Frontend now has a Vitest/Testing-Library harness (`npm test`); `@testing-
  library/react@16` + `@testing-library/dom@10` are pinned so `user-event` and
  RTL share one `dom` copy.

## 5. Authority order

Newest owner ruling → verified outer repo + tests → this handoff → WP briefs →
older records. The generator is authoritative for question-generation behaviour
and is changed only by its own WPs.
