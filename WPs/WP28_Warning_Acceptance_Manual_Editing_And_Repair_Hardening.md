# WP28 — Warning Acceptance, Persistent LLM Editing, and Repair Hardening

## Purpose

Reduce unnecessary LLM rejection/retry costs without allowing factually invalid questions into an exam.

The triggering audit (`WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md`) found:

- three candidates were rejected because exactly one distractor was a real, definitely incorrect, category-appropriate term but an implausible structural type;
- one otherwise-valid candidate was repaired correctly from `הצרבלום` to `Cerebellum`, then lost because the repair pipeline failed to add the newly introduced term to `concept_mentions`;
- a later operation repeated an already-seen faulty distractor pattern;
- the accepted text `Basillar Artery` passed despite the correct spelling being `Basilar Artery`;
- a failed replacement retained the old question, but this was not sufficiently clear to the owner;
- numerical ratios in the RTL exam-generation UI are displayed in reverse visual order.

WP28 introduces a non-blocking warning path, remembers only hard-rejection defects, lets the owner edit current LLM questions once inside the application, and hardens terminology repair.

This work package intentionally spans two repositories in strict order:

1. `exam_generator` submodule: generator/reviewer/repair contract.
2. Outer `questions-db`: integrate the new contract, persist warnings/failure memory/manual edits, and update the UI/exports.

Do not begin outer integration until the generator changes are committed, tested, and pushed successfully.

## Binding owner decisions

- Do **not** discourage a valid topic merely because the course material contains fewer than four same-type entities.
- A question such as “Which cerebellar layer contains Purkinje cells?” is desirable even though only three cerebellar cortical layers exist.
- If exactly one distractor is real, grounded, category-appropriate, and definitely incorrect but weak or type-mismatched, accept the question with a visible warning instead of rejecting/regenerating it.
- Only hard-rejected candidate defects enter failure memory. Warning-accepted questions do not.
- Failure memory must prevent repetition of the specific defect, not ban the underlying topic.
- Manual editing is initially available only for current LLM-origin questions, never DB-origin questions.
- Manual edits persist with the named exam and remain after reload/restart.
- All exports use the edited current question so the owner does not need to repeat corrections in Word and Excel.
- Unresolved warnings do not block export, but every export action must require a clear confirmation when warnings remain.
- Generated/edited questions still do not enter the question database automatically.
- Keep the public question itself in the established seven-field schema.

## Starting state and repository safety

From the outer `questions-db` root, record:

```bash
git rev-parse HEAD
git rev-parse origin/main
git status --short
git submodule status
git -C exam_generator rev-parse HEAD
git -C exam_generator rev-parse origin/main
git -C exam_generator status --short
```

Expected latest observed state:

- outer HEAD: `012d2a13a29649bb1141b0a33bafac852762fd11`;
- generator pin: `d20c46bbb332e4d40f735e843d31113176b755e5`;
- generator clean;
- these owner-owned audit reports may be untracked and must remain untouched/uncommitted:
  - `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`
  - `WPs/PRE_WP26R_AUDIT.md`
  - `WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md`

If the actual baseline differs, inspect and document why. Stop before editing if there is unrelated tracked drift or preserving owner work is uncertain.

Never modify, stage, delete, or commit:

- the three owner-owned `PRE_*.md` reports;
- `backend/src/database/app.db`;
- real job/audit artifacts under `artifacts/`;
- `.env*`, API keys, raw provider responses, or rendered live prompts;
- `../exam_generator_pre_submodule_backup/`.

No live provider/API call is authorized. Do not start application servers or access a real `OPENAI_API_KEY`.

## Part A — Generator repository

### A1. Separate hard validity from distractor quality

Refactor the review result so it can distinguish:

1. **Clean acceptance** — no blocking defects or warnings.
2. **Acceptance with warning** — public question is valid but one distractor is weak.
3. **Hard rejection** — question cannot safely be used without substantive correction.

