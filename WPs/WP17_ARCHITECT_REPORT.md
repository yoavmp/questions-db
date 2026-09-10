# WP17 — Integration Foundation — Architect Report

**Status:** ✅ Complete (offline). Outer repo committed; generator untouched.
**Date:** 2026-09-10 · **Executor:** Claude Code (Sonnet 5)
**Pinned generator:** `e5f4e0b34dda26f22c56090326f30af7170bcbd3` (WP16R).

A first pass halted at preflight (outer tree dirty; `exam_generator/` had **no
`.git`**, so the expected SHA was unverifiable and it could not be added as a
submodule without risking the working tree). The owner then supplied the
generator remote + authorizations; execution resumed and is summarised below.

## 1. Git topology

- `exam_generator/` was a plain untracked directory with no `.git`. It was
  **moved** (not deleted) to `../exam_generator_pre_submodule_backup/` (253
  files; sha256 manifest kept). Retained until this report is approved.
- Remote verified read-only first: `git ls-remote
  https://github.com/yoavmp/exam-generator.git` → `refs/heads/main =
  e5f4e0b3…` (== expected). `git submodule add` cloned straight to that commit.
  Submodule HEAD `e5f4e0b3…` on `main`, tree clean; outer index carries only
  `.gitmodules` + the `exam_generator` gitlink (160000) — no generator files.
- **Backup vs. fresh checkout:** all 210 common tracked files byte-identical.
  Backup-only content = `Data/` (43 files: course PDF + `Data/index/**`), which
  the generator's own `.gitignore` ignores (verified per file). Copied into the
  submodule; `git -C exam_generator status` stayed clean.

## 2. Ignore consolidation & hygiene (§2)

- New root `/.gitignore`, narrow & root-relative: OS/editor; `backend/**`
  Python bytecode + pytest/mypy/ruff/coverage caches; venvs (`backend/venv`,
  `backend/idoVenv`, `backend/michalVenv`, `backend/MichalVenvNew`, `.venv`);
  `.env`/`.env.*` with `!*.env.example`; `frontend/node_modules|dist|build|
  coverage|.vite`; `backend/static/`; `backend/src/database/*.db` +
  `!…/app.db`, `*_test.db`.
- **Blanket `*.md` removed** — `README.md`, `WPs/*.md`, `SETUP.md`,
  `QUICK_START.md`, `How To Run.md` now tracked. No component `.gitignore`
  existed to delete; `exam_generator/.gitignore` untouched.
- `frontend/node_modules/**` (6 600 files) **untracked index-only**; local
  files kept. `npm ci` (199 pkgs) + `npm run build` (1 258 modules) succeed;
  regenerated `node_modules/`+`dist/` stay ignored.
- Checks: `git check-ignore -v` on 13 ignored paths — all match; `git ls-files`
  for node_modules / venvs / caches / `.env` / secrets / stray `*.db` — clean
  (only `backend/src/database/app.db` retained). Outer tracked files: 6 640 → 60.

## 3. Dead-file removal & docs (§3)

Removed after a zero-reference sweep: `backend/src/routes/
test_generation_backup.py`, `…_old.py`, `generate_word.ipynb`,
`frontend/src/utils/categoryOrder.js` (duplicate hard-coded order; unused —
`App.jsx` renders the backend order). `app.db` retained. Port **5000 → 4567**
in README, SETUP.md, QUICK_START.md, `start_backend.{sh,bat}`, `main.py`
`__main__`. README gains a "Clone with submodules" section (recurse-submodules,
`submodule update --init`, re-pin note; no secrets).

## 4. Canonical category contract (§4)

- `CATEGORY_ORDER` vs pinned generator `config/categories.json` + readiness
  manifest: **20/20 names byte-identical**, set-equal (0 missing/extra/
  ambiguous), each → exactly one **strict-ready** context
  (`term_fidelity_approved: true`, 0 unresolved terms). **WP18 not blocked.**
- Display order differs (pedagogical vs chapter) — allowed; outer owns order.
- `backend/src/integration/category_map.py`: explicit
  `CANONICAL_TO_GENERATOR_CONTEXT`, **empty `ALIASES`**, strict exact-string
  resolver (never fuzzy), `verify_against_generator_catalog()` for re-pins.
  Full table → `WPs/WP17_CATEGORY_MAPPING.md`.
- `/api/test/categories` now returns all 20 canonical names in `CATEGORY_ORDER`
  (extras Hebrew-collated last) with **live DB availability counts**, not the
  stale `Category.question_count`.

## 5. Read-only generator adapter (§5)

`backend/src/integration/generator_adapter.py` imports & invokes
`exam_generator.orchestrator.generate_one_question` after assembling its inputs
from the generator's own published loaders. **No** copied code / WP runner /
subprocess. Preserves WP16R generate→review→safe-repair→validation, dynamic
model config, `store: false` (re-asserted). Paths resolve from `__file__`.
Output: seven fields + audit/cost, or typed `question_rejected` /
`provider_output_failure` / `systemic_failure` / `cost_ceiling` (`cost_ceiling`
short-circuits before any import/call). Tests: fake-provider, socket-blocked —
6/6 pass with submodule+deps; 2 self-skip otherwise.

