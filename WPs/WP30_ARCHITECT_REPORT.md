# WP30 — Architect Report: Frontend dependencies and offline local application test

## 0. Summary

Installed frontend dependencies on the WP29 mounted working copy
(`/Volumes/home/Lab/Exam_Questions_Website/questions-db`) via a clean `npm
ci` from the committed lockfile, ran the complete offline frontend test
suite (155 passed) and production build (both succeeded), and performed a
bounded backend+frontend smoke test with `OPENAI_API_KEY` absent —
confirming DB-only readiness works and LLM generation is blocked solely by
the missing key. Every process this WP started was stopped and its port
verified free. `docs/SERVER_WORKING_COPY_SETUP.md` was extended with the
frontend install/run/stop instructions. This WP made no code change, no
provider/LLM call, and never read an API key. Two real, non-fabricated
deviations from the brief's literal expectations are documented in full in
§1 and §4 — neither blocked the WP, but both are reported honestly rather
than silently worked around.

## 1. Preflight — SHAs, statuses, tooling, and one real discrepancy found

- Mount `/Volumes/home/Lab/Exam_Questions_Website`: available, write-tested
  (`touch`/`rm` round-trip succeeded).
- Outer target repo: branch `main`, `HEAD = 7e16b4b04e53545885a04c433800edf9618e3c52`
  — **matches the WP's expected baseline exactly**. `git fetch origin main`
  confirmed `origin/main` is the same SHA (`HEAD == origin/main`).
  `git status --porcelain=v2 --branch`: `ab +0 -0` (no unpushed commits);
  the only untracked file was this WP's own brief,
  `WPs/WP30_Frontend_Dependencies_And_Offline_Local_Test.md` (already
  present in the target repo when this WP began — not something this WP
  added).
- Submodule: `git submodule status` → ` 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d
  exam_generator (heads/main)` — in sync with the outer gitlink, working
  tree clean. `git fetch origin main` inside the submodule confirmed
  `origin/main` is the same SHA.
- Node/npm: `/usr/local/bin/node` `v24.4.1`; `/usr/local/bin/npm` `11.4.2`.
- Package manager/lockfile: only `frontend/package-lock.json` is present
  (no `yarn.lock`/`pnpm-lock.yaml`) and `package.json` declares no
  `packageManager` field — **npm** is unambiguously authoritative; no
  conflicting lockfile.
- `frontend/node_modules/` did not exist yet; `.gitignore` already covers
  `frontend/node_modules/`, `frontend/dist/`, `frontend/build/`.

**`app.db` finding (the brief's §1 anticipated-restoration step, found
already unnecessary):** the brief instructed, if `app.db` was still modified
only from WP29's SQLite `.backup` byte-rewrite, to restore it from `HEAD`
after confirming against `WPs/WP29_ARCHITECT_REPORT.md`. On inspection,
`git status` showed **no modification to `app.db` at all** — the working
tree file already matched the committed blob exactly
(`sha256 79a40f554264ce14d000053f3fa324b9d1fb25c68d0eca472df899bd19b1ff86`,
identical to `git show HEAD:backend/src/database/app.db`), not the
WP29-`.backup`-rewritten checksum (`84b7e0dd...`) recorded in the WP29
report. So the file had already been restored to `HEAD` by some means
outside this WP's own actions (not investigated further, since it required
no action — the brief only asked to restore it, and it was already in the
target restored state). Verified no real content was lost before treating
this as settled: `PRAGMA integrity_check` → `ok`; `SELECT count(*) FROM
questions` → `459`; file size `249856` bytes — all consistent with the
WP29-documented pre-migration state. No restore action was taken because
none was needed; this is reported explicitly rather than silently assumed.

No preflight stop condition was met (mount available/writable; HEAD at the
expected baseline and equal to `origin/main`; no unexpected tracked
changes/staged files/unpushed commits; submodule in sync and clean;
Node/npm available; exactly one lockfile). Proceeded.

## 2. Frontend dependency installation

```bash
cd /Volumes/home/Lab/Exam_Questions_Website/questions-db/frontend
unset OPENAI_API_KEY
npm ci
```

