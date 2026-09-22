# WP27 — Two-Phase DB Review and LLM Generation

## Purpose

Change exam creation into two explicit, persisted phases:

1. Select and review the requested database questions without automatically generating any LLM questions.
2. Generate the originally requested LLM questions only after the user explicitly approves the current database selection.

This prevents paid LLM questions from being grounded against database questions that the user is about to replace.

This is an **outer `questions-db` repository** work package. Do not modify the `exam_generator` submodule.

## Confirmed owner decisions

These decisions are binding:

- Creating a mixed exam selects only the requested DB questions first. It must not call the generator, reviewer, pricing readiness, or provider.
- The DB-review state is persisted, survives refresh/restart, is reopenable by exam name, editable, and exportable.
- The waiting state must be clearly labeled in Hebrew, for example: `ממתין לאישור שאלות המאגר`.
- During DB review, both replacement buttons remain available on every accepted question:
  - `החלף בשאלה מהמאגר`
  - `צור שאלה אחרת`
- Pressing `צור שאלה אחרת` during DB review intentionally permits one paid LLM operation. It does **not** consume or reduce any originally planned LLM slot.
- Replacements may freely change the eventual DB/LLM source balance. Do not recompute, enforce, or prominently display a “current balance.” The A/B values are the original creation plan only.
- The automatic LLM batch begins only through an explicit button such as:

  `המשך ליצירת שאלות חדשות באמצעות בינה מלאכותית`

- Interim DB-review displays and exports contain only currently accepted questions, compactly numbered `1..N` in canonical category order. Never display/export empty LLM placeholders.
- When continuation starts, assign the complete exam's final numbering in canonical category order and preserve the application's established final-exam behavior.
- Internal `instance_id`/slot identity must remain stable even when public question numbers change.
- A DB-review job cannot be branched. Branching becomes available only after the originally planned LLM phase is complete.
- If every requested LLM count is zero, the job completes immediately and no Continue button appears.
- If DB count is zero but LLM count is positive, persist and show an empty DB-review screen with the Continue button.
- Continue is exactly-once/idempotent. Double-clicks, repeat requests, concurrent requests, refreshes, and restarts must not duplicate generation.
- API-key/provider/pricing readiness is checked only immediately before a paid LLM operation: a manual LLM replacement or the explicit Continue action. Initial DB selection must work without `OPENAI_API_KEY`.
- Pending planned LLM slots are not questions and must never enter semantic similarity context. Each generation call receives all other currently accepted questions in the category, earlier accepted questions from the same continuation run, and retained displaced-LLM history.

## Starting state and repository boundaries

Before editing, inspect and record:

```bash
git rev-parse HEAD
git status --short
git submodule status
git -C exam_generator rev-parse HEAD
git -C exam_generator status --short
```

Expected baseline:

- Outer `main`/`origin/main`: `8302c43498b6310e18ab667ef5e1d8ec02941640`.
- Generator pin: `d20c46bbb332e4d40f735e843d31113176b755e5`.
- Generator clean and unchanged.
- The only expected owner-owned untracked files are:
  - `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`
  - `WPs/PRE_WP26R_AUDIT.md`

If the actual baseline differs, document it. Stop before editing if there is unrelated tracked drift or if preserving owner work is uncertain.

Do not modify, stage, delete, or commit:

- anything inside `exam_generator/`;
- the generator gitlink;
- `backend/src/database/app.db`;
- real job artifacts or live audit data;
- `.env*` or credentials;
- either owner-owned `PRE_*.md` file;
- `../exam_generator_pre_submodule_backup/`.

No live provider/API calls are authorized in WP27. No API key or running backend/frontend server is required.

## Required behavior

### 1. Persist an explicit workflow phase

Add a small, explicit, backward-compatible workflow state rather than inferring the phase from slot contents.

Recommended model:

- `db_review` — initial database selection has been persisted and automatic LLM generation has not started.
- `llm_generation` — the explicit continuation has been claimed and planned LLM generation is running or recoverably interrupted.
- `complete` — the originally planned LLM phase is finished, or there were no planned LLM questions.

Names may differ if the existing model makes another representation cleaner, but the API must expose an unambiguous phase/status. The user-facing waiting label should be `ממתין לאישור שאלות המאגר`.

Keep operational outcomes such as partial failure, cost ceiling, interruption, and retryability available. Do not flatten them into the workflow phase.

Legacy persisted jobs without the new field must load safely and retain their existing behavior. Infer their phase conservatively from their existing terminal/running status and persisted slots; do not rewrite historical files merely by reading them.

