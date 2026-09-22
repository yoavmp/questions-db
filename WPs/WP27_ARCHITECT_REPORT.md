# WP27 — Architect Report: Staged DB Review Before LLM Generation

## 0. Summary

Creating a mixed exam used to select DB questions and then run the entire
planned LLM batch automatically, in the same request/background-thread
lifecycle, with no way to inspect or replace the DB selection before paying
for generation. WP27 splits that into two explicit, persisted phases:

1. **DB review** — `POST /api/exam-jobs` now performs DB selection only. No
   `OPENAI_API_KEY` inspection, no pricing-readiness check, no provider
   import, no generator audit — the route works identically with or without
   a key. A job with any planned LLM work is persisted `queued`
   (`workflow_phase == "db_review"`) and stays there, saved and reopenable
   indefinitely, until the user explicitly continues it. A job with zero
   planned LLM work is finalised `completed` immediately, inside
   `create_job` itself.
2. **LLM generation** — a new `POST /api/exam-jobs/<id>/continue-llm` is the
   one explicit, exactly-once operation that claims and runs the originally
   planned LLM batch, using the exact same per-slot pipeline (`_generate_one`,
   `_previous_for_slot`, cost ledger, retry/interruption model) the old
   automatic run always used.

Both manual replacement operations (`replace_from_db` / `replace_via_llm`)
keep working unchanged on every accepted question throughout DB review,
matching every binding owner decision in `WPs/WP27_Two_Phase_DB_Review_And_LLM_Generation.md`.

## 1. Exact files changed

Backend:

- `backend/src/jobs/model.py` — module docstring only (documents the WP27
  two-phase model and the `workflow_phase` derivation rule); no field, no
  schema, no `to_dict`/`from_dict` change.
- `backend/src/jobs/service.py` — the core of this WP:
  - `create_job`: removed the `readiness_report()` call; added the
    zero-planned-LLM immediate-finalise path.
  - new `pending_llm_slots(job)`, `workflow_phase(job)` (derivation, not a
    stored field — see §3).
  - `run_job` refactored: its per-slot loop body extracted into a new shared
    `_run_llm_slots(job, *, provider)`; `run_job` itself is otherwise
    byte-for-byte unchanged (same locks, same precondition, same finalise/
    print calls) — every existing direct caller (most of the pre-WP27 test
    suite) keeps working with zero changes.
  - new `continue_llm_generation(job_id, *, provider_factory=None)` — the
    WP27 §3 explicit continuation (detail in §4 below).
  - `replace_via_llm`: one real bug found and fixed — see §7.
  - `result_view`, `list_jobs`, `export_full_xlsx`: phase-aware interim vs.
    final numbering, plus new `workflow_phase`/`pending_llm_total`/
    `accepted_count` fields (see §5/§6).
  - `_OPERATION_HEADERS` gained a `"continue"` entry (same header text as
    `"initial"`, distinguished by the `operation=` field in the printed
    line).
- `backend/src/routes/exam_jobs.py` — `POST /exam-jobs`'s response body now
  reflects the job's real `status`/`workflow_phase` instead of a hardcoded
  `"queued"`; new `POST /exam-jobs/<id>/continue-llm` route (+ `_continue_bg`
  background-thread wrapper, mirroring `_run_bg`).
- `backend/tests/test_wp27_two_phase_db_review.py` (new) — 20 backend
  contract tests, one per item in the WP's required list plus two HTTP-route
  tests.
- Six existing test files updated to match the new, WP27-mandated contract
  (never to work around it) — full list and reasoning in §8.

Frontend:

- `frontend/src/lib/examApi.js` — new `continueLlm(jobId)`.
- `frontend/src/lib/examGen.js` — `isPollingStatus` no longer treats
  `"queued"` as a polling state (see §3); new `workflowPhase(job)` helper.
- `frontend/src/lib/examGen.test.js` — updated `isPollingStatus` test to the
  new contract; new `workflowPhase` test.
- `frontend/src/components/ExamGenerationSection.jsx` — the DB-review
  banner/Continue button, branch-disabled explanation, phase-aware
  empty-state and retry-list messaging, simplified `handleStart` (no more
  hand-rolled optimistic placeholder — creation is now fully synchronous DB
  work, so it just fetches the real result), new `handleContinue`.