Do not change the public seven-field question schema. Carry warnings as separate typed metadata in the internal/production result.

Recommended warning representation:

```json
{
  "code": "weak_distractor_type_mismatch",
  "severity": "warning",
  "field": "answer4",
  "answer_id": 4,
  "message_he": "תשובה 4 אינה מאותו סוג מבני: Fastigial Nucleus הוא גרעין ולא שכבה."
}
```

Field names may be adapted to existing typed models, but the outer application must receive stable structured fields rather than parse prose.

### A2. Exact acceptance boundary

A candidate may be accepted with **at most one** warning-level distractor only when all conditions below hold:

- the stem is unambiguous and explicitly supported by retrieved source context;
- the selected correct answer is explicitly supported;
- exactly one answer is defensibly correct;
- all four answer strings are non-empty and distinct;
- the weak distractor is a real course term or source-grounded phrase;
- it belongs to the requested category/chapter context;
- it is definitely incorrect for the stem;
- its only defect is low plausibility or a structural/type mismatch;
- the question is semantically distinct from prior accepted/current/history questions;
- terminology policy is satisfied after deterministic safe repair.

Examples that should become warning acceptances:

- `Fastigial Nucleus` offered as the fourth option in a cerebellar-layer question when the other answers are the three real layers.
- `Superior Medullary Velum` offered as the fourth option in a “which cerebellar peduncle” question, provided it is source-grounded, category-appropriate, and unquestionably not a peduncle.

The warning must identify the exact answer field and explain the mismatch in Hebrew.

Hard rejection remains mandatory when any of the following applies:

- correct answer or stem is unsupported;
- more than one answer could reasonably be correct;
- a distractor may actually satisfy the stem;
- an option is fabricated, misspelled without a safe deterministic repair, absent from permitted source/terminology, or category-inappropriate;
- two or more distractors have serious plausibility/type defects;
- the candidate is a semantic duplicate;
- meaning/correctness would need substantive rewriting;
- schema/output is malformed or safety policy fails.

Do not weaken grounding of the correct answer or uniqueness of correctness.

### A3. Do not suppress limited-pool topics

The generation prompt must **not** say or imply that the model should avoid a concept because fewer than four same-type terms exist.

It may prefer strong, same-type distractors when available, but topic diversity is more important than forcing every option into an artificial four-member ontology. A natural question about one of three cerebellar layers is permitted. If the only available fourth option is definitely incorrect but weak, the reviewer may accept it with the warning defined above.

Do not automatically rewrite such questions into a different topic or question form solely to eliminate the warning.

### A4. Preserve safe repair before warning/rejection

Existing safe same-call repair remains preferred for deterministic terminology, spelling, and minor language defects.

Fix the demonstrated repair bug generally:

- after a patch introduces or changes a recognized course term in a public field, reconcile that field's `concept_mentions` against the patched public text before deterministic revalidation;
- use the existing inventory/reverse-index resolution mechanism;
- add a newly introduced uniquely resolved term mention;
- correct a wrongly tagged mention;
- remove stale mentions whose surfaces no longer appear;
- do not blindly trust an arbitrary LLM replacement string as a valid concept;
- preserve category/provenance checks and ambiguity rejection.

The patched `הצרבלום` → `Cerebellum` candidate from the audit must survive post-repair validation when no other defect exists.

This must be a systemic reconciliation step, not a one-off `Cerebellum` special case.

### A5. Correct `Basilar Artery` handling

Inspect the source attestation and terminology inventory for `Basillar Artery`.

Required output policy:

- permitted/canonical generated form: `Basilar Artery`;
- `Basillar Artery` is never accepted in final public output;
- when the intended term is unambiguous, safely repair `Basillar Artery` to `Basilar Artery` without another generation call;
- retain source provenance if the misspelling originated in extracted material, but do not preserve the misspelling as an allowed generated surface.

