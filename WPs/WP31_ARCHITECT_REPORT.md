# WP31 — Architect Report

**WP brief:** `WPs/WP31_Runtime_Reliability_Pricing_Auth_And_Editing.md`.
Spans this outer repo and the `exam_generator` submodule. See
`exam_generator/WPs/WP31G_ARCHITECT_REPORT.md` for the generator-side
Part A (provider-level classification) and all of Part B (pricing refresh).
This report covers everything in this outer repo: the rest of Part A (job
service / circuit breaker), Part C (CORS/editing), and Part D (terminal
summary), plus the combined verification/delivery record.

No live/provider call was made anywhere in this WP. `OPENAI_API_KEY` was
unset for every test run. One unauthenticated HTTPS GET of the official
OpenAI pricing documentation was made (generator side only, see that
report) — never touching `OPENAI_API_KEY`.

## 0. Preflight

- Outer: HEAD `f9b51c8` (`WP28: record final commit SHA and push outcome in
  architect report`), branch `main`, remote `origin` =
  `https://github.com/yoavmp/questions-db.git`. `git status --short` showed
  only pre-existing untracked owner WP brief files (`PRE_WP25_…`,
  `PRE_WP26R_AUDIT.md`, `PRE_WP28_…`, `WP29_Server_Working_Copy_And_Host_Venv.md`,
  this WP's own brief) — no unexpected overlapping changes. Proceeded.
- Generator submodule: HEAD `5200b531f559b9fcd963cb7a3ca22ebcc6f4a98d`
  (`heads/main`), clean.
- **Mid-WP discovery:** `origin/main` had advanced two WPs ahead of the
  local outer HEAD (WP29 "establish server working copy" + WP30 "prepare
  frontend local development", docs-only — `docs/SERVER_WORKING_COPY_SETUP.md`,
  two new `WPs/WP29*`/`WP30*` reports, a `.gitignore` addition, and an
  `ARCHITECT_HANDOFF.md` update — none overlapping any file this WP
  touches). Stashed this WP's then-in-progress working-tree changes
  (`git stash push -u`), fast-forwarded local `main` to `origin/main`
  (`git merge --ff-only`, clean fast-forward, no conflicts), then restored
  the stash (one harmless "already exists" note for an untracked WP brief
  file that WP29 had since committed identically — confirmed byte-identical
  via `git diff`, stash entry dropped). Re-ran every affected test after
  this merge; no regression. This outer repo is now based on
  `f55402c` (WP30), not the stale `f9b51c8` recorded at preflight.

## 1. Root cause and exact correction, per confirmed defect

### Defect 1 — invalid-key failures retried and charged conservative cost

**Root cause** (generator-side origin, outer-side consumption): see the
generator report §1 for the full provider-level root cause
(`openai.AuthenticationError` folded into the generic systemic-failure
bucket, which prices every no-response attempt at its conservative bound).
On this outer repo's side, nothing distinguished this from any other
`"failed"` slot, so there was no mechanism to stop the rest of a job's
queued LLM slots from also being sent to a provably-dead credential.

**Correction** (`backend/src/jobs/service.py`):

- A new `AUTH_FAILURE_HEBREW_MESSAGE` constant — the one fixed, actionable,
  secret-free Hebrew sentence shown for every credential failure (never the
  raw internal `failure_reason`).
- `_generate_one` gained an `elif result.status == "authentication_failure"`
  branch (alongside the pre-existing `"cost_ceiling"` branch): the slot is
  marked `status="failed"` (no new slot-status value — reuses the existing
  `SLOT_STATES` enum exactly as the WP asks, "zero attempts/cost as
  appropriate to the existing slot semantics") with
  `safe_error=AUTH_FAILURE_HEBREW_MESSAGE`, and calls a new
  `_trip_auth_circuit_breaker(job, except_slot_id=slot.slot_id)`.
- `_trip_auth_circuit_breaker` sets `job.safe_error` (job-level, survives
  even a `_restore_slot` rollback on a failed `replace_via_llm`) and marks
  **every other** currently-`"queued"` LLM slot in the **whole job** (not
  just the current category) `"failed"` with the same message — no provider
  call, no cost-ledger entry, for any of them.
- Because this lives inside `_generate_one` itself, the breaker applies
  uniformly to every caller that reaches it: the initial automatic run
  (`_run_llm_slots`), a manual `retry_slot`, and `replace_via_llm` alike.
  `_run_llm_slots`'s loop gained an explicit `if slot.status != "queued":
  continue` guard plus a `stopped_by_auth_failure` break (mirroring the
  pre-existing `stopped_by_ceiling` pattern exactly) so it never re-sends an
  already-blocked slot to the provider just because the loop reached it
  next in the same pass.
- Cost: `$0`, `basis="calculated"` — fixed at the generator layer (see that
  report); this outer repo's ledger (`_record_cost`) needed no change, since
  it already just records whatever `result.cost_usd`/`total_cost_basis` the
  adapter returns.

**Proof** (`backend/tests/test_wp31_auth_circuit_breaker.py`, new, 5 tests):
a two-slot same-category job with a fake invalid-key provider makes
**exactly one** provider invocation total (the fake's own call counter),
**zero** review calls, both slots `"failed"` with the actionable Hebrew
message (never the raw internal reason — asserted `"sk-"` / exception class
name are never in `safe_error`), job `accumulated_cost_usd == "0"`, exactly
one cost-ledger entry (the second slot never even got one — no call was
made for it), and exactly one terminal-summary line. A second test proves
the same across **two different categories** (the breaker is exam-level,
not per-category). A third proves a manual `retry_slot` while the same
credential failure is still active makes exactly one call (the one the
operator explicitly asked for), costs `$0`, and prints one summary line —
no inappropriate automatic re-retry. A fourth directly contrasts the
ledger's zero-cost auth entry against an ordinary charged
(`conservative_bound`) content-rejection entry from the same test file, in
the same run, proving the two are distinguishable. A fifth is a sanity
check that an ordinary successful job is completely unaffected.

### Defect 2 — stale bundled pricing snapshot

Entirely generator-side; see that report §2 for the full account (verified
the selected model, `gpt-5.6-terra`, against the live official doc on
2026-10-16 — no numerical price changed, only `verified_at`/`source`
refreshed) and the new `pricing_refresh.py` module. This outer repo's only
involvement: `backend/src/integration/generator_adapter.py` now opts every
real call in to the new cache (`pricing_cache_path=os.environ.get(
"EXAM_GENERATOR_PRICING_CACHE_PATH", <default artifacts path>)`), and
`backend/tests/conftest.py` gained an autouse `_pricing_cache_isolated`
fixture that seeds a fresh, isolated, per-test cache (exactly the bundled
numbers) so no backend test ever depends on or risks a network call.

### Defect 3 — manual editing broken by a missing CORS preflight authorization

**Root cause:** `backend/src/main.py` configured Flask-CORS with
`methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']` — **`PATCH` was
missing**. `flask_cors.core.get_cors_headers` only emits
`Access-Control-Allow-Methods` / `-Headers` on a preflight at all when the
request's `Access-Control-Request-Method` is itself a member of the
configured `methods` list (confirmed by reading `flask_cors`'s own source);
with `PATCH` absent, the whole conditional block was skipped, so the
preflight response carried `Access-Control-Allow-Origin` (set
unconditionally, earlier in the same function) but neither of the other two
headers — exactly the evidence captured (`Allow: PATCH, OPTIONS, HEAD, GET`
+ `Access-Control-Allow-Origin: http://localhost:3000`, with
`Access-Control-Allow-Methods`/`-Headers` both absent). The browser
therefore never sent the real `PATCH` at all. Separately, `origins='*'` was
an unrestricted wildcard (legal here since no credentials are used, but not
what the WP asks for).

**Correction:** factored the whole CORS policy out of `main.py` into a new
`backend/src/cors_config.py` ("Diagnose the current Flask/CORS
configuration rather than adding route-local ad hoc headers" — WP31 Part C
§1) — `DEV_FRONTEND_ORIGINS = ["http://localhost:3000",
"http://127.0.0.1:3000"]` (both documented dev-frontend forms, from
README.md/SETUP.md's own Vite-port-3000 instructions; never a wildcard),
`ALLOWED_METHODS` now includes `PATCH`, and a `configure_cors(app)` function
`main.py` calls once. This is also what makes the fix independently
testable without importing `src.main` (which runs DB migrations against a
fixed path at import time, per the existing test-suite convention).

**Proof** (`backend/tests/test_wp31_cors_and_edit.py`, new, 6 tests): a
`PATCH` preflight (`Origin: http://localhost:3000` /
`http://127.0.0.1:3000`, `Access-Control-Request-Method: PATCH`,
`Access-Control-Request-Headers: Content-Type`) against a minimal app using
the real `configure_cors` now returns
`Access-Control-Allow-Origin: <exact origin>` (echoed exactly, never `*`),
`Access-Control-Allow-Methods` containing `PATCH`, and
`Access-Control-Allow-Headers` containing `Content-Type`, for **both**
documented origins; an unsupported origin (`evil.example.com`,
`localhost:9999`, `null`) gets **none** of the three CORS headers; `"*"` is
asserted absent from the configured origin list. A sixth end-to-end test
confirms the fix sits in front of the unchanged `edit_llm_question` service
call: editing makes zero provider calls, survives a fresh `store.load`, and
the edited text is present in both the LLM-only and full Excel export
bytes (opened with `openpyxl` and searched cell-by-cell) — the persistence/
export/no-provider-call guarantees are the same ones WP28's own test suite
(`test_wp28_warning_edit_and_repair_hardening.py`, `test_wp28_routes.py`,
32 tests, still green — §5) already proves in depth; this file's one new
test is a regression confirmation, not new generation-side logic.

Live CORS smoke check (Verification §6), reproducing the owner's exact
failing request against the real route/blueprint:

```
status: 200
Allow: PATCH, OPTIONS
Access-Control-Allow-Origin: http://localhost:3000
Access-Control-Allow-Methods: DELETE, GET, OPTIONS, PATCH, POST, PUT
Access-Control-Allow-Headers: Content-Type
```

`Access-Control-Allow-Methods`/`-Headers` are now present and correct,
where the owner's original evidence showed both absent.

The frontend's generic `"Failed to fetch"` was replaced too (Part C §5):
`frontend/src/lib/examApi.js` gained a `safeFetch` wrapper around every raw
`fetch()` call — a rejected `fetch()` promise (CORS block, backend down, no
network — all indistinguishable browser-level failures) is caught, logged
to the console with the original error for developer diagnostics
(`err.cause`), and re-thrown as a fixed Hebrew message
(`NETWORK_ERROR_MESSAGE_HE`, exported for tests) with `isNetworkError:
true`. An HTTP-level (non-2xx) response is completely unaffected — that
path (`jsonOrThrow`) is untouched, still surfaces the backend's own Hebrew
reason. No raw exception payload is ever shown to the user; the component's
existing `e.message || <fallback>` pattern already picks up the new message
with zero component-side change needed beyond that.

### Defect 4 — duplicate terminal summaries

**Root cause:** `service._print_terminal_summary` called **both**
`log.warning(line)` and `print(line, flush=True)` with the identical
string. The `"exam_jobs"` logger has no handler configured anywhere in this
app (confirmed directly: `logging.getLogger("x").warning("y")` with no
config prints `y` to **stderr** via Python logging's own `lastResort`
handler, which uses the bare `%(message)s` format — i.e. byte-identical to
the message itself). Both `stdout` (the `print`) and `stderr` (the
`lastResort`-handled `log.warning`) land in the same terminal window when
running `python run.py` interactively, so one HTTP operation visibly
printed the same line twice. This is **not** a value-level duplicate from
two identical operations — it was always two separate `write()` calls from
the same one operation, on two different streams — so no amount of
deduplicating by comparing adjacent printed values could ever have been the
right fix, exactly as the WP warns against.

**Correction:** removed the `log.warning(line)` call (and the now-unused
`import logging` / module-level `log` object), keeping `print(...)` as the
**one** canonical emission channel — the one already asserted exactly-once
by the pre-existing `test_wp20_terminal_cost_log.py` suite via `capsys`
(which only captures `stdout`, so that suite could never have caught this
specific duplication in the first place — it only showed up watching a real
terminal, exactly as the owner reported).

**Proof:** the pre-existing `test_wp20_terminal_cost_log.py` (6 tests)
still passes unchanged (§5) — confirming the single `print` channel still
fires exactly once per operation, for every operation kind it already
covered. The new `test_wp31_auth_circuit_breaker.py` tests independently
confirm exactly one line for the two *new* code paths this WP added
(an authentication-failure-terminated initial run, and a manual retry
during an active credential failure) via the same `capsys` pattern.

## 2. Selected models, tier, source, cache TTL, fallback (summary; full
   detail in the generator report)

Selected generation **and** review model: `gpt-5.6-terra`. Processing tier:
Standard (implicit — no `service_tier` override is ever sent). Official
pricing source: `https://developers.openai.com/api/docs/pricing.md`. Cache
TTL: 7 days, Git-ignored, at
`exam_generator/artifacts/pricing_cache/openai_pricing_cache.yaml` by
default (overridable via `EXAM_GENERATOR_PRICING_CACHE_PATH`, used by this
repo's own test isolation). Fallback order on any refresh failure: last
validated cache for the exact model → bundled `config/pricing.yaml` →
(only if genuinely absent from both) a fatal, pre-call
`"systemic_failure"` via the pre-existing `_verify_pricing` model-match
check — unchanged by this WP.

## 3. Proof: invalid-key calls cost $0 and are never retried

See §1 Defect 1 above (outer, job-level) and the generator report §1
(provider/production-level: `generation_calls == 1`, `review_calls == 0`,
`total_cost_usd == "0"`, `total_cost_basis != "conservative_bound"`, no
second attempt). Both layers independently proven, by tests at each layer.

## 4. Proof: the fixed preflight authorizes PATCH/Content-Type and an edit persists/exports

See §1 Defect 3 above — CORS test results, live smoke check, and the
end-to-end persistence/export confirmation.

## 5. Proof: each terminal summary prints exactly once

See §1 Defect 4 above.

## 6. Focused and full test/build counts and exit statuses

Focused (new WP31 tests only):

| Suite | Command | Result |
|---|---|---|
| Generator | `pytest tests/test_wp31_authentication_failure.py tests/test_wp31_pricing_refresh.py tests/test_wp05_llm_contracts.py -q` | **67 passed, 0 failed** |
| Backend | `pytest tests/test_wp31_auth_circuit_breaker.py tests/test_wp31_cors_and_edit.py tests/test_wp18_readiness.py tests/test_wp20_terminal_cost_log.py -q` | **23 passed, 0 failed** |
| Frontend | `npx vitest run src/lib/examApi.test.js src/components/ExamGenerationSection.wp31.test.jsx` | **20 passed, 0 failed** |

Full suites, serially, `OPENAI_API_KEY` unset, provider/network access
trapped (generator: suite-wide autouse socket trap, new this WP; backend:
the pre-existing WP18 trap, broadened this WP from WP18-only tests to every
test in the suite):

| Suite | Command | Result | Exit |
|---|---|---|---|
| Generator (submodule) | `pytest -q` | **1049 collected, 874 passed, 1 failed (pre-existing, unrelated — see below), 174 skipped** | 1 |
| Backend | `pytest -q` | **321 passed, 0 failed** | 0 |
| Frontend | `npx vitest run` | **9 files / 163 tests passed, 0 failed** | 0 |
| Frontend production build | `npm run build` | succeeds (`✓ built in 2.77s`) | 0 |

**The one generator failure is pre-existing and unrelated to this WP:**
`tests/test_wp16r_output_repair.py::test_bad_spelling_only_survives_in_labelled_provenance_or_source`
— a repo-wide spelling-audit allowlist test flags one narrative-prose
occurrence of a known historical misspelling in
`exam_generator/WPs/WP28G_ARCHITECT_REPORT.md`, a file committed by WP28G
before this WP started and never touched by it (confirmed via `git log`/
`git diff`). Full detail and the owner-decision option in the generator
report §5/§8.

During diagnosis, two earlier full-backend-suite runs (made while a second
full generator-suite run was *also* executing concurrently in the
background, both as `caffeinate`-wrapped processes competing for the same
CPU/filesystem) showed 4 failures that varied between runs and vanished
entirely in isolation or re-run alone — confirmed, by running the full
backend suite alone twice more, to be resource contention from running two
full suites simultaneously, not a defect in any changed code. One of the
earlier failures (`test_stale_pricing_warns_but_does_not_block`) was real
but unrelated to the contention — it asserted a hard-coded `pricing_stale_days=0`
threshold against the bundled snapshot's **real, wall-clock-measured** age,
which the generator-side `verified_at` refresh (§2 of that report, done
*as part of* this WP) legitimately made `0` days old; fixed by changing the
threshold to `-1` (any snapshot is stale at that threshold, regardless of
its real elapsed age — the test's actual intent, "stale never blocks", was
never about a specific elapsed day count).

## 7. Free pricing-refresh smoke-test result

Run standalone (`OPENAI_API_KEY` unset), never collected by any test suite:

```
selected generation model: 'gpt-5.6-terra'
selected review model:     'gpt-5.6-terra'
source URL:                https://developers.openai.com/api/docs/pricing.md

duration: 0.322s
warnings: (none)
cache destination: <temp path>/openai_pricing_cache.yaml
cache written: True

validated fields for the selected model:
  provider:            openai
  model:               gpt-5.6-terra
  verified_at:         2026-10-16
  source:              https://developers.openai.com/api/docs/pricing.md
  input (usd/1M):      2.00
  cached_input:        0.20
  cache_write:         2.50
  output:              12.00

matches bundled config/pricing.yaml exactly: True
```

The full downloaded document was never printed; only the above bounded
summary.

## 8. All changed files

Generator submodule (`exam_generator/`, pinned per §9): see that repo's own
report §6 for its full file list.

Outer repo:

```
backend/src/cors_config.py                     (new)
backend/src/integration/generator_adapter.py    (opt-in pricing cache wiring)
backend/src/integration/generator_pin.py        (re-pinned to 303cf39)
backend/src/jobs/service.py                     (circuit breaker; single terminal-print channel)
backend/src/main.py                             (CORS factored out to cors_config.configure_cors)
backend/tests/_wp18_fakes.py                    (InvalidKeyProvider fake)
backend/tests/conftest.py                       (pricing-cache isolation + broadened network trap)
backend/tests/test_wp18_readiness.py            (stale-threshold fix, see §6)
backend/tests/test_wp31_auth_circuit_breaker.py (new)
backend/tests/test_wp31_cors_and_edit.py        (new)
frontend/src/components/ExamGenerationSection.jsx (actual-vs-upper-bound cost label)
frontend/src/lib/examApi.js                     (safeFetch network-error wrapper)
frontend/src/lib/examApi.test.js                (network-error tests)
frontend/src/components/ExamGenerationSection.wp31.test.jsx (new)
```

## 9. Commit SHAs, push status, submodule pin, final git status

- Generator: committed `5660df4f8b182b35d66fec118c7202a0c73993bb`
  ("WP31G: classify provider authentication failures and add safe
  pricing-doc refresh") then `303cf394cc0b9839c459d1e56f8784e147e80e9f`
  ("WP31G: record final commit SHA and push outcome in architect report").
  Both pushed to `origin/main`
  (`https://github.com/yoavmp/exam-generator.git`); `git ls-remote origin
  main` confirmed `303cf39…` landed **before** the outer gitlink below was
  staged. `git status --short` in the submodule: clean.
- Outer: gitlink advanced to `303cf394cc0b9839c459d1e56f8784e147e80e9f`;
  `backend/src/integration/generator_pin.py::EXPECTED_GENERATOR_PIN`
  updated to match (confirmed equal to the submodule's actual `HEAD` via a
  direct comparison, §1 above was already re-run against this pin with the
  full backend suite green).
- Outer commit SHA, push status, and final outer `git status` are recorded
  in a follow-up commit to this same report (established WP convention).

## 10. Deviations, unresolved risks, owner decisions needed

- **The pre-existing, unrelated generator test failure** (§6): a one-line
  allowlist addition (`"WPs/WP28G_ARCHITECT_REPORT.md"`) in
  `exam_generator/tests/test_wp16r_output_repair.py` would make that suite
  fully green. Deliberately left unresolved — not one of this WP's four
  confirmed defects, and that allowlist belongs to WP16R's own audit
  mechanism, not this WP's scope. **Owner decision needed:** fix now
  (trivial, low risk) in a follow-up, or leave as a known, tracked gap.
- **`origin/main` had moved ahead by two WPs mid-session** (§0) — handled
  via a clean stash/fast-forward/restore with zero conflicts and zero file
  overlap; flagged here per the instruction to stop on unexpected changes,
  even though this one resolved safely and transparently. No owner action
  needed, but noting it for the record.
- **Processing tier is still implicit** (generator report §8) — a future
  change that adds an explicit `service_tier` override to the provider call
  must also update `pricing_refresh.EXPECTED_PROCESSING_TIER`/
  `_TIER_HEADING`, or pricing-doc refresh will silently target the wrong
  tier's table. Flagged as a structural coupling to watch, not a defect.
- No security, billing, pricing-source, data-integrity, or compatibility
  ambiguity remains that would block live provider use on these four
  defects' own terms. This WP made no live provider call and recommends
  none until the owner has reviewed this report.
