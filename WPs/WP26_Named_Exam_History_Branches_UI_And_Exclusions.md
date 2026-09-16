# WP26 — Named Exam History, Immutable Branches, UI Polish, and DB Exclusions

## Goal

Add a usable saved-exam library: name exams, reopen and export them, and explicitly branch an older exam into a new editable version without altering the original. Restore the optional Excel-based exclusion list for database questions, complete the requested RTL/design cleanup, and correct retry/replacement telemetry.

This is an **outer `questions-db` work package only**. Do not modify or advance `exam_generator`.

This brief supersedes the unexecuted `WP25_Named_Exam_History_Branches_And_UI_Polish.md`. Do not execute that older brief.

## Fixed owner decisions

- New exams support either a structured name or a custom name.
- Structured fields:
  - `קורס`: closed choice of `מבנה המוח` or `נוירואנטומיה`;
  - `שנה`: editable, default = current year from the browser clock;
  - `סוג`: closed choice of `מבחן אמצע` or `מבחן מסכם`;
  - `מועד`: editable, default = `א`.
- Example display name: `מבנה המוח 2026 מבחן מסכם מועד א`; safe download slug: `מבנה_המוח_2026_מבחן_מסכם_מועד_א`.
- Opening an older exam is read-only. `יצירת גרסה חדשה` asks for a new name and creates a new active editable branch. The original is never changed.
- The current active exam remains editable and survives navigation/app restart. Creating a new exam or branch makes it active; older jobs remain in history.
- Keep completed, incomplete, failed, interrupted, and cost-ceiling jobs visible. Legacy unnamed jobs receive a calculated fallback label such as `מבחן ללא שם – 16.09.2026 – 14f2a1ea`; do not rewrite their files merely to add a name.
- Duplicate visible names are allowed because job IDs remain authoritative; disambiguate entries using date, status, and short ID.
- A branch starts with zero new LLM spend and a fresh ledger/audit state. Existing questions and semantic history are copied. Parent costs/audits remain only with the parent.
- Generated questions never enter the question database automatically.
- An optional uploaded `.xlsx` exclusion file applies only to DB questions. Resolved DB questions must be excluded from both initial DB selection and every later `החלף בשאלה מהמאגר` operation for that exam and its descendants.
- A discarded DB question is not semantic evidence that its topic is unwanted, so DB questions removed by replacement continue **not** to enter LLM semantic history.

## Preflight and boundaries

Expected starting state:

- outer `main` at `63398340b1f6d66b39bf8f6bd2995f3fe7987996`;
- generator clean and pinned at `d20c46bbb332e4d40f735e843d31113176b755e5`;
- the only pre-existing extra local file is untracked `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`. Do not modify, stage, move, delete, or commit it. This WP brief may also be untracked when execution begins.

Record outer branch/HEAD/remotes/status, submodule status/HEAD, and the backup-directory state before editing. Stop if either repository has other drift, the pin differs, or the expected outer commit is absent. The outer baseline need not equal `origin/main` at preflight, but any eventual push must pass the fast-forward checks in §9.

During this WP:

- make zero live/provider calls; do not read `OPENAI_API_KEY` and do not start either server;
- do not modify the generator, generator gitlink, backup, real `artifacts/exam_jobs/**`, `backend/src/database/app.db`, local `Data/**`, `.env*`, dependencies, prompts, or generated audit evidence;
- use temporary job stores/databases and fixture workbooks in tests; block non-loopback network access;
- do not install or upgrade packages;
- preserve all working WP25G behavior, including inverse/reciprocal semantic-duplicate protection.

## 1. Persisted naming and history API

Extend the job JSON contract backward-compatibly with validated naming and lineage metadata. Use the job ID—not a user name or slug—for storage paths.

Required behavior:

- `POST /api/exam-jobs` accepts structured or custom identity data and returns normalized `display_name` plus a filesystem-safe download slug.
- Structured course/type values are closed enums. Year and sitting are trimmed and validated. Custom names are non-empty, length-bounded Unicode; reject control characters and path traversal.
- Existing job JSON lacking all new fields loads unchanged and receives only a calculated fallback label in API output.
- Add or extend a read-only jobs-list endpoint returning every persisted job newest-first with ID, display label, created/updated time, status, accepted/total counts, parent/root lineage, and exclusion summary. Do not include question bodies, prompts, audits, or course-source content in the list.
- Preserve the existing single-job result route and its status/cost/telemetry fields.