Implement this through the terminology/repair system rather than a question-specific string replacement in orchestration code.

Add regression coverage proving that the audited arterial-origin question cannot leave the pipeline with `Basillar Artery`.

### A6. Hard-rejection failure memory contract

Add a backward-compatible optional input to the one-question production API for bounded structured hard-rejection feedback. Name it consistently with the codebase, for example `hard_rejection_feedback`.

This input is separate from `previous_public_questions`:

- it does not define semantic exclusion;
- it does not make a topic forbidden;
- it tells the generator not to repeat a specific demonstrated defect;
- it must be rendered in a short, clearly labeled prompt section.

Example:

```json
{
  "category": "המוח הקטן",
  "question_summary": "שאלה על שכבות קליפת ה-Cerebellum",
  "bad_field": "answer4",
  "bad_value": "Fastigial Nucleus",
  "failure_code": "distractor_type_mismatch",
  "instruction": "הנושא מותר, אך אין להשתמש בגרעין כתשובה לשאלה המבקשת שכבה."
}
```

Only candidate-level **hard rejections** produce records. Never create failure-memory records for:

- clean acceptance;
- warning acceptance;
- provider/network/systemic errors with no usable candidate;
- public questions merely displaced by user choice.

Within one production call, later internal attempts should receive safe structured feedback from earlier hard-rejected attempts. The production result must also return safe structured records so the outer job can persist and pass them to later operations.

Do not include raw prompts, hidden reasoning, full provider responses, credentials, or unbounded reviewer prose. Keep the representation deterministic, concise, serializable, and token-bounded.

### A7. Production result contract

Maintain backward compatibility for existing callers while exposing:

- accepted seven-field question;
- `review_quality`: `clean` or `warning`;
- structured `review_warnings` list;
- safe structured hard-rejection records accumulated during failed internal attempts;
- existing costs, attempts, audit references, and typed failure statuses.

A warning-accepted question is a successful result. It must:

- stop retrying;
- incur no additional retry solely because of the warning;
- remain eligible for normal numbering, replacement, persistence, and export;
- never be mislabeled as a failed attempt.

### A8. Generator tests and offline replay

Add focused tests for:

- one weak/type-mismatched distractor → accepted with one structured warning;
- two weak/type-mismatched distractors → hard reject;
- a distractor that may also be correct → hard reject;
- invented/category-inappropriate distractor → hard reject;
- warning acceptance does not generate failure memory or another attempt;
- hard rejection generates bounded safe feedback and later attempts receive it;
- feedback prohibits the defect but explicitly permits the topic;
- patched new term is added to `concept_mentions` and survives validation;
- stale/wrong mentions remain normalized safely;
- `Basillar Artery` is repaired to `Basilar Artery` and never emitted;
- public seven-field schema is unchanged.

Using sanitized fixtures derived from the audit, replay offline:

1. The AICA supply-area candidate repaired from `הצרבלום` to `Cerebellum` must be accepted.
2. The cerebellar-layer candidate with one `Fastigial Nucleus` distractor must be accepted with a warning identifying that answer.
3. The peduncle candidate with one `Superior Medullary Velum` distractor must be accepted with a warning.
4. A repeated hard-rejected defect must appear in later-attempt feedback without banning the layer topic.

Do not depend on the owner's real artifact directory in committed tests. Use minimal sanitized fixtures. The real audit may be replayed read-only as an additional local check, but never modified or committed.

Run the focused generator suite, then the full generator suite once, offline with network hard-blocked and `OPENAI_API_KEY` unset.

### A9. Generator documentation, report, commit, and push

Inside `exam_generator/`, save a generator-specific copy/summary of the applicable brief as:

`WPs/WP28G_Warning_Acceptance_And_Repair_Hardening.md`

Update its `WPs/ARCHITECT_HANDOFF.md` and relevant production API documentation.

Write:

`WPs/WP28G_ARCHITECT_REPORT.md`

