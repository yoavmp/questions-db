# WP25G — Inverse Semantic Duplicate Guard — Architect Report

Combined generator correction and outer re-pin. Offline only throughout: **zero provider calls,
`OPENAI_API_KEY` never accessed, no server started.** No real `artifacts/exam_jobs/**` entry, `app.db`
row, `Data/**` file, `.env*`, historical audit, or the `../exam_generator_pre_submodule_backup/` snapshot
was modified — the one real job used as read-only evidence (§1) was only read, never written.

Starting state: outer `questions-db` at `9c26189ea7f6bfe8273bece953fa5375719a0e28` (`WP24D`), `main ==
origin/main`; generator `exam_generator` at `eea91b06e2ec5d053eca3a5696656fdd354a05f9` (`WP24`), `main ==
origin/main`, equal to the outer gitlink and `EXPECTED_GENERATOR_PIN`. No drift. The two expected
possibly-untracked outer files (`WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`,
`WPs/WP25_Named_Exam_History_Branches_And_UI_Polish.md` — only the former is present in this checkout)
were left untouched and unstaged throughout.

## 1. Root cause: missing context, not a reviewer false negative

**Confirmed: a missing-context plumbing bug in outer `replace_via_llm`, not a generator/reviewer
uniqueness false negative.**

`backend/src/jobs/service.py::replace_via_llm` built its `previous` context for the replacement call as
`previous = _previous_for_slot(job, slot)`, called **before** the paid call. `_previous_for_slot`
(`service.py`) scans every *other* slot in the category by excluding the target slot's own `instance_id` —
correct for its other callers, but it means the slot's own current (about-to-be-displaced) question is
never included via that path. The other possible source, `job.category_history`, cannot supply it either:
the displaced question is appended there only **after** this same `replace_via_llm` call succeeds
(`if was_llm: job.category_history.setdefault(...).append(old_question)`, gated on success). Net effect:
the one question being displaced was the one question never shown to the generator or reviewer judging its
own replacement.

This was proven, not assumed, with a real preserved audit trail (read-only; not modified, not copied
verbatim into any tracked fixture): job `14f2a1ea-d4b8-4574-8ae3-553d73725cf6` under `artifacts/exam_jobs/`
(git-ignored, real, dated today) shows the exact incident. Its `job.json` records
`category_history["קרומים וסינוסים דוראליים"]` containing precisely the displaced question (public
`number: 8`, `answer1: "Arachnoid Villi"`), and the slot now holds precisely the accepted inverse-duplicate
replacement. The per-invocation `sequence_manifest.json` for that replacement call
(`slots/9ca316c7-.../replace_llm_0007_.../attempt_01/`) lists exactly two prior-question entries —
`number 7` (an unrelated prior DB question) and `number 8` itself (the candidate being judged) — with **no**
entry for the original Arachnoid-Villi wording. The displaced question was structurally absent from the
call, confirming the plumbing-bug diagnosis directly from the incident's own evidence, not inference alone.

Also weighing on the diagnosis: the generator's own comparison schema
(`exam_generator/src/exam_generator/generation_models.py::OverlapType`) already includes
`inverse_relationship` and `prior_answer_as_subject` as literal values, and the review prompt already
carried a worked stem/answer role-swap example (Striatum/Putamen) **before** this WP. The reviewer was
already equipped to recognize this failure shape once shown a pair to compare — it was never shown this
one.

**Fix** (`backend/src/jobs/service.py::replace_via_llm`, one line): the slot's own old question is now
appended to `previous` **ephemerally, for that one call only**:

```python
previous = _previous_for_slot(job, slot) + [old_question]
```

`category_history` mutation timing is completely unchanged — still appended only after success, still
gated on `was_llm` — matching the WP's explicit instruction not to mutate persisted history before a
replacement succeeds. Order and repeated public numbers are preserved: the ephemeral entry is appended
after every other current same-category question and after that category's earlier displaced-LLM history,
exactly the position it will occupy once persisted on success.

