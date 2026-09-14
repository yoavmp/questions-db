# WP24D — Release Documentation Corrections — Architect Report

Documentation-only correction pass over the WP24 release record. No code, configuration, test,
dependency, database, or generated-artifact file was touched. Zero provider calls; `OPENAI_API_KEY`
was never accessed; neither server was started.

## 1. Preflight

- Outer `questions-db` `HEAD`: `9b250145260c450ec7511660c809fefd00e98001` — **this is the previously
  omitted WP24 outer release SHA**. Confirmed `== origin/main`, branch `main`.
- Outer working tree clean except this WP's own untracked brief,
  `WPs/WP24D_Release_Documentation_Corrections.md` — matches the expected starting state.
- Generator `exam_generator` checked-out `HEAD`: `eea91b06e2ec5d053eca3a5696656fdd354a05f9`. This
  equals the outer recorded gitlink (`git submodule status`), `backend/src/integration/generator_pin.py::EXPECTED_GENERATOR_PIN`,
  and the release SHA stated in the WP24D brief — all four match exactly.
- Generator working tree: clean (`git -C exam_generator status`), branch `main`, up to date with its
  own `origin/main`.

No drift, divergence, pin mismatch, or dirty tree. Proceeded to edit.

## 2. Files changed

Outer repository only, documentation:

- `WPs/WP24_ARCHITECT_REPORT.md` — corrected (see below).
- `WPs/ARCHITECT_HANDOFF.md` — refreshed (see below).
- `SETUP.md` — new section added (the canonical setup document; `QUICK_START.md` already points to it
  as "detailed instructions" and it is the doc named in `ARCHITECT_HANDOFF.md`'s "Root install / start
  flow" row).
- `WPs/WP24D_Release_Documentation_Corrections.md` — this WP's own brief (already present, untracked).
- `WPs/WP24D_ARCHITECT_REPORT.md` — this report (new).

No other file was modified. No submodule gitlink change, no `backend/src/integration/generator_pin.py`
change, no Python/JS/config/test/dependency/database/artifact change.

## 3. Corrected false statements / open items

### `WPs/WP24_ARCHITECT_REPORT.md`

1. **Omitted outer release SHA** (§6 "Release SHAs"): the "Outer release SHA" bullet pointed only to
   "the closing terminal response" instead of stating the value. Added the exact value,
   `9b250145260c450ec7511660c809fefd00e98001`, with an inline note marking it a post-release
   correction.
2. **False "committed `Data/index/`" claim** (§7 "Skipped tests"): the report stated production reads
   "the committed `Data/index/`". This is inaccurate — `exam_generator/Data/` (including `Data/index/`)
   is Git-ignored by the generator's own `.gitignore` (`Data/index/`, `Data/*.pdf`, etc.) and is not
   tracked in either repository (`git ls-files | grep exam_generator/Data` returns nothing). Corrected
   to state production reads the pre-built, owner-local, Git-ignored data, with a cross-reference to
   the corrected residual-limitations section and the new setup-doc section.
3. **Stale residual-limitations section** (§9): originally carried forward, unchanged, two WP22-surfaced
   open items that were in fact already resolved before this report was written:
   - reviewer repair-patch `term_id` vs. its own replacement text — verified **resolved in WP23**
     (`exam_generator/WPs/WP23_ARCHITECT_REPORT.md` §1: `TermSurfaceIndex` /
     `repair.resolve_reviewer_patch_term_id`);
   - the reviewer's explicit-disproof strictness for a distractor already correctly excluded by
     evidence — verified **retired in WP23** (same report, §4: criterion 4 rewrite), and further
     sharpened by a **new** general distractor answer-type-alignment requirement verified **added in
     WP23R** (`exam_generator/WPs/WP23R_ARCHITECT_REPORT.md` §2).
   Rewrote §9 to state both are resolved, not open, each with its own citation.
4. **Dependency-pin split**: inspection confirmed it still exists —
   `backend/requirements.txt` pins `pytest==7.4.2`/`MarkupSafe==2.1.3`;
   `exam_generator/constraints.txt` pins `pytest==9.1.1`/`MarkupSafe==3.0.3`. Preserved as the one
   remaining open item, described as currently non-blocking and already handled by
   `scripts/dev_install.sh` (installs the generator package `--no-deps`, keeps the backend's own pins).
5. Every correction above is marked inline as a *(Post-release correction, WP24D: ...)* note rather than
   silently rewritten, so the corrections are not disguised as facts known before the original report
   was written.

### `WPs/ARCHITECT_HANDOFF.md`

1. Recorded the outer release SHA (`9b250145260c450ec7511660c809fefd00e98001`) in the §1 SHA table,
   replacing the placeholder comment that deferred to "the closing terminal response." The generator
   release SHA (`eea91b06e2ec5d053eca3a5696656fdd354a05f9`) was already correctly recorded there.
2. Added an explicit statement in the opening summary that WP24 is the functional release and all
   suites passed (generator 999/825/174 skipped/0 failed; outer backend 121/121; frontend 81/81;
   frontend build succeeded), citing `WPs/WP24_ARCHITECT_REPORT.md` §4.
3. Removed the two resolved WP23/WP23R items from the "Open items" list (the same two identified above),
   replacing them with a corrected note naming WP23/WP23R as the resolving WPs and citing both generator
   reports. The dependency-pin item and all other genuinely open items (frontend-only analytics,
   generated-row export convention, no live failure/retry/rollback exercised, no browser-automation
   tool, single-process worker, no realised-origin-count field, fixed-interval polling, legacy unused
   endpoints still mounted) were left unchanged — still genuinely open, none touched.
4. Clarified, in §2, that course source data and its derived index are local, Git-ignored, and never
   committed by either repository; that `git clone --recurse-submodules` does not download them; that
   this installation's own copy already exists locally (verified by direct file-existence check —
   `exam_generator/Data/index/` is a non-empty directory, `exam_generator/Data/Course_Material_Summary.pdf`
   exists, both confirmed without reading their contents or starting a server), so it is
   LLM-generation-ready on that axis (still subject to `OPENAI_API_KEY` and the other
   `readiness_report()` checks, which this WP did not run); and that a fresh clone is DB-only until the
   owner restores or rebuilds that exact tree. Cross-referenced the new `SETUP.md` section.

### Canonical setup documentation — `SETUP.md`

Confirmed `SETUP.md` is the canonical, already-referenced installation document: `QUICK_START.md`
explicitly says "Check SETUP.md for detailed instructions," and `ARCHITECT_HANDOFF.md`'s integration
table already lists `SETUP.md` (alongside `scripts/dev_install.sh`) as the "Root install / start flow."
`README.md` carries only a brief, pre-existing one-line mention of `exam_generator/Data/` in its
submodule-clone step; left untouched to avoid duplicating the same instructions across documents.

Added one new subsection, "Local course data required for LLM generation," directly under the existing
backend-setup step that already gestured at this topic. Content, derived from the current code (not
guessed):

1. `git clone --recurse-submodules` / `git submodule update --init --recursive` does not download
   `exam_generator/Data/`.
2. The exact required paths, read directly from `backend/src/integration/generator_adapter.py::generator_paths()`:
   `exam_generator/Data/index/` and `exam_generator/Data/Course_Material_Summary.pdf`.
3. That data must stay Git-ignored (already covered by `exam_generator/.gitignore`: `Data/index/`,
   `Data/*.pdf`, etc.) and never be committed or pushed.
4. How to check availability safely: `GET /api/exam-jobs/readiness`, whose `local_data` check
   (`backend/src/integration/readiness.py`) reports only boolean presence of the index directory and the
   PDF (`index_dir.is_dir() and any(...)`, `pdf.is_file()`) — never file contents, never course text.
5. That missing data disables LLM generation only (`ready_for_llm: false`, blocking reason listed) and
   never blocks DB-only functionality (`db_only_available` is unconditionally `true` in
   `readiness_report()`).

No new bootstrap mechanism was created; no source content, prompt, or secret was read or exposed.

## 4. Fresh-clone data requirement (documented outcome)

A fresh clone of `questions-db` (even with `--recurse-submodules`) will have the pinned `exam_generator`
code but no `Data/` tree at all — `readiness_report()`'s `local_data` check will report
`index_dir=False, pdf=False` and block LLM generation with a safe reason, while every DB-only feature
(question bank, Excel import/export, DB-only test generation, analytics) keeps working immediately.
This is now stated plainly in both `ARCHITECT_HANDOFF.md` and `SETUP.md`, sourced from the actual
`readiness.py`/`generator_adapter.py` code rather than asserted.

## 5. Verification results

- **Diff is documentation-only.** `git status`/`git diff --stat` show exactly: `SETUP.md`,
  `WPs/ARCHITECT_HANDOFF.md`, `WPs/WP24_ARCHITECT_REPORT.md` modified, plus the two new files
  (this WP's brief, already untracked before editing, and this report). No other path touched.
- **No submodule gitlink change**: `git diff --stat -- exam_generator` is empty. **No
  `backend/src/integration/generator_pin.py` change**: `git diff -- backend/src/integration/generator_pin.py`
  is empty.
- **Both working trees were clean before this commit**, apart from the intended outer documentation
  files and this WP's own untracked brief (confirmed in Preflight, §1 above).
- No repository-specific Markdown/link/path sanity-check tooling exists in this repo (checked
  `package.json`, `scripts/`, no markdownlint/remark/link-check config found) — none was installed or
  run, per the brief's instruction not to add tooling for a documentation-only change.
- `git diff --cached --check` — one flag: a trailing blank line at EOF in
  `WPs/WP24D_Release_Documentation_Corrections.md`. That file is the owner's own pre-existing WP brief,
  committed as-is per §3's instruction to include "the WP brief" in this documentation commit; not
  edited by this WP. No whitespace issue in any file this WP authored or edited.
- **Staged-content audit**: the diff was inspected directly (`git diff`) for secrets, `.env*`,
  `Data/**` content, course text, provider responses, prompts, and audits. Every `Data/`-related line
  in the diff is a path *reference* in prose (e.g. "`exam_generator/Data/index/`") describing where
  data lives, never the data itself. No `.env*`, credential, prompt, response, or audit content
  appears anywhere in the diff.

## 6. Untouched-scope confirmations

- **Generator contents**: not modified. `git -C exam_generator status` unchanged, clean, at
  `eea91b06e2ec5d053eca3a5696656fdd354a05f9` throughout.
- **Submodule gitlink**: not staged/changed (confirmed §5).
- **`EXPECTED_GENERATOR_PIN`**: not changed (confirmed §5).
- **`OPENAI_API_KEY`**: never read, requested, or referenced by value; not accessed.
- **Local owner data**: `exam_generator/Data/` was only checked for existence (`ls`/`is_dir`/`is_file`
  equivalents) to verify the fresh-clone-vs-current-installation statement — never opened, read, copied,
  or modified.
- **`../exam_generator_pre_submodule_backup/`**: not touched, not referenced by any tool call.
- Neither backend nor frontend server was started at any point.

## 7. Outer commit and push

Committed the five documentation files listed in §2 as `WP24D: correct release documentation`.
Fetched outer `origin` and confirmed `origin/main` was an ancestor of local `main` with no divergence —
fast-forward safe. Pushed outer `main` normally (no force, no rebase, no merge).

Final outer commit SHA and push status are in the closing response below. Outer tree is clean and
`HEAD == origin/main`. Generator remains clean and unmoved at
`eea91b06e2ec5d053eca3a5696656fdd354a05f9`.
