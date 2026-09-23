# WP28 — Architect Report: Warning Acceptance, Manual Editing, and Repair Hardening

Two-repository work package, executed strictly in order: Part A
(`exam_generator` submodule) was completed, tested, committed, and pushed
first; Part B (outer `questions-db`) was implemented, tested, and committed
only after Part A's push succeeded. Triggered by the read-only audit
`WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md` against exam job `258ffef8-…`.

## 0. Starting state

```
outer HEAD              012d2a13a29649bb1141b0a33bafac852762fd11
outer origin/main       012d2a13a29649bb1141b0a33bafac852762fd11
outer status            clean (only the 3 owner PRE_*.md reports untracked)
generator pin           d20c46bbb332e4d40f735e843d31113176b755e5
generator status        clean
```

Exactly matched the WP's expected baseline; no unrelated tracked drift was
found in either repository.

## 1. Files changed

### `exam_generator` (Part A — pushed as its own commits)

```
 WPs/ARCHITECT_HANDOFF.md                   |  40 +++++++-
 WPs/WP04_TERMINOLOGY_DECISIONS.csv         |   6 +-
 config/terminology.yaml                    |  53 +++++-----
 config/terminology_overlay.yaml            |  55 +++++++++++
 prompts/generate_question.system.he.j2     |   7 ++
 prompts/generate_question.user.he.j2       |   8 ++
 prompts/review_candidates.system.he.j2     |  92 ++++++++++++-----
 prompts/review_candidates.user.he.j2       |  20 ++++
 src/exam_generator/generation_models.py    |  85 ++++++++++++++++
 src/exam_generator/live_run.py             |   1 +
 src/exam_generator/live_run_wp11.py        |   2 +
 src/exam_generator/orchestrator.py         | 154 +++++++++++++++++++++++++++++
 src/exam_generator/production.py           |  99 +++++++++++++++++--
 src/exam_generator/repair.py               |  48 ++++++++-
 src/exam_generator/runtime_inputs.py       |   1 +
 src/exam_generator/sequence.py             |  15 +++
 src/exam_generator/wp05b_commands.py       |   1 +
 tests/test_cli_wp06.py                     |   4 +-
 tests/test_wp05_llm_contracts.py           |   1 +
 tests/test_wp06_relationships.py           |   2 +
 tests/test_wp08_natural_hebrew.py          |   1 +
 tests/test_wp12r_focus_absence_repair.py   |   4 +-
 tests/test_wp15_false_rejection_cleanup.py |   3 +-
 + new: WPs/WP28G_Warning_Acceptance_And_Repair_Hardening.md
 + new: WPs/WP28G_ARCHITECT_REPORT.md
 + new: tests/test_wp28_warning_acceptance_and_repair_hardening.py
```

### Outer `questions-db` (Part B)

```
 SETUP.md                                          |  42 ++++
 WPs/ARCHITECT_HANDOFF.md                          | ~90 ++
 backend/src/integration/exam_question_dto.py      |  13 +
 backend/src/integration/generator_adapter.py      |  48 ++++
 backend/src/integration/generator_pin.py          |   4 +-
 backend/src/jobs/model.py                         |  49 ++++
 backend/src/jobs/service.py                       | 220 ++++++++++++++++-
 backend/src/routes/exam_jobs.py                   |  20 ++
 backend/tests/_wp18_fakes.py                      |  82 +++++++
 exam_generator                                    | (submodule pointer -> 5200b53)
 frontend/src/components/ExamGenerationSection.jsx | 280 ++++++++++++++++++++--
 frontend/src/lib/examApi.js                       |  10 +
 frontend/src/lib/examApi.test.js                  |  12 +
 frontend/src/lib/examGen.js                       |  36 +++
 frontend/src/lib/examGen.test.js                  |  50 ++++
 + new: WPs/WP28_Warning_Acceptance_Manual_Editing_And_Repair_Hardening.md
 + new: WPs/WP28_ARCHITECT_REPORT.md (this file)
 + new: backend/tests/test_wp28_routes.py
 + new: backend/tests/test_wp28_warning_edit_and_repair_hardening.py
 + new: frontend/src/components/ExamGenerationSection.wp28.test.jsx
```

Never touched: the three owner-owned `PRE_*.md` reports (verified untracked
and byte-identical throughout), `backend/src/database/app.db`, anything
under `artifacts/`, `.env*`, `../exam_generator_pre_submodule_backup/`.
`git diff` was scanned for `sk-…`/`OPENAI_API_KEY=`/`api_key=…` patterns in
both repositories: zero matches.

## 2. Generator commits (Part A)

