# WP27R — Architect Report: Persisted Phase, Atomic Continue, and Recovery

## 0. Summary, and a baseline reconciliation

WP27R corrects two production-state gaps `WPs/WP27_ARCHITECT_REPORT.md` §13
already flagged as known limitations of WP27's original design:

1. WP27's `workflow_phase` was a **derived** value, recomputed from `status`
   on every read. An async Continue's `202` could be followed by an
   immediate `GET` that still observed the pre-claim `queued`/`db_review`
   state (nothing had been persisted synchronously yet), causing the
   frontend to stop polling while generation quietly ran in the background.
2. Retrying one `interrupted` slot while later planned slots stayed
   `queued` (a batch cut short mid-traversal) recomputed the derived phase
   from `status` alone — `status` doesn't distinguish "this slot was never
   attempted" from "this slot is genuinely done" the way WP27R now
   requires, so a `partial` status could compute as `complete`, hiding
   Continue and stranding real, untouched planned work.

Both are fixed by making `workflow_phase` a **persisted**, validated `Job`
field and splitting the continuation boundary into an atomic, synchronous
**claim** and a separate **claimed worker** — see §2-§4.

**Baseline note.** The brief's "Expected WP27 baseline" names outer
`HEAD == origin/main == a13b60d24eff0fe025ff6793bc445c2b02bb1298`. The
actual starting `HEAD` this session was `53177b87ab2d3f914f83a3a22bc3fa0c7ed74c45`
— one commit ahead, `53177b8 WP27R: record final commit SHA and push outcome
in architect report`. That commit's *subject* names "WP27R" by the same
labeling convention `WP26R`'s own closing commit (`8302c43`) used, but it in
fact closed out **WP27** (a documentation-only addendum recording WP27's own
final SHA into its architect report, exactly as `8302c43` did for WP26R) —
a naming artifact from the prior session pattern-matching that convention,
not a sign of unrelated or unreviewed work. `git log` confirms it touches
only `WPs/WP27_ARCHITECT_REPORT.md`. `origin/main` matched this same `HEAD`
exactly (no divergence, nothing unpushed), so this was not unrelated tracked
drift requiring a stop — documented here per the brief's own instruction
("If the actual baseline differs, document it") rather than treated as a
blocker.

## 1. Files changed

Backend:

- `backend/src/jobs/model.py` — new `WORKFLOW_PHASES` constant, new
  `_infer_legacy_workflow_phase(status, slots)`, new `Job.workflow_phase`
  field (default `"db_review"`), `to_dict` validates it before every write,
  `from_dict` trusts a recognized persisted value or infers one (never
  rewriting the source dict).
- `backend/src/jobs/service.py`:
  - `workflow_phase(job)` changed from a `status`-derivation to a thin,
    validating accessor over the persisted field.
  - `create_job`: relies on the field's dataclass default for the
    `db_review` case (unchanged construction call); the `llm == 0` immediate-
    finalise path is unchanged (`_finalise` now sets the field itself).
  - `run_job`: now also sets `workflow_phase = "llm_generation"` at the same
    point it sets `status = "running"`, so every direct/legacy caller (most
    of the pre-WP27R test suite) stays phase-consistent without going
    through the new claim/worker split.
  - **New** `claim_llm_continuation` / `run_claimed_llm_generation` /
    `abort_claim_as_interrupted` — the WP27R §3 split (detail in §3).
  - `continue_llm_generation` is now a **thin wrapper**: claim, then run, in
    the calling thread — kept for every direct/test caller and for the
    HTTP route's `EXAM_JOB_SYNC` path.
  - `_finalise`: now computes `workflow_phase` from the same `pending` set
    (`status` in `queued`/`running`/`interrupted`) already computed for
    `status` — `"llm_generation"` if anything is still untouched/mid-flight,
    `"complete"` once every planned slot has reached ANY terminal per-attempt
    outcome (detail in §5).
  - `replace_via_llm`: `was_db_review` now reads `job.workflow_phase`
    directly instead of inferring it from `status` (same invariant, now
    checked at the authoritative source).
  - `branch_job`: guard now requires `status == "completed" AND
    workflow_phase == "complete"`; the branched **child**'s constructor now
    explicitly passes `workflow_phase="complete"` (a real, if narrow, bug:
    without this the child would have silently inherited the dataclass
    default `"db_review"`, since a branch was the one `Job(...)`
    construction site the WP27 audit had not covered).
  - `result_view` / `list_jobs`: `branchable` now checks both fields too.
