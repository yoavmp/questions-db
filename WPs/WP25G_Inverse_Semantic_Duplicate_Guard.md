# WP25G — Inverse Semantic Duplicate Guard

## Goal

Fix the demonstrated uniqueness failure in which an accepted question was replaced by another question testing the same fact with the stem and answer roles reversed.

Displaced question:

> איזה מבנה מאפשר זרימה חד־כיוונית וסלקטיבית של CSF מן החלל הסאב־אראכנואידי אל הסינוסים?

Correct answer: `Arachnoid Villi`.

Accepted replacement:

> מהו כיוון הזרימה החד-כיוונית של CSF המתווך באמצעות Arachnoid Villi?

Correct answer: `מן החלל הסאב-אראכנואידי אל הסינוסים`.

These are the same learning target: the relationship between `Arachnoid Villi` and one-way CSF flow from the subarachnoid space to the sinuses. Reversing which side appears in the stem versus the correct answer does not create a new concept.

This WP must strengthen the existing generation/review process without restoring a relationship inventory, adding embeddings, or adding another LLM call.

## Repositories and expected baseline

This is a combined generator correction and outer re-pin.

- Outer `questions-db` expected at `9c26189ea7f6bfe8273bece953fa5375719a0e28`, `main == origin/main`.
- Generator expected clean at `eea91b06e2ec5d053eca3a5696656fdd354a05f9`, `main == origin/main`, and equal to the outer gitlink and `EXPECTED_GENERATOR_PIN`.
- Preserve `../exam_generator_pre_submodule_backup/` untouched.
- The following outer files may already be untracked and must remain unmodified and unstaged: `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md` and `WPs/WP25_Named_Exam_History_Branches_And_UI_Polish.md`. The WP25 UI brief is postponed and will be reissued later as WP26.

Stop before editing if there is any other drift, divergence, pin mismatch, or dirty generator state.

## Safety and execution limits

- Offline only: do not access `OPENAI_API_KEY`, start servers, or make provider/network calls.
- Do not alter real `artifacts/exam_jobs/**`, `app.db`, `Data/**`, `.env*`, source PDF/index, historical audits, or the backup.
- Do not add a terminology/relationship inventory, fuzzy semantic database, embedding model, or similarity API call.
- Preserve the seven-field public question schema and all existing Hebrew/English terminology behavior.
- Use fake providers and temporary stores in tests.
- Make at most two focused fix-and-rerun passes per repository. Stop and report if the bounded fix cannot be completed.

## 1. Verify the replacement context path

Trace the current production path from outer `replace_via_llm` through the adapter into generator `previous_public_questions`, and inspect the preserved latest-job evidence read-only.

Prove with an automated outer test that the question being displaced is included in the replacement generation/review context **before** the paid call, together with every other current same-category question and earlier displaced LLM history. Preserve order and repeated public numbers.

- Do not mutate `category_history` before a replacement succeeds.
- If the displaced target is currently missing from the call, pass it ephemerally for that invocation and append it to persisted history only after success.
- If it is already passed correctly, do not rewrite working outer logic; add the regression test only.

The report must state whether this incident was missing context or a reviewer/uniqueness false negative, with direct code/audit evidence.

## 2. Define inverse questions as the same learning target

Strengthen the existing generation and review prompts. State explicitly:

- uniqueness concerns the tested entity, relationship, property, process, or causal fact—not surface wording or grammatical direction;
- `Which structure performs/has X?` and `What does structure Y perform/have?` are duplicates when `Y ↔ X` is the same source-supported relationship;
- moving a fact from the correct answer into the stem, and moving the former stem fact into the correct answer, does not make a new question;
- a changed interrogative, answer ordering, distractors, or Hebrew phrasing does not establish a distinct learning target;
- a shared source unit alone is **not** sufficient to declare duplication because one unit may contain multiple independent facts;
- the reviewer must compare the semantic learning target against every supplied prior question, including the displaced target during replacement.

Keep this inside the existing generation and review calls. Do not add a separate similarity call.

## 3. Deterministic public-text safety net

Add a small deterministic guard based only on current and previous seven-field public questions. It is a fallback when the LLM reviewer incorrectly marks an obvious inverse pair as distinct.

Required behavior:

1. Resolve each question’s correct-answer text from `correct_answer` and `answer1`–`answer4`.
2. Normalize Unicode, Hebrew/ASCII hyphen variants, case, punctuation, and whitespace without translating or inventing synonyms.
3. Flag `semantic_duplicate_cross_role` when **both** reciprocal conditions hold:
   - the prior correct-answer text is a meaningful phrase in the current stem; and
   - the current correct-answer text is a meaningful phrase in the prior stem.
