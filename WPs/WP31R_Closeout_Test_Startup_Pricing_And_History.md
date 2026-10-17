# WP31R — Closeout: Green Suite, Startup Pricing Refresh, and Git History

## Goal

Close the three remaining WP31 issues without changing question-generation behavior:

1. restore a completely green `exam_generator` test suite by fixing the exact historical-report spelling-audit failure;
2. make the already implemented safe pricing refresh run automatically when the backend starts, rather than waiting for the first paid generation request;
3. reconcile the conflicting WP31 outer commit SHAs in the reports and handoff.

This is a narrow corrective WP. Do not redesign pricing, generation, review, editing, or job behavior.

## Execution location and boundaries

- Work only from the **local `questions-db` clone on `crazyjoe`**, not from the mounted server checkout.
- Before editing, record:
  - outer HEAD, branch, remotes, `git status --short`, and `origin/main`;
  - generator HEAD, branch, remotes, `git status --short`, and `origin/main`;
  - `git submodule status`;
  - the outer commits `b8e018d90230026ee2a7c79dacd346360664a55b` and `7847aa8` if they exist locally/remotely, including their subjects and parent relationship.
- Stop and report before editing if either repo contains unexpected overlapping user changes.
- Preserve the existing untracked owner audit files and do not stage them.
- Do not modify or commit databases, exam-job artifacts, generated exams, provider responses, pricing cache files, `.env*`, credentials, virtual environments, or `node_modules`.
- Do not inspect or use `OPENAI_API_KEY`.
- Make **zero paid provider/model calls**. All tests must run with `OPENAI_API_KEY` unset and provider access trapped.
- One unauthenticated HTTPS request to the official pricing-document URL is allowed only for the final free refresh smoke test.
- Run verification in the foreground. Do not start background polling loops or pause with a promise to resume later.

## Part A — Fix the exact generator spelling-audit failure

The reported failing test is:

```text
tests/test_wp16r_output_repair.py::test_bad_spelling_only_survives_in_labelled_provenance_or_source
```

It flags a historical misspelling in `exam_generator/WPs/WP28G_ARCHITECT_REPORT.md`.

1. Reproduce the single failure first and record the exact matched spelling and surrounding line.
2. Fix only that occurrence using the narrowest semantically honest correction:
   - correct ordinary narrative prose to the approved spelling; or
   - if the misspelling must remain as historical evidence, mark only that literal occurrence using the repository's existing accepted provenance/source convention.
3. **Do not allowlist the entire report file.** Do not weaken, delete, or broadly bypass the spelling audit.
4. Confirm that the historical meaning and provenance remain understandable.
5. Run the focused failing test, then the complete generator suite serially. The required result is **zero failures and zero errors**. Existing intentional skips are acceptable and must be counted.

## Part B — Refresh pricing automatically at backend startup

WP31 implemented a validated seven-day pricing cache and made real generation calls opt in to it. That protects generation, but the refresh currently waits until the first generation call. The owner requested automatic refresh when the backend starts.

### Required behavior

1. Locate the canonical backend startup/application-initialization path used by `python run.py`. Integrate the existing WP31 pricing refresh there through a small, testable function. Reuse `exam_generator/pricing_refresh.py`; do not create a second downloader or parser.
2. On backend startup:
   - resolve the selected generation and review models from the normal configuration;
   - inspect the configured/default local pricing cache;
   - if the cache is fresh (TTL: 7 days), make zero network requests;
   - if it is stale or absent, perform at most one unauthenticated, bounded HTTPS refresh from the already approved official URL;
   - validate and atomically store it using the existing WP31 implementation;
   - never read or transmit `OPENAI_API_KEY`.
3. Startup refresh is **best effort**:
   - a timeout, offline computer, malformed response, missing selected model, unwritable cache, or any other refresh error must not prevent the backend from starting when the bundled snapshot remains complete;
   - retain the last valid cache or bundled fallback;
   - emit one concise terminal warning without secrets, document contents, or a traceback intended for the user;
   - preserve the approved rule that pricing absent for a selected model from every trusted source blocks only the later LLM operation, not ordinary DB-only application use.
4. Prevent duplicate fetches or duplicate warnings under Flask's debug reloader and concurrent initialization. Reuse the existing thread/process-safe protection and atomic cache behavior. Do not add a second locking mechanism unless the existing one is insufficient and the report demonstrates why.
5. The existing generation-time refresh/check must remain as a safety net. Startup refresh should normally make it a cache hit, not remove it.
6. Keep the default cache Git-ignored. Do not rewrite tracked `config/pricing.yaml` during startup.
7. Surface a concise startup line containing only:
   - pricing source/basis (`fresh cache`, `refreshed`, or `bundled fallback`);
   - selected model IDs;
   - cache age or refresh date;
   - warnings if any.
   Do not print price-document contents, prompts, question text, responses, or credentials.