New outer regression, `backend/tests/test_wp25g_inverse_duplicate_guard.py`
(`test_displaced_question_reaches_its_own_replacement_context_before_the_call`): overwrites an accepted
LLM slot's question with the real, preserved displaced-question fixture, then calls `replace_via_llm` with
a capturing fake provider that records exactly what `request.previous_questions` contains on the call that
stands in for the real (paid) generation call. Asserts the displaced question is present, is the last
entry (order preserved), and that `category_history` is empty immediately before the call and holds
exactly the displaced question immediately after success — proving both halves of the fix (ephemeral
presence before the call, no premature persistence).

Since the gap **was** missing context (not already-correct working logic), the WP's fallback instruction
("if it is already passed correctly, do not rewrite working outer logic") did not apply — the one-line
fix above was required and made.

## 2. Generator-side: prompt and deterministic-policy changes

Independent of the outer fix, the generator submodule (its own commit, pushed separately — §5) adds two
purely textual, provider-call-free layers as a final safety net for the case where a reviewer genuinely is
shown an inverse pair and still misses it.

**Prompt strengthening** (`exam_generator/prompts/generate_question.system.he.j2`,
`review_candidates.system.he.j2`): explicitly states that uniqueness concerns the tested entity,
relationship, property, process, or causal fact — never surface wording or grammatical direction;
generalizes the existing Striatum/Putamen group-membership example into a template covering any
relationship (`"which structure performs/has X?"` / `"what does Y perform/have?"` are duplicates whenever
Y↔X is the same source-supported relationship), worked through a second example using the real incident
pair itself (Arachnoid Villi / one-way CSF flow direction) so the principle is anchored to a
non-membership relationship too; states the reversal is bidirectional — moving a fact from the correct
answer into the stem, or moving a stem fact into the new correct answer, are both covered; states a
changed interrogative, answer ordering, distractor set, or Hebrew phrasing alone never establishes a
distinct learning target; states a shared source unit alone is insufficient for duplication, because one
unit may contain multiple independent facts. Both prompts remain single system prompts rendered into the
same one generation call and one review call the pipeline already made — no new call, no second prompt.

