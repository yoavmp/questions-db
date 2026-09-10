# WP18 — Backend Exam-Generation Jobs — Architect Report

**Repository:** `questions-db` (outer) · **Executor:** Claude Code · **Date:** 2026-09-10
**Outer starting HEAD:** `3dbe68e3c1b38b168ba549ab65b8ac33daa88f1e` (`main`, 1 unpushed WP17 commit).
**Generator submodule:** re-pinned `e5f4e0b…` → **`ea59cd857e5618b0260d2bb146dd5573c9ca2309`**
(`origin/main` confirmed to contain it; gitlink staged; the submodule tree is **not** modified,
committed or pushed). `../exam_generator_pre_submodule_backup/` untouched.
**Frontend:** unchanged (WP19 switch). `npm ci && npm run build` OK.
**No provider calls, no `OPENAI_API_KEY` needed** — every test injects a fake provider and blocks sockets.

## 1. Repository boundary

- Verified the expected outer dirt only (advanced gitlink + duplicate outer WP17G/WP17GR briefs + WP18
  brief). Confirmed the authoritative `WP17G_Generator_Production_API.md` / `WP17GR_Production_API_Corrections.md`
  are committed **inside** `exam_generator/WPs/` (at `c9273e7` / `ea59cd8`) and byte-identical to the outer
  duplicates, then **removed the two outer duplicates**. `WPs/WP18_Backend_Generation_Jobs.md` is committed with this WP.
- `.gitignore`: added `artifacts/` (job state + per-slot generator audits live on disk only, never in Git,
  never in `app.db`).

## 2. Adapter + readiness (§1)

- **`backend/src/integration/generator_adapter.py` rewritten as a thin wrapper** over
  `exam_generator.production.generate_exam_question` (the consolidated API WP17G/WP17GR added). No copied
  pipeline logic, no WP runner, no subprocess, no `sys.path` hack — the generator package is installed by the
  root install flow and imported directly; if it is not importable every call fails closed as
  `systemic_failure` (`GENERATOR_IMPORT_ERROR`). Keeps the WP17 `AdapterRequest`/`AdapterResult`/
  `generate_category_question`/`generator_paths` surface (all 6 WP17 adapter tests still green) and adds
  `total_cost_basis`, `itemized_cost`, `remaining_cost_usd`, `pricing_verification`, `warnings`, `retries`.
  The WP17 pre-import cost-ceiling short-circuit is retained.
- **`backend/src/integration/readiness.py` + `GET /api/exam-jobs/readiness`** — non-network checks:
  generator import + version (`0.5.0`), submodule pin vs `generator_pin.EXPECTED_GENERATOR_PIN` (dev only),
  local `Data/index` + course PDF, 20/20 exact category mapping (`verify_against_generator_catalog`),
  selected models (`gpt-5.6-terra`/`gpt-5.6-terra`), complete **and model-matching** `config/pricing.yaml`,
  pricing age vs a configurable 30-day threshold, and `OPENAI_API_KEY` **presence only** (value never read
  or logged). A failure of import/data/mapping/pricing/key sets `ready_for_llm=False` but
  `db_only_available=True`; **stale pricing only warns**. `create_job` consults readiness only when some
  `llm > 0`; a DB-only job is created with the key absent.
- **`scripts/dev_install.sh`** (root-based, reproducible): `backend/requirements.txt`, then the pinned
  generator package editable `--no-deps`, then its **runtime** deps (`pydantic pymupdf pyyaml openai typer`)
  pinned to `exam_generator/constraints.txt`; runs `pip check` + an import smoke test. `SETUP.md` updated.

### Reported dependency conflicts (no pin file changed)

1. `exam_generator/constraints.txt` pins **`pytest==9.1.1`**; `backend/requirements.txt` pins
   **`pytest==7.4.2`** (+ `pytest-flask==1.2.0`, which does not support pytest 9). Resolution: the integrated
   backend env keeps pytest 7.4.2; the generator is installed `--no-deps` and its suite runs under its own
   constraints in a separate env. The targeted generator production tests below pass under **both** pytest 9.1.1
   (their native env) and 7.4.2.