### 2. Initial creation performs DB selection only

For a new request:

1. Validate the name, requested counts, cost ceiling, category names/order, and exclusion workbook using the current WP26R rules.
2. Run the existing global unique DB allocation for all categories.
3. Persist the original per-category plan, including the requested DB count and requested LLM count.
4. Persist accepted DB questions and an equivalent representation of planned-but-not-yet-generated LLM work.
5. Return the DB-review result immediately.

It is acceptable to persist pending LLM slots or a separate planned-count structure. Whichever design is used:

- pending work must have stable identity;
- it must not be rendered/exported as a question;
- it must not count as a failure, attempt, retry, or accepted question;
- it must not enter semantic context;
- continuation must be able to claim every planned item exactly once.

The creation route must not import/instantiate the provider unnecessarily, inspect `OPENAI_API_KEY`, perform pricing-readiness checks, render prompts, create generator audits, append a cost-ledger item, or call the LLM adapter.

Edge cases:

- If total planned LLM count is `0`, persist a completed job immediately.
- If total DB count is `0` and planned LLM count is positive, persist `db_review` with zero accepted questions and expose Continue.
- Existing feasibility/exclusion errors for DB allocation must remain precise and happen before a job is presented as successfully created.

### 3. Add one explicit continuation operation

Add a dedicated endpoint, for example:

```text
POST /api/exam-jobs/<job_id>/continue-llm
```

Use the route naming conventions already present in the application.

The operation must:

- verify that the selected job is the editable active job;
- verify it is in `db_review` and has planned LLM work;
- run readiness/pricing/API-key checks before provider calls and before irreversibly leaving a retryable waiting state;
- atomically claim the transition so two requests cannot both start the batch;
- persist the claim before the first provider call;
- generate only the originally planned pending LLM items;
- use canonical category order and sequential within-category generation;
- use the existing generation/review/retry/cost/telemetry pipeline;
- persist after each meaningful step so interruption recovery remains honest;
- never regenerate an item already accepted by this continuation;
- finish in the appropriate existing completed/partial/cost-ceiling outcome while exposing workflow completion clearly.

Idempotency rules:

- A double-click must create one generation run, not two.
- A concurrent second request while generation is active must return the current safe state or a clear conflict, never start another run.
- A request after the continuation has already started/completed must not reset or replay the planned batch.
- A readiness failure before any provider call must leave the job in `db_review`, with the Continue action safely available after the environment is fixed.
- Restart/interruption behavior must not convert an already-claimed item into duplicate paid generation. Reuse the existing interrupted/retry model where possible and document the precise recovery contract.

### 4. Preserve manual replacement behavior during DB review

Both existing replacement operations must work for every accepted current question during `db_review`.

`replace_from_db`:

- uses the existing DB selection rules;
- honors the uploaded exclusion workbook;
- excludes DB questions already in the exam;
- preserves stable slot/instance identity;
- makes no provider call and adds no LLM cost;
- does not add the displaced DB question to semantic history.

`replace_via_llm`:

- performs exactly the existing paid generate-review operation;
- checks readiness only when invoked;
- preserves the old question on failure;
- on success, keeps the job in `db_review`;
- does not consume/decrement any originally planned LLM item;
- accumulates attempts and cost in the same immutable ledger/telemetry used elsewhere;
- adds a displaced question to `category_history` only when that displaced question is LLM-origin, preserving the established rule.

Do not enforce the original A/B balance after any replacement.

### 5. Correct semantic context at continuation time

For each planned LLM question, pass the generator:

- every other currently accepted question in the same category, regardless of current origin;
- any earlier accepted planned LLM question generated during this continuation;
- all retained displaced-LLM questions in that category's semantic history.

Do not pass:

- planned pending placeholders;
- displaced DB questions;
- questions from other categories;
- duplicate synthetic representations introduced only by renumbering.

Changing a public number must not erase or fragment semantic history. Preserve repeated historical public numbers where the established history contract requires it.

### 6. Cost and retry accounting

- Initial DB-only creation costs exactly `$0.00` and produces no attempt ledger entries.
- Manual LLM replacements before Continue accumulate normally.
- Continue uses the same job-level cumulative cost ceiling and remaining budget; it does not receive a fresh budget.
- Failed paid attempts remain charged and visible.
- Planned pending items are not counted as attempts/retries/failures before generation begins.
- Existing backend terminal summaries must continue after each paid operation and after the automatic continuation run, with cumulative cost, remaining ceiling, accepted/failed counts, retry counts, and pricing warnings.
- Do not print question text, prompts, responses, credentials, or secrets.