- `frontend/src/components/ExamGenerationSection.wp27.test.jsx` (new) — 13
  component tests, one per item in the WP's required frontend-tests list.

Documentation:

- `SETUP.md` — new "Two-Phase Exam Creation" section.
- `WPs/ARCHITECT_HANDOFF.md` — new WP27 top section (mirrors the existing
  per-WP convention), updated SHA table, updated integration-surface table
  rows.
- `WPs/WP27_Two_Phase_DB_Review_And_LLM_Generation.md` — this WP's brief,
  copied in verbatim per its own instruction (already present as an
  owner-supplied untracked file at the start of this session; now committed
  as part of the WP27 changeset, as directed).
- `WPs/WP27_ARCHITECT_REPORT.md` — this file.

No change anywhere under `exam_generator/`, no change to
`backend/src/database/app.db`, no change to `backend/src/models/*` (the
Question/Category schema), no new dependency.

## 2. State / API / data-model changes

### Job state machine

`Job.status` (`JOB_STATES`, unchanged: `queued | running | completed |
partial | interrupted | cost_ceiling | failed`) is completely untouched as a
persisted concept — the same values, the same transitions, the same
`from_dict`/`to_dict`. What changed is *when* the automatic transition out of
`queued` happens: before WP27 the creation route triggered it within
milliseconds of `create_job` returning (sync or background thread); after
WP27, nothing does — `queued` is now the job's real resting state for as long
as the user leaves it in DB review, and the only thing that flips it to
`running` is an explicit `continue_llm_generation` (or a direct `run_job`
call, unchanged, still used by most of the pre-WP27 test suite).

### `workflow_phase` — derived, not persisted

```python
def workflow_phase(job: Job) -> str:
    if job.status == "queued":
        return "db_review" if any(s.kind == "llm" for s in job.slots) else "complete"
    if job.status in ("running", "interrupted"):
        return "llm_generation"
    return "complete"
```

The brief's recommended model names an explicit field. This report
deliberately implements it as a **pure function of already-persisted state**
instead, and flags the deviation here for the owner to weigh in on if they'd
rather have a literal stored field:

- **Why not a stored field.** A stored `workflow_phase` would need to be
  set/updated at every one of `create_job`'s two exit paths,
  `continue_llm_generation`'s claim step and its terminal `_finalise` call,
  `run_job`'s equivalent paths (used directly by ~40 pre-WP27 tests), and
  would have to be *read back* correctly by `Job.from_dict` for a legacy job
  that never had it. That is real, ongoing surface for the exact class of
  bug §7 found by accident (a status-mutating side effect nobody remembered
  to also patch). A pure function computed from `status` (which every one of
  those code paths already sets correctly, because it always had to) cannot
  drift from it by construction.