## 2. Optional exclusion Excel: parsing and preview

Restore an optional new-exam control labeled clearly, for example `קובץ שאלות להחרגה (אופציונלי)`. It accepts `.xlsx` only. Do not silently interpret other file types.

Implement a local, non-provider multipart preview/resolve endpoint. Reuse existing workbook parsing conventions and libraries; add no dependency. Enforce bounded upload size and bounded row count consistent with existing import/export protections. Parse values as data only—never evaluate formulas, macros, links, or embedded content. Never persist the uploaded workbook bytes.

Recognized header aliases:

| Meaning | Accepted headers |
|---|---|
| DB question ID | `מזהה_שאלה`, `id` |
| Question text | `שאלה`, `question` |
| Category | `נושא`, `קטגוריה`, `category` |

Resolution rules, in order:

1. A valid DB ID is authoritative. Resolve it directly; do not require its workbook text to equal current DB text.
2. Without a valid ID, use exact normalized question text plus canonical category when both exist.
3. Without a usable category, use exact normalized question text across the DB.
4. Normalize only safe presentation differences already handled by existing import logic (such as surrounding whitespace). Do not introduce fuzzy/semantic matching.
5. A text/category fallback that matches multiple DB rows excludes **all** exact matches and returns a visible ambiguity warning/count; it must never choose an arbitrary row.
6. Blank rows and export rows with blank/nonexistent DB IDs and no resolvable DB text are ignored and reported as unresolved, not treated as errors. This allows a previously exported full exam workbook to be uploaded: DB rows resolve, LLM-only rows are ignored.
7. Deduplicate the final DB-ID set while retaining useful preview counts.

The preview response must contain only safe metadata needed by the UI: sorted resolved DB IDs, resolved/deduplicated/unresolved/ambiguous counts, row-level safe warnings that do not expose server paths or internals, and adjusted available DB counts by canonical category. Do not return or log the raw workbook.

Frontend behavior:

- display the chosen filename, resolved exclusion count, warnings, and adjusted availability before creation;
- retain the resolved ID set in the new-exam form and submit it in job-creation JSON;
- replacing/clearing the selected file clears the prior preview and resolved IDs; creation without a file submits an empty set;
- parsing errors are actionable and must not start an exam job.

Backend job creation must revalidate every submitted exclusion ID against the current DB; never trust the preview result blindly. Reject malformed IDs. Valid IDs that disappeared between preview and creation may be dropped with a clear warning or rejected safely, but must not cause a paid call.

## 3. Persisted exclusion contract and selection safety

Persist only the normalized, deduplicated `excluded_db_ids` and a safe summary if useful. Do not store workbook bytes, original rows, local paths, or spreadsheet cell contents. Legacy jobs default to an empty exclusion set without rewriting their files.

Apply the persisted set to:

- initial random DB selection in every requested category;
- every later DB replacement, regardless of whether the displaced slot currently originated from DB or LLM;
- any shared helper that calculates DB availability for the job.

For DB replacement, exclude the union of:

- persisted `excluded_db_ids`;
- DB IDs currently used anywhere in the exam;
- any other exclusions already required by the established replacement algorithm.

Do not add displaced DB questions permanently to this set: the owner may reject one DB question for wording/history reasons while still allowing it to be selected again in another independent exam. Existing within-exam no-duplicate behavior remains.

Safety requirements:

- Before the first paid LLM call, validate that each category can satisfy its requested initial DB count after exclusions. If not, fail the job setup atomically with a category-specific Hebrew message showing requested versus available DB count. Do not select partial DB results and do not start LLM generation.
- If a later DB replacement has no eligible alternative, retain the current question unchanged and return the established typed safe conflict. Do not mutate history, counters, costs, or slot origin.
- Exclusions do not reject, filter, or influence LLM-generated questions and do not enter semantic-similarity context.
- Result/list diagnostics may display the number of excluded DB IDs, but the normal exam UI must not render excluded question text.
- A branch inherits the parent’s normalized exclusion set so all later DB replacements honor the same constraint.

## 4. Immutable exam snapshots and explicit branches

Add a branch endpoint/service operation for a completed saved exam. It must be atomic and lock-protected.

Branch requirements:

- Parent `job.json` remains byte-for-byte unchanged on both success and failure.
- The child gets a new job ID, slot IDs, and instance IDs. Preserve public numbers, canonical category order, current seven-field question snapshots, origin/DB IDs, frozen analytics, request metadata, `category_history`, and `excluded_db_ids`.
- Record `parent_job_id` and a stable `root_job_id` in the child.
- The child begins completed/accepted and editable, with no copied cost ledger, audit references, errors, attempts, retry/replacement counters, or terminal summary. New LLM activity is charged only to the child. Inherit the parent cost ceiling as the default ceiling for future child operations.
- Copied current questions and `category_history` still enter later same-category uniqueness context. Successful replacements retain established history rules; discarded DB questions remain outside semantic history.
- If branching is unsupported for a partial/non-completed job, return a typed safe conflict and disable the UI action while keeping view/export available. Do not invent partial-branch semantics.

Saved-exam immutability also applies to DB text and analytics: result view, DOCX, full Excel, and LLM-only Excel must use persisted slot snapshots. Later DB edits affect future selections only and must not retroactively alter an exam or branch.

Preserve both replacement buttons for every accepted question in the **active editable** job. Historical read-only views must never call mutation routes.

## 5. Frontend saved-exam workflow

Implement this without removing current generation, retry, replacement, analytics, category headings, export, exclusion preview, or persistence behavior:

1. `צור מבחן חדש` opens a setup dialog/step with `שם מובנה` versus `שם חופשי`, followed by the approved identity fields and optional exclusion workbook.
2. Structured mode produces the readable display name. Custom mode uses the trimmed custom name exactly for display. Downloads use a safe derived slug, never the raw value as a path.
3. Add a closed saved-exam selector/list showing all statuses. Each option shows name, date, status, and short ID.
4. Preserve separate local state for the active editable job and the job currently being viewed. Restore both after tab navigation and browser/app restart; fall back safely if a stored ID no longer exists.
5. A historical selection is visibly read-only: exports and review remain available, mutation controls are disabled/hidden, and `יצירת גרסה חדשה` is prominent.
6. Branch creation asks for a new structured/custom name, creates the child, and makes it active/viewed. Never mutate the parent and never branch implicitly on replacement.
7. Use the exam slug in DOCX/full-Excel/LLM-only-Excel filenames while preserving workbook schemas and DOCX content.
8. Display an inherited exclusion count for a branch/job if useful, but do not require re-uploading the workbook.

## 6. Requested UI corrections

- **Analytics:** current behavior was observed working. Do not rewrite it. Add regression coverage proving DB accuracy/distinction values render when present, genuine missing values render `N/A`, and LLM questions render `N/A`. Preserve exam-level average accuracy and above-threshold distinction summary, ignoring `N/A` as before.
- **LLM-only export button:** keep `ייצוא שאלות בינה בלבד`; adjust button/flex sizing and prevent text wrapping. Do not reduce font size. Whole buttons may wrap to another row on narrow screens.
- **Brand title:** use exactly `מאגר שאלות ומחולל בחינות – קורס מבנה המוח, אוניברסיטת תל אביב`.
- **About tab:** replace generic content with relevant Hebrew information for course staff: question-bank purpose; browsing/importing; performance measures; mixed DB/LLM construction; grounded LLM review/replacement; named history/branches; optional DB exclusions; Excel/DOCX exports; generated questions not entering the DB automatically; and human academic review. Avoid marketing filler and raw implementation details.
- **Top tabs:** visual RTL order must put `אודות המערכת` at the far right and `עיון בשאלות` at the far left. Preserve the two existing middle tabs in logical order. Test DOM/visual order rather than relying accidentally on flex reversal.
- **Question-browser topic bar:** render categories byte-for-byte in authoritative order from `backend/src/utils/category_order.py::CATEGORY_ORDER`. Do not alphabetize and do not use generator chapter order. Preserve counts/filter behavior.

## 7. Retry/replacement telemetry cleanup

Correct the known diagnostic quirk without changing ledger, costs, or established frontend semantics:

- intentional `replace_llm` must not increment a failure-driven retry counter;
- terminal summaries must derive `retries` and `replacements` from immutable ledger operation kinds and print them separately;
- old persisted jobs with conflated raw counters must report correct ledger-derived totals without rewriting old files;
- retry limits count genuine retry operations only;
- preserve every historical ledger/audit entry.

## 8. Required tests

Add focused offline coverage for at least:

### Naming/history/branching