- `backend/src/routes/exam_jobs.py`: `continue_llm` route rewritten so the
  claim (`service.claim_llm_continuation`) always runs **synchronously**
  inside the request — in both sync and async mode — before any `202` is
  returned; only the actual generation work is deferred to a background
  worker (`_run_claimed_bg`) in async/production mode. Worker-start failure
  is caught and calls `service.abort_claim_as_interrupted`.
- `backend/tests/test_wp27_two_phase_db_review.py` — 3 pre-existing tests
  updated for the new persisted-phase contract (detail in §7); 20/20 still
  pass.
- `backend/tests/test_wp27r_persisted_phase_and_recovery.py` (new) — 15
  tests, one per numbered item in the brief's backend test list (plus 2
  combined into single tests where the brief's items naturally paired).

Frontend:

- `frontend/src/lib/examGen.js`: `isPollingStatus(status, phase)` now takes
  both parameters (`status === "running" && phase === "llm_generation"`,
  was `status === "running"` alone).
- `frontend/src/lib/examGen.test.js`: updated for the two-parameter
  contract.
- `frontend/src/components/ExamGenerationSection.jsx`: the polling `useEffect`
  passes both `job.status` and `workflowPhase(job)`; `handleContinue`
  applies the claim response's real `status`/`workflow_phase` to local state
  immediately (starts polling without depending on a follow-up `GET`
  winning any race), then fetches the full result; a `409` response loads
  the current job instead of showing a fatal error; new "resume" banner
  (`data-testid="resume-banner"`) for a paused `llm_generation` job with
  real planned work remaining, offering the same Continue action.
- `frontend/src/components/ExamGenerationSection.test.jsx`: one pre-existing
  test's mocked intermediate view gained `workflow_phase: "llm_generation"`
  (detail in §7).
- `frontend/src/components/ExamGenerationSection.wp27r.test.jsx` (new) — 9
  tests covering the brief's frontend test list.

Documentation: `SETUP.md`, `WPs/ARCHITECT_HANDOFF.md` (new top section,
updated SHA table, updated integration-surface rows — WP27's own section
and history left untouched, as instructed), this report, and the brief
itself saved into the repository.

No change anywhere under `exam_generator/`, `backend/src/database/app.db`,
`backend/src/models/*`, or any dependency file.

## 2. Persisted phase schema and legacy inference

```python
WORKFLOW_PHASES = ("db_review", "llm_generation", "complete")

@dataclass
class Job:
    ...
    workflow_phase: str = "db_review"
```

`to_dict()` raises `ValueError` if `self.workflow_phase not in
WORKFLOW_PHASES` — a job can never be *persisted* with an invalid value,
catching a service-layer bug loudly at the point of writing rather than
silently writing bad state to disk ("validate ... on save").

`from_dict()` trusts a raw `workflow_phase` value only if it is already one
of `WORKFLOW_PHASES`; anything absent (every pre-WP27R job.json) or
unrecognized falls back to `_infer_legacy_workflow_phase(status, slots)`
("validate ... on load"). That function is **not** a plain `status` lookup:

```python
def _infer_legacy_workflow_phase(status, slots):
    has_any_llm = any(s.kind == "llm" for s in slots)
    has_pending_llm = any(s.kind == "llm" and s.status == "queued" for s in slots)
    if status == "queued":
        return "db_review" if has_any_llm else "complete"
    if status in ("running", "interrupted"):
        return "llm_generation" if has_any_llm else "complete"
    # completed / partial / cost_ceiling / failed / other terminal status
    return "llm_generation" if has_pending_llm else "complete"
```