4. Exclude empty, extremely short, and generic answer forms such as “all/none of the answers” from deterministic matching.
5. A guard hit overrides an incorrect reviewer `same_learning_target: false` and prevents acceptance. Record a safe internal diagnostic; do not add fields to the public JSON.
6. The guard must not use source-unit equality, terminology inventory membership, relationships, embeddings, or an LLM.

Integrate it at the smallest safe acceptance boundary. Preserve existing cost/audit accounting and retry behavior. The strengthened generation prompt should reduce recurrence; the deterministic guard is the final safety net and must not create an additional provider call of its own.

Do not broaden this into general fuzzy similarity. Semantic cases without reciprocal public-text containment remain the existing reviewer’s responsibility.

## 4. Exact regression coverage

Add the displaced/replacement pair above as a permanent regression fixture using complete seven-field questions.

Prove offline that:

- the displaced question reaches both generation and review context during replacement;
- the prompts describe inverse stem/answer questions as duplicates;
- a fake reviewer that incorrectly returns `same_learning_target: false` cannot cause this exact pair to be accepted;
- the deterministic diagnostic is internal and the seven-field schema is unchanged;
- a retry may proceed to a genuinely different learning target;
- two genuinely different facts from the same source unit are not rejected merely for sharing that unit;
- generic/short correct answers do not trigger the deterministic guard;
- Hebrew maqaf versus ASCII hyphen and English case differences normalize correctly;
- ordinary non-reciprocal questions and all existing uniqueness tests remain unchanged;
- zero network/provider calls occur.

Replay any preserved evidence only read-only. Do not copy raw provider responses, complete prompts, or protected source text into tracked fixtures or reports.

## 5. Generator verification, commit, and push

Inside `exam_generator`:

1. Run focused new/affected tests.
2. Run the complete generator suite once, serially, with `OPENAI_API_KEY` unset and network blocked. Reconcile counts against the WP24 baseline: 999 collected, 825 passed, 174 skipped, 0 failed.
3. Save the brief copy as `WPs/WP25G_Inverse_Semantic_Duplicate_Guard.md` and Claude’s generator summary as `WPs/WP25G_GENERATOR_REPORT.md`; refresh `WPs/ARCHITECT_HANDOFF.md`.
4. Audit the staged diff for secrets, `Data/**`, `.env*`, artifacts, raw responses, rendered prompts, or unrelated files.
5. Commit as `WP25G: reject inverse semantic duplicates`.
6. Fetch and push generator `main` only if fast-forward safe. Never force-push, rebase, or merge through divergence.

Record the exact pushed generator SHA.

## 6. Outer integration and verification

After the generator commit is confirmed on its remote:

- update the outer submodule gitlink and `backend/src/integration/generator_pin.py::EXPECTED_GENERATOR_PIN` to the exact generator SHA;
- include only the minimal outer replacement-context correction if Section 1 proves one is needed;
- add the outer regression proving the displaced question is present before replacement generation;
- update outer `WPs/ARCHITECT_HANDOFF.md`;
- save Claude’s authoritative combined report as `questions-db/WPs/WP25G_ARCHITECT_REPORT.md`.

Run affected backend tests, then the complete backend suite once, serially, offline. Do not run frontend tests/build because no frontend behavior belongs in WP25G. Verify readiness/pin tests and confirm the generator/outer public contract remains seven fields.

Stage only intended outer source/test/documentation files, the generator gitlink, and pin change. Do not stage the two postponed/untracked reports/briefs named in the baseline section.

Commit outer changes as `WP25G: integrate inverse duplicate guard`. A normal push of outer `main` is authorized only after fetching and proving fast-forward safety. Never force-push or push through divergence.

## 7. Required reports

`WP25G_ARCHITECT_REPORT.md` must concisely include:

- confirmed root cause: missing displaced-question context versus reviewer false negative;
- exact prompt and deterministic-policy changes;
- why the exact pair is now rejected;
- evidence that same-unit/different-fact questions still pass;
- provider-call count (must be zero);
- focused and full test results;
- generator commit/push SHA;
- outer commit/push SHA;
- final outer gitlink/pin equality;
- confirmation that generator and outer trees are otherwise clean, with only the two expected postponed files possibly untracked;
- confirmation that no real job, audit, database, local course data, credential, or backup was modified.

## Stop conditions

Stop and report rather than improvising if:

- the displaced question cannot be proven to reach the replacement context;
- the proposed guard would require fuzzy matching, a relationship inventory, embeddings, or another model call;
- the seven-field public schema or existing question-generation API would need to change;
- tests reveal substantial unrelated uniqueness regressions;
- either repository diverges or has unexpected changes;
- completion would exceed the two bounded repair passes.