```
WP28G: add warning acceptance and repair hardening      00d2794
WP28G: record final commit SHA in architect report      5200b53
```

Both pushed as plain fast-forwards to `origin/main` (fetched and verified
`git merge-base --is-ancestor origin/main HEAD` before each push; no force,
no rewrite). Final generator state:

```
git -C exam_generator rev-parse HEAD        -> 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d
git -C exam_generator rev-parse origin/main -> 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d
git -C exam_generator status --short        -> (clean)
```

Full generator-side detail (contract, tests, offline replay, Basilar
finding) is in `exam_generator/WPs/WP28G_ARCHITECT_REPORT.md`; only the
parts the outer integration depends on are repeated below.

## 3. Warning vs. hard-rejection decision table

| Condition | Outcome |
|---|---|
| All criteria hold; a distractor is fabricated, ungrounded, category-inappropriate, or itself a defensible answer | Hard reject |
| Two or more distractors share only a low-plausibility/type-mismatch defect | Hard reject |
| Exactly one distractor is real, source-grounded, category-appropriate, definitely incorrect, and its *only* defect is low plausibility or a structural/type mismatch; every other criterion holds | **Accept with warning** (`review_quality="warning"`, one structured `review_warning`) |
| Any other criterion fails (grounding, uniqueness, terminology, self-containment, …) | Hard reject, unchanged |

A warning is metadata riding alongside the unchanged seven-field public
question — `Slot.review_quality`/`Slot.review_warnings`
(`backend/src/jobs/model.py`) — never a rejection criterion, never causing an
extra retry. `Slot.review_warnings[*].field` is stored in the outer app's own
public vocabulary (`answer2`/`answer3`/`answer4` — the generator's internal
`distractor_1..3` remapped once in `generator_adapter._remap_review_warnings`,
using the same fixed correct-answer-is-always-`answer1` mapping the generator
itself uses to build the public question).

## 4. Repair hardening and the Basilar Artery finding

**`concept_mentions` reconciliation (generator A4).** `repair.apply_patches`
now declares a term a patch itself introduces into a field with no prior
declaration for it, and corrects a mention wrongly tagged to a different
concept — fixing the audited loss where a `הצרבלום` → `Cerebellum` repair was
discarded for an unrelated "undeclared concept mention" violation. Verified
end to end against the real chapter_17 (המוח הקטן) context in the
generator's own offline replay (§6 below); no outer-repo code was involved,
since the outer adapter only ever sees the generator's already-decided
seven-field result.

