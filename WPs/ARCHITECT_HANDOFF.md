# questions-db — Architect Handoff

**Repository:** `questions-db` (outer) — Hebrew exam question bank + test builder
(Flask backend, React/Vite frontend) integrating the Hebrew neuroanatomy
question **generator** as a Git submodule.
**Updated:** 2026-09-11 · **Latest completed WP:** WP20 + its owner-approved follow-up (live
end-to-end validation, `category_history` hidden from the exam UI, and a corrected
backend-terminal cost line).
**Next:** none scheduled. The "יצירת מבחן" screen uses `/api/exam-jobs*` end to end and has now been
validated against a real local backend + real OpenAI generation (one small mixed job, $0.087 of a
$1.00 authorized ceiling). The legacy synchronous `/api/test/generate` + `/api/test/replace-question`
endpoints are **still present** (nothing on the current screen calls them) and may be retired by a
later WP.

## 1. Repository SHAs

| Repo | Path | SHA | State |
|---|---|---|---|
| Outer `questions-db` | `.` | *(set by the `WP20 follow-up: print cumulative LLM cost` commit — `git rev-parse HEAD`; parent is the `WP20: validate live integrated exam flow` commit)* | branch `main`; **not pushed** |
| Generator `exam-generator` | `exam_generator/` (submodule) | `ea59cd857e5618b0260d2bb146dd5573c9ca2309` | `heads/main`, **fully clean** (the stray `.DS_Store` was deleted in the follow-up), **do not commit/push here** |

Generator remote: `https://github.com/yoavmp/exam-generator.git` — `origin/main`
contains `ea59cd8` (WP17GR). Pre-submodule snapshot preserved at
`../exam_generator_pre_submodule_backup/` (untouched).

## 2. Submodule update / re-pin procedure

```bash
git submodule update --init --recursive          # fresh clone / missing submodule
```

To **re-pin** to a newer generator commit:

```bash
git -C exam_generator fetch origin
git -C exam_generator checkout <new_sha>          # detached, exact commit
git add exam_generator                            # stages ONLY the gitlink
# update the recorded pin so readiness stops flagging drift:
#   backend/src/integration/generator_pin.py  ->  EXPECTED_GENERATOR_PIN
# then re-verify:
cd backend && python -m pytest -q                 # WP17 + WP18 suites
python -c "from src.integration.category_map import verify_against_generator_catalog as v; \
           print(v('../exam_generator/config/categories.json'))"
```

Rules: the outer repo tracks **only** `.gitmodules` and the `exam_generator`
gitlink. Never `git add exam_generator/<file>`. Never commit or push inside
`exam_generator/`. `exam_generator/Data/` is git-ignored course runtime input,
supplied out of band (copy it into the submodule working tree after any re-clone —
LLM readiness reports it missing otherwise).

## 3. Integration surface (outer repo)

| Area | Location |
|---|---|
| Canonical categories (spelling + display order) | `backend/src/utils/category_order.py::CATEGORY_ORDER` |
| Canonical ↔ generator context binding, aliases, strict resolver | `backend/src/integration/category_map.py` |
| Owner policy (attempts, $5 cap, arithmetic, DB ownership) | `backend/src/integration/owner_policy.py` |
| Per-category `{total,database,llm}` request contract | `backend/src/integration/request_contract.py` |
| Exam-question DTO (7 fields + meta, `docx_view()`) | `backend/src/integration/exam_question_dto.py` |
| **Thin** generator adapter over `production.generate_exam_question` | `backend/src/integration/generator_adapter.py` |
| Recorded generator pin (readiness drift check) | `backend/src/integration/generator_pin.py` |
| Non-network LLM readiness service | `backend/src/integration/readiness.py` |
| Persistent sequential job model / store / worker | `backend/src/jobs/{model,store,service}.py` |
| Cross-source replacement (DB↔LLM, both endpoints, any accepted slot) | `backend/src/jobs/service.py::replace_from_db` / `replace_via_llm` (WP18R) |
| Job + readiness API blueprint | `backend/src/routes/exam_jobs.py` (`/api/exam-jobs*`) |
| Ledger-derived attempt/retry telemetry (WP19) | `backend/src/jobs/service.py::ledger_telemetry` → `result_view()["attempt_telemetry"]` |
| Job-API exam screen (WP19) | `frontend/src/components/ExamGenerationSection.jsx` + `frontend/src/lib/examGen.js` (pure) + `examApi.js` (client) |
| Root install / start flow | `scripts/dev_install.sh`, `SETUP.md` |
| Contract + job tests (temp DB, fake provider, sockets blocked) | `backend/tests/test_wp17_*.py`, `test_wp18_*.py`, `test_wp18r_*.py`, `test_wp19_frontend_contract.py`, `test_wp20_semantic_history_boundary.py`, `test_wp20_terminal_cost_log.py` |
| Frontend tests (Vitest + Testing Library, fake API fixtures) | `frontend/src/**/*.test.{js,jsx}`; `cd frontend && npm test` |