- structured/custom validation, browser-year default, safe slugging, duplicate names, and legacy fallback names;
- newest-first listing and inclusion of every status;
- backward loading of pre-WP26 job JSON;
- branch success/failure atomicity and parent byte immutability;
- correct deep-copy/reset/lineage/new-ID behavior;
- copied semantic uniqueness context and inherited exclusions;
- DB text/analytics snapshot immutability across result view and every export;
- active versus historical UI modes, local restoration, explicit branching, and no mutation call from read-only views.

### Exclusion workbook

- accepted/rejected file types, upload and row bounds, aliases, whitespace normalization, ID precedence, category canonicalization, exact-match fallback, duplicate rows, ambiguity, unresolved rows, and blank LLM export rows;
- raw workbook bytes are never persisted or logged;
- frontend preview, warning display, clearing/replacing a file, and exact submitted ID set;
- backend revalidation of client-supplied IDs;
- exclusion in initial selection and DB replacement from both DB-origin and LLM-origin slots;
- union with current-exam DB IDs and no duplicate DB question;
- insufficient per-category availability fails before any provider call and leaves no partial paid job;
- replacement exhaustion retains the old slot and all counters/history/costs;
- exclusions remain outside LLM context and branch inheritance works;
- a realistic full-export fixture resolves DB rows while ignoring nonresolvable LLM rows;
- legacy jobs with no exclusion field behave exactly as before.

### UI/telemetry/regressions

- both replacement buttons remain on active accepted questions;
- full and LLM-only Excel schemas and DOCX behavior remain compatible;
- numeric DB analytics, justified `N/A`, and aggregate metrics;
- non-wrapping export text without font reduction;
- exact RTL tab endpoints, relevant About content, and canonical topic order;
- ledger-derived retry/replacement separation, including an old-job fixture;
- current WP25G reciprocal/inverse duplicate tests remain unaffected at the integration boundary.

Testing sequence:

1. Run new/affected backend and frontend tests.
2. Make at most two focused fix-and-rerun passes for failures caused by this WP. If still failing, stop and report instead of broadening changes repeatedly.
3. Run the complete outer backend suite once, complete frontend suite once, and frontend production build once, serially, with `OPENAI_API_KEY` unset and provider/network access trapped.
4. Do not run the generator suite; the submodule must remain unchanged.

## 9. Documentation, report, and Git

- Save this brief as `questions-db/WPs/WP26_Named_Exam_History_Branches_UI_And_Exclusions.md`.
- Update relevant setup/user documentation and refresh `WPs/ARCHITECT_HANDOFF.md`.
- Save Claude’s report to `questions-db/WPs/WP26_ARCHITECT_REPORT.md`—not inside the generator. Include contracts, backward compatibility, exact exclusion resolution behavior, branch/reset semantics, UI behavior, files changed, tests, limitations, and a concise architect summary.
- Explicitly report whether `PRE_WP25_LATEST_EXAM_REVIEW.md` remained untouched and uncommitted.
- Inspect the staged diff and scan for secrets, real jobs/questions, uploaded workbook contents, database changes, `.env*`, local data, prompts/responses, and submodule drift.
- Commit intended outer files only as `WP26: add named exam history and exclusions`.
- Claude may push outer `main`, but only after `git fetch origin`, proving the intended commit is based on the fetched `origin/main` or that a normal push is fast-forward. Never force-push, rebase/merge through divergence, or push the generator. If safety cannot be proven, leave the commit local and report.
- End with generator clean at `d20c46bbb332e4d40f735e843d31113176b755e5`. The outer tree may retain exactly the pre-existing untracked `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`; no other untracked or modified files may remain.

## Stop conditions

Stop and report before proceeding if:

- implementation would require generator changes, paid calls, real job/data migration, dependency changes, or server startup;
- historical jobs cannot load backward-compatibly;
- branching cannot preserve the parent byte-for-byte;
- the exclusion constraint cannot be enforced server-side for both selection and replacement;
- current exports cannot stay schema-compatible;
- canonical order differs across backend contracts;
- unrelated changes or repository divergence appear;
- completing the scope would require more than the two focused repair passes.

## Required final response

Return:

1. outer commit SHA and push result;
2. final outer and generator status/pins;
3. concise behavior summary, including exclusion resolution and branching;
4. exact backend/frontend test and build counts;
5. confirmation of zero provider calls and no secret/workbook/raw-artifact leakage;
6. the path to `WPs/WP26_ARCHITECT_REPORT.md` and any stop condition or limitation.