The generator report must include:

- exact warning vs hard-rejection rules;
- typed API additions;
- repair reconciliation design;
- Basilar inventory/source finding;
- failure-memory/token-bound design;
- offline replay results;
- complete test counts;
- zero provider calls;
- secret/artifact audit;
- final generator SHA and push result.

Commit inside `exam_generator` as:

```text
WP28G: add warning acceptance and repair hardening
```

Claude may push the generator commit normally only after fetching and proving a safe fast-forward/non-force update. Stop the entire WP if generator verification or push fails. Do not advance the outer gitlink to an unpushed generator commit.

## Part B — Outer questions-db integration

### B1. Consume warning-success results

Update the generator adapter and job service to treat warning acceptance as success.

Persist on the current LLM slot:

- `review_quality`: `clean` or `warning`;
- `review_warnings`: structured warning objects;
- resolution state for each warning;
- `manually_edited`: boolean;
- immutable manual edit history or an equivalent audit-safe representation.

Do not add these fields to the seven-field public question object. Expose them as slot/question metadata in the job API.

Warning-accepted questions count as accepted, appear immediately, stop retries, and participate in later semantic comparison through their current seven-field question.

### B2. Persist bounded hard-rejection memory

Add a separate job-level structure for safe hard-rejection feedback, organized at least by category and chronological insertion order.

Requirements:

- store only structured hard-rejection records returned by the generator;
- never store warning acceptances as failures;
- do not add these records to `category_history` or `previous_public_questions`;
- pass relevant same-category records through the adapter's separate feedback input;
- preserve them across save/reload and appropriate branch creation;
- bound the prompt contribution (choose and document a small deterministic limit, recommended 5–10 most recent records per category);
- preserve repeated defects only when they add distinct actionable information; avoid exact duplicate records;
- do not expose raw provider data or hidden reasoning in public job responses.

The prompt instruction must make clear that the topic remains allowed. This memory prevents repeating the specific invalid pairing/distractor, not the concept itself.

### B3. Persistent manual editing of LLM questions

Add a backend endpoint following existing route conventions, for example:

```text
PATCH /api/exam-jobs/<job_id>/questions/<instance_id>
```

Only permit editing when:

- the job is the current editable/active exam according to existing frontend/backend boundaries;
- the slot currently contains an accepted question;
- the current origin is `llm`;
- the job is not actively generating/locked by another operation.

Reject attempts to edit DB-origin questions, historical read-only exams, missing slots, or running jobs.

Editable fields:

- `question`
- `answer1`
- `answer2`
- `answer3`
- `answer4`
- `correct_answer`

`number`, category, `instance_id`, source origin, audit references, cost, and analytics are not editable.

Perform deterministic structural validation only:

- all five text fields are non-empty after trimming;
- four answer strings are distinct after sensible normalization;
- `correct_answer` is an integer in `1..4`;
- payload contains no unexpected public fields.

Do not call an LLM or require the API key for manual edits. The owner is authoritative for the content change.

On success:

- append an immutable edit-history entry with timestamp, before/after seven-field values, and affected warning IDs;
- update the current seven-field question;
- set `manually_edited = true`;
- if the exact field named by an unresolved warning changed, mark that warning `resolved_by = "manual_edit"` with a timestamp;
- do not resolve unrelated warnings automatically;
- save atomically;
- preserve slot/instance identity and public number.

After reload/restart, the edited text and history must remain. Later generation calls must receive the **current edited question** as semantic context. If the edited LLM question is later displaced, existing LLM history rules should retain the current edited version while immutable edit history preserves the originally generated text.

Branching a completed exam must copy current edited questions, warning/resolution metadata, edit history, and hard-rejection feedback according to existing snapshot rules.

DB questions remain non-editable so their stored analytics continue to describe the actual DB content.

### B4. Frontend warning and edit experience

For every current LLM question:

- show `נוצרה באמצעות בינה מלאכותית` as before;
- when warnings exist, add a clear `דורש בדיקה` badge;
- highlight the exact affected answer/stem field without obscuring the text;
- display the Hebrew warning explanation;
- if resolved, show a quieter `תוקן ידנית` state rather than the active warning;
- provide `ערוך שאלה` only for LLM-origin questions.

The edit UI should be an accessible inline panel or modal containing:

- stem input;
- four answer inputs;
- correct-answer selector;
- Save and Cancel;
- clear validation errors.

Use the current values as defaults. Saving updates the displayed exam immediately and persists through the backend. Do not expose an edit button for DB-origin questions.

Editing must not change source-origin badges, cost, number, category, or DB data.

### B5. Export confirmation and edited content

Before each question-content export action (full DOCX, full Excel, and LLM-only Excel), count unresolved warnings among current accepted questions.

If the count is greater than zero, show a Hebrew confirmation such as:

```text
במבחן קיימות 2 שאלות הדורשות בדיקה. האם להמשיך בייצוא?
```

- Cancel performs no export request/download.
- Confirm continues normally.
- Warnings never hard-block export.
- Resolved warnings do not contribute to the count.
- Historical/read-only views use the same confirmation based on their persisted snapshot.

Every export must use the current edited seven-field question. Do not add warning labels to the student-facing DOCX. Preserve established Excel schemas unless an existing metadata extension point safely accommodates `manually_edited`; schema compatibility takes priority.

### B6. Make failed replacement retention explicit

When `replace_llm` exhausts its attempts without an accepted question:

- keep the original question exactly as today;
- show a clear Hebrew message:

  `לא נוצרה שאלה חלופית. השאלה המקורית נשמרה.`

- include the operation's attempt count and cost when already available from the safe response/ledger;
- never imply that the unchanged question is a newly generated replacement;
- persist hard-rejection feedback from the failed attempts for later calls;
- do not create `category_history` displacement because no replacement succeeded.

Add frontend tests reproducing the audited scenario: two failed replacement attempts, unchanged original question, explicit retention message, and no semantic-history displacement.

### B7. Correct RTL/LTR numerical ratios

Render all numerical ratio expressions on the exam-generation page in isolated LTR direction while preserving the surrounding Hebrew RTL layout.

Examples:

- `10 / 15`, never visually `15 / 10`;
- `0 / 5`, never visually `5 / 0`;
- `$0.00 / $5.00` in its logical source order.

Use semantic bidi isolation such as `<bdi dir="ltr">...</bdi>` or an equivalent tested component. Do not reverse operands in JavaScript and do not set the entire Hebrew card/page to LTR.

Audit every count/cost ratio in the exam-generation view and use one reusable implementation where practical.

### B8. Outer tests

Add focused backend tests proving:

- warning acceptance maps to an accepted slot and stops retrying;
- warning metadata survives save/reload;
- warning acceptance never enters hard-rejection memory;
- hard-rejected candidate feedback is stored, bounded, deduplicated, and passed separately on a later same-category call;
- the topic itself remains permitted and feedback targets only the defect;
- manual edit succeeds for current LLM question with no provider call;
- DB-origin, historical, running/locked, malformed, and invalid-answer edits are rejected safely;
- edit history preserves before/after values and survives reload;
- edited current text enters later semantic context;
- replacement history stores the current edited outgoing version;
- branches copy edits/warnings/failure memory correctly;
- all exports use edited current text;
- unresolved warnings do not block backend export behavior;
- failed replacement retains the old question, stores only hard-rejection feedback, and reports attempts/cost safely;
- old/legacy job JSON without new fields loads safely without rewrite-on-read.

Add focused frontend tests proving:

- warning badge, exact field highlighting, and Hebrew explanation;
- only LLM questions have an edit control;
- edit form validation, cancel, successful save, and immediate rerender;
- reload displays persisted edits and resolved-warning state;
- each export asks for confirmation when unresolved warnings exist;
- cancelling makes no export call; confirming makes exactly one;
- resolved warnings do not prompt;
- failed LLM replacement clearly says the original was retained;
- all count/cost ratios are isolated LTR and display logical operand order;
- existing two-phase, naming/history, replacement, analytics, and export tests remain green.

Use deterministic fake providers and hard network traps. No real provider call.

### B9. Documentation and reports

Save this complete brief in the outer repository as:

`WPs/WP28_Warning_Acceptance_Manual_Editing_And_Repair_Hardening.md`

Update outer `SETUP.md` and `WPs/ARCHITECT_HANDOFF.md` with:

- warning vs hard rejection;
- hard-rejection failure memory;
- persistent manual editing rules;
- export warning confirmation;
- failed-replacement retention behavior;
- generator submodule SHA/API contract.

Write the outer report to:

`WPs/WP28_ARCHITECT_REPORT.md`

The report must include:

- exact files changed in both repositories;
- generator and outer commits;
- warning/hard-rejection decision table;
- repair and Basilar findings;
- failure-memory representation, bound, and prompt impact;
- manual edit/history/persistence behavior;
- export and RTL behavior;
- offline replay results;
- all focused/full test counts and build result;
- zero live/provider calls;
- secret/artifact/database audit;
- final outer and generator SHAs/statuses/push results;
- remaining limitations or owner decisions.

### B10. Verification protocol

Run focused tests while implementing. After they pass:

1. Run the complete generator suite once before committing/pushing Part A.
2. Run the complete outer backend suite once after integration.
3. Run the complete frontend suite once.
4. Run the frontend production build once.

All long commands must remain in the foreground and be actively awaited in the same Claude turn. Never use `run_in_background`, `&`, detached commands, or unattended polling. On macOS use `caffeinate -i` and a timeout of at least 15 minutes.

Run all test processes with `OPENAI_API_KEY` unset and non-loopback network blocked. Do not start application servers.

If a full command is killed or its result is lost, stop and report honestly; do not promise automatic continuation or start an overnight loop. Permit at most two bounded repair-and-rerun passes per repository before reporting a blocker.

### B11. Outer commit and push

After generator commit/push succeeds and all outer verification passes:

- confirm the outer gitlink points to the new pushed generator SHA;
- inspect the complete outer diff;
- exclude the three owner-owned PRE reports and all ignored artifacts;
- scan staged content for secrets, raw provider responses, real job artifacts, and DB changes.

Commit the outer repository as:

```text
WP28: add review warnings and persistent LLM editing
```

Claude may push normally to outer `origin/main` after fetch and safe fast-forward verification. Never force-push or rewrite history.

At completion report:

```bash
git rev-parse HEAD
git rev-parse origin/main
git status --short
git submodule status
git -C exam_generator rev-parse HEAD
git -C exam_generator rev-parse origin/main
git -C exam_generator status --short
```

The only permitted remaining untracked outer files are the three pre-existing owner-owned PRE reports. Both repository working trees must otherwise be clean.

## Stop conditions

Stop and report before proceeding if:

- a warning candidate could have more than one defensible correct answer;
- the implementation would treat an entire topic as forbidden because of one failed distractor;
- warning acceptance would bypass correct-answer grounding, semantic uniqueness, or terminology safety;
- hard-rejection feedback cannot be kept structured, bounded, and separate from semantic history;
- manual edits would mutate DB rows or invalidate DB analytics;
- exports cannot use one persisted current edited version consistently;
- generator API compatibility requires an unbounded breaking change;
- either repository has unrelated tracked drift that cannot be preserved;
- a DB schema migration, new dependency, live API call, credential access, or server start appears necessary;
- a generator commit cannot be pushed before the outer gitlink advances;
- verification requires unattended background execution;
- more than two bounded repair passes are required in either repository.

Do not silently weaken the accepted policy to avoid a stop condition.
