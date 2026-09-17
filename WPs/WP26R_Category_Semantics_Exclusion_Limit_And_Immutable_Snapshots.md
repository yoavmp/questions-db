# WP26R — Category Semantics, Exclusion Limit, and Immutable Saved Exams

## Goal

Correct three verified WP26 issues without changing the generator:

1. reject an exclusion workbook containing more than 100 nonblank data rows instead of accepting a truncated exclusion set;
2. make the DB question’s full category list the single source of selection eligibility, preserve the exam slot’s fixed target category, and guarantee globally unique feasible DB selection before any provider call;
3. make every displayed/exported saved-exam field an immutable persisted snapshot rather than re-reading live DB content.

This is an **outer `questions-db` work package only**. Do not modify or advance `exam_generator`.

## Fixed owner decisions

- The exclusion workbook limit applies to the optional `.xlsx` of DB questions that must not appear in the exam.
- The header does not count. Up to 100 nonblank data rows are accepted. The 101st nonblank data row rejects the **entire** workbook; no partial preview or exclusion set may be returned or applied.
- `Question.categories`—the complete category list—is the sole source of DB-question eligibility for category selection and replacement.
- The legacy singular `Question.category` remains for compatibility/display as the primary category, but it must be derived from and equal to the first entry of `Question.categories`. It must not independently widen eligibility.
- `Slot.category` remains necessary: it is the fixed category quota under which that question was selected for this exam. It controls exam grouping, category history, and both DB/LLM replacement context.
- Categories are processed/displayed in canonical `CATEGORY_ORDER`.
- DB question choice remains random **within fixed requested category slots**. A question is never randomly assigned a category it does not contain. Once a DB ID fills one slot, it cannot fill any other slot in that exam.
- All requested DB slots must have a globally feasible unique assignment before the job is persisted or any provider call is possible.
- All displayed saved-exam data is frozen: question text, four answers, correct answer, target category, primary category, full category list, analytics, origin, and DB ID. Reopening, branching, DOCX, full Excel, and LLM-only Excel must not change after later DB edits.
- Do not silently modify the real question database to repair category inconsistencies. Report them and stop at the specified gate.

## Preflight and boundaries

Expected starting state:

- outer `main` and `origin/main` at `c49036b305c750cbcdc8fb92a5461a871cfb2c1f` (`WP26: add named exam history and exclusions`);
- generator clean and pinned at `d20c46bbb332e4d40f735e843d31113176b755e5`;
- expected untracked, owner-owned files:
  - `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`;
  - `WPs/PRE_WP26R_AUDIT.md`.

Do not modify, stage, move, delete, or commit either PRE file. This WP brief may also be untracked at the start and should be committed as part of WP26R.

Stop before editing if either repository has other drift, a pin differs, or outer history has diverged.

During this WP:

- zero live/provider calls; do not read `OPENAI_API_KEY` and do not start backend/frontend servers;
- do not modify the generator, gitlink, backup, real `artifacts/exam_jobs/**`, `backend/src/database/app.db`, local `Data/**`, `.env*`, dependencies, prompts, or generated audit evidence;
- the real DB may be inspected **read-only** for the category-invariant audit below;
- use temporary databases/job stores/workbooks in tests and block provider/network access;
- do not install or upgrade packages.

## 1. Read-only category-model audit and gate

Before changing eligibility logic, inspect the model, all question create/edit/import/category-rename paths, selection/replacement paths, and the real DB read-only.

For every DB question, check:

- `categories` parses to a nonempty ordered list;
- every entry is a byte-exact canonical category from `backend/src/utils/category_order.py::CATEGORY_ORDER`;
- entries contain no duplicates;
- singular `category` is present in the list;
- singular `category` equals `categories[0]`.

Report counts for each invariant and safe affected DB IDs/category values only—do not copy question text into the committed report.

**Gate:** if any real row violates these invariants, stop before changing selection behavior or the DB. Make no database repair and no eligibility migration. Save the findings in `WPs/WP26R_ARCHITECT_REPORT.md`, leave both repositories otherwise unchanged, and request an owner decision. If all rows pass, continue.

Also document the three distinct semantics in code/docs:

| Concept | Persisted meaning |
|---|---|
| DB `Question.categories` | Complete authoritative eligibility list |
| DB `Question.category` / API `primary_category` | Compatibility/display primary, equal to the first list entry |
| Job `Slot.category` / result `category` | Fixed exam quota/target category for this slot |

Do not rename the persisted legacy fields in this WP; preserve backward-compatible APIs and job loading.

## 2. Exclusion workbook: hard 100-row rejection

Change the preview parser to enforce `MAX_ROWS = 100` nonblank **data** rows, excluding the header.

Required behavior:

