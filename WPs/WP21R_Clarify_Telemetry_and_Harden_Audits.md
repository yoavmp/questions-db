# WP21R — Clarify attempt telemetry and make audits crash-safe

## Goal

Apply the owner’s WP21 decisions: keep the recovered `N/A` display, separate failure retries from intentional LLM replacements, and make every audit invocation permanently unique even across crashes.

## Boundary and baseline

- Work only in outer `questions-db`.
- Expected latest commit subject: `WP21: restore exam analytics and complete exports`, with parent lineage from `4c0a7df1b551bca8bf55dd56ddea3e1d0f7aeabe`; working tree clean except this brief.
- Keep `exam_generator` untouched, clean, and pinned at `ea59cd857e5618b0260d2bb146dd5573c9ca2309`.
- Do not touch `../exam_generator_pre_submodule_backup`.
- Offline only: no provider calls and no API-key access.
- Stop and report if these conditions differ.

## 1. Preserve the recovered missing-value convention

- Keep standard JSON `null` internally/API-side.
- Keep visible `N/A` for missing question analytics and overall analytics.
- Keep the historical Excel missing-cell convention recovered in WP21.
- Add/retain an explicit regression test so no literal `NaN`, zero, or fabricated measurement replaces missing data.

## 2. Separate attempt types in the UI

Use immutable `attempt_telemetry.by_slot` only. Do not read rollback-prone slot counters.

Display distinct, plainly labeled values per relevant slot/question:

- `ניסיונות`: all recorded LLM candidate attempts for that slot;
- `ניסיונות חוזרים לאחר כשל`: attempts whose top-level operation is `retry`;
- `החלפות LLM`: attempts whose top-level operation is `replace_llm`;
- expose failed-attempt count in the same compact diagnostic area when nonzero.

An intentional replacement must never increase the displayed failure-retry count. A failed paid replacement must remain present in total/failed/replacement counts after question rollback. Keep accessible labels/tooltips if the compact mobile layout requires abbreviations.

Do not change retry eligibility, cost accounting, semantic history, or replacement behavior.

## 3. One immutable directory per LLM invocation

For every top-level `initial`, `retry`, or `replace_llm` invocation, allocate a fresh directory before the generator call:

```text
<job>/<slot>/<operation>_<sequence>_<uuid>/attempt_01
```

Requirements:

- UUID is the authoritative collision-proof identity; operation and sequence are human-readable context only.
- Never reuse, overwrite, truncate, or delete an earlier invocation directory.
- A crash after directory allocation but before ledger append must not block or collide with the next invocation.
- Write a small atomic, secret-free invocation manifest before the provider boundary containing only safe identifiers/timestamps/state (`job_id`, `slot_id`, operation, sequence, UUID, creation time). It must make an orphaned crash directory diagnosable without prompts or responses.
- When an outcome is recorded, link its ledger record to the UUID and safe relative audit reference. Do not expose absolute paths or audit contents in the normal UI.
- Preserve readability of existing WP18–WP21 jobs and audit artifacts.

Use secure UUID generation. Do not solve collisions by deleting an existing directory or incrementing until a path appears free.

## Verification

Offline tests with fake providers and blocked external network must prove:

- `N/A`/`null`/Excel missing-value behavior remains unchanged;
- initial attempts, failure retries, intentional replacements, and failed replacement rollback produce the correct separate UI counts;
- two or more operations on one slot create different UUID directories and ledger links;
- simulated crash after allocation but before ledger append leaves the first directory byte-preserved and the next invocation uses a different directory;
- manifests contain only the permitted safe fields and no question, prompt, response, source content, credential name/value, or absolute path;
- existing job fixtures remain readable;
- WP21 headings, analytics, two exports, DOCX, replacement, history, cost, and ordering tests stay green.

Run the full backend suite serially with an isolated temporary DB, frontend tests, and frontend production build. The generator submodule must remain unchanged.

## Deliverables and checkpoint

- Save under outer `questions-db/WPs/`:
  - `WP21R_Clarify_Telemetry_and_Harden_Audits.md`
  - `WP21R_ARCHITECT_REPORT.md` (concise)
  - refreshed `ARCHITECT_HANDOFF.md`
- Report exact counter semantics, final audit layout/manifest/ledger link, crash simulation, tests, files changed, and any owner decision needed.
- Commit outer changes as `WP21R: clarify telemetry and harden audit storage`.
- Do **not** push.
- End with outer SHA/status, generator pin/status, backup confirmation, tests/build, and confirmation of zero provider calls/key access and no committed runtime artifacts.