Ran to real completion in the foreground (auto-backgrounded once by the
harness after its 120s tool-call timeout — a harness artifact, not a
completion signal — and was actively polled via `TaskOutput` until it
actually exited, never assumed done from partial output). Wall clock ~5m03s
(slow SMB small-file I/O, not an error). **Exit code 0**:

```
added 414 packages, and audited 415 packages in 5m
69 packages are looking for funding
15 vulnerabilities (2 low, 3 moderate, 9 high, 1 critical)
```

`npm ci` was used (not `npm install`) specifically because it installs
exactly what `package-lock.json` records and never rewrites the lockfile —
confirmed after the fact (§3) that both `package.json` and
`package-lock.json` are still byte-for-byte identical to `HEAD`. No old
`node_modules`/cache was copied from anywhere; this was a clean install
from the committed lockfile on this machine only. No package version was
upgraded or otherwise changed.

`npm ls --depth=0` afterward showed every top-level dependency resolved
cleanly (`react`, `react-dom`, `vite`, `vitest`, `tailwindcss`, testing
libraries, etc.) with no `UNMET DEPENDENCY`/`invalid`/`extraneous` lines.

**Vulnerabilities (reported, not fixed, per the brief):** `npm audit`
reports 15 total — 2 low, 3 moderate, 9 high, 1 critical
(`npm audit --json` → `{'info': 0, 'low': 2, 'moderate': 3, 'high': 9,
'critical': 1, 'total': 15}`). All are in the dev/build toolchain (the
`vite`/`vitest`/`esbuild`/`postcss`/`glob`/`minimatch`/`brace-expansion`/
`nanoid`/`picomatch`/`browserslist`/`@babel/core` dependency graph — build
and test tooling, not application runtime code shipped to a browser).
`npm audit fix`/`--force` was **not** run, per the brief; several fixes
would pull breaking major-version bumps (e.g. `vite@8.3.1`) that must go
through a deliberate dependency-update WP, not routine local setup. Flagged
here for the owner's awareness, not resolved.

## 3. Offline frontend verification

All with `OPENAI_API_KEY` confirmed absent (`unset OPENAI_API_KEY`; `env |
grep -i OPENAI` printed nothing before the test run).

**Test suite** (`npm test` → `vitest run`), run to real completion in the
foreground (again auto-backgrounded by the harness past 120s and actively
polled to its actual exit, not assumed):

```
Test Files  8 passed (8)
     Tests  155 passed (155)
  Duration  239.82s
```
**Exit code 0.** (The 239.82s duration is almost entirely `setup`/
`environment`/`prepare` overhead intrinsic to running `jsdom`+Vitest off the
SMB mount — the actual test execution itself was 5.43s.)

**Production build** (`npm run build` → `vite build`), ran in the
foreground and completed without needing to background:

```
✓ 1261 modules transformed.
dist/index.html                   0.78 kB
dist/assets/index-*.css          22.91 kB
dist/assets/ui-*.js               2.40 kB
dist/assets/index-*.js           73.10 kB
dist/assets/vendor-*.js         139.72 kB
✓ built in 36.90s
```
**Exit code 0.**

**Build output / caches remain ignored:** `git status --porcelain=v2`
after both the test run and the build showed **no new tracked/staged
paths** — only the pre-existing untracked WP brief. `git check-ignore -v
frontend/dist` and `frontend/node_modules` both confirmed ignored by the
existing `.gitignore` rules (lines 64/63).

**`package.json`/lockfile unchanged:** `git diff --stat -- frontend/package.json
frontend/package-lock.json` produced **empty output** — byte-for-byte
identical to `HEAD`, both before and after install/test/build. No
pre-existing repository defect forced an edit; nothing here needed the
brief's "stop and report" fallback.

## 4. Bounded backend–frontend smoke test

### A real, pre-existing process this WP found and correctly left alone

