# WP27R — Persisted Phase, Atomic Continue, and Recovery

## Purpose

Correct the production-state gaps identified in `WPs/WP27_ARCHITECT_REPORT.md` without changing WP27's user-facing two-phase design.

WP27 correctly introduced DB-only review followed by explicit LLM continuation, but its derived `workflow_phase` and asynchronous Continue handoff leave two unsafe edge cases:

1. A successful `202` response can be followed by an immediate read of the old `queued` state, causing the frontend to stop polling while generation runs in the background.
2. Retrying an interrupted slot while later planned LLM slots remain `queued` can set the operational status to `partial`; the derived phase then becomes `complete`, potentially hiding Continue and stranding the untouched planned slots.

WP27R must make workflow phase persistent and make the Continue claim visible before the HTTP request returns.

This is an **outer `questions-db` repository** work package. Do not modify the `exam_generator` submodule.

## Fixed owner/architect decisions

- Keep WP27's two-phase behavior unchanged:
  - `db_review`: DB questions are selected, reviewable, replaceable, and exportable; automatic LLM generation has not started.
  - `llm_generation`: the planned LLM batch has been claimed, is running, or needs recovery/resumption.
  - `complete`: the planned automatic batch has finished traversing its intended work, or no LLM questions were requested.
- `workflow_phase` must now be a persisted job field. Operational `status` remains a separate concept.
- Continue must be claimed atomically and persisted **before** the async endpoint returns `202`.
- The frontend must begin/continue polling from the persisted claim and must not depend on a lucky background-thread scheduling order.
- A second concurrent/repeated Continue must never start another batch. It should receive an honest current-state response or a clear conflict, not another misleading “started” response.
- If a batch is interrupted, it remains in `llm_generation` until its planned work is resolved according to the existing retry/resume model.
- Retrying one interrupted slot must not mark the workflow complete or strand later queued planned slots.
- Keep all WP27 contracts for numbering, exports, replacements, semantic history, cost accounting, exclusions, naming, persistence, and branching.
- No live provider call is authorized in this WP.

## Starting state and boundaries

Before editing, inspect and record:

```bash
git rev-parse HEAD
git rev-parse origin/main
git status --short
git submodule status
git -C exam_generator rev-parse HEAD
git -C exam_generator status --short
```

Expected WP27 baseline:

- Outer `HEAD == origin/main == a13b60d24eff0fe025ff6793bc445c2b02bb1298`.
- Generator pin: `d20c46bbb332e4d40f735e843d31113176b755e5`.
- Generator clean and unchanged.
- The only expected untracked files are:
  - `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`
  - `WPs/PRE_WP26R_AUDIT.md`

If the actual baseline differs, document it. Stop before editing if unrelated tracked drift is present or owner work cannot be preserved safely.

Do not modify, stage, delete, or commit:

- anything inside `exam_generator/` or the generator gitlink;
- `backend/src/database/app.db`;
- real job/audit artifacts;
- `.env*`, credentials, prompts, or provider responses;
- either owner-owned `PRE_*.md` report;
- `../exam_generator_pre_submodule_backup/`.

Do not start the backend/frontend servers. Do not read or require a real `OPENAI_API_KEY`.

## Required corrections

### 1. Persist `workflow_phase`

Add `workflow_phase` to the persisted `Job` model with exactly these values:

- `db_review`
- `llm_generation`
- `complete`

Validate it on load and save. Do not derive the phase afresh on every API read from `status` alone.

Required transitions:

| Event | Resulting phase |
|---|---|
| Create job with planned LLM count > 0 | `db_review` |
| Create job with planned LLM count = 0 | `complete` |
| Successful atomic first Continue claim | `llm_generation` |
| Process/server interruption during batch | remain `llm_generation` |
| Resume/retry while untouched planned slots remain | remain `llm_generation` |
| Planned automatic batch traversal finishes | `complete` |
| Manual replacement after completion | remain `complete` |
| Manual replacement during DB review | remain `db_review` |

Operational `Job.status` continues to report `queued`, `running`, `interrupted`, `partial`, `completed`, `cost_ceiling`, or other existing outcomes. A workflow phase must not erase that detail.

