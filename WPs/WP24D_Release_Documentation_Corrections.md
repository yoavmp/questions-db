# WP24D — Release Documentation Corrections

## Goal

Correct the WP24 release documentation and architect handoff without changing application behavior. Record the omitted outer release SHA, remove already-resolved issues from the active backlog, and document that `exam_generator/Data/` is local ignored owner data required for LLM generation on a fresh installation.

## Repository and scope

Work from the `questions-db` root. Modify and commit the **outer repository only**.

- Do not modify or commit anything inside the `exam_generator` submodule.
- Do not advance the submodule gitlink or change `EXPECTED_GENERATOR_PIN`.
- Do not touch `../exam_generator_pre_submodule_backup/`.
- Do not access `OPENAI_API_KEY`, start either server, or make provider/network calls.
- Do not change Python, JavaScript, configuration, prompts, tests, dependencies, database files, or generated artifacts.
- Do not add `Data/**`, extracted source text, the PDF, `.env*`, credentials, prompts, responses, or audits to Git.

Expected generator release SHA and outer gitlink:

`eea91b06e2ec5d053eca3a5696656fdd354a05f9`

## 1. Preflight

Before editing:

1. Record the full current outer `HEAD`; this is the omitted **WP24 outer release SHA**.
2. Confirm outer `HEAD == origin/main`, branch `main`, and the outer working tree is clean except for this WP brief if the owner placed it under `WPs/`.
3. Confirm the checked-out generator SHA, recorded gitlink, and `EXPECTED_GENERATOR_PIN` all equal the generator release SHA above.
4. Confirm the generator working tree is clean.

Stop and report without editing if there is unrelated drift, divergence, a different generator pin, or a dirty generator tree.

## 2. Correct the release documentation

Inspect the current files before editing. Make only the smallest necessary corrections.

### `WPs/WP24_ARCHITECT_REPORT.md`

- Add the exact WP24 outer release SHA captured during preflight.
- Correct the statement that production uses a **committed** `Data/index/`. The accurate statement is that production uses the pre-built, owner-local, Git-ignored data under `exam_generator/Data/`; it was copied into this installation out of band and is not included by cloning either repository.
- Correct the residual-limitations section transparently. State that these items are already resolved and are not open work:
  - reviewer repair-patch `term_id`/replacement resolution — resolved in WP23;
  - excessive explicit-disproof requirements for distractors — retired in WP23;
  - distractor answer-type alignment — added in WP23R.
- Preserve the dependency-pin split as an open item only if inspection confirms it still exists. Describe it as currently non-blocking and already handled by the documented integrated installation process.
- Mark these as post-release documentation corrections; do not disguise them as facts known before the original report was written.

### `WPs/ARCHITECT_HANDOFF.md`

Refresh the authoritative integrated-project state so a new architect conversation can continue from this file alone:

- record the WP24 outer release SHA and generator release SHA;
- state that WP24 is the functional release and all suites passed;
- remove the three resolved WP23/WP23R items from active/open work;
- state clearly that course source data and its derived index are local, ignored, and never committed;
- explain that the current installation is LLM-ready because its local data exists, while a fresh clone is DB-only until the owner restores or rebuilds the required `exam_generator/Data/` tree;
- retain only genuinely open, current limitations.

### Canonical setup documentation

Find the existing canonical installation/setup document (`SETUP.md`, README, or the document currently referenced by setup instructions) and add one concise section titled approximately **Local course data required for LLM generation**. Do not duplicate the same instructions across multiple documents.

The section must explain:

1. `git clone --recurse-submodules` does not download `exam_generator/Data/`.
2. The owner must securely copy or rebuild the expected local data at the exact paths required by the current readiness code.
3. The copied data must remain Git-ignored and must never be committed or pushed.
4. How to use the existing readiness endpoint/check to verify availability without printing course text or any secret.
5. Missing data blocks LLM generation but must not block DB-only exam functionality.

Derive exact paths and readiness behavior from the current code; do not guess, expose source contents, or create a new bootstrap mechanism in this WP.

## 3. Verification

- Confirm the diff contains documentation only: the WP brief, corrected report, refreshed handoff, canonical setup document, and the new architect report.
- Confirm no submodule gitlink or `backend/src/integration/generator_pin.py` change.
- Confirm both repository working trees were clean before the documentation commit, apart from intended outer documentation files.
- Run Markdown/link/path sanity checks that already exist, if any. Do not install tools or run full application suites for documentation-only changes.
- Run `git diff --check` and inspect the staged diff.
- Audit staged paths/content for secrets, `.env*`, `Data/**`, course text, provider responses, prompts, audits, and artifacts.

## 4. Report, commit, and push

Save Claude’s report as:

`questions-db/WPs/WP24D_ARCHITECT_REPORT.md`

The report must include:

- the previously omitted WP24 outer release SHA;
- exact files changed;
- each corrected false statement/open item;
- the documented fresh-clone data requirement;
- verification results;
- confirmation that generator contents, gitlink, expected pin, API key, local data, and backup were untouched;
- the final outer commit SHA and push status in Claude’s closing response.

Commit the intended outer documentation files with:

`WP24D: correct release documentation`

The owner authorizes a normal push of outer `main` only after fetching and proving fast-forward safety. Never force-push, rebase, merge through divergence, or push the generator repository. End with the outer tree clean and `HEAD == origin/main`; confirm the generator remains clean at the release SHA.

## Stop conditions

Stop and report instead of improvising if:

- correcting the documentation appears to require a code/configuration/test change;
- required local data is missing from the current installation;
- the exact required data paths cannot be established from existing code;
- either repository is dirty or diverged beyond the intended brief file;
- the generator SHA, gitlink, or expected pin differs from the release SHA.

