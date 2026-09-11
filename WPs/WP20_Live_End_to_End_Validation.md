# WP20 — Live end-to-end validation and final UI cleanup

## Goal

Hide internal semantic-history data from the normal interface, then validate one small mixed exam through the real frontend, backend job system, generator, replacements, exports, and cost reporting.

## Baseline and boundaries

- Work in outer `questions-db` only.
- Expected outer HEAD: `d41f4f4eadba8fccbf7557283c50554c71bf7876`, clean except this brief.
- Keep `exam_generator` clean and pinned at `ea59cd857e5618b0260d2bb146dd5573c9ca2309`; do not edit or commit it.
- Do not touch `../exam_generator_pre_submodule_backup`.
- A live OpenAI test is authorized with a **hard cumulative ceiling of $1.00**. Do not exceed it, bypass cost gates, or make unrelated provider calls.
- Never print, log, store, transmit to the frontend, or commit `OPENAI_API_KEY`. Check only whether it is present.
- Stop and report if the baseline differs or safe live execution is impossible.

## 1. Final UI cleanup — offline first

- Remove `category_history` from the ordinary user-facing exam screen. It is internal semantic-uniqueness state, not exam content.
- Preserve it unchanged in backend persistence and in the context sent to later LLM generation.
- It may remain visible in backend diagnostic data; do not expose it in normal UI text or question cards.
- Keep initial `C/A/B` values as provenance only. Never calculate, display, or enforce a current aggregate DB/LLM balance after replacements.
- Add/update tests proving both rules.

Run the relevant backend/frontend tests and frontend production build before any live call. Fix offline failures first.

## 2. Credential boundary

The owner has already exported `OPENAI_API_KEY` and verified it as available in a VS Code integrated terminal. Do not request or repeat key setup. Claude must:

- in the shell that will launch the backend, verify only presence with a boolean/nonempty check that cannot display the value;
- if present, launch the backend from that environment so the SDK inherits it;
- never print the variable, ask the owner to paste it, or place it in chat, source, config, `.env`, fixtures, reports, frontend code, or recorded commands;
- confirm the key cannot appear in browser requests or built frontend assets;
- use the repository’s documented backend/frontend startup commands and report them without secrets.

If Claude's command environment reports the variable missing even though the owner verified it in the integrated terminal, do not reconfigure or request the key. Pause and ask the owner to launch the backend from the already-verified VS Code terminal; then continue testing against that local backend.

## 3. Authorized live scenario

Use the real local application and owner data. Prefer category `היסטולוגיה`, which has already produced valid questions and should reduce content-related confounds.

1. Create one category plan: `C=2`, `A=1`, `B=1`, exam ceiling `$1.00`; all other categories zero.
2. Confirm the DB question is selected first and the LLM question is generated with that DB question as previous-question context.
3. Once both are accepted, replace the DB-origin question using `צור שאלה אחרת` (DB→LLM). Confirm its displaced DB question is not added to semantic history.
4. Replace one LLM-origin question using `החלף בשאלה מהמאגר` (LLM→DB). Confirm the displaced LLM question is retained in semantic history for future uniqueness.
5. Do not perform further paid generations. A failed/retried attempt counts toward the same `$1.00` ceiling; never reset the job or create another paid job merely to evade the limit.

If generation fails honestly or the cap stops the sequence, preserve the evidence and report it; do not force acceptance or silently expand scope.

## 4. Verify the complete workflow

During the scenario, verify and record:

- canonical ordering, progress polling, partial results, origin badges, and correct button availability;
- stable question instance/number/category across both replacement types;
- mutation locking and failure rollback;
- previous-question context growth and the exact displaced-question history policy;
- cumulative cost including failed attempts/retries, pricing basis/warnings, and the final backend-terminal cost line;
- generated-question Excel export contains only current LLM questions and does not insert them into the DB;
- Hebrew DOCX generation uses the final current questions, strips integration metadata, preserves answer randomization, and renders acceptably in RTL.

Inspect exported files without committing them. Keep live audits/exports under already-ignored artifact paths. Do not include raw provider responses or rendered prompts in the report.

## 5. Owner-review evidence

In `WPs/WP20_ARCHITECT_REPORT.md`, include:

- each accepted live-generated question’s seven public JSON fields, labeled as initial or replacement;
- a concise source-grounding and Hebrew-language assessment;
- operation/attempt count, per-operation cost, final cumulative cost, calculation basis, and warnings;
- the final origin sequence and history-policy result;
- Excel/DOCX verification result;
- any rejection/retry reason, without raw provider payloads or hidden prompts.

Do not make subjective content changes merely to improve the report. Surface questions honestly for owner review.

## 6. Tests, report, and Git checkpoint

- After the live test, rerun affected automated tests and the frontend production build without additional provider calls.
- Save the brief, concise report, and refreshed handoff under outer `questions-db/WPs/`:
  - `WPs/WP20_Live_End_to_End_Validation.md`
  - `WPs/WP20_ARCHITECT_REPORT.md`
  - `WPs/ARCHITECT_HANDOFF.md`
- Commit outer changes as `WP20: validate live integrated exam flow`.
- Do **not** push.
- Do not stage live artifacts, exports, data, secrets, `.env*`, raw responses, or generator changes.
- End with outer SHA/status, generator pin/status, backup confirmation, tests/build, exact number of provider operations, final cost, and confirmation that no secret or raw provider response was committed.