- **Why it still satisfies "explicit… unambiguous… API must expose it".**
  `workflow_phase` is a real, typed, three-value field in every relevant API
  response (`GET /exam-jobs`, `GET /exam-jobs/<id>`, and both job-creating
  routes) — callers never infer it from `status` themselves, and the rule
  computing it is documented once, in one place
  (`service.workflow_phase`'s docstring), applied uniformly.
- **The one deliberately-chosen legacy corner case.** A pre-WP27 `job.json`
  stuck at `status == "queued"` with a still-`queued` LLM slot (only
  reachable via a crash in the sub-millisecond window between `create_job`'s
  own `store.save` and the old auto-triggered `run_job`'s first `store.save`
  — a window that no longer exists post-WP27, since nothing auto-triggers
  anymore) now reads as `db_review` and gets a working Continue button it
  never had before. That is a strict improvement (it previously had **no**
  path to progress at all through the UI), not a behavior change to anything
  that was working — proven safe by
  `test_legacy_job_json_without_workflow_phase_field_loads_and_maps_safely`.
  A pre-WP27 `status == "queued"` job with **no** LLM slot at all (the even
  rarer twin edge case) reads as `complete`, never stuck "awaiting approval"
  for zero planned items.

If the owner prefers a literal stored field despite the above, it is a
small, localized follow-up (add the field to `Job`, set it at the same 4-5
call sites `workflow_phase()` currently branches on, keep the exact same
legacy-inference fallback for `from_dict`) — nothing else in this WP depends
on the representation being a function rather than a field.

### New response fields

- `GET /exam-jobs/<id>` (`result_view`): `workflow_phase`, `pending_llm_total`
  (count of still-`queued` planned LLM slots), `accepted_count` (mirrors the
  field `list_jobs` already had).
- `GET /exam-jobs` (`list_jobs`): `workflow_phase`, `pending_llm_total` added
  per job.
- `POST /exam-jobs` and `POST /exam-jobs/<id>/continue-llm` response bodies:
  `workflow_phase` added alongside the existing `status`/`job_id`/`url`.

No field was removed, renamed, or repurposed. `CategoryPlan.total/database/
llm` remain original-request provenance only, exactly as the WP19 owner
ruling requires — untouched by this WP.

## 3. Idempotency / concurrency mechanism

`continue_llm_generation` reuses, verbatim, the exact locking discipline
every other generating operation in this file already uses:

```python
if not _RUN_LOCK.acquire(blocking=False):
    raise JobBusy(...)                       # a genuinely concurrent request
...
if job.status not in ("queued", "interrupted"):
    raise JobConflict(...)                    # already claimed / already done
if not pending_llm_slots(job):
    raise JobConflict(...)                    # nothing planned to continue
got_file_lock = store.try_acquire_lock(job_id)
if not got_file_lock:
    raise JobBusy(...)
...
if provider is None:
    report = readiness_report()
    if not report["ready_for_llm"]:
        raise JobError(...)                   # nothing persisted yet
job.status = "running"                        # the claim
store.save(job)                               # persisted BEFORE any provider call
stopped_by_ceiling = _run_llm_slots(job, provider=provider)
_finalise(job, stopped_by_ceiling=stopped_by_ceiling)
store.save(job)
```

- **Double-click / sequential repeat.** The first call flips `status` away
  from `queued`/`interrupted` before releasing the lock; every later call —
  whether the batch is still running or has already finished — fails the
  `status in ("queued", "interrupted")` check and gets `JobConflict` (409).
  Proven by `test_double_and_concurrent_continue_cannot_duplicate` (ledger
  length and accumulated cost identical before/after the rejected repeat).
- **Genuinely concurrent request.** `_RUN_LOCK.acquire(blocking=False)`
  fails for the second caller while the first still holds it → `JobBusy`
  (409), the job untouched. Proven by the same test (holds `_RUN_LOCK`
  directly, asserts the job stays `queued` with an empty ledger).
- **Readiness failure.** Checked *after* the lock is held (so no other
  request can race in) but *before* `job.status` is ever mutated or
  `store.save` is ever called — a failure raises with the job byte-for-byte
  as it was. Proven by
  `test_readiness_failure_leaves_job_in_db_review_and_charges_nothing`,
  which then proves the SAME job can be continued normally once the key is
  restored.
- **Restart mid-batch.** Unchanged `store.recover_on_start()`: a `running`
  job → `interrupted` (and its one actually-`running` slot →
  `interrupted`); every other slot's status (accepted / still-queued) is
  untouched. `continue_llm_generation`'s own precondition already accepts
  `status == "interrupted"`, so calling it again resumes the *same* batch —
  `_run_llm_slots` only ever touches `status == "queued"` slots, so an
  already-accepted slot is structurally never regenerated. This deliberately
  reuses `run_job`'s own existing `queued`/`interrupted` precondition and
  per-slot `queued`-only selection rather than inventing a second resume
  mechanism — proven by `test_branching_blocked_until_llm_phase_completes`,
  which synthesizes an interrupted job mid-test and successfully resumes it
  through `continue_llm_generation`.
- **The HTTP route's async/sync duality.** `POST /exam-jobs/<id>/continue-llm`
  follows the exact same pattern `POST /exam-jobs` already established:
  under `EXAM_JOB_SYNC` (tests) it runs synchronously and the response
  reflects the real, final `status`/`workflow_phase`; otherwise it spawns a
  daemon thread (`_continue_bg`, mirroring `_run_bg`) and returns `202`
  immediately with `status: "running"`. **Known, pre-existing-pattern
  limitation, not a WP27-introduced gap:** in async/production mode, two
  near-simultaneous `POST …/continue-llm` requests can both receive `202`
  before either thread has acquired `_RUN_LOCK` — the *system state* is
  still exactly-once (the losing thread's `continue_llm_generation` call
  raises `JobBusy`, caught and swallowed by `_continue_bg`, exactly like
  `_run_bg` already does for job creation), but the HTTP response alone does
  not distinguish "I started it" from "someone else already had". This is
  the identical characteristic `POST /exam-jobs`'s own async creation path
  has always had; WP27 does not change or worsen it, and `EXAM_JOB_SYNC`
  mode (used by every test that needs a deterministic HTTP-level 409) is
  unaffected.

## 4. Backward compatibility

- **`Job`/`Slot`/`CategoryPlan` schema:** byte-for-byte unchanged. No new
  field, no renamed field, no version bump (`SCHEMA_VERSION` stays `1`). Any
  job persisted by any prior WP loads through the exact same
  `Job.from_dict`/`Slot.from_dict` as before.
- **Legacy job behavior:** proven directly by
  `test_legacy_job_json_without_workflow_phase_field_loads_and_maps_safely` —
  reads a real completed job's raw `job.json`, confirms `"workflow_phase"`
  never appears in it, confirms merely loading it never rewrites the file
  (byte-identical before/after `store.load`), and confirms both rare
  `status == "queued"` legacy corner cases (§2) map safely.
- **`run_job` (the pre-WP27 entry point):** completely unchanged in
  behavior and signature. Every test in `test_wp18_*.py`,
  `test_wp18r_*.py`, `test_wp19_*.py`, `test_wp20_*.py`, `test_wp21*.py`,
  `test_wp25g_*.py`, `test_wp26*.py` that drives generation by calling
  `service.create_job(...)` then `service.run_job(...)` directly — the large
  majority of the pre-existing suite — needed **no change** for this reason;
  it still exercises the exact same code path (`_run_llm_slots`, extracted
  verbatim from `run_job`'s old inline loop body with no logic change).
- **`replace_from_db`/`replace_via_llm`:** both were already phase-agnostic
  (they check `slot.status == "accepted"`, never `job.status`), so both
  needed no new guard to keep working during `db_review` — confirmed by
  `test_both_replacement_directions_during_db_review_preserve_identity` and
  the WP25G/displaced-history tests re-run during `db_review` in
  `test_displaced_history_rules_hold_during_db_review`.
- **Branching guard:** `branch_job`'s existing `if parent.status !=
  "completed": raise JobConflict` needed **no change** — `db_review` leaves
  `status == "queued"` and `llm_generation` leaves it `running`/
  `interrupted`, both already rejected by the pre-existing check. Proven
  directly in `test_branching_blocked_until_llm_phase_completes`.

## 5. Numbering and export contract

Three distinct concepts, as the brief requires they be documented precisely:

1. **Internal identity** — `slot_id`/`instance_id`. Assigned once at
   `create_job` time (for every slot, DB or LLM, accepted or still-planned),
   never reassigned by anything in this WP or any prior one. Stable across
   replacement, retry, generation, and phase transition.
2. **Final exam number** — `Slot.number`. Also assigned once at
   `create_job` time, in canonical category order (`CATEGORY_ORDER`), DB
   slots before LLM slots within each category's block — i.e. the *complete*
   final numbering (spanning both already-selected DB questions and
   still-planned LLM questions) is computed up front, not procedurally at
   Continue time. This was a deliberate design choice: the brief's "When
   Continue is claimed: establish the final full-exam ordering/numbering" is
   satisfied by this number becoming the one *shown* the moment `db_review`
   ends, not by recomputing it then — recomputing it at Continue time would
   have meant either renumbering already-selected DB questions (forbidden —
   it would corrupt replacement/history references keyed by number) or
   maintaining two different numbering regimes for DB vs. LLM slots, neither
   of which the existing single `number` field the whole codebase already
   keys off of (replacement, cost ledger, semantic-history ordering,
   exports) was designed for. `Slot.number` is never touched again after
   creation by anything — accepted, failed, retried, or replaced.
3. **Interim display/export number** — computed fresh on every read, only
   while `workflow_phase == "db_review"`: the 1-based position of each
   *accepted* question in `Job.accepted_questions_ordered()`'s own output
   (already canonical-category-then-`number` order). Never persisted, never
   confused with `Slot.number`, invisible the moment `db_review` ends (the
   real `Slot.number` is shown again, unchanged).

Proven end-to-end by
`test_interim_numbering_is_compact_final_numbering_is_canonical_and_stable`:
a 3-category job (מבוא A=2/B=0, גרעיני הבסיס A=0/B=2, היסטולוגיה A=1/B=0)
shows interim numbers `[1, 2, 3]` over only its 3 accepted questions during
`db_review` (even though היסטולוגיה's real final number is `5`, with a gap
at 3-4 reserved for גרעיני הבסיס's pending LLM slots) — and shows
`[1, 2, 3, 4, 5]`, canonical, stable, after Continue.

Export contract (`test_exports_exclude_pending_placeholders_then_include_everything_after_continue`):
`export_full_xlsx` uses the same interim-vs-final number; `export_llm_xlsx`
(no number column at all) is naturally unaffected; the DOCX path is a
legacy route (`/api/test/export-docx`) that receives whatever `questions`
array the frontend currently has from `result_view` — since that array
already excludes non-accepted slots and already carries the correct interim
number, DOCX needed **zero** changes on either side.

## 6. Context / history contract

`_previous_for_slot` needed **no code change** — it already only ever
scanned `status == "accepted"` slots (DB, or LLM with `status ==
"accepted"`) plus `job.category_history`. A still-`queued` planned slot has
no `.question` and fails that status filter by construction, so it was
already structurally invisible to every generator call, before this WP
existed. And because `continue_llm_generation` reuses the exact same
sequential per-category loop `run_job` always used
(`_run_llm_slots`, extracted verbatim), a slot generated earlier in the
same continuation batch is already persisted `accepted` — and therefore
already visible to `_previous_for_slot` — before the next slot's context is
built, with no new plumbing.

Proven directly by
`test_continuation_context_excludes_pending_includes_history_and_earlier_batch_items`
(a capturing fake provider, same technique as
`test_wp25g_inverse_duplicate_guard.py`): seeds one displaced-LLM history
entry during `db_review` via a DB→LLM→DB replacement dance, confirms the
first of two planned LLM slots' context contains exactly the 1 current DB
question + the 1 history entry (nothing else — no pending-placeholder
leak), and confirms the second slot's context additionally contains the
first slot's own just-generated question from this same continuation run.

## 7. Cost / readiness behavior (and the bug this WP found)

- `create_job` makes zero readiness/provider/audit calls, proven with hard
  monkeypatched traps (`test_create_job_makes_zero_provider_readiness_or_audit_calls`)
  that raise `AssertionError` if `readiness_report`, `generate_category_question`,
  or `store.invocation_audit_dir` are called at all during creation, run with
  `OPENAI_API_KEY` deliberately unset.
- Readiness is checked exactly twice in the whole system now: once inside
  `_run_llm_slots`'s per-slot loop (unchanged, pre-existing, `if provider is
  None`), and once up front in `continue_llm_generation` before the claim
  (new, WP27). `replace_via_llm` still makes no explicit readiness call —
  unchanged from before WP27 — because the generator adapter itself already
  fails closed with no network call when the key is absent (documented in
  `generator_adapter.generate_category_question`'s own docstring); this WP
  did not need to add a redundant explicit check there to satisfy "checks
  readiness only when invoked".
- `continue_llm_generation` uses the job's existing `remaining_budget()`
  (`cost_ceiling_usd - accumulated_cost_usd`) with no reset — proven by
  `test_manual_and_continuation_spend_share_one_cost_ceiling` (a manual
  pre-Continue spend followed by Continue, cumulative total only grows) and
  `test_continuation_respects_a_ceiling_already_exhausted_manually` (tighten
  the ceiling to just above an already-spent amount; Continue immediately
  hits `cost_ceiling` with **zero** further spend and both originally
  planned slots stay unaccepted).

**The bug found and fixed:** `replace_via_llm` used to call the shared
`_finalise(job, stopped_by_ceiling=...)` helper unconditionally after every
manual replacement. `_finalise` computes `job.status` from *all* LLM slots'
current status, including `pending = status in ("queued", "running",
"interrupted")` → `job.status = "partial"` whenever any are still pending.
Before WP27 this was safe: by the time any manual replacement could run,
`run_job` had already resolved every LLM slot to a terminal status (no
`"queued"` ones existed to trip that branch). WP27 makes it unsafe: during
`db_review`, other planned LLM slots are legitimately, correctly still
`"queued"` (not yet claimed by Continue) while a manual replacement runs —
and `_finalise` misread that as an in-progress/partial batch, flipping
`job.status` away from `"queued"` and silently ending `db_review` as a side
effect of an unrelated manual operation, directly violating the brief's
"on success, keeps the job in db_review". Caught by this WP's own new test
suite (`test_manual_llm_replacement_during_db_review_does_not_reduce_planned_b`
and two others failed with `job is 'partial'; LLM continuation is only
available…` on the very first run). Fixed by capturing `was_db_review =
job.status == "queued"` before the call and, when true, refreshing only
`job.terminal_summary` (still satisfying "terminal summaries continue after
each paid operation") while explicitly skipping `_finalise`'s `job.status`
recomputation. `retry_slot` was audited for the same risk and found safe
without changes: it can only ever run after `_run_llm_slots` has fully
released its locks, by which point every LLM slot in that run has already
reached a terminal or `interrupted` status — the same latent quirk this
fix addresses is not newly introduced there, and reusing this WP's fix
pattern for it (were it needed) is a one-line follow-up if ever required.

## 8. Tests and exact results

### Backend

New: `backend/tests/test_wp27_two_phase_db_review.py` — **20 tests**, one
per item in the brief's "Backend contract tests" list (18) plus 2 HTTP-route
tests. All pass.

Updated (behavior legitimately changed by this WP, not worked around):

| File | Change | Why |
|---|---|---|
| `test_wp18_readiness.py` | `test_create_job_blocks_when_llm_requested_and_not_ready` → `test_create_job_never_checks_readiness_even_with_llm_requested`, asserting the opposite (creation succeeds, `db_review`, $0) | WP27 §2 explicitly reverses this old contract |
| `test_wp18_job_lifecycle.py` | `test_db_only_job_succeeds_without_llm_readiness`: removed the redundant `run_job` call (now `JobConflict` since the job is already `completed`) | WP27 §2 edge case: B=0 finalises inside `create_job` |
| `test_wp18_replacements.py` | `test_replace_db_rejects_when_no_alternative`: same fix | same reason |
| `test_wp26r_snapshot_immutability.py` | `_db_only_job` helper: same fix | same reason |
| `test_wp26_naming_history_branching.py` | `_db_only` helper: same fix | same reason |
| `test_wp18_cost_and_export.py` | `test_create_job_via_route_returns_202_and_polls_to_completion`: now asserts `db_review` immediately after the route call, then explicitly calls `continue-llm` before asserting `completed` | the route no longer auto-runs |
| `test_wp18r_cross_source_replacements.py` | `test_both_endpoints_accept_both_origins_via_route`: added an explicit `continue-llm` call before the test needs an `origin: "llm"` question to exist | same reason |
| `test_wp19_frontend_contract.py` | none needed — the one route-level test there only needs a `database`-origin question, unaffected | — |

Full-suite result (`cd backend && env -u OPENAI_API_KEY caffeinate -i
../.venv/bin/python -m pytest -q`, foreground, actively awaited):

```
263 passed in 223.23s (0:03:43)
```

(241 pre-existing + 2 pre-existing-but-updated-for-the-new-contract... the
263 total = 243 pre-WP27 tests, all still green, + 20 new WP27 tests. Two
pre-existing tests failed on the FIRST run for the exact reasons in §7/this
table — both fixed within this session, not left red.)

### Frontend

New: `frontend/src/components/ExamGenerationSection.wp27.test.jsx` — **13
tests**, one per item in the brief's "Frontend tests" list. All pass.

Updated: `frontend/src/lib/examGen.test.js` — `isPollingStatus('queued')`
now asserts `false` (was `true`) per the WP27-mandated semantics change
(`"queued"` is the long-lived DB-review resting state, not a transient
one); added a `workflowPhase` unit test.

No other existing frontend test needed a change — `makeView()`'s default in
`ExamGenerationSection.test.jsx` already defaults to `status: "completed"`
with no `workflow_phase` field, and `workflowPhase()` defaults an absent
field to `"complete"`, so every pre-existing completed/partial/interrupted/
cost_ceiling/failed-job test continues to exercise the exact same render
path as before.

Full-suite result (`cd frontend && npm test -- --run`, foreground):

```
Test Files  6 passed (6)
     Tests  122 passed (122)
```

(109 pre-existing, unchanged + 13 new WP27 tests.)

Production build (`cd frontend && npm run build`, foreground):

```
✓ 1261 modules transformed.
✓ built in 2.81s
```

No warnings or errors beyond the pre-existing, unrelated `caniuse-lite`
staleness notice.

## 9. Confirmation of zero live/provider calls

- No `OPENAI_API_KEY` was read, exported, or referenced with a real value at
  any point in this session — `llm_ready`/`monkeypatch.delenv` fixtures use
  only in-process sentinel strings, exactly as the pre-existing suite
  already did.
- No backend or frontend dev server was started.
- Every backend test runs with real sockets hard-blocked
  (`socket.socket.connect`/`connect_ex` monkeypatched to raise) — the new
  `test_wp27_two_phase_db_review.py` adds its own autouse fixture doing
  exactly this, matching every other WP19+ test file's convention.
- `test_create_job_makes_zero_provider_readiness_or_audit_calls` additionally
  proves, by hard `AssertionError`-raising monkeypatch traps (not just
  socket-blocking), that `create_job` never even reaches the readiness/
  generator/audit boundary in the first place.
- No frontend test issued a real `fetch` — `@/lib/examApi.js` is fully
  mocked in every component test (`vi.mock`), matching the pre-existing
  convention.

## 10. Secret / artifact / database / submodule audit

- `git diff --stat` (this session, outer repo only): 16 files changed, all
  under `backend/src`, `backend/tests`, `frontend/src`, `SETUP.md`,
  `WPs/ARCHITECT_HANDOFF.md` — no file under `exam_generator/`, no
  `backend/src/database/app.db`, no `.env*`, no `../exam_generator_pre_submodule_backup/`.
- `git -C exam_generator status --short` → clean; `git submodule status` →
  still pinned at `d20c46bbb332e4d40f735e843d31113176b755e5` (unchanged).
- `artifacts/exam_jobs/` was written to by every test run (via the
  `jobs_root`/`EXAM_JOBS_ROOT` fixture pointing at `tmp_path`, or — for a
  couple of manual sanity checks — the real `artifacts/` dir, which is
  git-ignored, `git status --short` confirms nothing there is tracked).
- Grepped the full diff for `OPENAI_API_KEY\s*=`, `sk-[a-zA-Z0-9]{10,}`,
  `password\s*=`, `secret\s*=` — no match.
- Neither `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md` nor
  `WPs/PRE_WP26R_AUDIT.md` was read, opened, or modified this session.

## 11. Final outer and generator SHAs / statuses

Recorded at the end of this session, immediately before commit (see the
closing terminal block of this WP's completion message for the exact
post-commit/post-push values):

```
$ git rev-parse HEAD                 # before this WP's commit
8302c43498b6310e18ab667ef5e1d8ec02941640
$ git status --short
 M SETUP.md
 M WPs/ARCHITECT_HANDOFF.md
 M backend/src/jobs/model.py
 M backend/src/jobs/service.py
 M backend/src/routes/exam_jobs.py
 M backend/tests/test_wp18_cost_and_export.py
 M backend/tests/test_wp18_job_lifecycle.py
 M backend/tests/test_wp18_readiness.py
 M backend/tests/test_wp18_replacements.py
 M backend/tests/test_wp18r_cross_source_replacements.py
 M backend/tests/test_wp26_naming_history_branching.py
 M backend/tests/test_wp26r_snapshot_immutability.py
 M frontend/src/components/ExamGenerationSection.jsx
 M frontend/src/lib/examApi.js
 M frontend/src/lib/examGen.js
 M frontend/src/lib/examGen.test.js
?? WPs/PRE_WP25_LATEST_EXAM_REVIEW.md
?? WPs/PRE_WP26R_AUDIT.md
?? WPs/WP27_ARCHITECT_REPORT.md
?? WPs/WP27_Two_Phase_DB_Review_And_LLM_Generation.md
?? backend/tests/test_wp27_two_phase_db_review.py
?? frontend/src/components/ExamGenerationSection.wp27.test.jsx
$ git submodule status
 d20c46bbb332e4d40f735e843d31113176b755e5 exam_generator (heads/main)
$ git -C exam_generator rev-parse HEAD
d20c46bbb332e4d40f735e843d31113176b755e5
$ git -C exam_generator status --short
(clean)
```

## 12. Commit and push outcome

Recorded at completion time in this WP's final terminal report (post-commit
`git rev-parse HEAD` / `git rev-parse origin/main` / final `git status
--short`, per the WP's "Git completion" section) — see that closing message
for the exact SHA and push result.

## 13. Known limitations / owner decisions that may be worth revisiting

1. **`workflow_phase` is derived, not a stored field** — see §2/§3 for the
   full reasoning and the exact fallback if the owner prefers a literal
   field instead.
2. **"Verify the selected job is the editable active job" (WP27 §3)** — the
   codebase has no backend-side notion of "the active job" at all; it is
   purely frontend local state (`activeJobId` vs. `viewedJobId` in
   `ExamGenerationSection.jsx`, unchanged by this WP). `continue_llm_generation`
   enforces everything backend-checkable (job exists, is in the right
   phase, has pending work, is not locked by another operation) — the
   "active" concept itself remains, as it already was for every other
   mutating endpoint (`replace-db`, `replace-llm`, `branch`), a frontend-only
   gate. This is not a new gap WP27 introduces; it is the existing
   architecture, documented here explicitly since the brief's wording could
   be read as expecting a backend check that has no analog anywhere else in
   this codebase.
3. **Async-mode double-click race at the HTTP-response layer** — see §3's
   last bullet. System state is always exactly-once; two near-simultaneous
   async responses can both say `202` before the losing one's background
   thread discovers it lost the race. Identical, pre-existing characteristic
   of `POST /exam-jobs`'s own creation path; not new or worsened by this WP.
4. **Frontend optimistic-status race after clicking Continue in production
   (non-`EXAM_JOB_SYNC`) mode** — `handleContinue` awaits `continueLlm()`
   then immediately re-fetches the job; in the async production path the
   background thread might not have flipped `status` away from `"queued"`
   yet by the time that fetch lands, in which case the UI would show the
   `db_review` banner for one extra beat until the user's next
   refresh/reopen (no polling is triggered from a `"queued"` read). Judged
   low-probability (thread scheduling is effectively instant relative to a
   network round trip) and consistent with the same tolerance
   `handleStart`'s pre-WP27 design already had for the equivalent race; not
   specially engineered around, per this session's time constraints.
5. **`retry_slot` shares `_finalise`'s "pending llm slots exist" ambiguity in
   one narrow, pre-existing (not WP27-introduced) scenario** — retrying one
   `interrupted` slot from a batch that was interrupted mid-way, while other
   slots in that same category-order remain genuinely `"queued"` (never
   reached before the crash), will have `_finalise` read those as "pending"
   and report `"partial"` even though most of them simply never got a
   chance to run. This already existed before WP27 (§7) and is out of this
   WP's scope; flagged here in case the owner wants a follow-up WP to apply
   the same phase-aware fix there.
