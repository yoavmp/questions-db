# WP21R — Clarify attempt telemetry and harden audit storage — Architect Report

**Repository:** `questions-db` (outer) · **Executor:** Claude Code · **Date:** 2026-09-11
**Outer starting HEAD:** `05e6162cc1a7181fc9deccfadea981b6e0c2a360` (`WP21: restore exam analytics
and complete exports`), parent `4c0a7df1b551bca8bf55dd56ddea3e1d0f7aeabe` — matched, clean bar the
untracked brief.
**Generator submodule:** `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, clean, untouched throughout.
**Offline throughout:** no `OPENAI_API_KEY` read, zero provider/network calls (fake providers only;
`llm_ready` sets only an in-process sentinel env var).

## 1. Missing-value convention (§1) — unchanged, regression strengthened

WP21's convention was already correct end to end: JSON `null` internally (`model.missing_analytics()`
→ `{"accuracy": None, "distinction": None, ...}`), `'N/A'` on screen (`examGen.formatMeasure`), and
the legacy Excel blank-cell convention (`service._legacy_perf_cell` → `""`, never `0`, never `"NaN"`).
Nothing here needed to change. What was weak was the **backend export regression test**:
`test_full_export_schema_order_and_missing_value_convention` used `assert not r[9]`, which a
*fabricated* `0` would also satisfy (`not 0 == True`). Replaced with explicit `r[9] in (None, "")` plus
an explicit `!= 0` / `!= "NaN"` check on every missing cell, for both LLM rows and DB rows with no
history. The frontend already had a strict, correctly-worded test
(`formatMeasure` — `'is N/A -- never the literal text "NaN", never a fabricated 0'`); a duplicate
backend-side check (`missing_analytics()` values are `None`, not `0`, not `NaN`) was added to the new
WP21R test file for symmetry.

## 2. Separated attempt/retry/replacement telemetry (§2)

**Root cause found:** `ledger_telemetry` (`service.py`) already computed `retries` and `replacements`
as two separate ledger counters — the backend was never the problem. The bug was entirely in the
frontend: `examGen.slotAttemptCounts` / `slotAttemptCountsByInstance` **folded** them —
`retries: (b.retries || 0) + (b.replacements || 0)` — into one figure labeled `חזרות`, and `SlotChips`
/ `ResultQuestion` rendered only that combined number. Concretely, this meant an **intentional**
`replace_llm` call showed up identically to a **failure retry** — exactly what the owner ruled must
never happen.

**Fix:** the two helpers now return `{ attempts, retries, replacements, failedAttempts }` — four
separate fields, none folded. `SlotChips` and `ResultQuestion` render up to four distinct,
plainly-labeled pieces, each shown only when non-zero (kept compact, no abbreviation needed):

```
ניסיונות: N                              — always shown when attempts > 0
· ניסיונות חוזרים לאחר כשל: N            — only if retries > 0  (kind == "retry")
· החלפות LLM: N                          — only if replacements > 0  (kind == "replace_llm")
· נכשלו: N                               — only if failedAttempts > 0  (charged or not)
```

The aggregate telemetry card (category/totals rollup, unchanged section, WP21) was relabeled for
terminology consistency: `ניסיונות חוזרים לאחר כשל` / `החלפות LLM` instead of the looser `ניסיונות
חוזרים` / `החלפות בבינה`.

Source is still exclusively `attempt_telemetry.by_slot` (never the mutable, rollback-prone
`slot.attempts`/`slot.retries`) — that rule was already correctly followed and is untouched. Retry
eligibility, cost accounting, semantic history, and replacement behavior are all untouched — this WP
is display-only on the frontend, plus a backend telemetry field addition (§3) that the UI does not
consume.

**Verified (new/updated tests, `examGen.test.js` + `ExamGenerationSection.test.jsx`):** retries and
replacements never fold together; an intentional replacement renders `החלפות LLM` and explicitly
never renders `ניסיונות חוזרים לאחר כשל`; a genuine failure retry renders the reverse; a failed paid
replacement's charged failure (`נכשלו`) stays visible after the slot's own mutable counters roll back
(WP18R) — extending the existing WP21 rollback-visibility test rather than replacing it.

## 3. One immutable, crash-safe directory per invocation (§3)

**Root cause found and fixed** (this is the substantive backend change). WP21's `_generate_one` built
each invocation directory as `<kind>_<seq>` where `seq = len(job.cost_ledger) + 1`, computed
*before* the (possibly crashing) provider call, and only made durable *after* it returns
(`_record_cost` appends to `cost_ledger`, which only happens once `generate_category_question`
returns). **If the process died anywhere inside that call — the exact crash window this WP is about —
`cost_ledger` stayed unchanged, so the next invocation for that slot recomputed the identical `seq`.**
With the old `invocation_audit_dir`'s `mkdir(..., exist_ok=True)`, that next invocation **silently
reused the crashed invocation's directory**, letting the generator's own `attempt_01`/`attempt_02`
counter overwrite whatever evidence the crashed call had already written. This is precisely the
"crash after allocation but before ledger append" scenario the brief asked to harden against, and it
was reproducible: two calls with the same `kind` on the same slot, ledger unchanged in between,
collide on name.

**Fix — UUID is now the sole authoritative identity:**

```
<job_id>/slots/<slot_id>/<operation>_<sequence>_<uuid4>/
  invocation_manifest.json      # written BEFORE the provider call
  attempt_01/ ...               # the generator's own evidence (unchanged)