### 7. Numbering and stable identity

During `db_review`:

- Derive a public view of accepted current questions only.
- Order categories by `utils/category_order.py`.
- Compactly number visible/exported questions from `1` through the number currently accepted.
- Do not persist renumbering in a way that changes stable instance identity or corrupts replacement/history references.

When Continue is claimed:

- establish the final full-exam ordering/numbering in canonical category order;
- leave room/order for the planned LLM items according to the application's established category grouping;
- preserve final numbering through accepted generation, failures, retry, replacement, reload, and export;
- ensure every final accepted question has one unique public number.

If a continuation ends partially, preserve stable final slots and the existing retry behavior. Do not compact failed slots in a way that changes accepted questions' identities unexpectedly.

Document the exact difference between internal identity, interim display/export numbering, and final exam numbering in the report.

### 8. UI flow

After new-exam creation, show the persisted DB-review screen rather than an automatic progress run.

Required UI behavior:

- Keep canonical category headings and the existing question cards/source badges/analytics.
- Explain clearly in Hebrew that the DB questions have been selected for review and that automatic AI generation has not started.
- Show the planned number of new LLM questions.
- Show current cumulative LLM cost; normally `$0.00` unless the user manually generated replacements.
- Present the prominent Continue button:

  `המשך ליצירת שאלות חדשות באמצעות בינה מלאכותית`

- Keep both replacement buttons functional.
- Keep current full DOCX/full Excel/LLM-only Excel actions functional.
- Disable branching and explain that it becomes available after new-question generation is complete.
- Disable the Continue control while the request is being submitted/running and protect it against repeat clicks.
- Reopening the named exam or refreshing the page must restore the same review state.
- If A=0 and B>0, show an intentional empty-review state, not an error.
- If B=0, show the job as completed and omit Continue.
- Historical non-active jobs remain read-only according to the existing named-exam rules.

Do not introduce a visible “current DB vs LLM balance” requirement after replacements. It is not operationally meaningful.

### 9. Results, analytics, and exports

During DB review, all result statistics and exports operate only on accepted current questions:

- no pending placeholder rows/cards;
- category headings remain canonical;
- analytics ignore missing values as already specified;
- DB accuracy/distinction snapshots remain intact;
- manually generated LLM questions use the existing `N/A` analytics representation;
- full Excel keeps the established historical schema and includes all currently accepted questions;
- full DOCX contains all currently accepted questions;
- LLM-only Excel contains any currently accepted manually generated LLM questions;
- existing metadata columns/defaults remain unchanged.

After continuation, exports use the final complete-exam numbering and existing schemas.

Named-exam list/result APIs should distinguish:

- original planned total;
- current accepted count;
- pending planned LLM count;
- workflow phase/user-facing status.

Do not mislabel pending items as failed or retried.

### 10. Naming, persistence, history, branching, and exclusions

Preserve all WP26/WP26R behavior:

- structured/custom names and uniqueness rules;
- saved-job listing and reopening;
- immutable historical snapshots;
- active/editable vs historical/read-only boundaries;
- category aliases and canonical order;
- global unique DB allocation across all category-list memberships;
- exclusion workbook limit of 100 data rows;
- exclusion matching and persisted inherited exclusion set;
- DB replacement exclusions and no duplicate active DB IDs.

A job may remain in DB review indefinitely. It must remain saved and reopenable.

Branching:

- reject/disable branching from `db_review` or active `llm_generation` jobs;
- permit branching only from the established completed states;
- preserve the existing branch snapshot/ledger rules after completion.

## Tests

### Backend contract tests

Add focused tests that prove at least:

1. Mixed A/B creation with `OPENAI_API_KEY` absent and provider/network traps selects DB questions, persists `db_review`, costs zero, and makes zero provider/readiness/audit calls.
2. B=0 completes immediately with no continuation action.
3. A=0/B>0 creates a valid empty DB-review job.
4. Continue generates exactly the planned B items once.
5. Double and concurrent Continue requests cannot duplicate slots, calls, cost, or ledger records.
6. Readiness failure before a provider call leaves the job in retryable DB review and charges nothing.
7. A manual LLM replacement during DB review works and is charged but does not reduce planned B; Continue later still generates all B items.
8. Both replacement directions work during DB review and preserve stable identity.
9. Displaced-LLM vs displaced-DB history rules remain correct.
10. Pending planned items never enter semantic context; current accepted category questions and displaced-LLM history do.
11. Earlier questions accepted in the same continuation enter later same-category context.
12. Manual pre-Continue spending and automatic continuation share one cumulative ceiling.
13. Interim view/export numbering is compact and canonical, with no placeholder rows; final numbering is canonical and stable.
14. DOCX, full Excel, and LLM-only Excel behave correctly in both phases.
15. Reload/restart restores DB review without starting generation.
16. Awaiting/running jobs cannot be branched; completed jobs retain existing branch behavior.
17. Legacy persisted jobs without the new phase load safely.
18. Exclusion, global DB matching, analytics snapshot, named-history, replacement, cost-ledger, and export regressions remain green.

