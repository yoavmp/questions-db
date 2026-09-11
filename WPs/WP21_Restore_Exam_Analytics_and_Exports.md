# WP21 — Restore exam analytics and complete Excel exports

## Goal

Restore the native exam-display and analytics features removed during the async-job migration, provide both full-exam and LLM-only Excel exports, make attempt counts ledger-accurate, and prevent audit overwrites. Preserve all WP18–WP20 behavior.

## Boundary and baseline

- Work only in outer `questions-db`.
- Expected outer HEAD: `4c0a7df1b551bca8bf55dd56ddea3e1d0f7aeabe`, clean except this brief.
- Keep `exam_generator` untouched, clean, and pinned at `ea59cd857e5618b0260d2bb146dd5573c9ca2309`.
- Do not touch `../exam_generator_pre_submodule_backup`.
- Offline only: no provider calls and no API key access.
- Stop and report if the baseline differs.

## 1. Recover historical behavior before editing

Use read-only Git history (`git show`, `git log -S`, etc.) to identify the exact pre-WP19 implementation of:

- category headings in generated exams;
- per-question accuracy and distinction/discrimination displays, including multiple historic values and missing values;
- overall mean accuracy and the count/proportion above the user-selected distinction threshold;
- the former complete Excel export schema, column order, labels, and missing-value convention.

Do not approximate behavior that remains recoverable from history. Record the source commit/files and the recovered contract in the report. Do not use destructive checkout commands.

## 2. Restore grouped exam presentation

- Keep questions in canonical category/global-number order.
- Restore a clear heading before each category group; do not repeat a heading within one group.
- Preserve origin badges and both replacement buttons on every accepted question.
- Keep internal `category_history` hidden.
- Do not calculate or show a current aggregate DB/LLM balance.

## 3. Restore per-question analytics

- Carry the existing database question’s complete historical accuracy and distinction values into the persisted job result and frontend.
- Display all values exactly as the legacy screen did: `NaN` when untested/missing and multiple values when the question appeared in multiple exams.
- LLM-generated questions receive missing analytics and display `NaN` for both measures.
- Use standard JSON-safe missing data (`null`) at API/persistence boundaries; convert it to the legacy UI/export representation at presentation time.
- Keep analytics outside the seven-field public question object. Never pass analytics, DB IDs, or job metadata into generator previous-question context.
- Replacement transitions must update analytics correctly:
  - DB→DB: metrics of the new DB question;
  - DB→LLM and LLM→LLM: `NaN`/missing metrics;
  - LLM→DB: metrics of the selected DB question.
- Preserve stable `instance_id`, number, category, ordering, semantic-history policy, and rollback behavior.

## 4. Restore overall analytics

- Restore the legacy control/default for distinction threshold `x` and its original calculation.
- Restore the generated exam’s mean accuracy and the number/proportion of eligible questions above `x` distinction.
- Ignore missing/`NaN` observations exactly as the historical implementation did.
- Handle the all-missing case explicitly as `NaN`/not available—never zero and never divide by zero.
- Recalculate immediately after every successful replacement; failed replacements leave analytics unchanged.

## 5. Provide two Excel exports (owner-approved Option A)

1. **Full current exam export:** every current DB and LLM question, in canonical final order, using the complete historical Excel schema and column order.
2. **LLM-only export:** only current LLM-origin questions, retained as a separate clearly labeled download for later manual database upload.

Requirements:

- Give the exports unambiguous Hebrew buttons and explicit API routes/parameters; do not overload one label with two meanings.
- The full export must use current post-replacement questions, not initial selections or displaced history.
- DB rows retain all original exportable metadata and analytic values.
- LLM rows populate the same historical columns: category and seven public fields normally; unavailable IDs, accuracy, distinction, and other historical-only values use the established missing-value convention. Do not invent measurements or identifiers.
- LLM-only export uses the same upload-compatible schema unless the legacy upload contract demonstrably requires a different existing schema; document any justified difference.
- Generated questions are never automatically inserted into the DB.
- DOCX behavior and answer randomization remain unchanged.

## 6. Make attempt/retry display truthful

- Question-card counts must come from immutable `attempt_telemetry.by_slot`, not rollback-prone mutable slot counters.
- Replace unexplained abbreviations with clear Hebrew labels such as `ניסיונות: 3 · חזרות: 1` (accessible compact presentation is acceptable).
- A failed paid `replace_llm` must remain included after question rollback.
- Preserve cost-ledger totals, terminal summaries, and current retry semantics.

## 7. Prevent audit overwrite in the outer integration

- Give every top-level LLM action (`initial`, `retry`, `replace_llm`) a unique immutable invocation directory before calling the generator. Internal `attempt_01`, `attempt_02` folders may then repeat only beneath distinct invocation directories.
- Use a collision-resistant and traceable identity containing at least job, slot, operation, and a persisted sequence/ID. Never derive uniqueness only from mutable attempt counters.
- Store a safe relative audit reference/identifier with the corresponding ledger record so a failure can be traced without exposing prompts or local absolute paths in the UI.
- Never overwrite or delete earlier invocation evidence. Existing jobs/artifacts remain readable.
- Do not expose raw prompts, responses, source text, or audit paths on the ordinary exam screen.

## Verification

All tests are offline with fake providers and blocked external network. Cover at minimum:

- headings for multiple canonical categories;
- DB metrics with zero, one, and multiple historic values; LLM `NaN`; JSON-safe missing values;
- all four replacement transitions and failure rollback;
- historical overall calculations, threshold changes, missing-value exclusion, and all-missing behavior;
- full export contents/schema/order and LLM-only export contents/schema;
- no DB insertion, unchanged DOCX behavior, and seven-field-only generator context;
- ledger-derived counts after failed paid replacement;
- repeated operations on one slot create distinct audit trees linked to distinct ledger records, with earlier files byte-preserved;
- no current DB/LLM aggregate and no visible semantic history.

Run the full backend suite serially with an isolated temporary DB, frontend tests, and frontend production build. Run targeted generator contract tests only if imports require them; the submodule must remain unchanged.

## Deliverables and checkpoint

- Save under outer `questions-db/WPs/`:
  - `WP21_Restore_Exam_Analytics_and_Exports.md`
  - `WP21_ARCHITECT_REPORT.md` (concise, about 180 lines maximum)
  - refreshed `ARCHITECT_HANDOFF.md`
- Report recovered legacy contract, implementation, routes/schema, calculations, tests, files changed, limitations, and any decision needed from the owner.
- Commit outer changes as `WP21: restore exam analytics and complete exports`.
- Do **not** push.
- End with outer SHA/status, generator pin/status, backup confirmation, tests/build, and confirmation of zero provider calls/key access and no committed runtime artifacts.