```

- `store.new_invocation_uuid()` draws a fresh `uuid.uuid4()` (OS CSPRNG) for **every** call, never
  derived from ledger length or any other mutable state.
- `store.invocation_dir_name(operation, sequence, uuid)` builds the name; `operation`/`sequence` stay
  as human-readable context exactly as before (`operation` restricted to
  `initial|retry|replace_llm`), but carry **no** collision-avoidance responsibility any more.
- `store.invocation_audit_dir` now calls `mkdir(..., exist_ok=False)` — a name collision (which should
  be cryptographically impossible with a fresh v4 UUID) is now a loud `FileExistsError`, never a
  silent reuse. The function still never deletes, truncates, or steps around an existing path.
- `store.write_invocation_manifest(audit_dir, manifest)` — atomic (`tempfile` + `os.replace`, same
  pattern as `store.save`) — writes `invocation_manifest.json` **before** `generate_category_question`
  is called. It rejects (`ValueError`) any field outside the fixed safe set
  `{job_id, slot_id, operation, sequence, invocation_uuid, created_at}` — no question, prompt,
  response, source content, credential, or absolute path can enter it structurally, not just by
  convention.
- `cost_ledger` entries gained an `invocation_uuid` field (alongside the existing `audit_ref`), so a
  ledger record can be matched to its on-disk manifest directly.
- `_generate_one` (service.py) is the single call site for all three top-level operations
  (`initial`/`retry`/`replace_llm` all funnel through it), so this is one change covering every
  invocation path.

**Crash simulated exactly as specified:** a test manually allocates a directory + manifest + fake
`attempt_01` evidence for the *same* `(operation, sequence)` the real run will independently compute
(ledger left unchanged, reproducing the crash state), then runs the real job. The real run lands in a
**different** directory (different UUID); the crashed directory's manifest and evidence are
byte-for-byte unchanged; the crashed UUID never appears in the real ledger.

**Readability preserved:** `audit_ref` is stored and displayed as an opaque string; nothing parses or
validates the format of an *already-persisted* `audit_ref` (validation only runs when a *new*
directory is being created). A dedicated test persists a job with a pre-WP21R-style `audit_ref`
(`slots/<slot_id>/initial_0001`, no UUID) and confirms it still round-trips through `store.save`/
`store.load` unchanged.

## 4. Files changed

Backend: `src/jobs/store.py` (`new_invocation_uuid`, `invocation_dir_name`,
`write_invocation_manifest`, hardened `invocation_audit_dir`, updated `_INVOCATION_RE`/module
docstring), `src/jobs/service.py` (`_generate_one` allocates UUID-based dir + pre-call manifest,
`_record_cost` gains `invocation_uuid`), `tests/test_wp21_analytics_and_exports.py` (strengthened §1
export assertions), `tests/test_wp21r_audit_hardening.py` (new, 8 tests).
Frontend: `lib/examGen.js` (`slotAttemptCounts`/`slotAttemptCountsByInstance` return four separate
fields instead of one folded figure), `components/ExamGenerationSection.jsx` (`SlotChips`,
`ResultQuestion`, aggregate telemetry card labels), `lib/examGen.test.js` (+1 test, existing tests
updated for the new shape), `components/ExamGenerationSection.test.jsx` (+1 test, existing
replace_llm-visibility test extended to assert the retry/replacement separation).

No change to `src/integration/generator_adapter.py` or any generator-facing contract — `audit_dir` is
still passed through as a plain string; the generator's own internal `attempt_NN` writing is
untouched.

## 5. Tests / build

- Backend `pytest -q`, serial, temp DB, sockets blocked (WP18-named tests; WP21/WP21R tests use the
  same offline fakes without needing the name-gated network block): **121 passed** (113 prior + 8
  new). Zero failures.
- Frontend `npx vitest run` (full suite: `examApi.test.js` + `examGen.test.js` +
  `ExamGenerationSection.test.jsx`): **81 passed** (WP21's reported 79 + 2 new — one proving an
  intentional replacement is never counted as a retry, one proving a genuine failure retry renders
  distinctly from any replacement). `npm run build`: OK (same pre-existing, unrelated CSS-minify
  warning as WP21, nothing touched here).
- Generator-boundary tests: not run — no adapter/generator-interface change.

## 6. Owner decisions already applied (no open questions)

Every item in the brief was a direct, unambiguous instruction (this is a "clarify + harden" WP, not a
design WP) — nothing here required a judgment call back to the owner:

- Keep `N/A` display + `null` internally: confirmed already correct, only the regression test was
  weak (fixed).
- Separate retry vs. replacement display, never fold: implemented exactly as specified, including the
  "never increase the displayed failure-retry count" and "failed paid replacement stays visible after
  rollback" invariants, both directly tested.
- UUID-authoritative, crash-safe invocation directories, pre-call safe-field-only manifest, no
  deletion/collision-stepping: implemented exactly as specified and crash-simulated per the brief's
  verification list.

## 7. Git

- Outer commit: `WP21R: clarify telemetry and harden audit storage` — the files in §4 plus this report
  and the refreshed `ARCHITECT_HANDOFF.md`. **Not pushed.**
- Generator submodule untouched, pinned at `ea59cd857e5618b0260d2bb146dd5573c9ca2309`. Backup
  (`../exam_generator_pre_submodule_backup`) untouched. Zero provider calls, zero `OPENAI_API_KEY`
  access (real or sentinel outside test fixtures), no runtime artifact (`artifacts/exam_jobs/…`)
  committed.