The last branch is the important one: a legacy **terminal** status
(`completed`/`partial`/`cost_ceiling`/`failed`) can still have a genuinely
untouched `"queued"` slot left behind — e.g. a pre-WP27R job that was
interrupted, had its one `interrupted` slot retried, and had its `status`
recomputed to `partial` by the *old*, not-yet-phase-aware `_finalise` while
later categories' slots were still sitting `queued`, never reached. A plain
`status`-only lookup (WP27's original derivation) would report that as
`complete`, permanently hiding Continue/resume for real planned work — this
is, in miniature, the exact WP27R incident, applied retroactively to a
legacy file. The rule instead asks the only question that matters: is there
a planned LLM slot nobody has attempted yet?

Merely loading a legacy job never rewrites its file — proven directly by
`test_legacy_json_loads_safely_and_gains_the_field_only_on_legitimate_save`
(byte-identical before/after `store.load`) and by
`test_workflow_phase_is_now_persisted_and_legacy_json_still_loads_safely`
(same, plus the two rare legacy corner cases carried over from WP27's own
report: a stuck `queued`+pending-LLM job infers `db_review`; a `queued` job
with no LLM slot at all infers `complete`). The field appears on disk only
the next time the job is legitimately mutated and saved.

## 3. Claim/worker locking and failure recovery

```python
def claim_llm_continuation(job_id, *, provider_factory=None) -> tuple[Job, Any]:
    if not _RUN_LOCK.acquire(blocking=False):
        raise JobBusy(...)
    got_file_lock = False
    try:
        job = store.load(job_id)
        ...eligibility + readiness checks...
        got_file_lock = store.try_acquire_lock(job_id)
        ...
        job.workflow_phase = "llm_generation"
        job.status = "running"
        store.save(job)
        return job, provider          # locks intentionally still held
    except Exception:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()
        raise
```

On success this function returns **without releasing either lock**. This is
deliberate: the brief requires "the implementation must not create a gap
where another mutation can alter the same job after claim but before the
worker obtains protection." Since any thread may call `.release()` on a
`threading.Lock` it did not itself acquire, handing the still-held locks
from the claiming call (the request thread) to a spawned background worker
thread — which then owns releasing them, in `run_claimed_llm_generation`'s
`finally` — closes that gap completely: from the moment the claim succeeds
to the moment the batch fully finishes, the lock hold is continuous, with
only a control-flow handoff between threads, never an unlock/relock window.
`run_claimed_llm_generation` assumes (and requires) both locks are already
held on entry and is the sole subsequent owner of releasing them — its
docstring says so explicitly, and the only two callers that may invoke it
(`continue_llm_generation` and the route's `_run_claimed_bg`) both always do
so immediately after a successful claim, never independently.

Eligibility (checked inside the held lock, before readiness/persistence):

- `workflow_phase == "db_review"` requires `status == "queued"` — the first
  claim.
- `workflow_phase == "llm_generation"` requires `status != "running"` (i.e.
  `partial`/`interrupted`/`cost_ceiling` with real planned work still
  `queued`) — a resume, reusing the exact same claim path (no separate
  resume mechanism).
- any other phase (`complete`, or `llm_generation` while genuinely
  `running`) is rejected with `JobConflict`.
- `pending_llm_slots(job)` empty is also rejected — nothing to continue.

Readiness (`readiness_report()`, bypassed only when a provider is injected —
tests) is checked once, inside the held lock, **before** `store.save` ever
runs — a failure raises with the job completely untouched and both locks
released by the `except` above, proven byte-for-byte by
`test_readiness_failure_leaves_exact_db_review_state`.

**Worker-start failure.** If `threading.Thread(...).start()` itself raises
(simulated in tests by monkeypatching it), the route's `except` calls
`service.abort_claim_as_interrupted(job_id)`:

```python
def abort_claim_as_interrupted(job_id):
    try:
        job = store.load(job_id)
        if job is not None and job.status == "running":
            job.status = "interrupted"
            job.safe_error = "worker failed to start; unfinished slots are retryable"
            for s in job.slots:
                if s.status == "running":
                    s.status = "interrupted"
            store.save(job)
    finally:
        store.release_lock(job_id)
        _RUN_LOCK.release()
```

`workflow_phase` stays `"llm_generation"` — never flipped back to
`db_review` and never left permanently `running` with no worker ever going
to finish it. This mirrors `store.recover_on_start()`'s own process-crash
recovery, applied synchronously here instead of waiting for the next
backend boot. Proven end-to-end (route returns `500`, job shows
`interrupted`/`llm_generation`, and a subsequent real Continue then
succeeds normally) by
`test_worker_start_failure_leaves_recoverable_interrupted_llm_generation`.

## 4. HTTP behavior: winner, concurrent loser, repeat, resume

`POST /exam-jobs/<id>/continue-llm` now performs the claim **synchronously**
in every mode — this is the core WP27R fix. Only what happens *after* a
successful claim differs by mode:

- **`EXAM_JOB_SYNC` (tests):** `run_claimed_llm_generation` runs in the
  request thread; the response reflects the real final state.
- **Async (production default):** a background thread runs
  `run_claimed_llm_generation`; the response reflects the just-persisted
  claim (`status="running"`, `workflow_phase="llm_generation"`) — never a
  hardcoded guess, since it is read back from the `job` the claim itself
  returned.

**Winner:** `202` with `{job_id, status, workflow_phase, url}` — `status`/
`workflow_phase` are always the real, already-persisted values.

**Concurrent loser:** `claim_llm_continuation` fails to acquire `_RUN_LOCK`
→ `JobBusy` → route returns `409`; no worker is spawned, no provider call is
made, no ledger entry is added. Proven at the route level
(`test_route_level_concurrent_continue_returns_409_for_the_loser`) and at
the service level with cost/ledger assertions
(`test_two_concurrent_claims_yield_one_winner_no_duplicate_cost_or_calls`).
The brief allows either a `409` or an idempotent current-state `200`; this
implementation uses `409` uniformly, matching the convention every other
mutating endpoint in this codebase (`replace-db`, `replace-llm`, `retry`,
`branch`) already uses for the identical `JobBusy`/`JobConflict` situation —
introducing a second, differently-shaped "success" response only for this
one endpoint would be a new, untested asymmetry for no functional gain, so
this report treats "a clear `409`" as the chosen branch of that either/or,
not a partial implementation.

**Repeat after completion:** `workflow_phase == "complete"` → `JobConflict`
→ `409`, ledger/cost unchanged — proven by
`test_repeated_continue_after_completion_cannot_replay`.

**Resume:** identical code path as a fresh claim (§3's eligibility rule);
`test_interrupted_slot_retry_with_later_queued_slots_stays_resumable` proves
the brief's exact required sequence: claim → simulate one `interrupted` +
two never-reached `queued` slots → `retry_slot` the interrupted one → phase
still `llm_generation`, both `queued` slots still visible as pending → a
further `continue_llm_generation` call resumes and finishes all three, no
duplicates → phase becomes `complete` only then.

**Async claim visible before `202`, even with a blocked worker:**
`test_async_claim_persisted_before_202_and_get_observes_it_with_worker_blocked`
monkeypatches `threading.Thread.start` to a no-op that never actually runs
the worker, then asserts the `202` body and an immediate follow-up `GET`
both already show `status="running"`, `workflow_phase="llm_generation"` —
proving the response/claim visibility never depended on the worker making
any progress at all.

## 5. Phase-aware finalisation and retry

```python
pending = [s for s in llm_slots if s.status in ("queued", "running", "interrupted")]
...
job.workflow_phase = "llm_generation" if pending else "complete"
```

This single `pending` set — already computed for `job.status` — now also
drives `workflow_phase`, so the two can never read as contradictory
signals computed by different rules. Concretely:

- **`partial` + `llm_generation`**: a slot was retried successfully but
  later planned slots are still `queued` — `status="partial"` (per the
  pre-existing status rule: `pending` non-empty), `workflow_phase=
  "llm_generation"` (same `pending` set) — proven by
  `test_interrupted_slot_retry_with_later_queued_slots_stays_resumable`.
- **`interrupted` + `llm_generation`**: unchanged, `recover_on_start` never
  touches `workflow_phase` — it was already `llm_generation` from the
  claim, and stays so.
- **A ceiling that stops traversal while a `queued` slot remains**:
  `status="cost_ceiling"`, `workflow_phase="llm_generation"` (that slot is
  in `pending`) — proven by
  `test_cost_ceiling_before_all_planned_slots_stays_llm_generation_not_complete`,
  which also proves the more subtle half of this rule: a **slot** already
  marked `cost_ceiling` (as opposed to one still `queued`) is a *terminal*
  per-attempt outcome for phase purposes — the automatic traversal does not
  silently re-attempt it even after the ceiling is raised (unchanged,
  pre-existing `retry_slot`-only-resolves-cost_ceiling-slots rule); once the
  one remaining genuinely-`queued` slot is picked up and every slot has been
  attempted at least once, `workflow_phase` becomes `complete` even while
  that one cost_ceiling'd slot is still individually unresolved and
  `job.status` still reads `cost_ceiling` — resolving it via an explicit
  `retry_slot` call then also brings `job.status` itself to `completed`.
- **A fully traversed batch with one genuinely rejected slot**: `status=
  "partial"`, `workflow_phase="complete"` (nothing left in `pending` — a
  `"failed"` slot was attempted, not skipped) — proven by
  `test_fully_traversed_batch_with_a_rejected_slot_is_complete_with_partial_status`.
- **Manual replacement during `db_review`**: unchanged from WP27's own fix —
  `replace_via_llm` still skips `_finalise` entirely when `was_db_review` is
  true (now read from `job.workflow_phase` directly), refreshing only the
  cost/telemetry summary.
- **Manual replacement after completion, or on a paused `llm_generation`
  job**: `_finalise` still runs, but since the OTHER slots' statuses are
  untouched by a single accepted-slot content swap, `pending` reflects
  exactly what it did before the call — phase never spuriously flips either
  direction. Proven by `test_db_review_regressions_remain_green_with_persisted_phase`
  for the `db_review` case; the `complete`/paused cases follow from the same
  `pending`-recomputation logic and are exercised incidentally throughout
  the rest of the suite (e.g. `retry_slot` after full completion, which
  `test_wp18_persistence.py::test_partial_results_and_slot_retry` already
  covers end-to-end unchanged).

## 6. Frontend polling behavior

`examGen.isPollingStatus(status, phase)` now requires **both**
`status === "running"` and `phase === "llm_generation"` — `"queued"`
(`db_review`) never polls under any phase reading, and a paused
`llm_generation` job (`partial`/`interrupted`/`cost_ceiling`) does not poll
on its own; only actively resuming it (which flips `status` back to
`"running"`) does.

`handleContinue` applies the claim response's `status`/`workflow_phase`
to local state via an optimistic merge **before** any follow-up fetch — this
merge alone is what starts polling (the `useEffect` above re-evaluates on
every `job.status`/`job.workflow_phase` change), so it never depends on a
follow-up `GET` winning a scheduling race against the (already-started, by
now, thanks to §4's synchronous claim) worker. A full `GET` still follows
immediately after, since `continue-llm`'s own response body is intentionally
small (status-only, same shape as job creation's) and does not carry the
question list. Proven independent of the `GET`'s timing by
`applies the returned claimed state immediately, independent of a slow
follow-up GET` (the mocked `fetchJob` never resolves during the assertion
window; the UI still shows `"רץ"` from the merge alone).

A `409` response (someone else legitimately won the claim, or it already
finished) is handled distinctly from every other error: `handleContinue`
loads the current job via `fetchJob` instead of showing a fatal error
banner — proven by `a concurrent/already-claimed (409) response loads the
current job instead of showing a fatal error` (no `role="alert"` element
appears, and the job renders as its real, now-`running`, state). Any other
error status still shows the error banner normally.

A new "יצירת השאלות בבינה מלאכותית הופסקה" banner
(`data-testid="resume-banner"`) renders whenever `phase === "llm_generation"
&& status !== "running" && pending_llm_total > 0` — distinct from the
`db_review` banner (something already ran here, vs. nothing has run yet) —
offering the identical Continue action (same handler, same endpoint) to
resume. The existing per-slot retry mechanism (`SlotChips`' "נסה שוב"
buttons) remains available alongside it, unchanged, for resolving one
specific failed/interrupted/cost_ceiling slot independently of resuming the
whole remaining batch.

## 7. Existing tests updated for the new contract (not worked around)

Three pre-existing WP27 backend tests needed updates because
`workflow_phase` genuinely stopped being a pure `status` derivation:

- `test_branching_blocked_until_llm_phase_completes` (kept, renamed
  implicitly by its content, not its name) — its synthetic status mutations
  (`running.status = "running"`, `interrupted.status = "interrupted"`) now
  also set `workflow_phase = "llm_generation"` explicitly, since a real code
  path always sets both together and a test simulating that state must too.
- `test_legacy_job_json_without_workflow_phase_field_loads_and_maps_safely`
  → renamed
  `test_workflow_phase_is_now_persisted_and_legacy_json_still_loads_safely`
  and rewritten: its original core assertion
  (`"workflow_phase" not in raw_before`) proved the *opposite* of WP27R's
  new contract on purpose — WP27's field genuinely was never persisted; the
  rewrite proves the new contract instead (the field *is* now persisted for
  a fresh/mutated job; a job.json with the field stripped out, simulating a
  genuinely pre-WP27R file, still loads safely with no rewrite-on-read).

One pre-existing frontend test
(`polls a running job to completion and shows accepted partials
immediately`) needed its mocked intermediate `"running"` view to also carry
`workflow_phase: "llm_generation"`, since `isPollingStatus` now needs both
fields and the test's `makeView()` helper does not set one by default.

No other pre-existing test in either suite needed any change.

## 8. Tests and exact results

### Backend

New: `backend/tests/test_wp27r_persisted_phase_and_recovery.py` — 15 tests
covering every numbered item in the brief's backend test list. Updated: 3
tests in `test_wp27_two_phase_db_review.py` (§7). All pass.

Full-suite result (`cd backend && env -u OPENAI_API_KEY caffeinate -i
../.venv/bin/python -m pytest -q`, foreground, actively awaited):

```
278 passed in 241.72s (0:04:01)
```

(263 pre-existing WP27/earlier tests, all still green + 15 new WP27R tests.)

### Frontend

New: `frontend/src/components/ExamGenerationSection.wp27r.test.jsx` — 9
tests covering the brief's frontend test list. Updated: 1 test in
`ExamGenerationSection.test.jsx` (§7); 1 test in `examGen.test.js`
(two-parameter `isPollingStatus` contract).

Full-suite result (`cd frontend && npm test -- --run`, foreground):

```
Test Files  7 passed (7)
     Tests  131 passed (131)
```

(122 pre-existing WP27/earlier tests, all still green + 9 new WP27R tests.)

Production build (`cd frontend && npm run build`, foreground):

```
✓ 1261 modules transformed.
✓ built in 3.12s
```

No warnings or errors beyond the pre-existing, unrelated `caniuse-lite`
staleness notice.

## 9. Confirmation of zero live/provider calls

- No `OPENAI_API_KEY` was read, exported, or referenced with a real value —
  `llm_ready`/`monkeypatch.delenv` fixtures use only in-process sentinel
  strings, matching the pre-existing suite exactly.
- No backend or frontend dev server was started.
- Every backend test runs with real sockets hard-blocked (autouse
  `_no_network` fixture, `socket.socket.connect`/`connect_ex` monkeypatched
  to raise) — `test_wp27r_persisted_phase_and_recovery.py` carries its own
  copy of this fixture, matching every WP19+ test file's convention.
- No frontend test issued a real `fetch` — `@/lib/examApi.js` is fully
  mocked (`vi.mock`) in every component test.

## 10. Secret / artifact / database / submodule audit

- `git diff --stat` (this session, outer repo only): 10 files changed
  (`SETUP.md`, `WPs/ARCHITECT_HANDOFF.md`, 3 backend `src` files, 1 backend
  test file, 4 frontend files) plus 3 new files (this report, the WP27R
  brief, and 2 new test files) — no file under `exam_generator/`, no
  `backend/src/database/app.db`, no `.env*`, no
  `../exam_generator_pre_submodule_backup/`.
- `git -C exam_generator status --short` → clean; `git submodule status` →
  still pinned at `d20c46bbb332e4d40f735e843d31113176b755e5` (unchanged).
- Grepped the full diff for `OPENAI_API_KEY\s*=`, `sk-[a-zA-Z0-9]{10,}`,
  `password\s*=`, `secret\s*=` — no match.
- Neither `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md` nor
  `WPs/PRE_WP26R_AUDIT.md` was read, opened, or modified this session.
- `WPs/WP27_ARCHITECT_REPORT.md` (the historical WP27 report) was read for
  context but not rewritten — its documented limitations remain visible as
  the record of what motivated this WP, per the brief's explicit instruction.

## 11. Final SHAs / statuses and push outcome

Before this WP's commit:

```
$ git rev-parse HEAD
53177b87ab2d3f914f83a3a22bc3fa0c7ed74c45
$ git rev-parse origin/main
53177b87ab2d3f914f83a3a22bc3fa0c7ed74c45
$ git submodule status
 d20c46bbb332e4d40f735e843d31113176b755e5 exam_generator (heads/main)
$ git -C exam_generator rev-parse HEAD
d20c46bbb332e4d40f735e843d31113176b755e5
$ git -C exam_generator status --short
(clean)
```

Committed as `679a3812ef245fe9590262df18b435f1909b861b`
(`WP27R: harden staged continuation recovery`, 14 files changed). Pushed to
`origin/main` after confirming a safe fast-forward (`git fetch origin` +
`git merge-base --is-ancestor origin/main HEAD` — the branch was exactly 1
commit ahead, no divergence), no force, no rewrite. Final state:

```
$ git rev-parse HEAD
679a3812ef245fe9590262df18b435f1909b861b
$ git rev-parse origin/main
679a3812ef245fe9590262df18b435f1909b861b
$ git status --short
?? WPs/PRE_WP25_LATEST_EXAM_REVIEW.md
?? WPs/PRE_WP26R_AUDIT.md
$ git submodule status
 d20c46bbb332e4d40f735e843d31113176b755e5 exam_generator (heads/main)
$ git -C exam_generator rev-parse HEAD
d20c46bbb332e4d40f735e843d31113176b755e5
$ git -C exam_generator status --short
(clean)
```

`HEAD == origin/main`; the only remaining outer untracked files are the two
pre-existing owner-owned PRE reports; the generator submodule is unchanged
and clean.

## 12. Remaining limitations / owner decisions

1. **Concurrent-loser response shape.** This implementation always returns
   `409` for a losing concurrent Continue request (§4). The brief allows an
   alternative idempotent `200` "current state" response instead; `409` was
   chosen for consistency with every other mutating endpoint's existing
   `JobBusy`/`JobConflict` convention. If the owner specifically wants a
   `200` here, it is a small, isolated route-level change.
2. **A cost-ceiling'd slot is not auto-retried by resume**, only a genuinely
   untouched (`queued`) one is (§5) — unchanged, pre-existing behavior
   carried forward deliberately, not a WP27R gap: resolving an individual
   `failed`/`cost_ceiling`/`interrupted` slot has always been
   `retry_slot`'s job, separate from the automatic batch. Documented
   explicitly here since it is easy to assume "resume" means "retry
   everything not accepted."
3. **The "editable active job" concept remains frontend-only**, as WP27's
   own report already documented (§13 item 2 there) — unchanged by WP27R;
   `claim_llm_continuation` enforces everything backend-checkable (phase,
   pending work, lock availability), not a server-side notion of which job
   a particular user currently has "active."
4. **Async double-click race at the HTTP-response layer** for the *worker
   spawn* (not the claim) still exists in the sense that two requests could
   theoretically both reach the "spawn a thread" step in rapid succession —
   but this is now structurally impossible for two *successful* claims,
   since the second one's `claim_llm_continuation` call fails at the lock
   acquisition before ever reaching thread-spawning code. Only one thread is
   ever spawned per successful claim, by construction.