**Deterministic guard** (new `exam_generator/src/exam_generator/duplicate_guard.py`,
`semantic_duplicate_cross_role_problems`): resolves each question's correct-answer text (`correct_answer`
index into `answer1`-`answer4` for a prior question; the candidate's own `correct_answer` field directly);
normalizes Unicode (NFKC), Hebrew maqaf and common hyphen/dash variants to ASCII `-`, drops
geresh/gershayim/quote variants and remaining punctuation, casefolds, collapses whitespace — no
translation, no synonym table; flags `semantic_duplicate_cross_role` only when **both** reciprocal
containments hold — the prior's correct-answer text is a substring of the candidate's stem, *and* the
candidate's correct-answer text is a substring of the prior's stem; excludes empty/short (under 3
normalized characters) and generic answer forms (Hebrew "כל התשובות נכונות"/"אף אחת מהתשובות אינה נכונה"
and variants, English "all/none of the above/answers"). No source-unit equality, no terminology or
relationship inventory, no embeddings, no LLM/provider call — confirmed by inspection (the module imports
only `re`, `unicodedata`, and this repo's own Pydantic models) and by the zero-network assertions in its
tests.

**Integration**: wired into `orchestrator.py::generate_one_question`, immediately after
`problems += review.comparison_problems(previous_questions)`:

```python
problems += review.comparison_problems(previous_questions)
problems += semantic_duplicate_cross_role_problems(working, previous_questions)
problems += corrected_fact_problems(working, source_facts=facts)
```

This is the smallest safe acceptance boundary that **preserves the existing retry behavior**: a guard hit
feeds into the same `if problems: rejected_ids.append(candidate_id); continue` every other rejection
reason already uses, so it rejects only that one candidate through the existing per-position attempt
budget — a later attempt in the same call, or a later position in a `sequence.py` run, is never aborted by
a guard hit elsewhere. This is deliberately a different boundary than `sequence.py`'s own cross-position
`focus_correction_ids` fact-key guard (which has no retry and ends the whole sequence position) — WP25G
needed the retry-preserving boundary specifically.

## 3. Why the exact pair is now rejected

The real displaced/accepted-replacement pair from the incident:

- Displaced (accepted): `"איזה מבנה מאפשר זרימה חד־כיוונית וסלקטיבית של CSF מן החלל הסאב־אראכנואידי אל
  הסינוסים?"` → `Arachnoid Villi`.
- Accepted replacement (the bug): `"מהו כיוון הזרימה החד-כיוונית של CSF המתווך באמצעות Arachnoid
  Villi?"` → `"מן החלל הסאב-אראכנואידי אל הסינוסים."`

With the outer fix, this pair now reaches the reviewer together (§1) — the strengthened prompt (§2) is
expected to reject it directly via `same_learning_target: true`. Independently, even if a reviewer call
still returns an incorrect `same_learning_target: false` for this exact pair, the deterministic guard
catches it: the displaced question's correct-answer text (`"Arachnoid Villi"`) is a substring of the
replacement candidate's stem, and the replacement's own correct-answer text
(`"מן החלל הסאב-אראכנואידי אל הסינוסים"`) — after normalizing the displaced stem's Hebrew maqaf
(`הסאב־אראכנואידי`) against the replacement's ASCII hyphen (`הסאב-אראכנואידי`) and stripping the trailing
period — is a substring of the displaced question's own stem. Both reciprocal conditions hold, so
`semantic_duplicate_cross_role_problems` returns a non-empty problem list, rejecting the candidate
regardless of the reviewer's verdict.

Proven directly, offline, in the generator repo's `tests/test_wp25g_inverse_duplicate_guard.py`
(`test_wrong_reviewer_false_negative_cannot_accept_the_exact_pair_and_retry_recovers`): a scripted fake
reviewer that incorrectly marks the exact pair `same_learning_target: false` cannot get it accepted; the
internal rejection diagnostic names `semantic_duplicate_cross_role` and is confirmed absent from the
public `FinalQuestion.model_dump()` (still exactly the seven public fields); the next attempt, given a
genuinely different candidate, is accepted normally through the same retry loop.

## 4. Evidence that same-unit/different-fact questions still pass

`tests/test_wp25g_inverse_duplicate_guard.py::test_two_different_facts_from_the_same_source_unit_both_accepted`
runs a two-position sequence where both questions cite the identical source `source_unit_id` but test
genuinely different, non-reciprocal facts (one about the flow-enabling structure, one about a distinct
regulatory function of that same structure) — both are accepted; the deterministic guard's reciprocal-text
check never keys on source-unit identity, so a shared citation alone cannot trigger it.
`test_guard_requires_both_reciprocal_directions` additionally proves a candidate that contains a prior
question's correct-answer text in its own stem, but whose own correct-answer text is *not* found in that
prior's stem (one direction only), is not flagged — reusing a term or unit is never sufficient on its own.

## 5. Provider-call count

**Zero**, throughout every test in both repositories. Every generator test uses `ScriptedFakeProvider` or
the `_wp18_fakes` dispatch fakes; every backend test runs with `socket.socket.connect`/`connect_ex` hard-
blocked (`backend/tests/conftest.py::_wp18_no_network`, autouse) and `OPENAI_API_KEY` unset for the full
suite runs (§6). No test, fixture, or helper added by this WP imports `openai` or constructs a real
provider client.

## 6. Test results

**Generator, focused** (`test_wp25g_inverse_duplicate_guard.py` plus every existing file exercising
`previous_questions`/sequential uniqueness/orchestrator evidence — `test_wp10_sequential_uniqueness.py`,
`test_wp10r_hardening.py`, `test_wp23_regression_candidates.py`, `test_wp21g_orchestrator_evidence.py`):
**69 passed, 1 skipped** (the one skip is that file's own pre-existing `Data/`-conditional test,
unaffected by this WP).

**Generator, complete suite**, serial, `OPENAI_API_KEY` unset: **1007 collected, 833 passed, 174 skipped,
0 failed, 0 errors** — reconciled exactly against the WP24 baseline (999 collected, 825 passed, 174
skipped, 0 failed): this WP added exactly 8 net new tests (825 + 8 = 833, 999 + 8 = 1007); the 174 skips
are the unchanged, already-diagnosed Data-dependent/macOS-font set.

**Outer backend, focused** (`test_wp25g_inverse_duplicate_guard.py`,
`test_wp18r_cross_source_replacements.py`, `test_wp18_replacements.py`,
`test_wp20_semantic_history_boundary.py`, `test_wp21_analytics_and_exports.py`): **38 passed**.

**Outer backend, complete suite**, serial, `OPENAI_API_KEY` unset: **122 passed, 0 failed** — reconciled
exactly against the WP24 baseline (121 passed): this WP added exactly 1 net new test. No frontend test/
build was run — no frontend behavior belongs in WP25G, per the brief.

**Readiness/pin check**: `readiness_report()["submodule_pin"]` = `{"checked": true, "expected":
"d20c46bbb332e4d40f735e843d31113176b755e5", "actual": "d20c46bbb332e4d40f735e843d31113176b755e5",
"matches": true}` — verified live, after the re-pin, before this report was finalized.

## 7. Generator commit / push SHA

Committed `d20c46bbb332e4d40f735e843d31113176b755e5` on `main`, subject `WP25G: reject inverse semantic
duplicates`. Fetched `origin` first; confirmed `origin/main` (`eea91b06e2ec5d053eca3a5696656fdd354a05f9`,
WP24) is an ancestor of the new commit — fast-forward-safe. Pushed normally (no force). Verified after
push: `git fetch && git rev-parse HEAD == git rev-parse origin/main` — both
`d20c46bbb332e4d40f735e843d31113176b755e5`; working tree clean.

## 8. Outer commit / push SHA

Staged only the intended outer source/test/documentation files, the generator gitlink, and the pin change
— **not** the two postponed/untracked reports/briefs named in the baseline section (neither was staged).
Committed as `WP25G: integrate inverse duplicate guard` on `main`. Exact SHA, and the post-push
verification (fetch + fast-forward confirmation + push), are recorded in this WP's closing terminal
response, together with the generator SHA above — both repositories' final state is summarized there.

## 9. Final outer gitlink / pin equality

`git submodule status` → `d20c46bbb332e4d40f735e843d31113176b755e5 exam_generator (heads/main)` (no `+`/`-`
prefix once the outer commit lands — exact checkout, no divergence). `backend/src/integration/
generator_pin.py::EXPECTED_GENERATOR_PIN` = `"d20c46bbb332e4d40f735e843d31113176b755e5"`. Both equal the
generator's own pushed `origin/main`. `readiness_report()["submodule_pin"]["matches"]` = `true` (§6).

## 10. Tree cleanliness / untouched real data

Generator `exam_generator/`: clean after push, `HEAD == origin/main` (§7). Outer `questions-db`: clean
after the outer commit except the two files the baseline explicitly allows to remain untracked and
unstaged — in this checkout, only `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md` is present (the second named file,
`WPs/WP25_Named_Exam_History_Branches_And_UI_Polish.md`, does not exist in this checkout at all).

No real job under `artifacts/exam_jobs/**`, no `app.db` row, no `Data/**` file, no `.env*`, no historical
audit directory, and no file under `../exam_generator_pre_submodule_backup/` was modified anywhere in this
WP. The one real job used as read-only root-cause evidence (§1,
`artifacts/exam_jobs/14f2a1ea-d4b8-4574-8ae3-553d73725cf6/`) was only read — confirmed by `git status`/
`git diff` showing no change under `artifacts/` at any point in this WP, and by this WP's test fixtures
containing only the two questions' seven public fields (never a raw provider response, a rendered prompt,
or protected source text copied from that job).

## Stop conditions — none triggered

The displaced question was proven to reach the replacement context (§1, after the fix). The guard required
no fuzzy matching, relationship inventory, embeddings, or extra model call (§2 — text-only, one existing
call pair, unchanged). The seven-field public schema and the generator's production API signature are
byte-for-byte unchanged (§6, §3). No unrelated uniqueness regression appeared in either full suite (§6). No
repository diverged or carried unexpected changes (starting-state check, above). Both repositories
completed within their own single fix-and-rerun pass — well inside the two-pass bound.
