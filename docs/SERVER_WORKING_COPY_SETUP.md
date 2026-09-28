# Server working copy and host-specific backend environment (WP29 + WP30)

This document explains what this working copy is, why its Python environment
is host-specific, and how another Mac can set up its **own** equivalent
environment from the same mounted share (WP29), plus how to install the
frontend's dependencies and run backend + frontend together locally with no
API key (WP30). It intentionally does **not** configure production services,
a reverse proxy, authentication, public/network access, or an
`OPENAI_API_KEY`. That is deferred to a later, explicitly production-focused
WP.

## What the mounted path represents

This repository lives at:

```
/Volumes/home/Lab/Exam_Questions_Website/questions-db
```

`/Volumes/home` is a network share (SMB) mounted on the Mac that is currently
working from it. It is **not** a server filesystem in the Linux/production
sense — it is a folder on a NAS/file server that happens to be mounted, at a
point in time, on someone's Mac. Any absolute path under `/Volumes/home/...`
is only meaningful on a Mac that has that same share mounted at that same
mount point.

## Why virtual environments are host- and OS-specific and must never be copied

A Python virtual environment (`venv`) embeds:

- absolute paths back to the interpreter that created it (`pyvenv.cfg`,
  script shebangs in `bin/`);
- compiled extension wheels (e.g. `pandas`, `numpy`, `lxml`, `pymupdf`,
  `greenlet`, `SQLAlchemy`) built for one CPU architecture and OS ABI.

A venv created from this mounted share by Mac A is usable only by Mac A. If
Mac B activates it, every script's shebang points at a Python binary that
does not exist on Mac B (or worse, happens to exist but is the wrong
version), and any native wheel built for Mac A's architecture may crash or
silently misbehave on Mac B. This is true even when both Macs are Apple
Silicon, because the venv also pins absolute Homebrew/Framework paths.

**Consequence:** every environment created from this mounted checkout must be
named for the host that created it and never reused, symlinked into, or
activated from a different machine. That is why environments live under
`backend/.venvs/<sanitized-hostname>-py<major.minor>/` — one directory per
host — and `backend/.venvs/` is git-ignored in full.

This is also why the destination is called a **migration-stage** environment,
not a portable or production-server environment: it was built by whichever
Mac happened to mount the share, for that Mac only.

## Prerequisites

- Access to the `/Volumes/home/Lab/Exam_Questions_Website` share, mounted
  read/write.
- Git, with recursive-submodule support (any recent Git works).
- **Python 3.12** (the version this working copy was verified against).
  `exam_generator`'s `pyproject.toml` declares `requires-python = ">=3.11"`,
  but prefer 3.12 to match the currently-working setup and avoid drift.
- No `OPENAI_API_KEY` is required for anything in this document. Do not set
  it while following these steps.

## Creating your own environment on another Mac

Do this from **your own** clone/checkout of this share (or, if you are
opening this same mounted checkout from a different Mac, from this same
`questions-db` directory — see the warning below either way).

```bash
cd /Volumes/home/Lab/Exam_Questions_Website/questions-db

# Pick a name unique to your machine, e.g. "your-hostname-py3.12".
# Sanitize the hostname: lowercase, non-alphanumeric -> '-', trimmed.
HOSTSLUG="$(hostname -s | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//')"

VENV="$(pwd)/backend/.venvs/${HOSTSLUG}-py3.12" \
PYTHON=python3.12 \
bash scripts/dev_install.sh
```

`scripts/dev_install.sh` is the repository's own documented, committed
install flow. It is derived from the current committed manifests only — it
does **not** use a historical `requirements.txt` snapshot and does **not**
reconstruct dependencies with `pip freeze`:

1. installs `backend/requirements.txt` into the new venv;
2. installs the pinned `exam_generator` submodule editable, with `--no-deps`;
3. installs `exam_generator`'s own runtime deps
   (`pydantic`, `pymupdf`, `pyyaml`, `openai`, `typer`), constrained by
   `exam_generator/constraints.txt`;
4. runs `pip check` and an import smoke test.