- `/api/test/categories` still returns all 20 canonical categories in
  `CATEGORY_ORDER` with live DB availability (incl. a zero-count category). The
  WP19 job UI should use it; WP18 adds no parallel categories route.
- **Cross-source replacement (WP18R):** `POST …/replace-db` and `…/replace-llm`
  each accept **any** accepted slot (DB→DB, LLM→DB, DB→LLM, LLM→LLM). `instance_id`,
  `slot_id`, `category`, `order_in_category`, public `number` are stable; the
  slot's `kind`/`db_id`/metadata and DTO `origin` switch to the new origin on
  success. Only a displaced **LLM** question enters `category_history`
  (post-success); a displaced DB question never does and never reaches a later
  generator context. Cross-source failure is a full rollback (slot + Excel/DOCX
  identical); a failed LLM attempt is still ledgered. Export = current
  `kind == "llm"` only. `CategoryPlan.total/database/llm` stay at the original
  request quotas (request provenance only — no realised/current DB-vs-LLM
  balance is computed or exposed anywhere; per-question `origin` is the only
  composition signal).
- **WP19:** `replace_from_db` now takes the same `_RUN_LOCK` + `job.lock` as
  every other job mutation (`JobBusy → 409` on a double click / concurrent op).
  `GET /api/exam-jobs/<id>` adds `attempt_telemetry` — attempt/retry/charged-
  failure counters folded from the immutable `cost_ledger`, by category and slot,
  so a charged failed attempt stays diagnosable after a rollback. No route/verb
  or generator-boundary change.
- **WP20 (UI only — no backend change):** `frontend/src/components/ExamGenerationSection.jsx` no
  longer renders `category_history` anywhere (the "שאלות בינה שהוחלפו" card was removed). The field
  still round-trips through backend persistence and still feeds `_previous_for_slot` for later LLM
  generation, and it still appears in `result_view` as backend diagnostic data — only the
  user-facing screen stopped showing it. New tests on both sides prove this
  (`ExamGenerationSection.test.jsx`, `backend/tests/test_wp20_semantic_history_boundary.py`).
