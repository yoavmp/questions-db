# WP30 — Frontend dependencies and offline local application test

## Goal

Prepare the mounted WP29 working copy for local use from this Mac by installing the frontend dependencies and verifying that the backend and frontend can run together without an OpenAI API key.

Target repository:

`/Volumes/home/Lab/Exam_Questions_Website/questions-db`

This WP is local-development setup only. Do not configure production hosting, server services, authentication, an API key, or external access.

## Fixed constraints

- Work only in the mounted target repository, not `/Users/crazyjoe/Projects/questions-db`.
- Expected outer baseline: `7e16b4b04e53545885a04c433800edf9618e3c52` on `main`, equal to `origin/main`.
- Preserve `exam_generator` unchanged at the SHA pinned by the outer gitlink.
- Use the existing host-specific backend environment under `backend/.venvs/joes-imac-py3.12/`.
- Keep `OPENAI_API_KEY` absent throughout this WP.
- Make no provider/API calls and do not access any secret value.
- Do not copy `node_modules` from the old local repository. Install from the committed lockfile.
- Long-running commands must be run in the foreground and actively awaited to their real exit code.

## 1. Preflight

Before changing anything, record:

- mount availability and write access;
- outer branch, HEAD, upstream, `origin/main`, remote and status;
- submodule SHA/status;
- Node and npm executable paths and versions;
- the frontend package manager/lockfile declared by the repository;
- whether `frontend/node_modules/` already exists and whether it is ignored.

Stop and report without mutation if:

- the mount is unavailable/read-only;
- outer HEAD differs from the expected baseline or `origin/main`;
- there are unexpected tracked changes, staged files or unpushed commits;
- the generator is dirty or does not match the outer gitlink;
- Node/npm are unavailable;
- more than one conflicting lockfile/package manager is present.

If `backend/src/database/app.db` remains modified only because WP29's SQLite `.backup` rewrote an otherwise logically identical database, confirm this against `WPs/WP29_ARCHITECT_REPORT.md`, restore it from `HEAD`, and verify that no real database content is lost. Do not restore any other modification.

## 2. Install frontend dependencies

Inspect `frontend/package.json` and the committed lockfile first.

- Use `npm ci` when `package-lock.json` is authoritative.
- Do not use `npm install` merely to regenerate or update the lockfile.
- Do not upgrade packages or change dependency versions.
- Do not copy old `node_modules` or caches.
- Keep `frontend/node_modules/` ignored and unstaged.
- Treat the installed modules as host/platform-specific. They must be reinstalled for a different operating system or deployment host.

Run the installation from:

`/Volumes/home/Lab/Exam_Questions_Website/questions-db/frontend`

The mounted SMB share may make installation slow. Continue waiting while the command is making progress; do not leave it as an unattended background task or claim completion from partial output.

After installation, run an appropriate dependency-tree check such as `npm ls --depth=0`. Report any vulnerabilities separately, but do not run `npm audit fix` or mutate dependencies in this WP.

## 3. Offline frontend verification

With `OPENAI_API_KEY` explicitly absent:

1. Run the complete frontend test suite using the repository's existing test command.
2. Run the production frontend build.
3. Confirm generated build output and caches remain ignored/untracked.
4. Confirm `package.json` and the lockfile remain byte-for-byte unchanged unless a genuine pre-existing repository defect makes that impossible; if so, stop and report before editing them.

## 4. Bounded backend–frontend smoke test

Use the existing backend environment:

`backend/.venvs/joes-imac-py3.12/`

Perform a bounded local smoke test with no API key:

- confirm backend DB-only readiness is available and LLM readiness is unavailable only because the key is absent;
- start the backend locally using the established development entry point;
- start the frontend development server using `npm run dev`;
- record the actual URLs/ports emitted by both processes;
- verify the frontend page responds;
- verify at least one harmless backend endpoint used by the frontend responds;
- verify there is no provider call and no requirement for a key merely to browse questions or begin DB-only exam selection;
- stop every process started by this WP and prove the ports are free afterward.

Do not perform LLM generation, retry, replacement, or any other paid operation. Do not modify `app.db` or create a real saved exam during the smoke test.

If automated browser tooling is unavailable, HTTP-level verification plus the passing component tests/build is sufficient; state that limitation honestly.

## 5. Update setup documentation

Update `docs/SERVER_WORKING_COPY_SETUP.md` with:

- verified Node/npm versions;
- the exact clean-install command for frontend dependencies;
- the exact two-terminal commands for the owner to run the backend and frontend locally with no API key;
- the actual local URLs;
- an explanation that DB browsing and DB-only exam preparation work without a key, while LLM operations remain unavailable;
- a warning that `node_modules` is host/platform-specific and must not be copied to another computer;
- instructions to stop each development server;
- brief troubleshooting for `npm: command not found` and `vite: command not found`.

Do not include secrets or suggest storing an API key in the repository.

## 6. Verification and Git hygiene

At completion, verify:

- no server process remains running;
- no API key was read;
- no provider/network call was made, except ordinary npm registry access required by `npm ci`;
- database, artifacts, generator data and generator gitlink were unchanged;
- `node_modules`, build products and caches are ignored;
- only intended documentation/report files are staged.

Run a secret/data scan over the staged diff.

## 7. Report, commit and push

Save:

- this brief under `WPs/WP30_Frontend_Dependencies_And_Offline_Local_Test.md`;
- the report under `WPs/WP30_ARCHITECT_REPORT.md`;
- a concise updated entry in `WPs/ARCHITECT_HANDOFF.md`.

The report must include:

- preflight SHAs/statuses;
- Node/npm versions;
- exact install/test/build/smoke commands and exit codes;
- frontend test and build totals;
- URLs/ports actually verified;
- confirmation that all temporary processes were stopped;
- final Git status and intended files committed;
- confirmation that generator/data/database were unchanged;
- confirmation that no API key was read and no provider call occurred;
- any warnings, deviations or blockers.

Commit only the intended tracked documentation/report changes in the **outer target repository**, then push normally to `origin/main` after confirming a fast-forward push is safe. Never force-push. Do not commit or push within `exam_generator`.

Suggested commit message:

`WP30: prepare frontend local development`

Finish with a short owner-facing summary containing the exact commands the owner should run in two terminals to test the application. Do not call the WP complete unless dependency installation, tests, build and bounded smoke verification all finished successfully.