Do not mechanically define every `partial`, `failed`, or `cost_ceiling` job as workflow-complete. Decide completion from whether the planned automatic batch was actually traversed/closed, not from a one-to-one status lookup. In particular:

- `partial` can coexist with `llm_generation` when later planned slots were never reached;
- `interrupted` must coexist with `llm_generation`;
- a terminal batch that attempted all intended slots may have phase `complete` even when some individual slots remain rejected/retryable;
- a ceiling that stops traversal while planned queued slots remain must not silently pretend those slots were completed.

If another small persisted marker is required to distinguish “batch traversal finished” from “stopped before remaining queued work,” add it narrowly and document it. Do not overload public question counts or source origin.

### 2. Backward-compatible loading

Legacy job JSON has no `workflow_phase`. `Job.from_dict` must infer a safe value only for that legacy-loading case:

- no planned/pending LLM work and terminal historical job → `complete`;
- legacy `queued` job with planned LLM work → `db_review`;
- legacy `running`/`interrupted` job with planned LLM work → `llm_generation`;
- other legacy combinations must use a conservative rule that never strands queued planned work or makes a historical completed job editable.

Merely loading a legacy job must not rewrite its file. The persisted field should appear when that job is next legitimately mutated and saved.

If the project uses a schema version, make the smallest backward-compatible change. Do not run a bulk/destructive migration and do not modify real artifacts.

The existing `workflow_phase(job)` helper may remain as an accessor, but it must return/validate the persisted value rather than recomputing the phase from `status` for new WP27R jobs.

### 3. Split continuation into atomic claim and claimed worker

Refactor the continuation boundary so the route can persist a claim synchronously before starting background generation.

The logical operations should be equivalent to:

1. `claim_llm_continuation(job_id)`
   - acquire the established in-process and per-job/file locking protection;
   - load the current job;
   - confirm it is eligible (`db_review`, or a recoverable `llm_generation` interruption with remaining planned work);
   - perform readiness/pricing/API-key checks before the first claim from `db_review` and before any provider call;
   - on readiness failure, leave the job byte-for-byte in `db_review`, charge nothing, and make no provider call;
   - persist `workflow_phase = "llm_generation"` and an honest running/claimed operational state;
   - persist before returning success;
   - produce an unambiguous result/token/state for exactly one worker.
2. `run_claimed_llm_generation(...)`
   - run only after a successful claim;
   - process only eligible, not-yet-accepted planned slots;
   - reuse the existing generation/review/cost/context pipeline;
   - never repeat accepted work;
   - persist progress and final workflow/operational state;
   - release locks cleanly on every path.

Function names may differ. Preserve clean service boundaries and avoid duplicating `_run_llm_slots` logic.

The implementation must not create a gap where another mutation can alter the same job after claim but before the worker obtains protection. Inspect all existing locks and replacement/retry endpoints; use the smallest robust design rather than relying on thread scheduling.

If worker/thread creation fails after the claim was persisted, immediately persist a recoverable `interrupted` state while keeping `workflow_phase = "llm_generation"`. Never leave a permanently fake `running` job.

### 4. Honest and idempotent Continue endpoint

For asynchronous production mode:

- Perform the claim synchronously inside the request lifecycle.
- Return `202` only after the job has been persisted as `llm_generation` with a polling status.
- Include the actual persisted `status`, `workflow_phase`, `job_id`, and result URL.
- Start exactly one background worker for the successful claim.

For repeated/concurrent requests:

- exactly one request may win a fresh claim;
- a loser must not spawn a worker;
- return either a clear `409` or an idempotent current-state response with semantics documented and tested;
- never let two requests both claim that they freshly started work;
- never duplicate provider calls, costs, ledger entries, or slot generation.

For synchronous test mode, reuse the same claim and worker functions; do not maintain a separate state machine.

For recovery:

- the same endpoint may resume a persisted `llm_generation` job only when it is genuinely interrupted/recoverable and no worker holds its lock;
- accepted slots remain accepted and are never regenerated;
- remaining queued planned slots stay eligible;
- an interrupted individual slot follows the existing explicit retry rule unless the current established behavior intentionally includes it in resume—document and test the chosen rule.

### 5. Phase-aware finalisation and retry

Audit `_finalise`, `retry_slot`, `replace_via_llm`, recovery-on-start, and all other state-mutating paths.

Required behavior:

- Manual LLM replacement during `db_review` preserves `db_review` and does not consume planned B, as WP27 already fixed.
- Retrying one interrupted/rejected slot during `llm_generation` must not set `workflow_phase = "complete"` while later planned queued slots remain.
- If queued planned slots remain after a single-slot retry, preserve a recoverable operational state that still permits Continue/resume.
- Once automatic traversal genuinely finishes, set phase `complete` exactly once; subsequent slot retries/replacements do not reopen or replay the automatic batch.
- `_finalise` must not infer workflow completion merely because the current operation ended.
- Branching remains unavailable unless `workflow_phase == "complete"` and the existing branchable-status rules also pass.

Explicitly test the previously untested sequence:

1. Start a planned multi-slot batch.
2. Simulate interruption with one interrupted slot and one or more later queued planned slots.
3. Retry the interrupted slot.
4. Confirm phase is still `llm_generation`, remaining queued slots are visible as pending work, and Continue/resume can process them exactly once.
5. Confirm the final phase becomes `complete` only after planned traversal ends.

### 6. Reliable frontend polling

Correct the production race in `ExamGenerationSection.jsx` and the API/state helpers.

After a successful Continue response:

- immediately use the returned persisted `running`/`llm_generation` state;
- start polling without requiring an immediate follow-up GET to win a scheduling race;
- keep the Continue control disabled while claimed/running;
- if a follow-up GET occurs, it must observe the persisted claim;
- refresh/reopen during generation must recognize `llm_generation` and resume polling when operational status is pollable;
- interrupted/recoverable state must show the correct recovery action rather than the DB-review banner;
- completion returns to the established final-exam UI.

Do not restore `queued` as a globally pollable status: `queued + db_review` is intentionally a long-lived resting state. Polling must consider workflow phase and operational status together.

Handle `409` or an idempotent already-running response by loading/polling the existing job rather than showing a false fatal error when another request legitimately won the claim.

### 7. Preserve all unaffected WP27 behavior

Do not regress:

- no readiness/API/provider work during initial DB selection;
- A=0/B>0 empty DB review;
- B=0 immediate completion;
- manual LLM replacement before Continue does not consume planned B;
- both replacement buttons on accepted questions;
- compact interim numbering and canonical final numbering;
- pending slots excluded from views, exports, analytics, and semantic context;
- current accepted same-category questions and displaced-LLM history included in context;
- shared cumulative cost ceiling and immutable ledger;
- exclusion workbook and global unique DB allocation;
- saved names/history/snapshots and read-only historical exams;
- existing export schemas;
- terminal cost reporting without content/secrets;
- generator isolation.

## Required tests

### Backend focused tests

Add or extend tests proving:

1. New mixed job persists `workflow_phase = db_review`; B=0 persists `complete`.
2. Serialized job JSON contains the phase for new/mutated jobs.
3. Legacy JSON without the field loads safely without rewrite and gains the field only on legitimate save.
4. Async Continue claim is persisted as `llm_generation`/running before the route returns `202`.
5. A GET immediately after the `202` observes the claimed state, even when the fake worker is deliberately blocked from starting.
6. Two concurrent Continue requests yield one claim and one worker; the loser is honest; costs/provider calls/ledger entries remain single.
7. Repeated Continue after completion cannot replay generation.
8. Readiness failure leaves exact DB-review state and zero cost/calls.
9. Worker-start failure produces recoverable `interrupted + llm_generation`.
10. Restart recovery preserves `llm_generation` and accepted slots.
11. The interrupted-slot-retry-plus-later-queued-slots sequence remains resumable and completes without duplicates.
12. Automatic traversal sets `complete` only at the correct boundary.
13. A normal fully traversed batch with rejected/retryable slots has the documented phase/status combination.
14. Cost-ceiling-before-all-planned-slots behavior is explicit, consistent, and cannot strand work behind a false `complete` phase.
15. Branching remains blocked before workflow completion and unchanged afterward.
16. DB-review manual replacement, history, context, numbering, exports, exclusions, and cost regressions remain green.

