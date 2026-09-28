# WP29 — Architect Report: Server working copy and host-specific backend environment

## 0. Summary

Created a second, Git-connected working copy of `questions-db` (+ the same
pinned `exam_generator` submodule) at
`/Volumes/home/Lab/Exam_Questions_Website/questions-db`, on a mounted SMB
share. Migrated the three durable local-data paths current code proves are
needed to reopen saved exams / run generation, and built a fresh
host-specific backend Python environment for this Mac
(`backend/.venvs/joes-imac-py3.12/`) from the repository's own committed,
documented install flow (`scripts/dev_install.sh`) — no historical
`requirements.txt` snapshot, no `pip freeze` reconstruction. Verified the new
environment offline: imports, DB-only readiness, and the complete backend
test suite (310 passed) all succeed with `OPENAI_API_KEY` absent. Wrote
`docs/SERVER_WORKING_COPY_SETUP.md` so another Mac can reproduce an
equivalent (but never shared) environment. This is migration/setup only — no
production service, reverse proxy, authentication, public/network access, or
`OPENAI_API_KEY` was configured, read, or referenced by value anywhere.

**One process-discipline deviation, self-caught and corrected:** while
verifying "backend imports succeed," a probe command (`python run.py
--help`) was run against the actual `run.py` entrypoint, which has no CLI
argument handling and unconditionally starts the Flask **development**
server. This briefly bound `0.0.0.0:4567` in debug mode (with its reloader
child process) on this Mac. It was caught within the same turn, both
processes were killed, and port 4567 was confirmed free before continuing.
No further verification used `run.py`; all later import/readiness checks
used direct one-off `python -c` invocations instead. Flagged here in full
per the WP's own "unresolved blockers or deviations" requirement, even
though the end state is clean.

## 1. Source and target paths

| | Path |
|---|---|
| Source outer root | `/Users/crazyjoe/Projects/questions-db` |
| Target outer root | `/Volumes/home/Lab/Exam_Questions_Website/questions-db` |
| Mount | `/Volumes/home` — SMB share `//yoav@132.66.206.120/home`, 750 GiB total / 355 GiB free at migration time, confirmed writable (`touch`/`rm` round-trip) |

## 2. Source and final target outer SHAs/status/remotes

**Source (untouched by this WP):**

