# WP24 — Final Metadata Fix and Release

## Scope

Complete one final generator-side false-rejection correction, fully verify both repositories, push the generator, pin that exact remote commit in `questions-db`, then push the outer repository.

Owner authorization: **Claude may push both repositories**. Do not force-push, rewrite history, tag a release, make live/provider calls, or access `OPENAI_API_KEY`.

Expected starting state:

- generator `exam_generator` HEAD: `85c0baf2c3fea747e0e3a342452acdddfdacb023`, clean and not pushed;
- WP23R code commit contained within it: `c490fca550a544df8bfbe93c705a656812daefcc`;
- outer `questions-db` HEAD begins `9350877d`; determine and record the full SHA;
- outer tree should differ only because the checked-out generator is ahead of the recorded submodule pin. Stop on other unexpected changes.

## Phase 1 — Final generator correction

### Policy

Extend WP23R's “public seven-field text is authoritative” rule to an unknown or malformed internal `concept_mentions.term_id`.

Internal concept declarations are disposable bookkeeping and must never independently reject valid public text:

- If the declared surface is actually displayed and uniquely resolves through the existing `TermSurfaceIndex`, validate it using the resolved real concept, regardless of whether the supplied ID is wrong or nonexistent.
- If a global surface ambiguity narrows to one concept through existing category scoping, use that concept.
- If the declaration is not displayed in its claimed field, drop it and record an audit diagnostic.
- If its surface/ID cannot be reconciled, ignore the declaration with an audit diagnostic; do not guess and do not use it as proof of validity.
- Continue validating the displayed public text independently. Unknown, misspelled, reordered, forbidden, category-inappropriate, or otherwise invalid displayed English must still block through the existing field/Latin-run checks.
- `english_required` remains enforced from actual displayed text, never from a declaration.
- Do not add fuzzy matching, aliases, inventories, LLM calls, or repeated inventory scans.

The intended boundary is simple: **bad hidden metadata is advisory; bad displayed text is blocking**.

### Focused tests

Add tests proving:

1. displayed valid permitted surface + nonexistent declared ID → resolved and accepted;
2. declaration with nonexistent ID but absent surface → dropped/advisory, not rejected;
3. displayed unknown Latin text remains rejected independently of metadata;
4. ambiguous surface is category-resolved only when unique, otherwise never guessed;
5. diagnostics remain internal and the public output is exactly seven fields;
6. WP23R Ectoderm, Neural Tube, and Foramen Magnum outcomes remain unchanged;
7. no provider/network call and no new call in the production contract.

Run focused tests, then the complete generator suite serially once with `OPENAI_API_KEY` unset. Do not weaken unrelated protections or tests.

### Generator documentation and commit

Inside `exam_generator/WPs/`, save:

- a copy of this brief as `WP24_Final_Metadata_Fix_And_Release.md`;
- `WP24_GENERATOR_REPORT.md`;
- refreshed `ARCHITECT_HANDOFF.md`.

Commit generator changes with subject:

```text
WP24: make internal concept ids advisory
```

Before pushing:

- inspect the staged diff and secret-sensitive paths;
- confirm no `Data/`, `artifacts/`, `.env*`, credentials, rendered protected prompts, or raw provider responses are staged;
- fetch generator `origin`;
- prove `origin/main` is an ancestor of local `main` and that no divergence exists.

Push generator `main` normally. Stop rather than force if it is not fast-forward safe. Verify local generator `HEAD == origin/main`, record the full SHA, and confirm the generator tree is clean.

## Phase 2 — Outer integration release

Only after the generator push is verified:

1. Confirm the checked-out submodule commit is exactly the newly pushed generator SHA.
2. Verify that commit is reachable from the generator remote.
3. Stage the `exam_generator` gitlink so the outer repository records that exact SHA.
4. Do not vendor generator files into the outer repository.
5. Do not modify or delete `../exam_generator_pre_submodule_backup`.

Save in outer `questions-db/WPs/`:

- `WP24_Final_Metadata_Fix_And_Release.md`;
- `WP24_ARCHITECT_REPORT.md`;
- refreshed `ARCHITECT_HANDOFF.md`.

The outer report is the authoritative combined release report. Avoid duplicating raw reports or live artifacts between repositories.

## Phase 3 — Final verification

Run the repository's established commands, serially where required:

- generator complete test suite;
- outer backend complete test suite;
- frontend complete test suite;
- frontend production build;
- any existing offline submodule/readiness/adapter contract tests.

No live LLM test is required: WP23R already completed the authorized brainstem live test successfully. Make zero provider calls in WP24.

Verify:

- canonical category order and all 20 categories remain unchanged;
- public generated-question schema remains exactly seven fields;
- full-exam and LLM-only Excel exports retain their established schemas;
- DOCX generation remains intact;
- both replacement buttons remain available for every accepted question;
- initial A/B/C quotas and later free replacement behavior remain intact;
- retry/cost/audit telemetry behavior remains intact;
- ignored owner data, live audits, API credentials, and backup remain untouched;
- `.gitmodules` points to the correct generator repository;
- outer recorded gitlink equals generator remote `main` HEAD.

If a test fails, diagnose it. Do not push the outer repository until all production-gating tests pass. Do not make unrelated cleanup changes.

## Phase 4 — Outer commit and push

Stage only the intended outer files: updated generator gitlink, WP24 brief/report, and refreshed handoff, plus any strictly necessary integration correction exposed by tests. List every staged file in the report.

Run a staged-diff credential/artifact audit. Commit with subject:

```text
WP24: release integrated exam generation
```

Fetch outer `origin`; prove `origin/main` is an ancestor of local `main`. If history diverged, stop and report—do not merge, rebase, or force-push without owner direction.

Push outer `main` normally. Verify:

- outer local `HEAD == origin/main`;
- generator local `HEAD == generator origin/main`;
- outer recorded gitlink equals that generator SHA;
- both working trees are clean;
- `git submodule status` has no `+`, `-`, or `U` prefix.

## Stop conditions

Stop before the affected push if:

- either repository has unexpected changes;
- either remote has diverged;
- a production-gating test/build fails;
- the generator commit is not remotely reachable;
- the submodule pin does not match the pushed generator SHA;
- a secret, protected source, live artifact, or raw provider material would be staged;
- completion would require force-push, history rewriting, destructive cleanup, or new live API use.

## Final report and response

Explain in owner-readable language:

- the unknown-ID correction and why displayed-text safeguards remain strict;
- focused and complete generator test results;
- backend/frontend/build results;
- exact generator release SHA and exact outer release SHA;
- confirmation both were pushed and match `origin/main`;
- exact recorded submodule pin and clean status;
- every committed file in both repositories;
- skipped tests and whether any affect production;
- confirmation of zero provider calls and no credential/artifact leakage;
- any residual limitation or follow-up that genuinely remains.