**BLOCKER for WP18 — missing consolidated boundary.** The pinned generator has
no single production one-question API; the only assembly of context/terms/
provider/config/prompts lives in the WP live-runners, which WP17 forbids
calling. The adapter re-implements that assembly in the outer repo as a
documented stopgap and lacks the runners' cost-preflight / audit-redaction
depth. Recommend a **generator** WP to expose e.g.
`exam_generator.production.generate_exam_question(*, category_name, number,
previous_public_questions, max_attempts, cost_ceiling_usd, price_snapshot,
audit_dir, provider=None)`. Do not change the generator in WP17.

## 6. Request & question contracts (§6)

- `request_contract.py` — `{total,database,llm}`: strict non-negative ints
  (rejects bool/float/str), `A+B==C`, availability limits `A` only.
- `owner_policy.py` — exam-session-only (never auto-insert); ≤2 attempts/slot;
  editable **$5.00** cap; "actual spend + one conservative next pair" ceiling
  rule; ≥20 LLM questions; answer randomisation stays with exam/DOCX code;
  partial work preserved / failed slots retryable; frontend arithmetic
  (`C→A=⌈C/2⌉,B=⌊C/2⌋`; `A/B→C=A+B`).
- `exam_question_dto.py` — `ExamQuestionDTO`: seven public fields + unique
  `instance_id`, nullable `id`, `origin`, canonical `category`/
  `primary_category`/`categories`, null/empty performance for `llm`,
  `generation_meta` **excluded from `docx_view()`**.

## 7. Offline verification (§7)

- **Pinned generator suite, network-blocked** (scratch venv; run from
  `exam_generator/`): **869 collected.** With a **dummy** `OPENAI_API_KEY` set
  (still fully socket-blocked, zero network): **692 passed / 174 skipped /
  3 failed**. Without the key: 683 passed / 12 failed (the extra 9 are runner
  tests that gate on key *presence* before using their injected stub provider).
  - The **3 persistent failures** — `test_cli_wp05` (×2), `test_cli_wp06` (×1) —
    compare a freshly written CSV to a **CRLF** committed fixture (`\r\n` vs
    `\n`): the pin's fixtures were authored on Windows, regenerated LF on macOS.
    Pre-existing cross-platform artifact, unrelated to WP17.
  - **174 skips** (WP16R reported 0): the preserved `exam_generator/Data/`
    runtime input is partial — the course PDF is present but not every rebuilt
    index/extraction artifact — so PDF-rebuild tests self-skip. Not a code
    regression; owner supplies `Data/` out of band.
  - The suite rewrites `WPs/WP04_TERMINOLOGY_DECISIONS.csv` +
    `WP06_TERMINOLOGY_MIGRATION.csv` in place (same CRLF/LF); **restored** via
    `git -C exam_generator checkout --`. Nothing in the submodule committed.
- **Backend WP17 suite** (`backend/tests/`, temp sqlite via `tmp_path` —
  `app.db` never opened), serial: **35 passed** (submodule+deps present),
  **33 passed + 2 skipped** without.
- **Excel upload compat:** `ExamQuestionDTO.docx_view()` rows with the live
  `/api/upload-excel` Hebrew headers import cleanly with correct fields / empty
  performance (`test_wp17_excel_upload_compat.py`).
- **Frontend:** `npm ci` + `npm run build` succeed; artifacts ignored.
- **Submodule proof:** `git submodule status` → ` e5f4e0b3… (heads/main)`, no
  `-dirty`; outer tracks only `.gitmodules` + gitlink; no DB mutation; no
  secret/runtime artifact staged.
- **Dependency conflict (do not action in WP17):** generator `pyproject` pins
  only lower bounds; with today's latest `openai`/`pymupdf`/`pydantic` the
  suite is green apart from the two environment issues above. Lockfile + LF
  fixtures + self-set dummy key are **generator-side** fixes for a future WP.

## 8. Deliverables & commit

- Outer `WPs/`: this report, `WP17_CATEGORY_MAPPING.md`, refreshed
  `ARCHITECT_HANDOFF.md`. Nothing under `exam_generator/WPs/`.
- New outer code: `backend/src/integration/` (6 modules), `backend/tests/`
  (6 files + `conftest.py`), `backend/pytest.ini`.
- Commit (outer only): `WP17: establish integration foundation`. No push.

## Decisions needed before WP18

1. **Generator WP** to add the consolidated production one-question API (§5).
2. **Generator WP** for cross-platform test hygiene (LF CSV fixtures; dummy
   `OPENAI_API_KEY` inside the 9 runner tests; dependency lockfile).
3. Confirm `/api/test/categories` returning all 20 canonical categories
   (incl. zero-count) is the desired integrated-builder behaviour.
4. Keep `../exam_generator_pre_submodule_backup/` until this report is approved.