Before starting anything, port 4567 (the backend's hardcoded port) was
already **listening**, owned by a Python process pair
(`PID 39300`/`39301`, `run.py`) with a `TTY` of `s001` — i.e. started from
an actual interactive terminal at `19:20:38`, well before any command this
WP ran. This was not something this session started (this session's own
process ancestry runs under a detached/background TTY, `??`, not `s001`).
Per this session's standing instruction to investigate unfamiliar state
before touching it rather than assume and override: this was **not**
killed, and the smoke test was designed around it rather than through it.

Querying it (read-only `curl`, no mutation) showed it is a **different,
apparently mis-configured instance**: its own `/api/exam-jobs/readiness`
reported `generator_import: ModuleNotFoundError: No module named
'exam_generator'` — i.e. it is not running from the correctly configured
`backend/.venvs/` environment, so it could not by itself prove the brief's
required "LLM readiness is unavailable **only** because the key is absent"
(its generator import was *also* broken, for an unrelated reason). Left
exactly as found; not stopped, not restarted, not otherwise touched at any
point in this WP.

### The environment actually used

The brief names `backend/.venvs/joes-imac-py3.12/` as "the existing
host-specific backend environment." That exact path **no longer exists**.
In its place, `backend/.venvs/yoav-py3.12/` exists, and its own
`pyvenv.cfg` records `command = ... -m venv .../backend/.venvs/joes-imac-
py3.12` — i.e. it is the *same* environment WP29 built, renamed on disk
(hostname is still `Joes-iMac`/`Joes-iMac.local`, unchanged, so this was
not a hostname change; most plausibly a deliberate manual rename by the
owner between WP29 and WP30, to identify the environment by owner rather
than host). Verified fully functional before relying on it: `python
--version` → `3.12.7`; `pip check` → `No broken requirements found.`;
`from src.main import app` and `GENERATOR_IMPORT_ERROR is None` both
succeeded. Used as-is; not recreated, not renamed back, not duplicated.
`docs/SERVER_WORKING_COPY_SETUP.md` now notes this explicitly (§ "Note on
this specific mounted copy").

### Smoke test performed

1. **DB-only readiness, no API key**, via the correctly configured venv
   directly (no server needed for this check):
   ```
   db_only_available: True
   openai_api_key_present: False
   ready_for_llm: False
   blocking_reasons: ['OPENAI_API_KEY is not set (LLM generation only; DB-only functions unaffected)']
   ```
   `app.db` confirmed untouched by this import (`git status --porcelain=v2
   -- backend/src/database/app.db` → empty, before and after).

2. **Backend started** on an **alternate port, 4568** (not 4567, to avoid
   any interference with the pre-existing owner process found above) using
   the correctly configured `yoav-py3.12` venv, `debug=False`,
   `use_reloader=False` (single process, nothing extra to track/kill):
   ```
   python -c "... from src.main import app; app.run(host='127.0.0.1', port=4568, debug=False, use_reloader=False)"
   ```
   Confirmed listening (`lsof -iTCP:4568 -sTCP:LISTEN`) within ~4s.
   `GET http://127.0.0.1:4568/api/exam-jobs/readiness` → HTTP 200,
   `blocking_reasons` containing **only** the missing-API-key entry, every
   other check (`generator_import`, `submodule_pin`, `local_data`,
   `category_mapping`, `selected_models`) `ok: true` — this is the actual
   proof the brief asks for, obtained against a correctly configured
   instance since the pre-existing one on 4567 could not provide it.
   `GET http://127.0.0.1:4568/api/test/categories` → HTTP 200, 20
   categories with real question counts (a harmless, non-mutating,
   frontend-used endpoint).

3. **Frontend dev server started** on an alternate port, `5180`
   (`npm run dev -- --port 5180 --strictPort`, to avoid the two unrelated
   Node preview servers already listening on 4173/4174, also pre-existing
   and also left untouched):
   ```
   VITE v4.5.14 ready
   Local:   http://localhost:5180/
   ```
   `GET http://localhost:5180/` → HTTP 200, full React app HTML shell
   (Hebrew RTL `<title>מאגר שאלות בחינה בעברית</title>`, `/src/main.jsx`
   entry point served).
   Separately confirmed the pre-existing owner backend on port 4567 (the
   frontend's actual hardcoded `API_BASE_URL` target,
   `http://127.0.0.1:4567/api`) also serves `/api/test/categories`
   correctly (HTTP 200, real data) — so a browser opening the app the
   *normal* way (frontend on its default port, backend on 4567) would see
   working DB-only browsing today, even though 4567's own generator import
   is separately broken (§ above) — that only affects the LLM-readiness
   claim specifically, not DB-only browsing.

4. **No browser-automation tool** (Playwright/Puppeteer/Cypress/etc.) is
   installed in this environment — consistent with the same finding
   recorded in `WPs/WP22_ARCHITECT_REPORT.md` for the backend side. Per the
   brief's own allowance, HTTP-level verification (above) plus the passing
   component test suite and production build (§3) is treated as sufficient
   here; stated honestly rather than claiming a literal click-through that
   did not happen.

5. **No LLM/provider call, no paid operation, no `app.db` mutation, no
   saved exam created** at any point in this smoke test — every check
   above is either a pure readiness/import probe or a `GET` against a
   read-only endpoint.

### Stopping the smoke-test processes

```
kill 40254            # backend smoke instance (port 4568)
kill 40339 40324       # vite child + npm parent (port 5180)
```

Verified afterward:
- `ps -p 40254` / `-p 40324` / `-p 40339` → no such process, for all three.
- `lsof -iTCP:4568 -sTCP:LISTEN` → nothing (port free).
- `lsof -iTCP:5180 -sTCP:LISTEN` → nothing (port free).
- The three **pre-existing, not-started-by-this-WP** processes were
  confirmed **still present and untouched**: `4567` (owner's backend,
  `PID 39300`/`39301`), `4173` and `4174` (two unrelated Node preview
  servers, `PID 73278`/`31697`).
- `app.db` still matches `HEAD` exactly (`sha256 79a40f55...` both sides);
  `git submodule status` still ` 5200b531f5...` (in sync, unchanged).

## 5. `docs/SERVER_WORKING_COPY_SETUP.md` updates

Added, without removing or altering any WP29 content:

- verified Node/npm versions (`v24.4.1` / `11.4.2`);
- the exact clean-install command, `npm ci` from `frontend/`, with why
  (never `npm install`, never a copied `node_modules`);
- a warning that `frontend/node_modules/` is host/platform-specific, exactly
  parallel to the existing backend-venv warning, and must never be copied
  between machines;
- the exact two-terminal commands to run backend (`run.py`, port `4567`)
  and frontend (`npm run dev`, port `3000` — `vite.config.js`'s
  `server.port`) locally with `OPENAI_API_KEY` unset;
- the actual local URLs (`http://localhost:4567` API,
  `http://localhost:3000` app);
- an explicit explanation of what works without a key (DB browsing,
  DB-only exam selection/`db_review`) vs. what needs one (anything that
  calls the LLM generator);
- stop-server instructions for both processes, including the
  npm-spawns-a-vite-child wrinkle, and a reminder to check for an
  already-running instance (exactly the situation this WP itself hit)
  before starting a new one;
- troubleshooting entries for `npm: command not found` and
  `vite: command not found`;
- a short note on the `joes-imac-py3.12` → `yoav-py3.12` rename this WP
  discovered (§4), so a future reader is not confused by the mismatch
  between the venv's own `pyvenv.cfg` and its actual directory name.

No secret, key value, or credential was added. No suggestion to store an
API key in the repository appears anywhere in the update.

## 6. Verification and Git hygiene

- **No server process remains running** that this WP started (§4,
  verified by PID and by port). The three pre-existing, independently
  owned processes on 4567/4173/4174 were confirmed still running,
  unmodified by this WP — they are outside this WP's scope to stop.
- **No API key was read.** `OPENAI_API_KEY` was `unset` before every
  install/test/build/smoke command that could plausibly see it, and its
  absence was explicitly asserted inline more than once. `readiness_report()`
  and the frontend's own code only ever check *presence*, never a value.
- **No provider/network call was made**, except ordinary `npm ci` registry
  traffic to install the pinned packages (expected, and the only network
  access this WP performed).
- **Database, artifacts, generator data, and the generator gitlink were
  unchanged:** `app.db` sha256 identical to `HEAD` before and after every
  step (§1, §4); `git submodule status` unchanged
  (`5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d`, in sync) throughout; no file
  under `artifacts/exam_jobs/` or `exam_generator/Data/` was created,
  modified, or deleted by this WP (nothing in this WP's command list
  touches either path).
- **`node_modules`, build products and caches are ignored:** confirmed via
  `git check-ignore -v` for both `frontend/node_modules` and
  `frontend/dist` (§3), and via a clean `git status` after install/test/
  build.
- **Only intended documentation/report files are staged** — see §7 for the
  exact list and the secret scan.

## 7. Report, commit and push

**Files staged (target outer repo only):**

- `WPs/WP30_Frontend_Dependencies_And_Offline_Local_Test.md` (already
  present untracked in the target repo before this WP; now committed,
  matching this repo's convention of tracking both a WP's brief and its
  report)
- `WPs/WP30_ARCHITECT_REPORT.md` (new, this file)
- `WPs/ARCHITECT_HANDOFF.md` (refreshed — new WP30 summary at the top,
  WP29's own summary preserved as the next-most-recent entry, all older
  content otherwise untouched)
- `docs/SERVER_WORKING_COPY_SETUP.md` (extended per §5)

**Explicitly never staged:** `frontend/node_modules/`, `frontend/dist/`
(both ignored, confirmed §3/§6); `backend/src/database/app.db` (already
clean against `HEAD`, nothing to stage — §1); `backend/.venvs/` (ignored,
untouched by this WP — no new environment was created); `exam_generator/`
gitlink/contents (untouched — no commit/push ever run with cwd inside it).

A secret/data scan (`git diff --cached | grep -iE
"api[_-]?key|secret|password|token|sk-[a-zA-Z0-9]|credential"`) was run
over the full staged diff before committing; every match was the literal
string `OPENAI_API_KEY` appearing in prose/instructions/commands — no key
value, credential, or other secret appears anywhere in the staged diff.

Commit message: `WP30: prepare frontend local development`.

- Fast-forward safety confirmed before pushing
  (`git merge-base --is-ancestor origin/main HEAD`) after a fresh
  `git fetch origin main`.
- Final target `HEAD` after commit: **`e9aa45473f0cd4a5a5221c5fcadb11fa50dfcf90`**
- `git push origin main` result: **success, fast-forward** —
  `7e16b4b..e9aa454  main -> main`. Verified post-push:
  `git rev-parse HEAD == git rev-parse origin/main ==
  e9aa45473f0cd4a5a5221c5fcadb11fa50dfcf90`. No force flag used.

## 8. Unresolved blockers or deviations

1. **`backend/.venvs/joes-imac-py3.12/` does not exist; `yoav-py3.12/` was
   used instead** (§4). Not a blocker — verified to be the identical WP29
   environment, fully functional. Flagged so the owner can confirm the
   rename was intentional, or rename it back if not.
2. **A pre-existing backend instance was already running on port 4567**
   with a broken `exam_generator` import, started independently of this WP
   from an interactive terminal before this WP began (§4). Left untouched
   throughout, per this session's standing instruction not to kill
   unfamiliar processes without understanding them first. Flagged for the
   owner's awareness — that specific already-running instance is not using
   the correctly configured venv and will misreport LLM readiness (though
   not DB-only availability) until it is restarted from
   `backend/.venvs/yoav-py3.12/`.
3. **No browser-automation tool is installed** (§4.4) — HTTP-level
   verification plus the passing component-test suite and production build
   stood in for a literal browser click-through, exactly as the brief
   permits when tooling is unavailable.
4. **15 npm-reported vulnerabilities** in dev/build tooling (§2) — reported,
   intentionally not fixed in this WP.
5. **`app.db` needed no restoration** (§1) — the brief's anticipated
   restore-from-`HEAD` step was already moot when this WP began; recorded
   explicitly rather than silently skipped.

None of the above blocked dependency installation, tests, build, or the
bounded smoke test — all four finished successfully with real, verified
exit codes, so this WP is reported as complete.

## 9. Confirmation: no API key read, no provider call made

- `OPENAI_API_KEY` was never set or exported by this WP; every
  install/test/build/smoke step explicitly unset it first, and its absence
  was asserted programmatically more than once.
- No command run by this WP constructs an LLM provider client, calls
  OpenAI, or performs any network I/O beyond ordinary `npm ci` registry
  traffic and `localhost`-only HTTP requests against this WP's own smoke
  processes.
- The pre-existing owner backend on port 4567 was queried read-only
  (`GET` requests only) and never mutated, restarted, or fed a key by this
  WP.