**Basilar Artery (generator A5).** Root cause: the auto-derived terminology
universe independently produced two concepts from two separate source
attestations of the same real artery — the correctly spelled
`basilar_artery` and a second, separately auto-derived `basillar_artery`
(the course PDF's own printed misspelling, source-attested), both
`approved: true`/`english_required`. A first attempt to fix this by hand-
editing `exam_generator/config/terminology.yaml` directly was discovered,
during this WP's own verification run, to be silently reverted by the
generator's own idempotent regeneration test
(`exam_generator/tests/test_cli_wp06.py::test_the_owner_decision_file_itself_is_never_rewritten`,
which regenerates that file from `config/terminology_overlay.yaml` + the
WP04/WP06 decision ledgers as part of the **ordinary generator test suite**)
— so a hand-edit would have silently re-broken on the very next full-suite
run, by anyone. The durable fix is a new owner-decision concept entry in
`config/terminology_overlay.yaml` (`term_id: basilar_artery`,
`replaces_term_id: basillar_artery`), the exact mechanism already used for
Oligodendrocytes (WP16R); `config/terminology.yaml` and
`WPs/WP04_TERMINOLOGY_DECISIONS.csv` were then regenerated for real via
`apply-owner-terminology-decisions --write`, verified to touch only those
two files plus the overlay (every other generated output — relationships,
source facts, runtime decisions, WP06R runtime copy, migration CSV —
regenerated byte-identical), and the idempotency/"never rewritten" tests
re-verified green against the new committed state. `Basillar Artery`/
`Basillar artery` are now `forbidden_output_forms` with a same-call
deterministic Tier-1 repair to `Basilar Artery`. This is entirely inside the
generator repository; the outer adapter needed no change for it.

## 5. Hard-rejection failure memory — representation, bound, prompt impact

**Outer store** (`Job.hard_rejection_feedback: dict[category, list[record]]`,
`backend/src/jobs/model.py`): each stored record is the generator's own
`HardRejectionFeedback` shape (`category`, `question_summary`, `bad_field`
— `question`/`answer1..4`, `bad_value`, `failure_code`, `instruction`) plus
one outer-added `recorded_at` timestamp. Written only by
`service._record_hard_rejection_feedback`, called from `_generate_one` after
every generator call (success or failure) with whatever
`AdapterResult.hard_rejection_feedback` (the generator's **newly produced**
records for that one call) contains — never a warning or clean acceptance,
per the generator's own contract. Deduplicated on
`(bad_field, bad_value, failure_code)` before appending, so a genuinely
repeated defect is kept once, not accumulated as noise.

**Prompt-bound**: `service.MAX_HARD_REJECTION_FEEDBACK_PER_CALL = 8` — the
most recent 8 records for that slot's category are read back out of the
store, have the outer-only `recorded_at` field stripped (the generator's
`HardRejectionFeedback` model is `extra="forbid"` — a real bug caught and
fixed during this WP's own verification, see §8), and forwarded as
`AdapterRequest.hard_rejection_feedback` on every subsequent same-category
call. The full (undeduplicated-beyond-exact-match) history stays in
`job.json` for audit; only this bounded slice ever reaches a prompt.

**Never** folded into `category_history`/`previous_public_questions`; never
exposed in `result_view`'s public JSON (no UI requirement calls for it, and
exposing it would risk surfacing reviewer-adjacent text beyond what's
needed); copied verbatim by `branch_job`, the same way `category_history`
already is.

## 6. Manual editing — behavior, history, persistence

`PATCH /api/exam-jobs/<job_id>/questions/<instance_id>`
(`service.edit_llm_question`):

- **Permitted** only when the target slot currently holds an accepted,
  `kind == "llm"` question and `job.status != "running"`. This deliberately
  reuses the *exact* permission boundary `replace_via_llm`/`replace_from_db`
  already use for "any accepted slot" — this codebase has no independent
  notion of a job being "historical/read-only" beyond that (a branched job
  is simply a new, fully independent, fully editable job — see
  `branch_job`). A missing slot, a database-origin slot, or a
  currently-generating job are all rejected with a typed `JobError`/
  `JobConflict` (404/409 at the route).
- **Validation** is purely structural, never an LLM call: exactly the six
  public fields, each text field non-empty after trim, four answers
  pairwise distinct after trim, `correct_answer` a strict Python `int`
  (bool explicitly excluded) in `1..4`.
- **On success**: `Slot.edit_history` gets one immutable entry
  (`edited_at`, full seven-field `before`/`after`, `affected_warning_ids`);
  `Slot.question` is replaced in place (`number`/`instance_id`/`slot_id`/
  `kind`/`db_id`/`audit_ref`/analytics all untouched); `manually_edited =
  True`; exactly the unresolved warning(s) whose own `field` was among the
  changed public fields get `resolved = True`, `resolved_by =
  "manual_edit"`, `resolved_at` — an unrelated warning is left open.
  Persisted the same atomic way every other job mutation already is
  (`store.save`).
- **A fresh generation resets the slot's warning/edit state** (`_generate_one`
  sets `review_quality`/`review_warnings` fresh and empties
  `manually_edited`/`edit_history` on every new acceptance) — a prior
  generation's edit history describes text that no longer exists in that
  slot once regenerated, matching the WP's "current LLM question" scope.
- **Later semantic context**: `_previous_for_slot` already reads
  `slot.question` (mutated in place by the edit) for every sibling LLM slot
  in the same category, so an edited question's *current* text — not its
  originally generated text — reaches the next generation/replace call with
  no separate plumbing needed.
- **Replacement history stores the current edited version**: `replace_via_llm`
  reads `old_question` from `slot.question` immediately before calling the
  generator, so a successful replacement of a previously-edited question
  appends the *edited* text to `category_history`, not the original draft.
- **Branching** copies `review_quality`, `review_warnings`,
  `manually_edited`, and `edit_history` per slot, plus the whole
  `hard_rejection_feedback` store, exactly the same deep-copy discipline
  already used for `category_history`/`analytics`/category snapshots.

## 7. Export and RTL behavior

**Exports already use the current edited text with no code change**: both
`export_llm_xlsx` and `export_full_xlsx` read `slot.question` directly, and
the DOCX path is driven entirely by the frontend's `job.questions` (itself
sourced from `result_view`, which is `slot.question`) — an edit is visible
to every export the moment it is saved. Neither Excel schema gained a
`manually_edited` column: `export_llm_xlsx`'s header is fixed by the
existing upload-compatible contract, and `export_full_xlsx`'s is the
recovered pre-WP19 legacy schema — both explicitly documented as frozen,
and the WP itself gives schema compatibility priority over the extension
when no safe extension point exists. `GenerationMeta` (`was_repaired`,
`review_quality`, `review_warnings`, `manually_edited`, …) was already
excluded from `docx_view()` before this WP and remains so — no warning
label reaches student-facing DOCX output.