- exactly 100 nonblank data rows may be parsed normally;
- encountering the 101st nonblank data row raises the typed exclusion-parse error;
- the preview endpoint returns the existing safe 4xx validation response with a clear Hebrew explanation that the maximum is 100 rows;
- do not return `resolved_db_ids`, counts, warnings, or any other partial preview from the first 100 rows;
- blank physical rows do not count toward 100;
- retain the existing 2 MB upload-size limit and `.xlsx`-only rule as independent safeguards;
- raw workbook bytes remain memory-only and are never persisted/logged;
- the frontend clears any prior successful preview/resolved ID set when a replacement upload fails, so stale exclusions cannot be submitted accidentally.

Preserve all WP26 resolution rules for valid files: ID precedence, exact normalized text/category fallback, exclude-all exact ambiguous matches, deduplication, backend ID revalidation, initial selection/replacement enforcement, and branch inheritance.

## 3. One authoritative DB category list

Centralize category normalization/validation so every future question create, edit, Excel import, and category rename maintains:

```text
categories = nonempty, ordered, unique canonical list
category = categories[0]
```

Requirements:

- Selection eligibility for requested category X is **only** exact membership of X in `Question.categories`.
- Remove the selector/precheck/replacement fallback `Question.category == X OR ...`; the singular value must not independently make a question eligible.
- Avoid substring/fuzzy category matching. Use exact parsed-list membership or an exact database JSON-membership mechanism already supported by the project.
- Browsing/filtering/category counts must remain consistent with the full list: a question associated with X appears under X even when X is not primary.
- Preserve the legacy singular field in storage and question-management API output for compatibility, derived from the list’s first entry.
- Reject future writes with empty, duplicate, unknown, or contradictory categories using clear validation errors; do not silently accept divergent values.
- Category rename must update the full list, preserve order/deduplicate, and recompute the singular primary.
- Do not rewrite `app.db` merely to restate already-valid values.

Add one narrowly-scoped shared helper/service for these invariants rather than duplicating slightly different rules across routes.

## 4. Globally feasible random DB selection

Replace the unreliable independent precheck plus greedy selection with one globally correct selection plan for all requested DB slots.

Model the request as fixed category slots:

- create exactly `A` DB slots for each requested category, ordered by canonical category then slot order;
- a DB question is a candidate for a slot only when the slot category is an exact member of that question’s authoritative `categories` list;
- remove uploaded `excluded_db_ids` before planning;
- one DB ID may match at most one slot in the whole exam.

Use a dependency-free bipartite matching/backtracking approach suitable for fewer than 500 DB questions and roughly at most 40 exam questions. Randomize candidate ordering through the existing injectable RNG so repeated exams can choose different eligible questions, while tests remain deterministic. The slot categories themselves are fixed and never randomized or inferred from a question’s primary category.

Required behavior:

- prove a complete matching exists before saving a job or reaching any provider code;
- if no complete matching exists, reject atomically with a safe Hebrew message explaining that unique DB questions cannot satisfy the requested category quotas after category overlap and exclusions; include requested/independent availability counts where useful, but do not falsely claim that per-category counts guarantee joint feasibility;
- no partial job, DB selection, cost entry, audit directory, or provider call may survive failure;
- when feasible, persist each matched question once with `Slot.category` equal to the fixed requested slot it filled;
- returned questions remain grouped/sorted by canonical `Slot.category` order;
- do not prefer a question’s primary category over another category in its list; every listed category is equally eligible;
- keep preview availability counts as independent per-category information, but do not present them as proof of joint feasibility.

### DB replacement

For `החלף בשאלה מהמאגר` on any accepted slot:

- target the existing `Slot.category`, regardless of the current question’s origin or primary category;
- randomly choose among DB questions whose authoritative category list contains that target;
- exclude persisted workbook exclusions and every DB ID currently used elsewhere in the exam;
- retain the current question unchanged on exhaustion;
- do not add a displaced DB question to semantic history or permanent exclusions;
- preserve both replacement buttons and the established source-balance freedom after initial construction.

## 5. Immutable question and category snapshots

Eliminate the live DB re-query in saved-exam rendering.

### New jobs and replacements

Persist enough selection-time metadata on each slot to render it without querying `Question`:

- existing seven public fields in `slot.question`;
- fixed target `slot.category`;
- selection-time `primary_category` snapshot;
- ordered full `categories` snapshot;
- existing frozen analytics;
- origin and DB ID.

For a DB replacement, replace these snapshots atomically with those of the newly selected DB question while keeping the slot’s target category/number/instance identity rules already established. For LLM-origin questions, category metadata should deterministically reflect the fixed target category.

### Read and export behavior

- `result_view` must build every accepted slot entirely from persisted job/slot data. It must not query the live `Question` row for question text, answers, correct answer, primary category, categories, or analytics.
- DOCX data derived from `result_view` therefore remains snapshot-based.
- Full Excel and LLM-only Excel remain schema-compatible and snapshot-based.
- Branches deep-copy all question/category/analytics snapshots and never refresh them from the DB.
- Deleting or editing a DB row after exam creation must not change or break the saved exam, branch, UI review, DOCX, or either Excel export.

### Legacy jobs

Load pre-WP26R jobs without rewriting their files:

- use their already-persisted seven fields and `Slot.category`;
- if category snapshot fields are absent, return `primary_category = Slot.category` and `categories = [Slot.category]` as a deterministic immutable fallback;
- never consult the live DB to enrich an old saved exam.

## 6. Required tests

Add focused offline tests covering at least:

### Exclusion limit

- 100 nonblank data rows accepted;
- 101 nonblank data rows reject the whole preview with no partial IDs/counts;
- header and blank rows do not count;
- frontend clears a prior preview after an oversized replacement upload fails;
- existing 2 MB/type/resolution/revalidation tests remain valid.

### Category invariants

- full-list exact membership is the sole eligibility rule;
- a contradictory singular primary cannot widen eligibility;
- create/edit/import/rename paths enforce nonempty, unique canonical lists and derive primary from the first entry;
- secondary-category browsing/counting still works;
- malformed/unknown/duplicate categories fail safely;
- no real DB mutation occurs during the audit.

### Joint selection

- reproduce the audit’s overlapping-category counterexample and now find a feasible unique allocation when one exists;
- reject an actually infeasible overlap before job persistence/provider access;
- a multi-category DB ID appears at most once across the whole exam;
- every selected question contains its `Slot.category` in its category snapshot;
- fixed canonical slot order plus deterministic injected RNG behavior;
- exclusions participate in the global plan;
- DB replacement uses `Slot.category`, accepts secondary-category candidates, excludes all current DB IDs, and retains the old question on exhaustion.

### Snapshot immutability

- after completing a DB-backed job, mutate the temporary DB question text, all answers, correct-answer ID, singular primary, full category list, and analytics source records;
- also test deletion of the live DB row;
- assert byte/field stability of `result_view`, frontend-visible question data, DOCX input/output semantics, full Excel, and applicable LLM-only Excel behavior;
- branch after the live DB mutation and prove the child copies the parent snapshot, not the DB’s new state;
- pre-WP26R jobs use the deterministic category fallback and are not rewritten;
- DB and LLM replacements create correct new snapshots.

Retain all WP26 naming/history/branch/exclusion/UI/telemetry regressions and WP25G inverse-duplicate behavior.

Testing sequence:

1. Run new/affected backend and frontend tests.
2. Make at most two focused repair passes for WP26R-caused failures. Stop and report if still failing.
3. Run the complete outer backend suite once, complete frontend suite once, and frontend production build once, serially, with `OPENAI_API_KEY` unset and provider/network access trapped.
4. Do not run the generator suite; the submodule must remain unchanged.

## 7. Documentation, report, and Git

- Save this brief as `questions-db/WPs/WP26R_Category_Semantics_Exclusion_Limit_And_Immutable_Snapshots.md`.
- Update relevant setup/user documentation and refresh `WPs/ARCHITECT_HANDOFF.md`.
- Save Claude’s summary only to `questions-db/WPs/WP26R_ARCHITECT_REPORT.md`.
- The report must include:
  - real-DB category audit counts and whether the gate passed;
  - exact authoritative semantics of all three category fields;
  - matching/selection algorithm and failure behavior;
  - exclusion 100-row behavior;
  - snapshot and legacy fallback contracts;
  - files changed and exact tests/build results;
  - concise architect summary;
  - final Git checkpoint and push outcome.
- Inspect the staged diff and scan for secrets, real question text, workbook bytes, real job artifacts, database changes, `.env*`, local data, prompts/responses, and submodule drift.
- Commit intended outer files only as `WP26R: harden categories exclusions and snapshots`.
- A normal push of outer `main` is authorized only after `git fetch origin` proves fast-forward safety. Never force-push, rebase/merge through divergence, or push the generator.
- End with generator clean at `d20c46bbb332e4d40f735e843d31113176b755e5`.
- The outer tree may retain exactly these owner-owned untracked files:
  - `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`;
  - `WPs/PRE_WP26R_AUDIT.md`.
  No other untracked or modified files may remain.

## Stop conditions

Stop and report before implementation/commit if:

- the real DB category audit finds any invariant violation requiring data repair;
- implementation requires modifying `app.db`, the generator, dependencies, real jobs/artifacts, prompts, or provider access;
- exact category-list membership cannot be implemented without breaking existing question management/import behavior;
- a full unique matching cannot be established before persistence/provider code;
- saved-exam rendering cannot be detached from live DB content backward-compatibly;
- unrelated repository drift/divergence appears;
- more than two focused repair passes are required.

## Required final response

Return:

1. outer commit SHA and push result;
2. final outer/generator status and pin;
3. category-audit result and final three-field semantics;
4. exclusion-limit and global-selection behavior;
5. snapshot/legacy behavior;
6. exact backend/frontend/build results;
7. confirmation of zero provider calls and no secret/workbook/question-text/artifact leakage;
8. confirmation that both PRE files remained untouched/uncommitted;
9. path to `WPs/WP26R_ARCHITECT_REPORT.md` and any limitation/stop condition.
