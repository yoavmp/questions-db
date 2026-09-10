# WP18R — Cross-Source Replacement Correction — Architect Report

**Repository:** `questions-db` (outer) · **Executor:** Claude Code · **Date:** 2026-09-10
**Outer starting HEAD:** `d793a9f5f78bdc746ba5cd4cd86f794c4ac40335` (`main`, clean bar the intended
untracked `WPs/WP18R_Cross_Source_Replacements.md`).
**Generator submodule:** `ea59cd857e5618b0260d2bb146dd5573c9ca2309`, `heads/main`, **clean, unchanged,
not committed/pushed**. No gitlink change. `../exam_generator_pre_submodule_backup/` untouched.
**No provider calls, no `OPENAI_API_KEY`** — every test injects an offline fake and blocks sockets.

## 1. Scope

Outer-repo only, three source files + one new test file:

| File | Change |
|---|---|
| `backend/src/jobs/service.py` | `replace_from_db` / `replace_via_llm` accept **any** accepted slot; per-origin state transition helpers; full rollback on failure; number-ordered previous-question context |
| `backend/src/jobs/model.py` | `accepted_questions_ordered` / `progress_view` order by preserved global `number` (stable when a slot changes `kind`) |
| `backend/src/routes/exam_jobs.py` | doc-comment only (handlers already map `JobConflict→409`, `JobError→400/404`) |
| `backend/tests/test_wp18r_cross_source_replacements.py` | new — 15 tests incl. the four-case matrix |

No change to the adapter, readiness, generator boundary, DTO, cost engine, locking, persistence,
API routes/verbs, or the legacy `/api/test/*` path.

## 2. Implementation

**Both endpoints, any origin.** Removed the `slot.kind != "database"` / `!= "llm"` guards. The only
precondition is now `status == "accepted"` with a stored question. `replace-db` handles DB→DB and
LLM→DB; `replace-llm` handles DB→LLM and LLM→LLM.

**Per-origin state transition** (only after success):
- → DB (`_apply_db_origin`): `kind=database`, integer `db_id`, the row's seven fields at the slot's
  preserved `number`, `attempts=retries=0`, `was_repaired=False`, `audit_ref=safe_error=None`.
- → LLM (`_apply_llm_origin`): `kind=llm`, `db_id=None`; seven fields + `GenerationMeta`
  (attempts/retries/cost/audit) already set by `_generate_one` on the accepted result.
- `instance_id`, `slot_id`, `category`, `order_in_category`, public `number` are never touched.
- `plan.db_selected_ids` is recomputed from the live DB slots after each transition.
- `CategoryPlan.total/database/llm` keep the **original request** quotas (see §5).

**Semantic history** — `category_history` only ever receives a displaced **LLM** question, and only
after the replacement succeeds:

| Old origin | New source | Append old to history? | Path |
|---|---|---:|---|
| DB | DB | No | `replace_from_db`, `was_llm=False` |
| DB | LLM | No | `replace_via_llm`, `was_llm=False` |
| LLM | DB | Yes, post-success | `replace_from_db`, `was_llm=True` |
| LLM | LLM | Yes, post-success | `replace_via_llm`, `was_llm=True` |

The generator call for an LLM replacement gets `_previous_for_slot` = every OTHER current category
question (DB group then accepted-LLM group, each in `number` order) + that category's persisted
history, order and repeated `number`s preserved. The target's own old question is excluded (by
`instance_id`) and reaches history — hence a later generator call — only on the LLM→x rows above.
A displaced **DB** question therefore never enters any generator context.

**Failure rollback.** `replace_via_llm` snapshots the slot's held-question/origin/metadata fields
before the attempt and, on any non-accepted result (reject, systemic, cost-ceiling, `None`),
`_restore_slot`s them exactly, keeping only a `safe_error`. `replace_from_db` raises `JobConflict`
before mutating anything when no alternative row exists. Cross-source failure leaves the slot and its
Excel/DOCX projection byte-identical.

