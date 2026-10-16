# WP31 — Runtime Reliability: Authentication, Pricing, Editing, and Logging

## Goal

Correct four defects confirmed during real use of the local `questions-db` application on `crazyjoe`:

1. OpenAI `401 invalid_api_key` failures were retried and incorrectly charged conservative internal cost.
2. The bundled pricing snapshot became stale and produced misleading conservative estimates.
3. Manual editing of an LLM-generated question failed because the browser's `PATCH` CORS preflight did not authorize `PATCH` and `Content-Type`.
4. Each terminal job summary was printed twice despite one HTTP operation.

This WP spans the outer `questions-db` repository and, only where required, its `exam_generator` submodule. Preserve the existing public seven-field question contract and all previously approved generation/review behavior.

## Execution location and boundaries

- Work from the **local `questions-db` clone on `crazyjoe`**, not the mounted server checkout.
- Before editing, record:
  - outer HEAD, branch, remotes, `git status --short`;
  - generator HEAD, branch, remotes, `git status --short`;
  - `git submodule status`.
- Stop if either repository contains unexpected user changes that overlap this WP. Preserve unrelated owner files.
- Do not modify or commit `app.db`, existing exam-job artifacts, generated exams, provider responses, `.env*`, API keys, local pricing cache, virtual environments, `node_modules`, or mounted-server data.
- Do not make any paid model/provider call. Run tests with `OPENAI_API_KEY` unset and non-loopback provider access trapped.
- One unauthenticated HTTPS GET of the official OpenAI pricing documentation is allowed for validating the refresh mechanism. It must not use or inspect `OPENAI_API_KEY`.
- Do not repair or rewrite the historical failed job `0375e052-a879-493c-9796-56ef7040c163`; it is evidence. New behavior must be correct prospectively.
- Use foreground commands. Do not start background polling loops or pause with a promise to resume later. For long test suites, run them in the foreground (use `caffeinate -i` on macOS if helpful), retain the final exit status, and continue to the next required step.

## Confirmed evidence to preserve in the report

### Invalid credential case

The failed job returned `401 invalid_api_key` for both LLM slots and later retries. Its internal ledger nevertheless accumulated a `$2.0285250` `conservative_bound`. These were unauthenticated requests and must not be represented as paid model usage.

### CORS case

The edit preflight returned:

```text
Allow: PATCH, OPTIONS, HEAD, GET
Access-Control-Allow-Origin: http://localhost:3000
```

but omitted:

```text
Access-Control-Allow-Methods: PATCH
Access-Control-Allow-Headers: Content-Type
```

Consequently, the browser sent `OPTIONS` but never sent the actual `PATCH`.

## Part A — Correct credential failures and retry behavior

1. Trace the generator/provider exception mapping and the outer job adapter/service behavior for OpenAI authentication failures.
2. Introduce or use a stable, machine-readable credential/authentication failure classification. Do not expose raw provider payloads or any API-key prefix/suffix in public API responses, UI messages, reports, or logs.
3. A provider `401`, SDK authentication exception, or equivalent invalid-key response must:
   - stop that invocation immediately;
   - never trigger an internal generation/review retry;
   - have provider cost exactly `$0` because no billable usage was returned;
   - not decrement the job cost ceiling;
   - retain a redacted diagnostic/audit entry stating that authentication failed;
   - produce a clear Hebrew frontend message instructing the operator to correct the backend API key and restart the backend.
4. Add an exam-level credential circuit breaker: after the first definite authentication failure, do not send the remaining queued LLM slots to the provider. Mark them with the same safe actionable failure, with zero attempts/cost as appropriate to the existing slot semantics.
5. Do not treat all provider failures as free. If an authenticated provider response contains token usage but later fails schema, review, validation, or repair, charge the actual usage normally.
6. Preserve immutable telemetry and ledger integrity. Explicitly distinguish:
   - request rejected before billable usage;
   - authenticated response with usage;
   - authenticated response whose usage metadata is genuinely unavailable.

## Part B — Accurate pricing with safe automatic refresh

### Policy

