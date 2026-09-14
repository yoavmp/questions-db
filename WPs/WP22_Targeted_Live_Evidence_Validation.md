# WP22 — Targeted Live Evidence Validation

## Scope

Validate WP21GR with three paid operations under one **hard cumulative ceiling of $0.50**. The owner has already started the backend from a key-bearing VS Code terminal at `http://127.0.0.1:4567`.

This WP is validation only. Do not change production code, weaken validation, add an API endpoint, update the submodule pointer, or push either repository.

## Goals

1. Test whether WP21GR fixes the two previous false rejections for which supporting distractor evidence existed.
2. Verify the real outer-backend → generator path, including the WP21R invocation-manifest contract.
3. Measure the real cost and prompt-size impact of candidate-aware evidence.

## Preflight

- Work from the `questions-db` root.
- Record exact outer and generator HEADs and working-tree statuses.
- Confirm the generator contains WP21GR and the backend health endpoint responds.
- Never display, request, read, store, or modify `OPENAI_API_KEY`.
- Confirm current pricing is usable and determine the available `$0.50` budget before any paid call.
- Make no automatic retry: each intended operation may be attempted once.

## Operation 1 — Integrated production generation

Using the already-running backend and its normal production job API:

- Category: `אמבריולוגיה`.
- Select one real DB question and generate one LLM question (`C=2, A=1, B=1`).
- The selected DB question must be supplied as previous-question context.
- Do not bypass the backend or generator pipeline.

Record the final seven-field LLM question, status, attempts/retries, evidence modes, exact cost, pricing basis/warnings, and terminal cost summary. Verify that the prewritten invocation manifest remains byte-identical and that a unique audit directory is used without collision or overwrite.

## Operations 2–3 — Reviewer-only replays

Locate the preserved candidates identified by WP21G/WP21GR:

- `chapter_01_q001`
- `chapter_03_emb_001`

For each candidate:

- Reuse the preserved candidate; do not regenerate it.
- Build its current WP21GR candidate-aware evidence pack.
- Run exactly one current reviewer request followed by the normal deterministic post-review validation.
- Compare the original and new criterion-level verdicts.
- Verify evidence for the correct answer and every distractor.
- Judge the public Hebrew question and answers manually; acceptance alone is not proof of correctness.

### Credential boundary for the replays

First check whether an existing safe interface can perform the reviewer-only replay through the running backend.

- Do not add a temporary endpoint.
- Do not expose the API key to Claude.
- If a replay must run from a process inheriting `OPENAI_API_KEY`, create an ignored, one-shot script under `artifacts/wp22/`, test it offline, and pause.
- Give the owner one exact command to run from the key-bearing terminal.
- The script must enforce the remaining shared budget before each call and must not print secrets, prompts, raw responses, or protected course text.
- Resume after the owner supplies the safe output.

## Shared cost enforcement

Before every paid call:

1. Calculate cost already incurred and remaining allowance.
2. Run the existing pricing/readiness check.
3. Refuse the call if it could violate the remaining ceiling.

Stop all further paid work once cumulative cost reaches `$0.50`. Do not reset or fragment the budget between paths.

## Stop conditions

Stop and report without further paid calls if:

- pricing is missing/blocking or the ceiling cannot be enforced;
- candidate identity or original verdict cannot be established reliably;
- the manifest/audit contract fails;
- a production-code modification would be required;
- repository state is unexpectedly dirty beyond known reports or the advanced submodule checkout.

If a defect is found, document its cause and smallest recommended correction. Do not implement it in WP22.

## Deliverables

Save in the **outer** repository:

- `WPs/WP22_Targeted_Live_Evidence_Validation.md`
- `WPs/WP22_ARCHITECT_REPORT.md`
- refreshed `WPs/ARCHITECT_HANDOFF.md`

The report must include:

- all three outcomes and exact public questions;
- original versus new replay verdicts and criterion changes;
- evidence coverage for the correct answer and each distractor;
- exact cost per operation and combined cost;
- prompt-size comparison where available;
- assessment of whether added evidence is cheaper than the retries it prevents;
- any remaining false rejection or false acceptance;
- both repository HEADs/statuses and secret/audit safety confirmation.

Do not include raw prompts, raw provider responses, protected course text, credentials, or secrets.

## Git checkpoint

After completing the report:

- Commit only the WP22 brief, report, and refreshed outer handoff.
- Do not stage or commit the advanced `exam_generator` gitlink.
- Do not commit live artifacts, replay scripts, prompts, responses, course data, or credentials.
- Leave the generator repository untouched and clean.
- Do not push.
- In the final response, provide the outer commit SHA and both repositories' exact HEAD/status.