If `pip check` reports a conflict, or the smoke test fails, **stop** — do not
hand-install packages to work around it. The gap should be fixed in
`backend/requirements.txt` / `exam_generator/constraints.txt`, not papered
over ad hoc on one machine.

This step never contacts an LLM provider and never needs `OPENAI_API_KEY`.

## Activation, verification and offline tests

```bash
source "backend/.venvs/${HOSTSLUG}-py3.12/bin/activate"

# Python executable/version come from the new venv:
python -c "import sys; print(sys.executable); print(sys.version)"

cd backend

# Backend imports:
python -c "import sys, os; sys.path.insert(0, os.getcwd()); from src.main import app; print(app)"

# Production generator adapter imports:
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from src.integration.generator_adapter import generator_paths, GENERATOR_IMPORT_ERROR
print(GENERATOR_IMPORT_ERROR)
"

# DB-only readiness, with NO OPENAI_API_KEY set:
python -c "
import sys, os
sys.path.insert(0, os.getcwd())
from src.integration.readiness import readiness_report
r = readiness_report()
print('db_only_available:', r['db_only_available'])
"

# Full offline backend test suite (sockets are blocked repo-wide in
# backend/tests/conftest.py; no provider/network call is ever made):
python -m pytest -q
```

All of the above must succeed with `OPENAI_API_KEY` **absent** from the
environment. `db_only_available` must be `True` even though
`openai_api_key_present` will correctly report `False` and LLM generation
will stay disabled — that is expected and is not a failure.

Do not start `backend/run.py` (or the frontend dev server) as part of this
verification unless you have a specific, bounded reason to — and stop
whatever you start as soon as you are done. `run.py` runs the Flask
**development** server in debug mode; it is not a readiness check.

> **Note on this specific mounted copy:** the backend environment currently
> installed here lives at `backend/.venvs/yoav-py3.12/` (renamed, after WP29
> first created it as `backend/.venvs/joes-imac-py3.12/`, to identify it by
> owner rather than hostname). Its `pyvenv.cfg` still records the original
> creation path — that mismatch is expected after a rename and is not a sign
> of a broken environment; `pip check` and the import/readiness/test
> commands above all pass unmodified from it. The general naming rule above
> (name a *new* environment after the host that creates it) still applies to
> any environment you create yourself.

## Frontend: dependencies and running the app locally (WP30)

Verified on this Mac: **Node v24.4.1**, **npm 11.4.2** (`node --version`,
`npm --version`). Any reasonably current Node 20+/npm 10+ should work; the
frontend does not pin a `packageManager` field, and only `package-lock.json`
is committed (no `yarn.lock`/`pnpm-lock.yaml`) — **npm** is the authoritative
package manager for this project.

### Installing frontend dependencies (clean, from the lockfile)

```bash
cd /Volumes/home/Lab/Exam_Questions_Website/questions-db/frontend
npm ci
```

`npm ci` installs **exactly** what `package-lock.json` records — it never
upgrades a version and never rewrites the lockfile (unlike `npm install`,
which can silently do both). If `npm ci` ever fails because the lockfile and
`package.json` have drifted apart, stop and fix that drift deliberately; do
not reach for `npm install` as a quiet workaround.

`frontend/node_modules/` is git-ignored. Like the backend venv, it is
**host/platform-specific** (native build steps, OS-specific binaries in some
transitive tooling) — never copy it from one computer to another, and never
commit it. Reinstall with `npm ci` on every machine instead.

`npm ci` reaches the public npm registry to download packages (ordinary,
expected network access for a package manager) — it makes no call to
OpenAI or any other LLM/provider endpoint.

After installing, `npm ls --depth=0` should show every top-level dependency
resolved with no `UNMET DEPENDENCY`/`invalid` lines. `npm audit` may report
known vulnerabilities in the installed tooling (dev-only build/test
dependencies, not application runtime code); review it periodically, but
do not run `npm audit fix`/`--force` casually — that changes pinned
versions and belongs in its own deliberate WP, not routine local setup.

