# WP18R — Cross-Source Replacement Correction

## Goal

Allow both replacement actions for every accepted exam question while preserving the intended semantic-history rules. Modify **only** the outer `questions-db` repository. **No live API calls.**

## Starting state

- Outer HEAD: `d793a9f5f78bdc746ba5cd4cd86f794c4ac40335`, clean.
- Generator pin: `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, clean and unchanged.
- Backup remains untouched.
- The new WP18R brief is an intended untracked file; stop for any other dirt or SHA mismatch.

## Required behavior

Both existing endpoints must accept any accepted current slot:

- `replace-db`: DB→DB and LLM→DB.
- `replace-llm`: DB→LLM and LLM→LLM.

Preserve the slot’s `instance_id`, category, order and public `number`. On success, update origin-specific state consistently:

- current DB question: `origin/kind=database`, integer `db_id`, DB metadata/defaults, no current LLM generation metadata;
- current LLM question: `origin/kind=llm`, `db_id=null`, LLM defaults and current generation metadata.

Historical job cost/ledger entries remain immutable when the current slot changes origin.

## Semantic-history rule

Only displaced **LLM-generated** questions enter `category_history`; displaced DB questions do not. This is intentional because a DB question may be rejected for prior use, wording or accuracy rather than its concept.

| Old origin | New source | Append old question to history? |
|---|---|---:|
| DB | DB | No |
| DB | LLM | No |
| LLM | DB | Yes, after success |
| LLM | LLM | Yes, after success |

- Append only after replacement succeeds. On failure, retain the old question and make no history/origin/metadata mutation.
- For LLM replacement, exclude the target’s old question from the current-question prefix. Include it through history only when it was LLM-origin and only in the persisted post-success history.
- Every later LLM generation/retry/replacement receives all other current category questions plus all prior displaced LLM questions, preserving insertion order and repeated numbers.
- DB selection continues excluding DB questions currently in the exam; no permanent exclusion of previously discarded DB questions is required.

## Cost, export and concurrency

- DB replacement adds no cost. LLM replacement uses and updates the existing cumulative job ceiling/ledger, including failed attempts.
- Cross-source failure must leave the slot and Excel/DOCX projections unchanged.
- Generated-question Excel export includes only questions whose **current** origin is `llm`; a displaced LLM retained only in history is not exported.
- Preserve the existing single-worker lock, atomic persistence, readiness checks, terminal cost summary and HTTP conflict behavior.

## Offline verification

Add a four-case replacement matrix test and verify:

- both endpoints accept both starting origins;
- stable `instance_id`/number/category/order;
- correct `kind`, `db_id`, current metadata and DTO origin after each transition;
- the exact history matrix above, including failure rollback;
- a displaced LLM later reaches generator context, while a displaced DB does not;
- current-question context, repeated history numbers and ordering remain intact;
- cost/ledger behavior and export membership across origin changes;
- no DB insertion of generated questions and no mutation of real `app.db`.

Run the complete backend suite serially with temporary DBs and sockets blocked. Run relevant generator-boundary tests only if needed; do not modify the submodule. Run the frontend build as a regression check. Zero provider calls.

## Outputs and Git

- Save `WPs/WP18R_ARCHITECT_REPORT.md` (≤120 lines) and refresh outer `WPs/ARCHITECT_HANDOFF.md`.
- Report implementation, four-way matrix, history/cost/export behavior, tests and any decision required before WP19.
- Commit only the outer repository as `WP18R: allow cross-source question replacement`; do not push.
- End with outer full SHA/status, generator pin/status, and confirmation that the backup is untouched.
