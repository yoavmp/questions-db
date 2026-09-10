# questions-db — Architect Handoff

**Repository:** `questions-db` (outer) — Hebrew exam question bank + test builder
(Flask backend, React/Vite frontend) integrating the Hebrew neuroanatomy
question **generator** as a Git submodule.
**Updated:** 2026-09-10 · **Latest completed WP:** WP18 (backend exam-generation jobs).
**Next:** WP19 — switch the frontend to the job API; retire the synchronous
`/api/test/generate` LLM path (DB-only `/api/test/*` stay until then).

## 1. Repository SHAs

| Repo | Path | SHA | State |
|---|---|---|---|
| Outer `questions-db` | `.` | *(set by the `WP18: integrate backend generation jobs` commit — `git rev-parse HEAD`)* | branch `main`; **not pushed** |
| Generator `exam-generator` | `exam_generator/` (submodule) | `ea59cd857e5618b0260d2bb146dd5573c9ca2309` | `heads/main`, clean, **do not commit/push here** |

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
| Job + readiness API blueprint | `backend/src/routes/exam_jobs.py` (`/api/exam-jobs*`) |
| Root install / start flow | `scripts/dev_install.sh`, `SETUP.md` |
| Contract + job tests (temp DB, fake provider, sockets blocked) | `backend/tests/test_wp17_*.py`, `backend/tests/test_wp18_*.py` |

- `/api/test/categories` still returns all 20 canonical categories in
  `CATEGORY_ORDER` with live DB availability (incl. a zero-count category). The
  WP19 job UI should use it; WP18 adds no parallel categories route.
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

**Open decisions for WP19**

- Confirm the in-process daemon-thread worker is acceptable (single-user desktop
  tool). A real queue/process is only needed for multi-user/multi-process.
- Two dependency-pin conflicts between `backend/requirements.txt` and
  `exam_generator/constraints.txt` (`pytest` 7.4.2 vs 9.1.1; `MarkupSafe` 2.1.3
  vs 3.0.3) are documented in `scripts/dev_install.sh` and the WP18 report, not
  resolved. A unified lockfile for the integrated env is optional.
- `/api/test/generate`'s LLM behaviour: WP19 retires it in favour of jobs; keep
  the DB-only path until the frontend switches.

## 5. Authority order

Newest owner ruling → verified outer repo + tests → this handoff → WP briefs →
older records. The generator is authoritative for question-generation behaviour
and is changed only by its own WPs.
