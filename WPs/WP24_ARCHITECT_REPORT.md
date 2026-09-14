# WP24 — Final Metadata Fix and Release — Architect Report

This is the authoritative combined release report for both repositories. Zero live/provider calls
anywhere in this WP; `OPENAI_API_KEY` was never accessed.

## 1. Preflight

- Outer `questions-db` HEAD at start: `9350877d739de21efb849b3311bdf9868da45812` ("WP22: targeted
  live evidence validation"). Working tree at start: `M exam_generator` (the already-known advanced
  submodule checkout, at that point WP23R's `85c0baf2c3fea747e0e3a342452acdddfdacb023`) + `??
  WPs/WP24_Final_Metadata_Fix_And_Release.md` (this WP's own brief). No other drift — matches the
  brief's expected starting state exactly.
- Generator `exam_generator` HEAD at start: `85c0baf2c3fea747e0e3a342452acdddfdacb023` (WP23R,
  containing `c490fca550a544df8bfbe93c705a656812daefcc` "WP23R: trust public text and validate
  brainstem"), clean, not pushed — matches the brief exactly.
- No `OPENAI_API_KEY` was displayed, requested, read, or stored at any point. Every test run in
  both repositories explicitly `unset OPENAI_API_KEY` first.

## 2. Phase 1 — Generator correction (offline)

Full detail in `exam_generator/WPs/WP24_GENERATOR_REPORT.md`; summary here.

### The fix

WP23R made the public seven-field text authoritative over the generator's own internal
`concept_mentions` bookkeeping for a declared-but-wrong `term_id` — except for one case it
explicitly left as a hard rejection: a declared `term_id` that does not exist in the terminology
inventory at all. `term_validator.validate_generated_text` (generator repo) now reconciles that case
identically to an existing-but-wrong one:

- surface not actually displayed in its declared field → dropped, non-blocking
  (`declared_mention_dropped_not_displayed`);
- surface displayed and it resolves to exactly one permitted concept (directly, or via the existing
  category scoping for a global ambiguity) → corrected for validation purposes
  (`declared_mention_term_id_corrected`);
- surface displayed but irreconcilable (no reverse index supplied, zero match, or an ambiguity
  category scoping cannot narrow) → ignored with an audit diagnostic, never guessed
  (`declared_mention_unreconciled_unknown_term` / `declared_mention_ambiguous_unresolved`).

None of these ever produce a `violations` entry. The independent per-field Latin/Hebrew scans that
decide whether the *displayed* text itself is valid are completely untouched — unknown, misspelled,
reordered, forbidden, category-inappropriate English, and `english_required` enforcement all still
block regardless of what any declaration says. The rule, now fully closed: **bad hidden metadata is
advisory, bad displayed text is blocking.** No fuzzy matching, alias table, or LLM/embedding call was
added; the reconciliation reuses the same `TermSurfaceIndex` built once per generation call, O(1) per
mention.

### Tests

New `exam_generator/tests/test_wp24_unknown_declared_id.py` (10 tests) proves every case the brief
asked for: displayed-surface resolution, absent-surface drop, displayed-invalid-text still rejects
(cross-category and altered-capitalization variants), category-narrowed ambiguity resolution,
category-unresolved ambiguity never guessing, zero-match never guessing, no-`reverse_index` never
guessing, diagnostics never entering the seven-field public schema, and the validator's call
signature/provider-freedom unchanged. One pre-existing test was updated per this WP's own required
outcome change (`test_term_validator.py::test_declared_concept_mention_unknown_term_fails` →
`..._is_advisory_not_rejected`) — not weakened, since accepting this case is exactly what the brief
requires. WP23R's three preserved regression candidates (Ectoderm, Neural Tube, Foramen Magnum) were
re-run unmodified and are unaffected — none of their fixtures declare a nonexistent `term_id`.

Focused suite: all pass. Complete generator suite, serial, `OPENAI_API_KEY` unset: **999 collected,
825 passed, 174 skipped, 0 failed, 0 errors** (baseline after WP23R: 989/815/174 — exactly 10 net new
tests). The 174 skips are the unchanged, already-diagnosed Data-dependent/macOS-font set; none gate
production. Zero network or provider calls anywhere in the run.

### Generator commit and push

Before committing: staged diff inspected (`git diff --cached --stat`) — exactly six files, all
source/test/doc, no `Data/`, `artifacts/`, `.env*`, credential, rendered protected prompt, or raw
provider response. Fetched generator `origin`; confirmed `origin/main` (`ea59cd857e5618b0260d2bb146dd5573c9ca2309`,
WP17GR) is an ancestor of local `main` with no divergence — fast-forward safe.

Committed as `WP24: make internal concept ids advisory`, pushed to generator `origin/main` (normal
push, no force). Verified after push: generator local `HEAD == origin/main ==
eea91b06e2ec5d053eca3a5696656fdd354a05f9`, working tree clean.

## 3. Phase 2 — Outer integration release

- Checked-out submodule commit (`git -C exam_generator rev-parse HEAD`) is exactly
  `eea91b06e2ec5d053eca3a5696656fdd354a05f9` — the newly pushed generator SHA.
- Reachability confirmed: `git -C exam_generator fetch origin && git rev-parse origin/main` returns
  the identical SHA — the commit is on the generator remote, not just local.
- Staged only the `exam_generator` gitlink (`git add exam_generator`) — no generator file was
  vendored into the outer tree.
- `../exam_generator_pre_submodule_backup/` was not touched (verified untouched, timestamps
  unchanged from before this WP).
- One "strictly necessary integration correction exposed by tests" (Phase 4's own allowance):
  `backend/src/integration/generator_pin.py::EXPECTED_GENERATOR_PIN` was updated from
  `ea59cd857e5618b0260d2bb146dd5573c9ca2309` (WP17GR, stale since WP21GR — five WPs of known,
  previously-accepted drift, e.g. WP22 §1: "deliberately left as-is") to the new
  `eea91b06e2ec5d053eca3a5696656fdd354a05f9` (WP24), with its label updated to match.
  `tests/test_wp18_readiness.py::test_submodule_pin_check_matches_recorded_pin` was the one backend
  test failing before this correction (confirmed pre-existing and unrelated to any WP24 code
  change — it fails identically at the untouched WP22 baseline, since the pin has been stale since
  WP21GR); it and the rest of the readiness suite pass cleanly after the one-line + one-comment fix.
  This closes the long-standing `submodule_pin` drift warning entirely, not merely working around it.

## 4. Phase 3 — Final verification

All commands run serially, `OPENAI_API_KEY` unset throughout.

| Suite | Result |
|---|---|
| Generator complete suite | 999 collected, 825 passed, 174 skipped, 0 failed, 0 errors |
| Outer backend complete suite | 121 collected, **121 passed**, 0 skipped, 0 failed, 0 errors (includes `test_wp18_readiness.py` and every existing offline submodule/readiness/adapter contract test) |
| Frontend complete suite (`npm test`) | 3 test files, **81 passed**, 0 failed |
| Frontend production build (`npm run build`) | Succeeded — `dist/` emitted (git-ignored, not staged); one pre-existing cosmetic CSS-minify warning, not a build error |

Verified, via the passing backend/frontend suites plus direct inspection:

- **Canonical category order / 20 categories** — `tests/test_wp17_category_contract.py`,
  `tests/test_wp17_test_categories_route.py`, `tests/test_wp17_generator_adapter.py` unchanged and
  passing; `category_mapping.ok: true, count: 20` in the live `readiness_report()` output reproduced
  during this WP.
- **Public generated-question schema is exactly seven fields** — reconfirmed directly:
  `FinalQuestion.model_fields == production._PUBLIC_FIELDS`, length 7 (generator's own
  `test_wp24_unknown_declared_id.py::test_diagnostics_never_enter_the_seven_field_public_schema`).
- **Full-exam and LLM-only Excel exports** — `tests/test_wp17_excel_upload_compat.py`,
  `tests/test_wp18_cost_and_export.py`, `tests/test_wp21_analytics_and_exports.py` unchanged and
  passing (schema order, round-trip upload, missing-value convention).
- **DOCX generation** — `tests/test_wp17_test_categories_route.py`'s `/api/test/export-docx` coverage
  unchanged and passing.
- **Both replacement buttons for every accepted question** — `tests/test_wp18_replacements.py`,
  `tests/test_wp18r_cross_source_replacements.py` unchanged and passing.
- **Initial A/B/C quotas and later free replacement behavior** — `tests/test_wp18_job_lifecycle.py`,
  `tests/test_wp18_persistence.py` unchanged and passing.
- **Retry/cost/audit telemetry** — `tests/test_wp20_terminal_cost_log.py`,
  `tests/test_wp21r_audit_hardening.py`, `tests/test_wp20_semantic_history_boundary.py` unchanged and
  passing.
- **Ignored owner data, live audits, API credentials, and backup remain untouched** — `git status`
  shows no change under `backend/artifacts/`, `exam_generator/Data/`, any `.env*`, or
  `../exam_generator_pre_submodule_backup/` at any point in this WP.
- **`.gitmodules` points to the correct generator repository** —
  `https://github.com/yoavmp/exam-generator.git`, unchanged, matches both remotes' actual `origin`.
- **Outer recorded gitlink equals generator remote `main` HEAD** —
  `eea91b06e2ec5d053eca3a5696656fdd354a05f9` on both sides, confirmed in §3.

No test failed after the one integration correction in §3; no unrelated cleanup was made.

## 5. Phase 4 — Outer commit and push

Staged exactly:

- `exam_generator` (gitlink update only, no vendored files)
- `WPs/WP24_Final_Metadata_Fix_And_Release.md` (new)
- `WPs/WP24_ARCHITECT_REPORT.md` (new, this report)
- `WPs/ARCHITECT_HANDOFF.md` (refreshed)
- `backend/src/integration/generator_pin.py` (the one strictly-necessary integration correction, §3)

Staged-diff credential/artifact audit: no `.env*`, no credential file, no `artifacts/exam_jobs/*`
content, no `Data/` content, no raw provider response staged — confirmed by `git diff --cached
--stat` naming only the five paths above plus the gitlink.

Committed as `WP24: release integrated exam generation`. Fetched outer `origin`; confirmed
`origin/main` is an ancestor of local `main` with no divergence — fast-forward safe, no merge/rebase
needed. Pushed outer `main` normally (no force).

Post-push verification:

- outer local `HEAD == origin/main`: confirmed — exact SHA in §6 below;
- generator local `HEAD == generator origin/main`: confirmed,
  `eea91b06e2ec5d053eca3a5696656fdd354a05f9`;
- outer recorded gitlink equals that generator SHA: confirmed;
- both working trees clean: confirmed;
- `git submodule status` shows no `+`, `-`, or `U` prefix: confirmed (plain, in-sync).

## 6. Release SHAs

- **Generator release SHA:** `eea91b06e2ec5d053eca3a5696656fdd354a05f9` — pushed to
  `https://github.com/yoavmp/exam-generator.git` `main`.
- **Outer release SHA:** `9b250145260c450ec7511660c809fefd00e98001` — the `WP24: release integrated
  exam generation` commit, pushed to outer `origin/main`.
  *(Post-release correction, WP24D: this report originally omitted the value here, pointing only to
  "the closing terminal response"; the SHA is recorded above from that same response.)*

## 7. Skipped tests

The 174 generator skips are the unchanged, already-diagnosed set carried through every prior WP
(§3g of `exam_generator/WPs/ARCHITECT_HANDOFF.md`): synthetic-PDF extraction tests needing a
Windows/Linux Hebrew TTF font this macOS box doesn't have (~70), and owner-local live-run replay
fixtures under `exam_generator/artifacts/` not present in this checkout (~100) — production reads the
pre-built `exam_generator/Data/index/` directly, never re-extracts, and none of these are needed for or
gate production. Zero skips in the outer backend or frontend suites this WP.
*(Post-release correction, WP24D: this paragraph originally called `Data/index/` "committed." It is
not: `exam_generator/Data/` is owner-local, Git-ignored data — see §9's corrected residual limitations
and the canonical setup document's "Local course data required for LLM generation" section — copied
into this installation out of band and not obtained by cloning either repository.)*

## 8. Confirmations

- **Zero provider calls**: every test command in both repositories explicitly `unset
  OPENAI_API_KEY` before running; the generator's own new tests additionally assert the validator's
  module source names no HTTP/provider library and its call signature is unchanged.
- **No credential/artifact leakage**: confirmed at both the generator commit (§2) and the outer
  commit (§5) staged-diff audits, and by `git status` showing no change under any ignored
  data/credential/audit path throughout.

## 9. Residual limitations

*(Post-release correction, WP24D: this section originally carried two WP22-surfaced items forward as
still open. Both were in fact already resolved, before this report was written, by generator-side WPs
this report never cross-checked against. Corrected below rather than left standing.)*

None introduced by this WP. Of the items WP22 surfaced as open (`WPs/ARCHITECT_HANDOFF.md` §"Open
items"):

- a reviewer repair patch's `term_id` vs. its own replacement text — **resolved in WP23**
  (`TermSurfaceIndex` / `repair.resolve_reviewer_patch_term_id`, §1 of
  `exam_generator/WPs/WP23_ARCHITECT_REPORT.md`);
- the reviewer's explicit-disproof strictness for a distractor already correctly excluded by evidence
  — **retired in WP23** (review-prompt criterion 4 rewrite, §4 of the same report), and further
  sharpened by a new general distractor answer-type-alignment requirement **added in WP23R** (§2 of
  `exam_generator/WPs/WP23R_ARCHITECT_REPORT.md`).

Neither is open work as of this release. The one item still genuinely open and unrelated to WP24's
scope is the pre-existing `backend/requirements.txt`/`exam_generator/constraints.txt` dependency-pin
split (`pytest` 7.4.2 vs. 9.1.1; `MarkupSafe` 2.1.3 vs. 3.0.3) — currently non-blocking and already
handled by the documented integrated installation process (`scripts/dev_install.sh` installs the
generator package `--no-deps` and keeps the backend's own pins; see `SETUP.md`).