All provider behavior must use deterministic fakes. Hard-block network access.

### Frontend focused tests

Add or extend tests proving:

- Continue uses the returned claimed state and starts polling without a race-prone immediate GET dependency;
- the button cannot double-submit;
- a concurrent/already-running response transitions into the existing polling view;
- refresh/reopen of `llm_generation + running` polls;
- `queued + db_review` does not poll;
- `partial/interrupted + llm_generation` with remaining planned work does not render as complete DB review and exposes the correct recovery path;
- completion stops polling and restores final-exam controls;
- existing WP27 UI, replacement, export, naming, and history tests remain green.

## Verification protocol

Run focused tests while implementing. Once focused tests pass, run each full suite/build once.

Every long command must stay in the foreground and be actively awaited in the same Claude turn. Do not use `run_in_background`, `&`, detached commands, or unattended polling. On macOS, use `caffeinate -i` and a tool timeout of at least 15 minutes.

Example backend command; adapt only the interpreter path if repository inspection requires it:

```bash
cd backend
set -o pipefail
env -u OPENAI_API_KEY caffeinate -i ../.venv/bin/python -m pytest -q 2>&1 | tee /tmp/wp27r-backend.log
```

Then run in `frontend`, in the foreground:

```bash
npm test -- --run
npm run build
```

Record actual exit codes and counts. Do not infer success from partial output. If a command is killed or its result is lost, stop and report; do not promise automatic resumption. Allow at most two bounded repair-and-rerun passes before reporting a blocker.

No live provider test, API key, or running application server is required.

## Documentation and report

Save this brief inside the repository as:

`WPs/WP27R_Persisted_Phase_Atomic_Continue_And_Recovery.md`

Update `SETUP.md` and `WPs/ARCHITECT_HANDOFF.md` where necessary. Preserve the historical WP27 report; do not rewrite it to hide the limitations that motivated WP27R.

Write the final architect report to:

`WPs/WP27R_ARCHITECT_REPORT.md`

The report must explain:

- files changed;
- persisted phase schema and legacy inference;
- exact phase/status transition table;
- claim/worker locking and failure recovery;
- HTTP behavior for winner, concurrent loser, repeat, and resume;
- frontend polling behavior;
- interrupted retry and cost-ceiling behavior;
- tests and exact results;
- zero live/provider calls;
- secret/artifact/database/submodule audit;
- final SHAs/statuses and push outcome;
- any remaining limitation or owner decision.

## Git completion

Before staging, inspect the complete diff and scan for credentials, real artifacts, DB changes, generator changes, and unrelated files.

Commit the intended outer-repository changes as:

```text
WP27R: harden staged continuation recovery
```

Claude may push normally to outer `origin/main` only after fetching and proving a safe fast-forward/non-force update. Never force-push or rewrite history. Do not push or alter the generator.

At completion, report:

```bash
git rev-parse HEAD
git rev-parse origin/main
git status --short
git submodule status
git -C exam_generator rev-parse HEAD
git -C exam_generator status --short
```

The only permitted remaining outer untracked files are the two pre-existing owner-owned PRE reports. All WP27R files must be committed.

## Stop conditions

Stop and report before proceeding if:

- the correction appears to require a generator-submodule change;
- the implementation cannot persist the claim before returning `202`;
- exactly-once slot generation cannot be preserved across concurrent requests or restart;
- legacy jobs require destructive/bulk migration;
- stable identities, numbering, exports, semantic history, or cost ledger would be weakened;
- a DB schema migration, dependency change, real API call, API-key access, or server start appears necessary;
- unrelated tracked drift cannot be preserved safely;
- verification can only be performed through an unattended background process;
- more than two bounded repair passes are required.

Do not silently weaken the contract to avoid a stop condition.