- Keep `exam_generator/config/pricing.yaml` as a version-controlled, validated fallback snapshot.
- Do **not** rewrite any tracked pricing/configuration file at application startup.
- Add a Git-ignored local runtime cache, preferably below the existing ignored runtime/artifact area, with a configurable path for tests.
- Refresh at most once every 7 days. A fresh cache must not trigger a network request.

### Refresh source and validation

1. Use the official OpenAI pricing documentation Markdown endpoint as the source:

   `https://developers.openai.com/api/docs/pricing.md`

2. Fetch without an API key, with:
   - a short bounded timeout;
   - bounded response size;
   - HTTPS only;
   - no redirects to an unapproved host;
   - no provider/model call.
3. Read the selected generation and review model IDs from the normal LLM configuration. Extract only exact matching model IDs and the processing tier actually used by this application. Never infer one model's price from a similarly named model.
4. Validate all required fields before accepting the refresh: model ID, input price, cached-input price where applicable, output price, units (per one million tokens), processing tier, source URL, and retrieval timestamp. Values must be finite and nonnegative.
5. Write the cache atomically. Retain provenance and a content hash or equivalent traceable source fingerprint.
6. If the refresh fails, is malformed, or omits a selected model:
   - retain the last validated cache if available;
   - otherwise use the bundled snapshot;
   - emit a concise warning;
   - do not corrupt or partially replace the last good data.
7. Preserve the approved policy: stale-but-complete pricing warns; pricing missing for a selected model in every trusted source blocks LLM generation.
8. Prevent duplicate refreshes caused by Flask debug reload, concurrent readiness requests, or concurrent local processes (use an appropriate process/thread-safe guard and atomic cache update).

### Bundled snapshot

During this WP, manually verify the currently selected generation and review model rates against the official pricing documentation and refresh the bundled fallback snapshot's values/date/source if needed. Record the exact selected model IDs, tier, official source, verification date, and whether any numerical price changed. Do not change model selection in this WP.

### Cost calculation and presentation

1. On successful authenticated calls, prefer the provider's returned input, cached-input, and output usage multiplied by validated prices.
2. Use `conservative_bound` only when an authenticated call may be billable but exact usage is genuinely unavailable.
3. Never use a conservative bound for a definite pre-authentication `401`.
4. In the API/frontend/terminal:
   - label token-derived cost as actual calculated usage cost;
   - label fallback cost explicitly as an estimated upper bound;
   - do not present an upper bound as money definitely spent.
5. Preserve the cumulative per-exam ceiling and terminal total. Add the pricing source/basis succinctly without printing question content, prompts, responses, or secrets.

## Part C — Fix LLM-question manual editing and CORS

1. Diagnose the current Flask/CORS configuration rather than adding route-local ad hoc headers.
2. For configured local-development frontend origins, ensure the preflight for the existing question-edit route returns at least:

   ```text
   Access-Control-Allow-Origin: <exact permitted origin>
   Access-Control-Allow-Methods: ... PATCH ...
   Access-Control-Allow-Headers: ... Content-Type ...
   ```

3. Support the project's documented frontend origins (`localhost` and `127.0.0.1` variants for the configured development port) without using an unrestricted wildcard if credentials are enabled.
4. Confirm that the actual `PATCH`:
   - remains restricted to editable LLM-generated questions under the approved policy;
   - performs no LLM/provider call;
   - persists the edited seven public fields and immutable edit history;
   - preserves or resolves distractor warnings consistently with the existing WP28 contract;
   - survives backend-store reload and frontend page reload;
   - is reflected in Word and Excel exports.
5. Replace generic frontend `Failed to fetch` with a concise Hebrew network/CORS-style message while retaining useful developer diagnostics in the console. Do not show raw exception payloads to users.

## Part D — Remove duplicate terminal summaries

1. Determine why one HTTP operation printed two identical terminal summaries. Do not merely suppress every second line by value.
2. Ensure exactly one summary is emitted for each completed operation:
   - initial database selection where currently intended;
   - `continue-llm` completion;
   - manual retry completion;
   - LLM replacement completion.
3. DB-only replacements must remain free and must not print a misleading LLM-cost update.
4. Make behavior stable under Flask debug reloader and under tests that construct the app more than once.

## Required offline tests

Add focused tests before running full suites.

### Generator tests