Use deterministic fake providers and hard network traps. No real provider calls.

### Frontend tests

Add focused component/integration tests proving:

- mixed creation opens the DB-review screen, not automatic LLM progress;
- waiting Hebrew status/message and planned count render correctly;
- canonical category headings and accepted DB cards render;
- both replacement controls remain usable;
- Continue is present only when appropriate and is protected from double submission;
- A=0/B>0 and B=0 states render correctly;
- refresh/reopen restores the state;
- interim exports and compact numbering exclude placeholders;
- cost display updates after a manual LLM action;
- branching is disabled until completion;
- completion restores the established full-exam controls;
- existing named-history, analytics, export, category-order, and replacement tests remain green.

## Verification protocol

Run focused tests while implementing, then run each full suite/build once after the focused tests pass.

All long commands must remain in the foreground and be actively awaited in the same Claude turn. **Do not** use `run_in_background`, `&`, detached commands, an unattended polling loop, or promise to resume automatically.

On macOS, use `caffeinate -i` and a tool timeout of at least 15 minutes. For example, adapt paths to the repository's actual virtual environment:

```bash
cd backend
set -o pipefail
env -u OPENAI_API_KEY caffeinate -i ../.venv/bin/python -m pytest -q 2>&1 | tee /tmp/wp27-backend.log
```

Then, in the frontend, run in the foreground:

```bash
npm test
npm run build
```

Record real exit codes and counts. Do not claim success from partial output. If a command is killed or its result is lost, stop and report that fact; do not start an overnight/background loop. Allow at most two bounded repair-and-rerun passes before reporting a blocker.

Do not start the application servers and do not run a live LLM test in WP27.

## Documentation and report

Save a copy of this brief as:

`WPs/WP27_Two_Phase_DB_Review_And_LLM_Generation.md`

Update the relevant setup/user documentation and `WPs/ARCHITECT_HANDOFF.md` with:

- the two-phase user flow;
- exact state transition/recovery semantics;
- readiness/API-key boundary;
- interim versus final numbering;
- manual-LLM-before-Continue behavior;
- branch restriction;
- A=0 and B=0 behavior.

Write the architect report to:

`WPs/WP27_ARCHITECT_REPORT.md`

The report must include:

- exact files changed;
- state/API/data-model changes;
- idempotency/concurrency mechanism;
- backward-compatibility behavior;
- numbering and export contract;
- context/history contract;
- cost/readiness behavior;
- tests and exact results;
- confirmation of zero live/provider calls;
- secret/artifact/database/submodule audit;
- final outer and generator SHAs/statuses;
- commit and push outcome;
- any known limitations or owner decisions required.

## Git completion

Before staging, inspect the complete diff and verify that no secret, environment file, real artifact, DB mutation, generator change, or owner-owned PRE report is included.

Commit the intended outer-repository work as:

```text
WP27: add staged DB review before LLM generation
```

Claude may push normally to outer `origin/main` only after fetching and verifying a safe fast-forward/non-force update. Never force-push or rewrite history. Do not push or modify the generator.

At completion, report:

```bash
git rev-parse HEAD
git rev-parse origin/main
git status --short
git submodule status
git -C exam_generator rev-parse HEAD
git -C exam_generator status --short
```

The expected final outer status may contain only the two pre-existing owner-owned untracked PRE reports. Everything created by WP27, including its brief and architect report, must be committed.

## Stop conditions

Stop and report before proceeding if any of these occurs:

- implementing the change appears to require modifying the generator submodule;
- the design cannot guarantee exactly-once/idempotent continuation;
- legacy jobs cannot be loaded safely without destructive migration;
- export compatibility or stable question identity cannot be preserved;
- a database schema migration or `app.db` mutation appears necessary without prior authorization;
- a dependency change, live API call, credential access, or server start appears necessary;
- unrelated tracked work is present and cannot be preserved safely;
- verification can only be completed via an unattended background task;
- more than two bounded repair passes are needed.

Do not silently weaken any confirmed contract to avoid a stop condition.