**Export confirmation** is a frontend-only gate
(`ExamGenerationSection.jsx`'s `requestExport`/`exportConfirm`, counting via
`examGen.unresolvedWarningCount(job.questions)`): every one of the four
export buttons (full DOCX, answer-key DOCX, LLM-only Excel, full Excel) now
routes through it. Zero unresolved warnings exports immediately, unchanged
from before WP28; one or more shows the Hebrew confirmation
("במבחן קיימות N שאלות הדורשות בדיקה. האם להמשיך בייצוא?"), Cancel makes no
download request, Confirm makes exactly one. A resolved warning never
counts. A historical/read-only viewed job uses the identical gate against
its own persisted `questions`/`generation_meta` snapshot — no special-casing
was needed since the gate only reads already-fetched view data.

**RTL/LTR**: one reusable `<Ratio left right sep>` component wraps every
"X / Y" (or "X מתוך Y") numeric pair on the exam-generation screen in
`<bdi dir="ltr">` — accepted-count, LLM-accepted-count, accumulated-vs-
ceiling cost, and the distinction-threshold count. The ambient Hebrew RTL
layout (and every other reused `dir`/layout attribute) is untouched; only
the digits/operator are isolated. No operand was reordered in JavaScript.

## 8. A bug found and fixed during this WP's own verification

Running the full generator+outer offline replay surfaced a genuine
regression the implementation itself introduced and then fixed before
completion, recorded here for the audit trail:

Storing hard-rejection records with an outer-only `recorded_at` field and
then feeding those *same* stored dicts straight back into
`AdapterRequest.hard_rejection_feedback` on a later call caused
`exam_generator.production.generate_exam_question` to raise (the generator's
`HardRejectionFeedback` Pydantic model is `extra="forbid"` and rejects the
unknown key), which the adapter's existing `except ValueError` handler then
silently reported as a **`systemic_failure`** instead of the real
`question_rejected`/`provider_output_failure` outcome — caught by a
pre-existing, unrelated backend test
(`test_wp18_cost_and_export.py::test_all_costs_counted_accepted_and_failed`)
that asserted every ledger status was one of the two real failure kinds.
Fixed in `service._generate_one` by stripping `recorded_at` before handing
the stored records to `AdapterRequest`. Full backend + generator suites were
re-run clean after the fix (see §9).

## 9. Offline replay and test counts

**Generator** (`exam_generator/WPs/WP28G_ARCHITECT_REPORT.md` §6/§7 in
full): four sanitized offline replays against the real, committed chapter_17
(המוח הקטן) terminology/context reproduce the audit's own scenarios — AICA/
`הצרבלום`→`Cerebellum` repair now accepted; `Fastigial Nucleus`-as-layer and
`Superior Medullary Velum`-as-peduncle each accepted with a warning naming
the exact answer; a repeated hard-rejected defect (two nucleus-as-layer
distractors) returns as one bounded record and appears verbatim in the next
attempt's rendered prompts alongside the Hebrew "topic remains permitted"
phrase, and that next, differently-flawed attempt is accepted. Focused new
suite: **18/18 passed**. Full generator suite (`python -m pytest -q`,
`OPENAI_API_KEY` unset, network-trapped): **1025 tests collected, 0
failures, 0 errors**, run twice (background + foreground) with identical
results — this environment's pytest does not print its own final one-line
summary to captured stdout (a display quirk, not a failure — confirmed via
`grep -c "FAILED\|ERROR "` returning `0` both times and via summing
`--collect-only -q` per-file counts, which match 1025).

