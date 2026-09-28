# WP29 — Server working copy and host-specific backend environment

## Goal

Create a Git-connected working copy of `questions-db` at:

`/Volumes/home/Lab/Exam_Questions_Website/questions-db`

Migrate the durable local application data needed to continue work, create a fresh backend Python environment for the Mac performing this migration, and document how another computer can recreate an equivalent environment.

This is a migration/setup WP only. Do **not** configure the OpenAI API key, production services, reverse proxy, authentication, or public/network access.

## Fixed decisions

- Run Claude from the current local `questions-db` repository root.
- Prefer a fresh Git clone from the current `origin` over copying the source tree.
- Preserve `exam_generator` as an independent Git submodule.
- The destination is a server share mounted on this Mac. Any virtual environment created through `/Volumes/...` is **host-specific**, not a Linux/server production environment.
- Do not copy the existing `.venv`, `node_modules`, caches, `.env*`, API keys, credentials, or raw provider responses.
- Do not make any provider/API call and do not read `OPENAI_API_KEY`.
- Do not modify, commit, or push the generator submodule.
- Claude may commit and push the outer repository documentation/hygiene changes produced by this WP.

## 1. Preflight — inspect before changing anything

Record in the report:

- source outer root, branch, HEAD, `origin` URL, upstream and status;
- source submodule status, pinned SHA, its own HEAD/status/remotes;
- whether outer `HEAD == origin/main` and whether the pinned generator commit exists on its remote;
- Python and Node/npm versions available on this Mac;
- mount availability, filesystem type, free space and write access for `/Volumes/home/Lab/Exam_Questions_Website`;
- whether the target path is absent, empty, or already populated.

Stop and report before mutation if:

- the mounted volume is unavailable or not writable;
- either repository has tracked modifications or unpushed commits;
- the submodule is out of sync with the outer gitlink;
- the target exists and is non-empty but is not already a valid clone of the same repository;
- replacing or merging target contents would be required.

Owner-owned untracked PRE audit reports may remain untouched in the source. List them, but do not copy, stage, delete, or commit them.

Do not delete or overwrite an existing target to make this WP succeed.

## 2. Establish the destination Git working copy

If the target does not exist or is empty:

1. Read the outer `origin` URL from the source repository.
2. Clone it into the exact target using recursive submodule initialization.
3. Check out the same pushed outer commit as the source.
4. Initialize/update `exam_generator` to the exact SHA pinned by the outer commit.

If the target is already a valid clean clone of the same repository, fetch and fast-forward it safely, then update the submodule recursively. Never force, reset away work, rebase, or replace its `.git` directory.

Configure the target working copy locally so that:

- `main` tracks `origin/main`;
- pulls are fast-forward-only;
- submodule recursion is enabled for relevant Git operations.

Verify and record:

- target outer HEAD equals the source pushed HEAD before any WP documentation commit;
- target submodule SHA equals the outer gitlink;
- the submodule is clean;
- both remotes are correct and fetchable.

Do not copy the source `.git` directory or flatten/vendor the submodule.

## 3. Migrate durable local data only

First inspect the code, `.gitignore` files and existing runtime paths. Produce a short source→destination inventory before copying.

Expected durable data includes, if present:

- `backend/src/database/app.db`;
- outer `artifacts/exam_jobs/` containing saved/named exam jobs and their persisted state;
- ignored course material and prepared indexes under `exam_generator/Data/`;
- any additional path that current code proves is required to reopen saved exams or run generation.

Rules:

- Ensure the local backend is stopped before taking the database snapshot. If it is running, pause and ask the owner to stop it.
- Back up any pre-existing target data before replacing it; never silently overwrite it.
- Use a consistent SQLite backup/snapshot method and run `PRAGMA integrity_check` on the destination database.
- Copy job artifacts and generator data with a resumable, metadata-preserving method suitable for the mounted filesystem.
- Verify copied file counts/sizes and use checksums for critical files where meaningful.
- Preserve ignored/untracked status. Never stage runtime data.
- If `app.db` is tracked and the migrated database causes an expected modification, leave it unstaged and document this clearly. Do not use `skip-worktree` or `assume-unchanged` without owner approval.

Explicitly exclude:

- all old virtual environments;
- `frontend/node_modules/` and build caches;
- Python/test caches and `.DS_Store`;
- `.env`, `.env.*`, credentials and API keys;
- generator live-run audits/raw provider responses unless current runtime code proves they are required for saved-exam functionality;
- temporary exports and unrelated PRE audit files.

Do not alter the source working copy or its durable data.

## 4. Create the migration-stage backend environment

Because the destination is mounted on this Mac, do not call this a portable or production-server environment.

Create a host-specific environment inside:

`backend/.venvs/<sanitized-hostname>-py<major.minor>/`

Do not create or copy a single shared `backend/.venv` that another computer might mistakenly reuse.

Requirements:

1. Use a supported Python version; prefer Python 3.12 to match the currently working Mac setup.
2. Derive installation commands from the repository’s current committed dependency manifests and generator constraints. Do not use a historical requirements file or reconstruct dependencies with `pip freeze`.
3. Install everything needed for the backend to import and call the local `exam_generator` submodule.
4. If the dependency manifests are insufficient for a reproducible installation, stop and report the exact gap instead of installing undocumented packages ad hoc.
5. Ensure `.gitignore` covers `backend/.venvs/`; add a narrow rule if required.
6. Do not install frontend packages in this WP.

Verify with `OPENAI_API_KEY` absent:

- Python executable and version come from the new host-specific environment;
- backend imports succeed;
- production generator adapter imports succeed;
- database-only application startup/readiness succeeds without requiring an API key;
- the complete backend test suite passes offline;
- run any small additional generator integration test needed to prove the installed environment works.

No paid/live calls. Trap or otherwise prevent outbound provider calls during tests.

## 5. Reproducibility README

Create a tracked document at:

`docs/SERVER_WORKING_COPY_SETUP.md`

It must contain:

- what the mounted `/Volumes/home/...` path represents;
- why Python virtual environments are host- and OS-specific and must not be copied/reused;
- prerequisites and supported Python version;
- exact commands, derived from the verified installation, for another Mac with access to the mounted share to create its own uniquely named environment under `backend/.venvs/`;
- activation, verification and offline test commands;
- Git pull/submodule-update commands;
- a warning not to overwrite another host’s environment;
- the durable-data paths and backup-before-update warning;
- a statement that production-server venv/service/API-key configuration is intentionally deferred;
- troubleshooting for an unavailable mount, wrong Python version, missing submodule, dependency failure and read-only permissions.

Do not include any secret, API-key value, machine credential, raw question data or raw provider response.

## 6. Verification discipline

- Run long commands in the foreground.
- Do not launch a background test and declare that you are waiting.
- If a tool invocation times out while the process continues, actively poll it until completion and report the real exit code.
- If interrupted, inspect state and resume; never claim a test passed without its completed result.
- Do not start the backend/frontend servers unless a bounded offline startup check requires it, and stop any process you start.

## 7. Commit and push

In the **target outer repository only**:

- stage only the intended README, any necessary narrow `.gitignore` change, this WP brief if copied into `WPs/`, the architect report and refreshed handoff;
- never stage the database, data, artifacts, environments, caches, secrets or submodule contents;
- inspect the staged diff for secrets and unintended data;
- commit with a concise message such as `WP29: establish server working copy`;
- push normally to `origin/main` only after confirming a fast-forward push is safe;
- do not force-push.

The source repository may consequently be one documentation commit behind; do not mutate it during this WP. State the later `git pull --ff-only` command in the report.

## 8. Required report

Save the report in the target repository as:

`WPs/WP29_ARCHITECT_REPORT.md`

Also refresh `WPs/ARCHITECT_HANDOFF.md`.

The report must give the architect:

- source and target paths;
- source and final target outer SHAs/status/remotes;
- generator pinned SHA/status and proof it was not changed;
- exact clone/update method used;
- durable-data inventory, copy method and verification results;
- whether `app.db` is tracked and whether it leaves an expected unstaged modification;
- exact environment path, Python version and dependency-install commands;
- complete test commands/results/exit codes;
- files committed and exclusions confirmed;
- final commit SHA and push result;
- unresolved blockers or deviations;
- confirmation that no API key was read and no provider call was made.

Finish your response with a concise owner summary. If anything is incomplete, say so plainly and do not describe the WP as complete.
