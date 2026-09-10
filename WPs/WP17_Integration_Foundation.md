# WP17 — Integration Foundation via Git Submodule

## Goal

Prepare the `questions-db` repository to integrate the finalized generator while keeping `exam_generator` an independent, updateable repository. Establish repository hygiene and offline integration contracts only.

**No API/provider calls. Do not modify generator behavior or implement the full live UI/job flow.**

## 1. Preflight and Git topology

Expected layout:

```text
questions-db/
├── backend/
├── frontend/
└── exam_generator/   # independent repository/submodule
```

- From the `questions-db` root, record outer Git root, branch, HEAD, status and remotes.
- Inside `exam_generator`, record branch, HEAD, status and remotes. Expected generator baseline: `e5f4e0b34dda26f22c56090326f30af7170bcbd3` (WP16R; 869 tests).
- Stop before mutation if either repository has unrelated changes, the generator SHA differs, or its remote/history is not recoverable.
- Convert/register the existing `exam_generator` checkout as a Git submodule of `questions-db`, pinned to the verified commit. Reuse its existing remote; do not reclone unnecessarily.
- `questions-db` should track `.gitmodules` and the submodule gitlink only—not generator files individually.
- Do not delete generator history, flatten/vendor it into the parent, or edit/commit/push inside it.

## 2. Ignore consolidation and repository hygiene

Repository boundaries remain explicit:

- Consolidate applicable root/backend/frontend ignore rules into `questions-db/.gitignore`.
- Do **not** merge or alter `exam_generator/.gitignore`; it belongs to the generator repository.
- Remove component ignore files only after every rule is preserved correctly at the outer root.
- Use narrow root-relative rules. Cover at least:
  - `frontend/node_modules/`, builds, coverage and frontend tool caches;
  - Python caches/bytecode, test/type/lint caches and virtual environments under the outer project;
  - outer `.env`/`.env.*`, while allowing intentional `.env.example` files;
  - temporary/test databases, while retaining `backend/src/database/app.db`;
  - OS/editor clutter.
- Remove the outer blanket `*.md` ignore. Track README and integration documentation.
- Test separately:
  1. `git check-ignore -v` on representative ignored paths;
  2. `git ls-files` for sensitive/generated paths already tracked.
- If `frontend/node_modules/**` is tracked, untrack it from the outer index without deleting the local directory; confirm `npm ci` recreates dependencies.
- Confirm the parent cannot stage `exam_generator/Data`, artifacts, `.env*`, credentials, provider responses, caches, or individual generator files through the submodule boundary.
- Audit the staged diff before commit. Never stage secrets or runtime data.

## 3. Remove verified dead outer-project files

Confirm no import/reference/build use, record evidence, then remove only if genuinely unused:

- `backend/src/routes/test_generation_backup.py`
- `backend/src/routes/test_generation_old.py`
- `backend/src/routes/generate_word.ipynb`
- duplicated frontend category-order utility

Retain `backend/src/database/app.db`. Correct README/start-command port mismatch to actual port `4567`, if still present, and document submodule-aware setup (`git clone --recurse-submodules`, initialization/update commands) without secrets.

## 4. Canonical category contract

- `backend/src/utils/category_order.py::CATEGORY_ORDER` is the sole external category spelling and display order.
- Compare it with the pinned generator’s category names, IDs, contexts and readiness data.
- Add explicit aliases in **outer integration config**, not in the generator repository. Never fuzzy-match.
- Each canonical category must map to exactly one strict-ready generator context. Missing/extra/ambiguous mappings block WP18.
- Save the complete mapping at `WPs/WP17_CATEGORY_MAPPING.md` in the outer repository. Do not write it inside the submodule.
- Make `/api/test/categories` use backend canonical order and DB availability counts. Remove any duplicate hard-coded frontend order.

## 5. Read-only adapter to the generator

Create an outer-project Python adapter/service that imports and invokes the pinned generator’s production one-question API. The adapter must not copy generator code, invoke WP runners, or use a subprocess/CLI wrapper.

Input:

- canonical category;
- requested question number;
- all previous category questions projected to the exact seven public fields;
- attempt/budget context and audit destination.

Output: accepted seven-field question plus audit/cost metadata, or typed failure: `question_rejected`, `provider_output_failure`, `systemic_failure`, `cost_ceiling`.

The adapter must preserve the generator’s WP16R generation → review → safe repair → validation behavior, dynamic model configuration and `store:false`. It must resolve paths reliably from any backend working directory. Add fake-provider, network-blocked contract tests only.

If the pinned generator lacks a suitable public Python boundary, **do not change it in WP17**. Document the exact missing interface and propose a separate generator WP/release before continuing integration.

## 6. Integrated request and question contracts

Define/test future per-category input `{total: C, database: A, llm: B}`: non-negative integers, `A + B = C`; DB availability limits A only.

Define a backend exam-question DTO containing:

- the seven public question fields;
- unique exam `instance_id`; nullable DB `id`;
- `origin: database | llm`;
- canonical `category`, `primary_category`, `categories`;
- null/empty performance defaults for LLM questions;
- `generation_meta` for attempts/retries/cost, excluded from DOCX content.

Freeze sequence: select all A DB questions first, then generate B sequentially. Every generation receives the canonical category, all selected A questions and every prior accepted LLM question for that category, projected to seven fields.

Store owner policy in outer integration config:

- generated questions are exam-session only; never auto-insert into DB;
- maximum two attempts per requested LLM slot;
- editable per-exam cap, default `$5.00`;
- enforce actual spend plus conservative cost of the next complete generation/review pair—not all hypothetical retries;
- provide preflight estimate/warning and support at least 20 LLM questions;
- later execution uses a background job with category/question progress;
- preserve successful partial work; failed slots are retryable; report retries by category and slot;
- replacement uniqueness history includes current and previously generated/discarded category questions;
- existing exam/DOCX code remains responsible for answer randomization;
- later frontend arithmetic: editing C gives `A=ceil(C/2)`, `B=floor(C/2)`; editing A/B gives `C=A+B`.

## 7. Offline verification

- Do not run provider calls or alter generator files.
- Run the pinned generator suite network-blocked: expected 869 tests. Any generator-created ignored runtime/cache files must remain inside and uncommitted in its repository.
- Backend contract/category/DTO tests must use a temporary database; never mutate `app.db`.
- Prove exported LLM questions remain compatible with the current Excel upload route.
- Run relevant backend tests serially and `npm ci && npm run build`.
- Prove: submodule clean at expected SHA; outer repo tracks only its gitlink; ignores work; no DB mutation; no secret/runtime artifact staged.
- Report dependency conflicts before changing models, prompts, terminology, acceptance logic or generator behavior.

## 8. Reports and commit

- Create outer `WPs/` if absent.
- Save `WPs/WP17_ARCHITECT_REPORT.md` (≤170 lines).
- Create/refresh outer `WPs/ARCHITECT_HANDOFF.md` with both repository SHAs and submodule update procedure.
- All integration WP summaries and decision files belong in outer `WPs/`; do not write reports into `exam_generator/WPs/`.
- Report Git topology, SHAs, `.gitignore` consolidation, removals/evidence, category mapping, adapter/DTO contracts, tests, blockers, deviations and decisions needed before WP18.
- Commit intended **outer-repository** changes as `WP17: establish integration foundation`. Do not push either repository.
- End with outer commit SHA/status plus generator pinned SHA/status. The generator working tree must remain clean and unchanged.