- Mocked `401`/authentication exception produces a safe credential failure.
- No internal retry after authentication failure.
- Authentication failure has zero cost and no conservative bound.
- Authenticated response with usage is still charged even if later rejected.
- Pricing refresh parses exact selected model rows from a fixture.
- Fresh cache performs zero network calls.
- Stale cache refreshes once and writes atomically.
- Concurrent/startup calls do not duplicate the fetch or corrupt the cache.
- Malformed/oversized/timed-out/wrong-host response falls back safely.
- Missing selected model warns with fallback and blocks only if absent everywhere.
- No test reads a real key or contacts a provider.

### Backend tests

- A two-slot job with a fake invalid-key provider makes exactly one provider invocation total, zero review calls, zero charged cost, and marks both slots actionably without further provider attempts.
- Retrying while the same credential failure is active does not add cost or make inappropriate automatic retries.
- Cost ledger distinguishes zero-cost auth failures, actual token-derived cost, and upper-bound fallback.
- Terminal summary occurs exactly once per relevant operation.
- Browser-style `OPTIONS` preflight authorizes `PATCH` and `Content-Type` for every documented dev origin.
- Unsupported origins remain unauthorized.
- Actual `PATCH` persists an LLM question edit and edit history after store reload.
- Edited text appears in both Word and Excel export paths.
- Editing performs zero provider calls.

### Frontend tests

- Editing an LLM question sends one `PATCH` with the expected payload.
- Successful edit remains visible after refetch/reload.
- CORS/network failure shows the new Hebrew message.
- Credential failure shows the actionable Hebrew key message and does not masquerade as a rejected neuroanatomy question.
- Actual versus upper-bound cost labels render correctly.

All tests must use fake providers, mocked documentation responses, temporary cache paths, and network traps.

## Verification

1. Run focused generator, backend, and frontend tests.
2. Run the complete generator suite serially with provider/network access trapped.
3. Run the complete backend suite with `OPENAI_API_KEY` unset and provider/network access trapped.
4. Run the complete frontend test suite and production build.
5. With `OPENAI_API_KEY` unset, perform one explicit free pricing-document refresh smoke test against the official URL. Report duration, selected models found, resulting validated fields, and cache destination; never print the full downloaded document.
6. Run a local CORS smoke check equivalent to the owner's failing request and show that the response now includes `Access-Control-Allow-Methods: PATCH` and `Access-Control-Allow-Headers: Content-Type`.
7. Do **not** perform a live generation/review request in this WP.

## Git and delivery

1. Keep generator changes inside `exam_generator` and outer changes in `questions-db`; do not vendor the submodule.
2. Commit and push generator changes first if the generator is modified. Confirm its remote contains the commit before advancing the outer gitlink.
3. Commit the outer changes, including the updated gitlink when applicable, and push normally to `origin/main`; never force-push.
4. Never stage local caches, artifacts, databases, generated exams, raw provider material, `.env*`, credentials, venvs, or `node_modules`.
5. Confirm both repositories are clean at the end, apart from explicitly identified owner-owned untracked files that existed at preflight.

## Reports and architect handoff

Write the reports **inside the repositories' `WPs` directories**:

- `questions-db/WPs/WP31_ARCHITECT_REPORT.md`
- `questions-db/exam_generator/WPs/WP31G_ARCHITECT_REPORT.md` if the submodule is modified

Refresh the relevant `WPs/ARCHITECT_HANDOFF.md` file(s).

The outer report must state, without assuming the architect has read implementation details:

- root cause and exact correction for each of the four confirmed defects;
- whether the bundled numerical prices changed;
- selected models, tier, source URL, cache TTL, and fallback behavior;
- proof that invalid-key calls cost `$0` internally and are not retried;
- proof that the fixed preflight authorizes `PATCH` and `Content-Type` and that an edit persists/exports;
- proof that each terminal summary prints once;
- focused and full test/build counts and exit statuses;
- the free pricing-refresh smoke-test result;
- all changed files;
- generator and outer commit SHAs, push status, submodule pin, and final git status;
- deviations, unresolved risks, and any decision needed from the owner.

If any security, billing, pricing-source, data-integrity, or compatibility ambiguity remains, stop before live provider use and explain it in the report. Do not hide a failed or interrupted verification step.