- **WP20 live validation:** one real job against the owner's local backend + real OpenAI calls —
  `היסטולוגיה`, `C=2/A=1/B=1`, $1.00 ceiling, **2 provider ops, $0.0869755 total (8.7% of cap)**,
  0 failures/retries. Confirmed live: DB-first selection with the DB question in the LLM's
  previous-question context; DB→LLM via `צור שאלה אחרת` does **not** add the displaced DB question
  to `category_history`; LLM→DB via `החלף בשאלה מהמאגר` **does** retain the displaced LLM question
  there (and it then appears in the next generation's context); stable `instance_id`/`number`/
  `category` across both transitions; Excel export = current LLM question only, no DB insert;
  Hebrew DOCX (± answers) strips job metadata, keeps the endpoint's own answer-shuffle, renders
  RTL. Full detail, per-operation costs, and the two accepted questions' seven fields are in
  `WPs/WP20_ARCHITECT_REPORT.md`.
- **WP20 follow-up — backend-terminal cost line, corrected.** WP20's live-validation report
  originally claimed no cost line is ever printed to the backend terminal; that was a **search
  error in that session**, not a real gap — `service._print_terminal_summary` has printed one
  since WP18 (`d793a9f`), after the initial run and after every LLM retry/replacement (accepted or
  failed alike), never for a DB-only replacement. The owner's follow-up asked for two fields it was
  missing; both are now in: `_print_terminal_summary(job, *, operation)` (was `header=`) prints
  `job=<id> operation=<initial|retry|replace_llm> status=<...> llm_cost=$<...> basis=<...>
  remaining=$<...> accepted=<n>/<n> failed=<n> retries=<n> pricing_warnings=<...>` — never a
  prompt, response, question, or secret. 6 new offline tests
  (`backend/tests/test_wp20_terminal_cost_log.py`) prove: one well-formed line per initial run;
  one line on a retry's acceptance *and* on its charged failure; one line on an LLM replacement's
  acceptance *and* on its charged failure; **no** line (and no cost movement) for
  `replace_from_db`; and the printed `remaining=$` matches `ceiling − accumulated` exactly. Full
  detail in `WPs/WP20_ARCHITECT_REPORT.md` §8.
- Backend entrypoint `backend/run.py`, **port 4567**. `src/main.py` runs
  `store.recover_on_start()` at import (running jobs → `interrupted`).
- Job state lives under git-ignored `artifacts/exam_jobs/<job_id>/` — JSON only,
  never in `app.db`, never in Git. Per-slot generator audits under
  `.../slots/<slot_id>/`. `EXAM_JOBS_ROOT` overrides the location (tests do).

## 4. WP17 blockers — both resolved

1. **Generator production API** — done (WP17G/WP17GR): `exam_generator.production.
   generate_exam_question(*, category_name, number, previous_public_questions,
   cost_ceiling_usd, audit_dir, max_attempts=2, provider=None,
   pricing_stale_after_days=30, <path overrides>) -> ProductionGenerationResult`.
   The WP18 adapter is a thin wrapper over it — no re-implemented assembly.
2. **Generator cross-platform test hygiene** — done (WP17G): LF fixtures,
   `.gitattributes`, self-set sentinel key in the stub-runner tests,
   `constraints.txt` + `docs/DEPENDENCY_LOCK.md`. The pinned generator's full
   suite is green (886→900 collected, 726 passed, 174 Data/font skips) and the
   targeted production tests pass network-blocked from this repo's env.

**Open items (post-WP20 follow-up)**

- No live failure/retry/rollback was exercised in WP20 (by design, to stay inside the one
  authorized paid job) — that surface keeps relying on the offline fake-provider suites
  (`test_wp18r_cross_source_replacements.py`, `test_wp19_frontend_contract.py`).
- No browser-automation tool (Playwright/Puppeteer/Cypress) is installed in this environment; a
  future live UI validation would need one added first if a literal click-through is required.

- The in-process daemon-thread worker is unchanged (single-user desktop tool);
  `replace_from_db` now also serialises through `_RUN_LOCK` (WP19). Concurrent
  job mutations return `409` and the frontend surfaces the reason. A real
  queue/process is only needed for multi-user/multi-process.
- **Realised origin count:** WP19 deliberately does **not** compute or display a
  current DB-vs-LLM balance (owner ruling). If one is ever wanted it must be a
  *separate* field, never a rewrite of `CategoryPlan.total/database/llm`.
- Progress polling is a fixed 1.5 s interval (no backoff / websockets) — fine for
  a sequential single-user job.
- Two dependency-pin conflicts between `backend/requirements.txt` and
  `exam_generator/constraints.txt` (`pytest` 7.4.2 vs 9.1.1; `MarkupSafe` 2.1.3
  vs 3.0.3) are documented in `scripts/dev_install.sh` and the WP18 report, not
  resolved. A unified lockfile for the integrated env is optional.
- Legacy `/api/test/generate` + `/api/test/replace-question` are unused by the UI
  but still mounted; a later WP may retire them (`/api/test/categories` and
  `/api/test/export-docx` stay — WP19 uses both).
- Frontend now has a Vitest/Testing-Library harness (`npm test`); `@testing-
  library/react@16` + `@testing-library/dom@10` are pinned so `user-event` and
  RTL share one `dom` copy.

## 5. Authority order

Newest owner ruling → verified outer repo + tests → this handoff → WP briefs →
older records. The generator is authoritative for question-generation behaviour
and is changed only by its own WPs.