- branch `main`, `HEAD = f9b51c8098d99e21991bbd06812e55adb6c7e90d`
- `origin = https://github.com/yoavmp/questions-db.git`
- `git fetch origin main` confirmed `origin/main = f9b51c8...` — **`HEAD == origin/main`**
- `git status --porcelain=v2 --branch`: `ab +0 -0` (no unpushed commits); only untracked files present:
  `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`, `WPs/PRE_WP26R_AUDIT.md`,
  `WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md`, `WPs/WP29_Server_Working_Copy_And_Host_Venv.md`
  (owner-owned untracked audit reports + this WP's own brief — left untouched
  in the source, never copied/staged/deleted there; the brief was copied
  into the **target's** `WPs/` only, per §7)
- No tracked modifications anywhere in the source outer repo.

**Target (this WP's own working copy), before any WP29 documentation commit:**

- `HEAD = f9b51c8098d99e21991bbd06812e55adb6c7e90d` — **identical to source pushed HEAD**
- `origin = https://github.com/yoavmp/questions-db.git`
- local config applied: `pull.ff = only`, `submodule.recurse = true`,
  `branch.main.remote = origin`, `branch.main.merge = refs/heads/main`
  (the latter two were already set correctly by `git clone`; set explicitly
  to be certain)

**Target, final state (after this WP's own commit):** see §11 for the exact
final SHA and push result.

## 3. Generator pinned SHA/status and proof it was not changed

- Outer gitlink / `git submodule status` (source): ` 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d exam_generator (heads/main)` —
  leading space = in sync with the recorded gitlink, working tree clean.
- Source submodule `HEAD = 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d`;
  `git fetch origin main` inside the submodule confirmed `origin/main` is
  the same SHA — submodule `HEAD == origin/main` too.
- Target submodule, after `git clone --recurse-submodules`:
  `git submodule status` → ` 5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d exam_generator (heads/main)` —
  **identical SHA, in sync, clean, detached HEAD** (normal for
  `git submodule update`).
- **Proof the generator was not changed by this WP:** no file was ever
  written inside `exam_generator/` other than the git-ignored `Data/`
  directory (§5); no `git add`/`git commit`/`git push` was ever run with
  cwd inside `exam_generator/`; `git -C exam_generator status` shows only
  the pre-existing ignored paths (`Data/`, `.venv/`, `.pytest_cache/`, etc.),
  never a tracked change. The outer `.gitmodules`/gitlink were never
  touched either.

## 4. Exact clone/update method used

Target path was absent before this WP (confirmed by `ls`), so the "fresh
clone" branch of the WP applied, not the "existing clone" branch:

```bash
git clone --recurse-submodules \
  https://github.com/yoavmp/questions-db.git \
  "/Volumes/home/Lab/Exam_Questions_Website/questions-db"
```

This one command satisfied all four sub-steps at once: read `origin` from
the source (used directly — same URL), cloned with recursive submodule
initialization, checked out the same pushed commit the source was on
(`main`'s tip at clone time == source HEAD, confirmed §2), and initialized
`exam_generator` to the exact SHA pinned by the outer commit's gitlink
(confirmed §3). No source `.git` directory was copied; no submodule was
flattened/vendored.

Then, in the target only:

```bash
git config pull.ff only
git config submodule.recurse true
git config branch.main.remote origin
git config branch.main.merge refs/heads/main
```

## 5. Durable-data inventory, copy method and verification results

Inventory taken from the source before any copy (per code inspection —
`backend/src/integration/readiness.py`/`generator_adapter.py` prove
`exam_generator/Data/index/` + `Data/Course_Material_Summary.pdf` are the
only additional generator-runtime paths beyond the two already named in the
WP; `exam_generator/config/*` is tracked in the submodule itself and needs
no separate copy):

| Path | Size | Files | Tracked? | Copy method |
|---|---|---|---|---|
| `backend/src/database/app.db` | 244 KiB | 1 | tracked (Git) | `sqlite3 <src> ".backup '<dst>'"` |
| `artifacts/exam_jobs/` | 4.5 MiB | 350 files / 183 dirs | ignored (`artifacts/` in `.gitignore`) | `rsync -a --partial` |
| `exam_generator/Data/` | 45 MiB | 43 files / 5 dirs | ignored (submodule's own `.gitignore`) | `rsync -a --partial --exclude='.DS_Store'` |

Backend was confirmed **stopped** before the database snapshot (`ps aux` /
`lsof` showed no `python`/`uvicorn`/`flask` process; only unrelated frontend
Node dev-server processes on ports 4173/4174 were running, untouched).

**app.db:**

- Source `PRAGMA integrity_check` → `ok`.
- The clone's git-checked-out `app.db` was byte-identical to the source
  (`sha256 79a40f55...`, matching the source exactly — expected, since the
  source had zero tracked modifications).
- Took a consistent snapshot with `sqlite3 <src> ".backup '<dst>'"` (not a
  raw file copy, which risks an inconsistent read of a possibly-open file).
- Destination `PRAGMA integrity_check` → `ok`.
- **Destination checksum after the snapshot differs from both the
  pre-snapshot checkout and the source** (`sha256 84b7e0dd...`). This is
  expected, not a data problem: a control experiment (`.backup`-ing the
  source to a throwaway file) produced a **third**, still-different
  checksum (`f7ea6e48...`) with identical row counts/content — SQLite's
  `.backup` command rewrites the file's page layout and increments its
  internal file-change counter on every run, so the bytes never round-trip
  identically even from a file to itself. See §6 for how this is left
  unstaged.

**artifacts/exam_jobs/** and **exam_generator/Data/**: `rsync -a` reported
350/350 and 43/43 files transferred respectively (`0` errors); destination
`find | wc -l` matched the source count exactly for both; a full SHA-256
manifest of every source file was diffed against a full SHA-256 manifest of
every destination file for both paths — **zero differences** in either set.
`git check-ignore -v` confirmed both destination trees stay ignored
(`artifacts/` outer rule; `Data/*.pdf` / implicit `Data/` submodule rule)
and were never staged.

Source working copy and its durable data were not altered by any of this.

## 6. Is `app.db` tracked, and does it leave an expected unstaged modification?

**Yes, tracked; yes, one expected unstaged modification**, exactly per the
WP's anticipated scenario in §3: the sqlite `.backup` snapshot changes the
file's bytes (see §5) even though the schema/rows are logically identical to
what's committed. `git status` on the target shows:

```
modified:   backend/src/database/app.db
```

This is left **unstaged** — not added, not committed — and is called out
here explicitly rather than silently. No `skip-worktree`/`assume-unchanged`
was applied (would need owner approval, not sought/needed for this WP).

## 7. Environment path, Python version and dependency-install commands

- Path: `backend/.venvs/joes-imac-py3.12/` (hostname `Joes-iMac` sanitized:
  lowercased, non-alphanumeric → `-`, trimmed → `joes-imac`).
- `.gitignore` gained one narrow rule, `backend/.venvs/`, next to the
  existing venv-ignore block (with a one-line comment explaining why it's
  host-specific and never shared).
- Python: 3.12.7 (`/usr/local/bin/python3.12`), matching the currently
  working Mac setup and comfortably inside `exam_generator`'s
  `requires-python = ">=3.11"`.
- Install commands (exactly the repository's own committed
  `scripts/dev_install.sh`, pointed at the host-specific path — no
  historical requirements snapshot, no `pip freeze` reconstruction):

  ```bash
  cd /Volumes/home/Lab/Exam_Questions_Website/questions-db
  VENV="/Volumes/home/Lab/Exam_Questions_Website/questions-db/backend/.venvs/joes-imac-py3.12" \
  PYTHON=python3.12 \
  bash scripts/dev_install.sh
  ```

  Which itself ran (unmodified script; quoted here for the record):

  1. `python3.12 -m venv "$VENV"`
  2. `pip install -r backend/requirements.txt`
  3. `pip install -e exam_generator --no-deps` (pinned generator, editable)
  4. `pip install -c exam_generator/constraints.txt pydantic pymupdf pyyaml openai typer`
  5. `pip check`
  6. an import smoke test (`flask, flask_sqlalchemy, openpyxl,
     exam_generator.production.generate_exam_question`)

- Result: `pip check` → `No broken requirements found.` Smoke test →
  `OK: backend + exam_generator 0.5.0 importable`. Exit code `0`. No
  manifest gap was hit; nothing was installed ad hoc outside the script.
- The install ran over the SMB mount and was genuinely slow (~20 minutes
  wall clock for many small site-packages files) but made continuous,
  verifiable forward progress the whole time (tracked via live process
  checks and raw log tailing, not assumed) — flagged here only as
  context for why it needed several `TaskOutput` polls, not as a defect.

## 8. Complete test/verification commands, results and exit codes

All run with `OPENAI_API_KEY` **absent** from the environment (`unset
OPENAI_API_KEY`; confirmed absent via `env | grep -i OPENAI` before each
run). All run in the foreground, waited on to actual completion (including
polling through the harness's 120 s auto-background cutoff via `TaskOutput`/
direct process checks — never declared done from a partial/backgrounded
state).

1. **Python executable/version:**
   ```bash
   backend/.venvs/joes-imac-py3.12/bin/python -c "import sys; print(sys.executable); print(sys.version)"
   ```
   → `.../backend/.venvs/joes-imac-py3.12/bin/python`, `3.12.7`. Exit `0`.

2. **Backend import:**
   ```bash
   cd backend && backend/.venvs/joes-imac-py3.12/bin/python -c \
     "import sys, os; sys.path.insert(0, os.getcwd()); from src.main import app; print(app)"
   ```
   → `<Flask 'src.main'>`. Exit `0`. (First attempt at this check mistakenly
   invoked `run.py --help` instead, which has no arg parsing and started the
   dev server — see §0. This direct-import form was used for the actual
   recorded verification and does not start any server.)

3. **Production generator adapter import:**
   ```bash
   backend/.venvs/joes-imac-py3.12/bin/python -c \
     "from src.integration.generator_adapter import generate_category_question, generator_paths, GENERATOR_IMPORT_ERROR; \
      print(GENERATOR_IMPORT_ERROR)"
   backend/.venvs/joes-imac-py3.12/bin/python -c \
     "from exam_generator.production import generate_exam_question; print('OK')"
   ```
   → `GENERATOR_IMPORT_ERROR = None`; `exam_generator.production` import
   `OK`. Exit `0` both.

4. **Database-only readiness/startup, no API key:**
   ```bash
   backend/.venvs/joes-imac-py3.12/bin/python -c \
     "from src.integration.readiness import readiness_report; \
      r = readiness_report(); print(r['db_only_available'])"
   ```
   → `True`. (The same call's `openai_api_key_present` is correctly `False`
   and LLM generation is correctly blocked on that one reason only — DB-only
   functions staying available while LLM generation alone is gated is the
   module's documented, intended behavior, not a gap.)

5. **Complete backend test suite, offline:**
   ```bash
   cd backend && backend/.venvs/joes-imac-py3.12/bin/python -m pytest -q
   ```
   → **`310 passed, 12376 warnings in 292.56s (0:04:52)`. Exit code `0`.**
   All warnings are SQLAlchemy 2.0 deprecation notices
   (`datetime.utcnow()`, `Query.get()`) — pre-existing, unrelated to this
   WP, not network/provider warnings. `backend/tests/conftest.py` monkey-
   patches `socket.socket.connect`/`connect_ex` to block real sockets for
   every test in the suite; `0` tests were skipped (grepped the full run
   log for "skip", zero matches), confirming the generator-adapter
   integration tests that self-skip when the submodule/its deps/local
   `Data/` are absent (`test_wp17_generator_adapter.py`,
   `test_wp17_category_contract.py`) actually **ran** against the real
   migrated `Data/index` + course PDF and passed — this **is** the "small
   additional generator integration test" the WP asks for; nothing further
   was needed since full coverage of that path already exists in the
   tracked suite and just proved itself against the real migrated data.

No paid/live call was made or attempted at any point (sockets structurally
blocked for the whole suite; the three isolated import/readiness probes
never construct a provider or open a socket either).

## 9. Files committed and exclusions confirmed

**Staged and committed (target outer repo only):**

- `docs/SERVER_WORKING_COPY_SETUP.md` (new)
- `.gitignore` (narrow addition: `backend/.venvs/`)
- `WPs/WP29_Server_Working_Copy_And_Host_Venv.md` (this WP's own brief,
  copied into the target's `WPs/`, matching this repo's established
  convention of tracking both the brief and the architect report — see e.g.
  `WPs/WP28_Warning_Acceptance_Manual_Editing_And_Repair_Hardening.md` +
  `WPs/WP28_ARCHITECT_REPORT.md`)
- `WPs/ARCHITECT_HANDOFF.md` (refreshed — new WP29 summary at the top,
  prior content otherwise preserved verbatim)
- `WPs/WP29_ARCHITECT_REPORT.md` (this file)

**Explicitly never staged, confirmed by `git status`/`git check-ignore`
immediately before commit:**

- `backend/src/database/app.db` — left as the one expected unstaged
  modification (§6).
- `backend/.venvs/joes-imac-py3.12/` — newly ignored (this WP's own
  `.gitignore` rule).
- `artifacts/exam_jobs/` — ignored (pre-existing outer rule).
- `exam_generator/Data/` — ignored (submodule's own `.gitignore`).
- `exam_generator/` gitlink/contents — untouched, not re-added, not
  committed/pushed (§3).
- No `.env`/`.env.*`, credential, API key, `node_modules/`, Python/test
  cache, or `.DS_Store` was ever created or staged by this WP.
- The three owner-owned untracked PRE-audit reports live only in the
  **source** repo and were never copied to the target, staged, or deleted
  (§2).
- The staged diff was read in full before committing; it contains
  documentation/config text only — no secret, key value, machine
  credential, raw question data, or raw provider response anywhere in it.

## 10. Repository SHAs table (for `ARCHITECT_HANDOFF.md`-style consumption)

| Repo | Path | SHA | State |
|---|---|---|---|
| Outer `questions-db` | `.` (target) | before this commit: `f9b51c8098d99e21991bbd06812e55adb6c7e90d`; after: see §11 | branch `main`, `pull.ff=only`, pushed to `origin/main` (fast-forward, confirmed safe before pushing) |
| Generator `exam-generator` | `exam_generator/` (submodule, target) | `5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d` — **unchanged by this WP** | `heads/main` (detached), clean, never committed/pushed here |

## 11. Final commit SHA and push result

Commit message: `WP29: establish server working copy`.

- Final target `HEAD` after commit: **`7f49e76c17742aa6314229e3f81681d7a1a52751`**
- `git push origin main` result: **success, fast-forward** —
  `f9b51c8..7f49e76  main -> main`. Verified post-push:
  `git rev-parse HEAD == git rev-parse origin/main ==
  7f49e76c17742aa6314229e3f81681d7a1a52751`.

**Source repository catch-up**, once the reader is ready (source stays
exactly at `f9b51c8098d99e21991bbd06812e55adb6c7e90d` until this is run —
this WP never mutated the source):

```bash
cd /Users/crazyjoe/Projects/questions-db
git pull --ff-only
```

## 12. Unresolved blockers or deviations

- The `run.py`/dev-server slip described in §0 — self-caught, corrected,
  confirmed clean (port free, no stray processes) before continuing. No
  lasting effect.
- None else. Every preflight/stop condition passed clean; the mount was
  available and writable; the target was absent (no merge/overwrite
  decision was ever needed); both repositories were clean with no unpushed
  commits; the submodule was in sync. Dependency installation completed
  with a passing `pip check` and no manifest gap.

## 13. Confirmation: no API key read, no provider call made

- `OPENAI_API_KEY` was never set, exported, or read by any command run in
  this WP; every verification step explicitly `unset` it first and several
  asserted its absence (`'OPENAI_API_KEY' not in os.environ`) inline.
- `readiness_report()`'s own `openai_api_key_present` check only tests
  *presence* (`"OPENAI_API_KEY" in os.environ`) and never reads/logs a
  value — by the module's own documented contract, unmodified by this WP.
- The full backend test suite runs with real sockets blocked
  (`backend/tests/conftest.py`), so even the tests that exercise the
  generator-adapter/production path made no network call.
- No `scripts/dev_install.sh` step, and no ad hoc command in this WP,
  constructs an LLM provider client or performs network I/O to an LLM
  endpoint.