### Required tests

Add focused offline tests proving:

- backend startup with a fresh cache makes zero network calls;
- stale/absent cache calls the injected fake downloader exactly once and writes a valid cache;
- debug-reloader/concurrent initialization does not duplicate the refresh;
- offline/timeout/malformed-response refresh failure still permits backend startup when the bundled snapshot is valid and produces one safe warning;
- missing selected-model pricing everywhere does not crash DB-only startup but remains a readiness/LLM-operation blocker;
- startup never accesses `OPENAI_API_KEY`;
- no test contacts the real pricing site or a provider.

Use dependency injection, monkeypatching, temporary cache paths, and network traps. Do not make tests depend on wall-clock snapshot age; inject/freeze time or set an unambiguously stale timestamp.

## Part C — Reconcile WP31 Git history and documentation

The owner-facing WP31 completion summary named outer commit `7847aa8`, while `WPs/WP31_ARCHITECT_REPORT.md` states that the final outer commit and `origin/main` were `b8e018d90230026ee2a7c79dacd346360664a55b`.

1. Inspect the actual commit graph and remote state. Do not guess.
2. Determine whether `7847aa8` is a later documentation/finalization commit whose parent or ancestor is the WP31 implementation commit `b8e018d…`, or whether one of the identifiers is erroneous.
3. Update `WPs/WP31_ARCHITECT_REPORT.md` and the relevant `WPs/ARCHITECT_HANDOFF.md` so they distinguish clearly between:
   - the WP31 implementation commit;
   - any later WP31 report/finalization commit;
   - the actual pre-WP31R remote HEAD.
4. Preserve the historical report; correct factual statements rather than silently deleting the discrepancy. Add a dated correction note if appropriate.
5. If `7847aa8` does not exist or is unrelated, say so plainly in the report. Do not invent a mapping.

## Verification

Run in this order, all in the foreground:

1. focused generator spelling-audit test;
2. focused pricing-refresh and backend-startup tests;
3. complete generator suite serially — required: zero failures/errors;
4. complete backend suite — required: zero failures/errors;
5. complete frontend suite and production build if any frontend file changed; otherwise state that no frontend file changed and why rerunning it was unnecessary;
6. one explicit free startup-refresh smoke test with `OPENAI_API_KEY` unset, using a temporary/ignored cache and the official pricing URL; report duration, selected models, outcome, and whether a cache was written, without printing the downloaded document;
7. a second startup against that fresh cache proving zero additional network refresh was needed.

If any required suite is killed or interrupted, rerun it in the foreground and do not describe it as passed until its final exit code is known.

## Git and delivery

1. If the generator changes, commit and push the generator first. Confirm its `origin/main` contains the commit before advancing the outer gitlink.
2. Commit outer changes, including the gitlink when applicable, and push normally to `origin/main`. Never force-push or rebase shared history.
3. Do not stage the owner-owned untracked audit files or any ignored runtime material.
4. Confirm both repositories are clean at the end apart from explicitly listed pre-existing owner-owned files.

Because a commit cannot truthfully contain its own SHA inside itself, do not create an endless chain of documentation-only commits. The report must record all known predecessor and implementation SHAs. The final response to the owner must provide the actual final pushed HEAD obtained after all commits.

## Reports and architect handoff

Write reports in the repositories' `WPs` directories:

- `questions-db/WPs/WP31R_ARCHITECT_REPORT.md`
- `questions-db/exam_generator/WPs/WP31RG_ARCHITECT_REPORT.md` if the generator changes

Refresh the relevant `WPs/ARCHITECT_HANDOFF.md` file(s).

The outer report must include:

- the exact misspelling-test root cause and narrow correction;
- complete generator test counts proving zero failures/errors;
- the startup-refresh call path and why it cannot block DB-only startup;
- fresh-cache, successful-refresh, failure-fallback, and duplicate-prevention test evidence;
- the free startup-refresh smoke-test result and the second-start cache-hit result;
- the reconciled `b8e018d…` / `7847aa8` history based on actual Git evidence;
- every changed file;
- generator and outer implementation commit SHAs, push status, final submodule pin, and final Git statuses;
- any deviation, unresolved risk, or decision needed from the owner.

Do not claim WP31R complete while any required suite has a failure or unknown/terminated outcome.