2. `constraints.txt` pins **`MarkupSafe==3.0.3`** vs the backend's **`MarkupSafe==2.1.3`**. Not constrained
   here — Flask 2.3.3 pulls `Jinja2 3.1.6` (≥3.1, all the generator needs) and it works with MarkupSafe 2.1.3.

## 3. Persistent, sequential job model (§2, §5)

- **`backend/src/jobs/`** — `model.py` (Job / CategoryPlan / Slot + JSON projection), `store.py` (atomic
  `os.replace` writes under `artifacts/exam_jobs/<uuid>/job.json`, UUID + path-traversal validation,
  best-effort `job.lock`, `recover_on_start()`), `service.py` (validation, worker, cost, replacements, export).
- **States:** job `queued|running|completed|partial|interrupted|cost_ceiling|failed`; slot
  `queued|running|accepted|failed|interrupted|cost_ceiling`. `progress_view()` exposes per-category and
  per-slot progress, attempts, retries and safe errors.
- **Reload on start** (`src/main.py` calls `store.recover_on_start()`): a job left `running` → `interrupted`,
  its running slots → `interrupted` (retryable). **Billable calls are never auto-resumed.**
- **One worker, one question at a time.** A process-wide `_RUN_LOCK` (non-blocking) serialises `run_job` /
  `retry_slot` / `replace_via_llm`; a held lock raises `JobBusy` (→ HTTP 409). No parallel provider calls.
- **Request** `{categories: {<canonical>: {total, database, llm}}, cost_ceiling_usd}`: strict non-negative
  ints, `database + llm == total`, unknown categories and insufficient DB availability rejected **before** the
  job is created (readiness required only when any `llm > 0`).
- **DB-first selection** using the existing random selector (primary OR secondary category, excludes rows
  already in the exam). Then LLM slots generated sequentially. **Global numbers** are assigned in canonical
  `CATEGORY_ORDER`, DB block then LLM block within each category — contiguous `1..N`, stable across replace.
- Each LLM call receives that category's selected DB questions + prior accepted LLM questions + retained
  history as exact seven-field JSON (order preserved, repeated numbers kept). Generated questions are
  **job data only** — never inserted into `app.db` (verified).

## 4. API surface (§3)

| Method & path | Purpose |
|---|---|
| `POST /api/exam-jobs` | validate + create; **202** `{job_id, url}`; worker runs in a daemon thread (`EXAM_JOB_SYNC` runs inline for tests) |
| `GET /api/exam-jobs/<job_id>` | progress / partial / final result (`result_view`: DTOs + progress + ledger + history) |
| `POST /api/exam-jobs/<job_id>/slots/<slot_id>/retry` | retry one `failed`/`interrupted`/`cost_ceiling` LLM slot |
| `PUT /api/exam-jobs/<job_id>/cost-ceiling` | raise/lower the cap; **rejected if below accumulated cost** (409) |
| `POST /api/exam-jobs/<job_id>/questions/<instance_id>/replace-db` | swap a DB question (existing selector, excludes in-exam) |
| `POST /api/exam-jobs/<job_id>/questions/<instance_id>/replace-llm` | regenerate; on success move old → history, on failure retain |
| `GET /api/exam-jobs/<job_id>/export.xlsx` | accepted `origin=llm` only, headers `נושא/שאלה/תשובה1..4/תשובה_נכונה` |
| `GET /api/exam-jobs/readiness` | the readiness report |

Mutations reject concurrent/double execution (`JobBusy`→409) and leave the current question unchanged on
failure. **Legacy `/api/test/*` endpoints are untouched** (verified). Replacement preserves the slot's
`instance_id` and public `number`; retries/replacements use the **same cumulative job budget and ledger**.

## 5. Cost accounting + terminal report (§4)

- `Decimal` end to end. Every LLM call passes `cost_ceiling_usd = cap − accumulated_cost`; a slot whose start
  would breach the cap is marked `cost_ceiling`, **no call is made**, and the run stops (completed slots kept).