**Cost / export.** DB replacement still adds nothing and writes no ledger row. LLM replacement (incl.
a failed attempt) is charged to the existing cumulative ceiling/ledger as `kind="replace_llm"`;
historical entries are immutable across an origin change. `export_llm_xlsx` iterates accepted slots
and filters on **current** `kind == "llm"`, so a slot moved LLM→DB drops out and a displaced LLM kept
only in history is never exported; a slot moved DB→LLM joins the export.

**Ordering.** With a slot's `kind` now mutable, `(db-first, order_in_category)` sort keys could
collide; switched the exam-order sorts to the preserved, unique global `number`. Same output for an
untouched job; correct after any cross-source swap.

## 3. Four-way matrix + verification (all covered by the new test file)

- `test_replacement_matrix` (parametrized ×4): both endpoints accept both starting origins; stable
  `instance_id`/`number`/`category`/`order`; correct post-transition `kind`, `db_id`, metadata and
  DTO `origin`; exact history table above.
- Per-transition: DB→DB costs nothing / swaps row; DB→LLM never feeds the displaced DB question to a
  later generator context; LLM→DB appends history + clears LLM metadata + immutable prior ledger;
  LLM→LLM appends history, new question keeps the number.
- Failure: DB→LLM reject → slot + xlsx rows identical, no history mutation, failed-attempt cost still
  ledgered; LLM→DB with no spare row → `JobConflict`, slot stays LLM, history empty.
- Cross-cutting: displaced LLM reaches `_previous_for_slot` while displaced DB does not; numbers stay
  `1..N` contiguous and category order intact across mixed transitions; export membership follows
  current origin; `app.db` row count/text set unchanged and no generated text inserted; both
  endpoints accept both origins over HTTP (`202` → `replace-llm` on a DB q, `replace-db` on an LLM q,
  final origins flipped).

## 4. Test execution — serial, temp DBs, sockets blocked, zero provider calls

- **Backend:** `cd backend && python -m pytest -q` → **84 passed** (69 prior + 15 WP18R), ~114s, one
  process. `conftest` autouse fixture blocks `socket.connect*` for every `wp18*` test; providers are
  `tests/_wp18_fakes` only.
- **Generator-boundary tests:** not run — no adapter/generator-interface change; the WP18R backend
  tests already drive `production.generate_exam_question` end-to-end through the offline fake.
- **Frontend:** `npm run build` (vite 4) → OK, 1258 modules, `dist/` written (unchanged from WP18).

## 5. Decisions / notes for WP19

- **`CategoryPlan.total/database/llm` are left at the original request quotas** after a cross-source
  swap (only `db_selected_ids` and live slot state move). `progress_view`'s per-category
  `accepted/failed/pending` are computed from real slots and stay correct; the quota line now just
  records "what was asked". If the WP19 UI wants the quota line to track realised origins, decide
  whether to mutate the plan or expose a separate "realised" count.
- **`replace_from_db` still takes no `_RUN_LOCK`/`job.lock`** (unchanged from WP18 — DB ops are
  cheap, provider-free). LLM→DB now also writes `category_history`, marginally widening the
  theoretical lost-update window against a concurrent `run_job`/`replace_via_llm`. Harmless for the
  single-user desktop tool; revisit only if WP19 introduces real concurrency.
- **Failure is a full metadata rollback** (attempts/retries/audit_ref restored), stricter than
  WP18's LLM→LLM behaviour which left them incremented. This matches the WP18R brief ("no
  history/origin/metadata mutation" on failure); a `safe_error` is still surfaced.
- No new endpoints/verbs — WP19's frontend switch is unaffected; `/api/test/*` untouched.

## 6. Git

- Commit (outer only): `WP18R: allow cross-source question replacement` — `backend/src/jobs/`,
  `backend/src/routes/exam_jobs.py`, `backend/tests/test_wp18r_cross_source_replacements.py`,
  `WPs/WP18R_Cross_Source_Replacements.md`, `WPs/WP18R_ARCHITECT_REPORT.md`, `WPs/ARCHITECT_HANDOFF.md`.
- **Not pushed.** Generator submodule not staged/committed/pushed. Backup untouched.