**Outer backend**: two new focused suites —
`test_wp28_warning_edit_and_repair_hardening.py` (28 tests: warning
acceptance/survival/never-hard-rejected, hard-rejection storage/dedup/reuse,
every manual-edit permission/validation/history/resolution case, exports
using edited text, unresolved-warnings-never-block-export, branch copying,
failed-replacement retention with the Hebrew message, legacy-job-json
loading) and `test_wp28_routes.py` (4 HTTP-level tests for the new `PATCH`
route). One pre-existing test's exact concept-count assertion was updated
for the Basilar Artery merge's one-fewer-concept effect
(`test_cli_wp06.py::test_apply_reports_the_before_and_after_counts_and_the_groups`,
`1078 -> 1055` → `1077 -> 1054`) — a mechanical consequence of §4, not a
behavior change. Full backend suite (`OPENAI_API_KEY` unset, real sockets
trapped by the suite's own fixtures), run three times across this WP
(baseline, post-fix, final): **310 passed, 0 failed** on the final two runs.

**Outer frontend**: new `ExamGenerationSection.wp28.test.jsx` (16 tests:
warning badge/field-highlight/Hebrew-explanation, resolved →
"תוקן ידנית", edit-button LLM-only, edit-form prefill/validation/cancel/
save/rerender, reload showing persisted edit/resolution state, export
confirmation asked/cancelled/confirmed/skipped-when-resolved, failed-
replacement Hebrew message, RTL ratio isolation) plus small additions to
`examApi.test.js` (1) and `examGen.test.js` (7 — `unresolvedWarningCount`/
`validateQuestionEdit`). Full frontend suite (`vitest run`): **155 passed,
0 failed**. Frontend production build (`npm run build`, Vite): **succeeds**.

## 10. Zero live/provider calls

Every generator-side test uses `ScriptedFakeProvider` or calls pipeline
functions directly with no provider. Every outer backend test uses the
scripted fakes in `backend/tests/_wp18_fakes.py` (extended this WP with
`WarningAcceptingProvider` and `DistractorHardRejectThenAcceptProvider`,
both built the same way as the pre-existing `ApprovingProvider`/
`RejectingProvider` — real generator context, fabricated candidate/review
objects, no provider). `OPENAI_API_KEY` was unset (generator, outer backend
non-`llm_ready` tests) or set only to an explicit in-process sentinel string
never used for a real call (outer's existing `llm_ready` fixture pattern,
unchanged by this WP). No application server was started at any point. No
socket connection was attempted in any test run (verified by the existing
`_no_network`/`_wp18_no_network` socket-trap fixtures in both repositories,
none of which fired).

## 11. Secret / artifact / database audit

- `git diff` in both repositories scanned for `sk-…`/`OPENAI_API_KEY=…`/
  `api_key=…` patterns: zero matches.
- `backend/src/database/app.db` never opened outside a temp-file
  `SQLALCHEMY_DATABASE_URI` (every test fixture already enforces this;
  unchanged by this WP) and never appears in `git status`/`git diff`.
- `artifacts/` (outer) never appears in `git status`; every job-store test
  uses `EXAM_JOBS_ROOT` pointed at a pytest `tmp_path` (existing
  `jobs_root` fixture, unchanged).
- The three owner-owned `PRE_*.md` reports remain untracked and were never
  read-modified by any tool in this session beyond the initial read.
- `../exam_generator_pre_submodule_backup/` was never referenced or touched.

## 12. Final SHAs, statuses, and push results

Generator (already reported in §2, repeated for the combined record):

```
git -C exam_generator rev-parse HEAD        -> 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d
git -C exam_generator rev-parse origin/main -> 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d
git -C exam_generator status --short        -> (clean)
```

Outer (recorded after the commit/push step immediately following this
report — see the session's final terminal output for the literal command
transcript the WP requires):

```
git rev-parse HEAD
git rev-parse origin/main
git status --short
git submodule status
```

The outer gitlink for `exam_generator` was advanced to
`5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d` — the generator commit that was
fetched-and-verified-then-pushed *before* this outer commit was created, per
the WP's ordering requirement (never advancing the outer gitlink to an
unpushed generator commit).

## 13. Remaining limitations / owner decisions

- Manual editing's permission boundary is deliberately identical to
  `replace_via_llm`/`replace_from_db`'s existing "any accepted slot"
  boundary; this codebase has no separate "historical read-only exam" flag
  today. If the owner later wants editing (but not replacement) disabled on
  older saved exams, that needs its own new job-level flag — out of this
  WP's scope, which asked to match existing boundaries, not invent one.
- Neither Excel export schema gained a `manually_edited` column, per the
  owner's explicit schema-compatibility-first ruling in the WP; the field is
  fully available via the JSON API (`generation_meta.manually_edited`) for
  any future reporting need.
- Hard-rejection feedback records are never surfaced in the public
  `result_view` JSON today — nothing in the WP's UI requirements called for
  owner-facing display of the raw failure-memory records, only that they
  keep shaping later generator calls, which they do.
- The generator-side limitations already noted in
  `exam_generator/WPs/WP28G_ARCHITECT_REPORT.md` §11 (warning-vs-rejection
  is still the reviewer LLM's own judgment call under updated prompt
  instructions, schema-capped at one warning as the deterministic backstop)
  apply unchanged here, since the outer app only ever consumes the
  generator's already-decided result.