### Running backend + frontend locally, in two terminals, no API key

**Terminal 1 — backend** (uses the environment verified above):

```bash
cd /Volumes/home/Lab/Exam_Questions_Website/questions-db/backend
unset OPENAI_API_KEY
../.venvs/yoav-py3.12/bin/python run.py
```

(Adjust the venv name if your own environment is named differently, e.g.
`.venvs/<your-hostslug>-py3.12/bin/python`.) This serves the API at
**`http://localhost:4567`** (hardcoded in `run.py`; the frontend's
`API_BASE_URL` default points at exactly this address).

**Terminal 2 — frontend:**

```bash
cd /Volumes/home/Lab/Exam_Questions_Website/questions-db/frontend
npm run dev
```

This serves the app at **`http://localhost:3000`** (and on the machine's
LAN IP at the same port — see `frontend/vite.config.js`'s `server.port`).
Open `http://localhost:3000` in a browser.

### What works without `OPENAI_API_KEY`, and what does not

With no key set, `GET /api/exam-jobs/readiness` reports
`db_only_available: true` and its only `blocking_reasons` entry is the
missing key itself (confirm the generator import / local Data / category
mapping / selected-models checks all read `ok` — if anything else is
`blocking` too, that is a real environment problem, not the expected
key-only gap). Concretely:

- **Works with no key:** browsing the question bank (`/api/test/categories`
  and friends), and creating/opening an exam job's **DB-selection** phase
  (`db_review`) — choosing/reviewing database-sourced questions.
- **Requires a key:** anything that calls the LLM generator — the
  `continue-llm` generation step, LLM-side retries/replacements, and any
  other paid operation. These stay unavailable (safely, with a clear
  reason) until `OPENAI_API_KEY` is set — which remains outside the scope
  of this document.

### Stopping each server

- Backend: `Ctrl+C` in its terminal (plain `python run.py`, no reloader
  child to worry about). If it was started detached/backgrounded instead,
  find and stop it with `lsof -iTCP:4567 -sTCP:LISTEN` then `kill <pid>`,
  and confirm the port is free afterward (`lsof -iTCP:4567` prints nothing).
- Frontend: `Ctrl+C` in its terminal. `npm run dev` spawns Vite as a child
  process; if you backgrounded it, `lsof -iTCP:3000 -sTCP:LISTEN` then
  `kill` **both** the `npm` and the child `vite`/`node` PID it started, and
  confirm `lsof -iTCP:3000` prints nothing afterward.
- Before starting either server, it is worth checking whether one is
  already running (e.g. `lsof -iTCP:4567 -sTCP:LISTEN`) — this is a shared
  mounted copy, and someone else may already have a backend or frontend
  instance up. Never kill a process you did not start yourself without
  confirming with whoever did.

## Git / submodule commands

```bash
cd /Volumes/home/Lab/Exam_Questions_Website/questions-db
git pull --ff-only
git submodule update --init --recursive
```

Local config already applied to this working copy (re-apply if you clone a
fresh copy of your own):

```bash
git config pull.ff only
git config submodule.recurse true
```

Never `git reset --hard`, force-push, or otherwise rewrite history in this
shared working copy without the owner's explicit sign-off — other people may
be relying on the exact state on the share.

## Warning: never overwrite another host's environment

Before creating an environment, check whether
`backend/.venvs/<your-hostslug>-py<major.minor>/` already exists. If it does
and it is not yours (i.e. you did not create it on this exact machine), stop
and pick a different, more specific slug rather than overwriting it.
`backend/.venvs/` can end up holding **several** host-named environments
side by side; that is expected and correct. Never delete another host's
subdirectory without that host owner's agreement.

## Durable-data paths and backup-before-update warning

These paths hold durable application state that is **not** fully recreated
by `git clone` / `git pull` alone:

- `backend/src/database/app.db` — the SQLite database. This file **is**
  tracked in Git, but the tracked copy can lag behind a live local copy on
  someone's machine; do not assume `git checkout` alone gives you the latest
  data across all users of the share.
- `artifacts/exam_jobs/` — saved/named exam jobs and their persisted state.
  Git-ignored; exists only on disk.
- `exam_generator/Data/` (the course PDF and `Data/index/`) — prepared
  source material and indexes the generator needs to run. Git-ignored
  (inside the submodule); exists only on disk.

**Before replacing any of these with a copy from elsewhere, back up the
existing target file/directory first.** Never silently overwrite durable
data. For the database specifically, use a consistent snapshot method
(SQLite's own `.backup` command, not a raw file copy of a possibly-open
file) and verify the result with `PRAGMA integrity_check;` before trusting
it.

If `app.db` shows as a modified-but-unstaged file after a snapshot
operation, that can be expected even when the logical content is identical:
SQLite's `.backup` command rewrites the file's on-disk page layout (and
increments its internal change counter), so the bytes differ from the
last-committed blob even though the rows are the same. Leave such a
modification unstaged; do not commit database contents as part of ordinary
setup/documentation changes, and do not use `git update-index
--skip-worktree` / `--assume-unchanged` on it without the owner's explicit
approval.

## Production-server configuration is deferred

This document and the working copy it describes are **migration/setup only**.
The following are intentionally **not** covered here and must not be inferred
from anything in this file:

- setting or reading `OPENAI_API_KEY`, or any other secret;
- a production-grade WSGI/ASGI server, process manager, or reverse proxy;
- authentication or public/network exposure;
- any provider/API call.

Those belong to a later WP explicitly scoped for production deployment.

## Troubleshooting

**Mount unavailable** — `/Volumes/home/Lab/Exam_Questions_Website` does not
exist or is empty: the SMB share is not mounted. Reconnect it (Finder → Go →
Connect to Server, or `open smb://<host>/home`) before retrying anything in
this document. Do not attempt to work around a missing mount by cloning to
local disk and later merging by hand.

**Wrong Python version** — `python3.12` is not found, or `python3 --version`
reports something other than 3.12.x: install Python 3.12 (e.g. via
python.org or Homebrew) and re-run `dev_install.sh` with
`PYTHON=/full/path/to/python3.12`. Do not substitute a different minor
version silently — name the venv directory after whichever version you
actually used (`backend/.venvs/<host>-py3.11/`, etc.) so it is never
mistaken for a 3.12 environment.

**Missing submodule** — `exam_generator/src/exam_generator/__init__.py` does
not exist, or `git submodule status` shows nothing: run
`git submodule update --init --recursive`. `dev_install.sh` checks for this
and exits with a clear message rather than partially installing.

**Dependency install failure** — `pip install` fails, or `pip check` reports
a conflict: stop. Do not hand-install packages, do not `pip install
--force-reinstall` ad hoc, and do not fall back to `pip freeze` from a
working machine. Report the exact `pip` error; the fix belongs in
`backend/requirements.txt` and/or `exam_generator/constraints.txt`.

**Read-only permissions** — writes to the share fail (e.g. `mkdir`, `git
clone`, or `pip install` inside `backend/.venvs/` raise permission errors):
confirm the share was mounted with write access for your account (test with
a throwaway `touch` in the share root), and confirm no one else has the
target directory locked open. Do not `chmod`/`chown` the share to work
around this without the owner's approval — fix the mount/account permissions
instead.

**`npm: command not found`** — Node.js is not installed (or not on `PATH`)
on this Mac. Install a current Node LTS (e.g. from nodejs.org, or `brew
install node`), open a new terminal so `PATH` picks it up, and re-check with
`node --version && npm --version` before retrying `npm ci`.

**`vite: command not found`** (from `npm run dev`/`npm run build`) — almost
always means `npm ci` was skipped, failed partway, or was run in the wrong
directory: `vite` is a dependency installed into
`frontend/node_modules/.bin/`, not a global tool. Re-run `npm ci` from
`frontend/` and let it finish to completion (it can be slow over this
mounted share — keep waiting rather than assuming it hung), then retry.
Never install `vite` globally as a workaround; that can silently diverge
from the pinned version in `package-lock.json`.