- Every returned cost is accumulated and ledgered (`kind ∈ initial|retry|replace_llm`): accepted, rejected,
  refusal, failed attempt, retry, LLM replacement. **DB operations cost nothing.**
- `job.cost_basis` folds each result's `total_cost_basis` (`none`→`calculated`/`conservative_bound`→`mixed`);
  ledger entries carry `itemized_cost` and `total_cost_basis`; `pricing_verification` and pricing/cost
  `warnings` are surfaced. Conservative/fallback amounts are never presented as provider-exact.
- **Terminal summary** (`_print_terminal_summary`, one `WARNING`+`print` line, no prompts/answers/raw/secrets):
  ```
  [EXAM JOB COMPLETE] job=<id> status=<s> llm_cost=$<x> basis=<b> accepted=<a>/<r> failed=<f> retries=<n> pricing_warnings=[...]
  ```
  Printed when the initial run reaches a terminal state and again after each manual retry / LLM replacement.

## 6. DTO / history / export (§5)

- `result_view` builds the WP17 `ExamQuestionDTO` (+ `GenerationMeta`) for every accepted slot; DB slots are
  re-hydrated from the row for performance history when an app context is available. `generation_meta` stays
  out of `docx_view()`. Global numbers win over the generator's internal number.
- `category_history` is a per-category list of discarded/replaced LLM questions — **repeated / non-monotonic
  public numbers preserved, never sorted or de-duplicated** before a generator call (`_previous_for_slot`).
- Excel export = accepted `origin=llm` only, exact upload headers; **round-trips through `/api/upload-excel`**;
  the export route itself inserts nothing.

## 7. Tests (§6) — serial, temp DBs, fake providers, sockets blocked

- **Backend:** `cd backend && python -m pytest -q` → **69 passed, 0 failed** (35 WP17 unchanged + 34 new
  `tests/test_wp18_*.py`). Covers: DB-only job without LLM readiness; mixed A/B order + Q3→Q4 prior growth;
  canonical category + contiguous global ordering; one-worker `JobBusy` + no re-run of a completed job;
  reload → `interrupted` recovery; partial + slot retry (retry cost on the same ledger); DB & LLM replacement,
  unchanged-on-failure, repeated-number discarded history; cumulative ceiling stop; all attempt/failure costs
  counted and summed; terminal summary contents/basis with a sentinel key never persisted; cap cannot drop
  below accumulated; readiness stale-warn vs missing-key/price blocking; generated questions never enter the
  DB and `app.db` is never mutated; Excel round-trip; legacy `/api/test/*` unchanged; route 202 + poll.
- **Targeted generator production tests, network-blocked, no key** (run in the submodule working dir; tree
  stays clean, nothing committed there): `test_wp17g_production_api.py`, `test_wp17gr_production_corrections.py`,
  `test_wp10_sequential_uniqueness.py`, `test_wp09_two_category_live.py` → **73 passed**.
- **Frontend:** `npm ci && npm run build` → OK (`dist/` built, 1258 modules).

## 8. Risks / decisions for WP19

- **Worker is an in-process daemon thread** (fine for a single-user desktop tool; `_RUN_LOCK` + `job.lock`
  serialise). No external queue/process. If multi-user or multi-process is ever needed, a real queue is WP19+.
- **Job UI categories:** the job builder should keep using `GET /api/test/categories` (all 20 canonical,
  live availability, including a future zero-DB category) — WP18 adds no parallel categories route.
- **`generator_pin.EXPECTED_GENERATOR_PIN`** must be updated together with `git add exam_generator` on every
  re-pin (readiness flags drift). Handoff §2 procedure updated.
- **Real LLM runs** need `OPENAI_API_KEY` exported for the backend process and the generator's local `Data/`
  present; otherwise LLM job creation is refused with a safe reason and DB-only features keep working.
- WP19 switches the frontend to the job API and retires the synchronous `/api/test/generate` LLM path (the
  DB-only `/api/test/*` endpoints stay until then).
- `pytest` / `MarkupSafe` version conflicts between the two pin sets are documented, not resolved; a future
  unified lockfile for the integrated env is optional.
