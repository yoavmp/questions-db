# WP18 — Backend Exam-Generation Jobs

## Goal

Integrate the pinned generator production API into the outer `questions-db` backend: persistent sequential jobs, mixed DB/LLM assembly, retries/replacements, readiness, and complete cost accounting. **No frontend implementation and no live API calls.**

## Starting state and repository boundary

- Outer expected HEAD: `3dbe68e3c1b38b168ba549ab65b8ac33daa88f1e`.
- Generator local/remote expected HEAD: `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, clean.
- Expected outer dirt: advanced `exam_generator` gitlink plus duplicate untracked outer WP17G/WP17GR briefs and this WP18 brief. Stop for anything else.
- Verify `origin/main` contains `ea59cd8…`, then stage the submodule gitlink at that exact commit.
- Modify/commit only the outer repo. Do not modify/push the submodule or touch `../exam_generator_pre_submodule_backup/`.
- Remove the two duplicate untracked outer WP17G/WP17GR briefs only after verifying their authoritative copies are committed inside `exam_generator/WPs/`.

## 1. Install, adapter and readiness

- Replace the WP17 stopgap assembly with a thin adapter over `exam_generator.production.generate_exam_question`; no copied pipeline logic, subprocesses, WP runners or `sys.path` hacks.
- Add a documented root-based installation/start flow that installs backend dependencies plus the local submodule package reproducibly using its constraints. Report dependency conflicts before changing pins.
- Add a non-network startup/readiness service and endpoint. Check: generator import/version, submodule pin in development, required local `Data` readiness, 20/20 exact category mapping, selected models, complete matching pricing, pricing age, and `OPENAI_API_KEY` presence without reading/logging its value.
- Missing key/data/import/pricing disables **LLM generation only**; DB-only application functions remain available. Stale pricing (> configured 30 days) warns but does not disable. Repeat readiness immediately before LLM job start.
- Return structured safe reasons/warnings to the future UI; never expose filesystem secrets or key values. Continue returning all 20 canonical categories, including any future zero-DB-count category.

## 2. Persistent, sequential job model

- Store job state atomically as JSON beneath ignored `artifacts/exam_jobs/<job_id>/`; never in `app.db` and never in Git. Use UUID job/slot IDs, locking, safe paths and atomic replace writes.
- Reload jobs on backend start. A job found as `running` becomes `interrupted`; retain completed questions and make unfinished/failed slots retryable. Never auto-resume billable calls after a crash.
- One worker processes one question at a time, categories in canonical order. No parallel provider calls.
- States must cover queued/running/completed/partial/interrupted/cost-ceiling/failed and expose per-category/per-slot progress, attempts, retries and safe errors.
- Keep legacy synchronous generation/replacement endpoints working until WP19 switches the frontend.

New job request:

```json
{
  "categories": {
    "<canonical category>": {"total": 4, "database": 2, "llm": 2}
  },
  "cost_ceiling_usd": "5.00"
}
```

- Validate strict non-negative integers and `database + llm = total`; reject unknown categories and insufficient DB availability before creating the job. LLM readiness is required only when any `llm > 0`.
- Select all A database questions first using the existing random-selection logic, excluding duplicates as today. Then generate B questions sequentially.
- Assign final global exam numbers in canonical display order. Every generated call receives that category’s selected DB questions, prior accepted LLM questions, and applicable retained history as exact seven-field JSON.
- Generated questions remain session/job data only and are never inserted into the question DB.

## 3. API surface

Implement coherent versioned routes (exact naming may follow Flask conventions) for:

- create job (return `202`, job id and polling URL);
- get job/progress/partial or final result;
- retry one failed/interrupted slot;
- update the per-exam cap (new cap cannot be below accumulated cost);
- replace a current question from DB;
- replace a current question through the LLM;
- download only accepted LLM-generated questions as an Excel file compatible with the existing upload flow.

Mutations must reject concurrent/double execution and leave the current question unchanged on failure.

Replacement rules:

- Preserve the slot’s `instance_id` and public `number`.
- DB replacement uses the existing selector and excludes DB questions currently in the exam.
- LLM replacement passes all other current category questions plus previously generated/discarded category history, preserving order and repeated numbers. On success move the old question to history; on failure retain it.
- Manual retries/replacements use the same cumulative job budget and add their attempts/costs to the same job ledger.

## 4. Cost accounting and terminal report

- Use `Decimal`; pass `remaining = cap - accumulated_cost` to every generator call.
- Accumulate every returned cost: accepted, rejected, refusal, failed attempt, retry and LLM replacement. Never count DB operations.
- Surface `total_cost_basis`, itemized costs, pricing verification and warnings. Do not present conservative/fallback amounts as provider-exact.
- When the initial whole-exam run reaches a terminal state, print/log one visible backend-terminal summary containing job id, final LLM cost, basis, accepted/failed LLM slots, retries and pricing warnings.
- Print an updated cumulative summary after each manual LLM retry/replacement completes. Never print prompts, answers, raw responses or secrets.

## 5. DTO, history and export

- Use the WP17 DTO: seven public fields plus stable `instance_id`, nullable DB `id`, `origin`, canonical category fields, LLM performance defaults and `generation_meta`; exclude metadata from DOCX question content.
- Persist current questions separately from immutable category history. History must support repeated/non-monotonic public numbers and must not be sorted or deduplicated before generator calls.
- Ensure replacement does not corrupt category order, global numbering or answer IDs.
- Excel export contains only accepted `origin=llm` questions, with the exact headers/defaults expected by the existing import endpoint; export does not insert them.

## 6. Offline verification

Inject fake providers/services and block network. Test at least:

- DB-only job succeeds when LLM readiness is unavailable;
- mixed A/B selection order and Q3→Q4 previous-question growth;
- canonical category/global question ordering;
- one-worker sequential behavior and no double execution;
- persistent reload and running→interrupted recovery;
- partial results plus slot retry;
- both replacement modes, unchanged-on-failure, and discarded repeated-number history;
- cumulative ceiling across failures/retries/replacements;
- exact terminal cost-summary contents/basis without secrets;
- stale warning versus missing-price/key blocking;
- generated questions never enter DB; `app.db` is never mutated in tests;
- Excel round-trip and unchanged legacy endpoints.

Run outer backend tests serially with temporary databases, targeted generator production tests network-blocked, and `npm ci && npm run build`. No provider calls. Verify ignored job/audit data and clean submodule.

## Outputs and Git

- Save `WPs/WP18_ARCHITECT_REPORT.md` (≤170 lines) and refresh outer `WPs/ARCHITECT_HANDOFF.md`.
- Report routes/contracts, persistence/recovery, readiness, history order, cost-log example, tests, risks and decisions for WP19.
- Commit only the outer repo as `WP18: integrate backend generation jobs`; do not push.
- End with outer full SHA/status, pinned generator SHA/status, and confirmation that the backup remains untouched.
