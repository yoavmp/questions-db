# WP31R — Closeout: Green Suite, Startup Pricing Refresh, and Git History

## Scope and boundaries actually observed

Work was done only in the local `questions-db` clone on `crazyjoe`
(`/Users/crazyjoe/Projects/questions-db`), never the mounted server
checkout. No database, exam-job artifact, generated exam, provider
response, pricing cache file, `.env*`, credential, virtual environment, or
`node_modules` was modified or committed. `OPENAI_API_KEY` was never
inspected. Every test ran with it unset and with real sockets trapped
(generator: its own autouse offline-socket guard; backend: the pre-existing
`_wp18_no_network` autouse fixture). The one real network call made was the
single, explicitly-authorized final smoke test (§6) to the official pricing
document URL — never a provider call.

## Pre-flight state (recorded before any edit)

- **Outer** HEAD: `7847aa85915f915e13cbc78dc0fcb31be4ba9240`, branch `main`,
  remote `origin` = `https://github.com/yoavmp/questions-db.git`,
  `origin/main` = same SHA (already in sync). `git status --short`: only
  the three pre-existing untracked owner audit files
  (`WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`, `WPs/PRE_WP26R_AUDIT.md`,
  `WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md`) plus this WP's own untracked brief
  (`WPs/WP31R_Closeout_Test_Startup_Pricing_And_History.md`) — no
  unexpected overlapping change.
- **Generator submodule** HEAD: `303cf394cc0b9839c459d1e56f8784e147e80e9f`,
  branch `main`, remote `origin` =
  `https://github.com/yoavmp/exam-generator.git`, `origin/main` = same SHA.
  `git status --short`: clean.
- `git submodule status`: ` 303cf394cc0b9839c459d1e56f8784e147e80e9f
  exam_generator (heads/main)` — no drift from the outer gitlink.
- `b8e018d90230026ee2a7c79dacd346360664a55b` and `7847aa8` both exist
  locally and on `origin/main`; `7847aa8`'s sole parent is `b8e018d`
  (`git show --no-patch --format='%H %P'`), and `git merge-base
  --is-ancestor b8e018d90230026ee2a7c79dacd346360664a55b 7847aa8` confirmed
  the ancestry. Full reconciliation in §7.

No unexpected overlapping user changes were found in either repository;
proceeded per the WP.

## Part A — the exact misspelling-test root cause and narrow correction

Failing test: `tests/test_wp16r_output_repair.py::test_bad_spelling_only_survives_in_labelled_provenance_or_source`.

Reproducing it first (before any edit) showed **two** unexpected files, not
the one named in the WP's own problem statement:
```
AssertionError: unexpected Olygodendrocytes occurrences:
['WPs/WP28G_ARCHITECT_REPORT.md', 'WPs/WP31G_ARCHITECT_REPORT.md']
```
- `WPs/WP28G_ARCHITECT_REPORT.md:141` — narrative prose citing the
  historical correction mechanism, literally spelling out `` `Olygodendrocytes`
  → `Oligodendrocytes` ``.
- `WPs/WP31G_ARCHITECT_REPORT.md:291` — a second occurrence this WP's own
  problem statement did not anticipate: WP31G's §6 test-results narrative,
  written specifically to *describe this same pre-existing failure*,
  quoted the literal bad spelling to explain what the flagged word was —
  which the audit then flagged as a third occurrence. Self-referential: the
  act of documenting the failure reproduced it.

**Narrow correction (option 1 of the WP: correct ordinary narrative prose
to the approved spelling):** both occurrences are plain narrative prose,
not provenance/audit records — the exact historical spelling is already
preserved canonically, and remains allowlisted, in
`exam_generator/WPs/WP16R_OUTPUT_REPAIR_LEDGER.yaml` and the WP16R reports.
Each was rewritten to drop the literal misspelling and point at that
canonical record instead, so the historical meaning stays fully
understandable without reproducing the flagged string. No file was added
to the test's `allowed_exact` allowlist; the audit's matching/scope was not
touched. Full before/after text and reasoning:
`exam_generator/WPs/WP31RG_ARCHITECT_REPORT.md` §2.

**Proof:** focused test now passes; complete generator suite, serially,
`OPENAI_API_KEY` unset, sockets trapped: **875 passed, 174 skipped, 0
failed, 0 errors** (exit `0`, 271.33s) — exactly the WP31 baseline's 874
passed/1 failed with that one failure fixed (874 + 1 = 875, every other
count unchanged). Full detail, including a note on a local pytest-output
quirk unrelated to this WP, in `exam_generator/WPs/WP31RG_ARCHITECT_REPORT.md` §3.

## Part B — automatic startup pricing refresh

### Call path

`python run.py` → `from src.main import app` (the canonical backend
startup/initialization path — `run.py` is a 3-line wrapper; all real
startup work, including the pre-existing WP18 job-recovery block this
mirrors, lives in `backend/src/main.py`'s module-level code) →
new block in `main.py`, guarded by `should_refresh_at_this_process` →
`src/startup_pricing.refresh_pricing_at_startup()` →
`exam_generator.llm_config.load_llm_config()` (resolves the selected
generation/review model, `gpt-5.6-terra`/`gpt-5.6-terra` in the shipped
config) → `exam_generator.pricing_refresh.load_price_snapshot_cached()` —
the exact function `backend/src/integration/generator_adapter.py` already
opts every real generation call into, reading/writing the exact same
Git-ignored cache file (`EXAM_GENERATOR_PRICING_CACHE_PATH`, same default
path). **No second downloader, parser, cache format, or lock was written.**

### Why it cannot block DB-only startup

`refresh_pricing_at_startup()` never raises: every failure mode (generator
package unimportable, unreadable `llm.yaml`, offline, timeout, malformed
document, wrong/missing model in the fetched table, unwritable cache, or
any other unexpected exception) is caught inside it (or inside
`load_price_snapshot_cached` itself, which already falls back internally)
and turned into one returned string that `main.py` simply prints. The
pre-existing `exam_generator.production._verify_pricing` check — unchanged
by this WP — remains the sole place a missing/incomplete price for the
selected model actually blocks anything, and it only blocks the later LLM
generation call, never DB-only routes (upload, categories, question CRUD,
exam export, etc.), which never call it.

### Duplicate-prevention under the debug reloader

`python run.py` always calls `app.run(debug=True)`, so `src/main.py`'s
module-level code runs **twice** per invocation: once while `run.py`'s
`from src.main import app` executes (before `app.run()` is even called —
Werkzeug's reloader has not re-spawned anything yet), and once more when
`app.run()`'s reloader respawns `python run.py` as a child process with
`WERKZEUG_RUN_MAIN=true`. Because the first pass runs its *entire* blocking
module body (including a possibly slow/timed-out network attempt) before
`app.run()` is even reached, the respawn cannot start until the first
pass's refresh attempt has already fully resolved — so, without a guard,
*both* passes would attempt the same fetch and, on a refresh failure, print
two warnings.

`backend/src/startup_pricing.should_refresh_at_this_process(*, debug,
environ=None)` is the small, independently testable decision that prevents
this: it returns `False` only when `debug` is true and
`WERKZEUG_RUN_MAIN` is not yet set (the pre-respawn "monitor" pass, which
never serves a request) and `True` otherwise — including the respawned
worker (`WERKZEUG_RUN_MAIN == "true"`) and any run that never uses the
reloader at all (`debug` false, e.g. a future production WSGI import), so
the refresh still always happens exactly once per real serving process.
`main.py` sets `app.debug = True` immediately after creating `app` (mirrors
the `debug=True` already hardcoded into both `app.run()` calls in that file
— not a new runtime behavior) purely so this decision can be made before
`app.run()` itself would otherwise set it. This is the standard Werkzeug
`WERKZEUG_RUN_MAIN` reloader-guard idiom, **not a second locking
mechanism** — genuine cross-process fetch/write safety during real
concurrent initialization still comes entirely from
`exam_generator.pricing_refresh`'s own in-process `threading.Lock` plus its
best-effort cross-process `flock`, proven directly by
`test_second_call_after_a_successful_refresh_is_a_zero_network_cache_hit`
(§ below): a first call that performs a real refresh is immediately
followed by a second call that reads the now-fresh cache with **zero**
network calls, exactly reproducing the monitor→worker sequence.

The whole block is additionally skipped whenever `TESTING=true` (matching
the existing `db_filename` branch in the same file), so it can never run
during the backend test suite — which, per `backend/tests/conftest.py`'s
own stated convention, never imports `src.main` anyway.

### New files / changes

- `backend/src/startup_pricing.py` (new) — `refresh_pricing_at_startup()`
  and `should_refresh_at_this_process()`.
- `backend/src/main.py` — `app.debug = True` added right after app
  creation; the new guarded startup-refresh block added after the
  pre-existing WP18 job-recovery block.
- `backend/tests/test_wp31r_pricing_startup.py` (new) — 13 focused, offline
  tests (§ below).

### Required-test evidence

All 13 new tests in `backend/tests/test_wp31r_pricing_startup.py` pass
(`pytest tests/test_wp31r_pricing_startup.py -v` → **13 passed**),
specifically proving every bullet the WP required:

- **Fresh cache → zero network calls**:
  `test_fresh_cache_makes_zero_network_calls` monkeypatches
  `fetch_pricing_markdown` to raise `AssertionError` if ever called, seeds
  a fresh cache, and asserts the returned line says `"fresh cache"`.
- **Stale/absent cache → the injected fake downloader called exactly once,
  valid cache written**: `test_stale_cache_refreshes_exactly_once_and_writes_a_valid_cache`
  and `test_absent_cache_refreshes_exactly_once` each assert a call counter
  on the monkeypatched downloader equals exactly `1`, and that
  `load_price_snapshot(cache_path)` reads back a valid snapshot for the
  selected model afterward.
- **Debug-reloader/concurrent initialization never duplicates the
  refresh**: `test_should_refresh_at_this_process_skips_only_the_reloader_monitor_pass`
  (parametrized over all four `debug`/`WERKZEUG_RUN_MAIN` combinations)
  proves the guard decision itself is correct in isolation;
  `test_second_call_after_a_successful_refresh_is_a_zero_network_cache_hit`
  proves the underlying cache mechanism independently guarantees a second,
  immediately-following call never re-fetches even if the guard were ever
  bypassed.
- **Offline/timeout/malformed-response failure still permits startup with
  one safe warning**: `test_offline_refresh_failure_still_permits_startup_with_one_warning`,
  `test_timeout_refresh_failure_still_permits_startup`, and
  `test_malformed_response_with_no_prior_cache_falls_back_to_bundled` each
  assert the function returns normally (never raises), the line says
  `"bundled fallback"`, and contains **exactly one** `"warning:"` marker.
- **Missing selected-model pricing everywhere → no crash, stays a
  readiness/LLM-operation blocker only**:
  `test_missing_selected_model_pricing_everywhere_does_not_crash_startup`
  monkeypatches the loaded config to select a model priced nowhere in the
  fetched table or the bundled fallback, and asserts the call still returns
  a normal string naming the mismatch rather than raising.
- **Startup never accesses `OPENAI_API_KEY`**:
  `test_startup_never_accesses_openai_api_key` replaces `os.environ` with a
  tracking dict that raises `AssertionError` the moment that specific key
  is read, then calls `refresh_pricing_at_startup()` and asserts it
  completes normally.
- **No test contacts the real pricing site or a provider**: every test
  above monkeypatches `exam_generator.pricing_refresh.fetch_pricing_markdown`
  directly for any path that could reach the network; the suite-wide
  `_wp18_no_network` autouse fixture in `backend/tests/conftest.py` traps
  any real socket connection as a defensive backstop regardless.

## Part C — reconciling `b8e018d…` / `7847aa8`

Both SHAs are correct; they name two different commits, confirmed by
direct Git inspection (not guessed):

- `b8e018d90230026ee2a7c79dacd346360664a55b` — the **WP31 implementation
  commit** ("WP31: credential circuit breaker, pricing cache wiring,
  CORS/editing fix, single terminal summary"). `WPs/WP31_ARCHITECT_REPORT.md`
  §9 names this as "the outer commit" — correct for what *implements* WP31.
- `7847aa85915f915e13cbc78dc0fcb31be4ba9240` — a later, **WP31 finalization
  commit** ("WP31: record final commit SHA and push outcome in architect
  report"), confirmed to be `b8e018d`'s **direct child** (`git show
  --no-patch --format='%P' 7847aa8` → exactly `b8e018d…`; `git merge-base
  --is-ancestor` confirms the ancestry). `git show --stat 7847aa8` shows it
  touches only `WPs/WP31_ARCHITECT_REPORT.md`, inserting the paragraph that
  records `b8e018d`'s own SHA/push outcome — the standard WP convention
  that a commit cannot truthfully contain its own SHA, so that bookkeeping
  is always a dedicated follow-up commit.

Because `7847aa8` is a real commit on `main`, it — not `b8e018d` — was the
actual `origin/main` HEAD once WP31 finished (confirmed: this WP's own
pre-flight `git rev-parse HEAD` / `origin/main` both read `7847aa8`
directly off the remote before any WP31R edit was made). The owner-facing
completion summary naming `7847aa8` and the architect report's §9 naming
`b8e018d` are therefore **both accurate** — one names the implementation
commit, the other the actual final commit that documents it and became the
true remote HEAD. `7847aa8` is neither missing nor unrelated; no mapping
was invented.

Dated correction notes (preserving the original text, not deleting the
discrepancy) were added to:
- `WPs/WP31_ARCHITECT_REPORT.md` §9 (immediately after the paragraph it
  clarifies).
- `WPs/ARCHITECT_HANDOFF.md` (top summary section).

## Verification (run in this order, all in the foreground)

1. Focused generator spelling-audit test: **1 failed → 1 passed** (before
   / after the fix).
2. Focused backend pricing-startup tests:
   `pytest tests/test_wp31r_pricing_startup.py -v` → **13 passed**.
3. Complete generator suite, serially, `OPENAI_API_KEY` unset, sockets
   trapped: **875 passed, 174 skipped, 0 failed, 0 errors**, exit `0`,
   271.33s.
4. Complete backend suite, serially, `OPENAI_API_KEY` unset, sockets
   trapped: **334 passed, 0 failed, 0 errors**, exit `0`, 282.49s.
   (An earlier attempt at this same run, launched concurrently with the
   still-running full generator suite in the background, surfaced 3
   failures — `test_wp21_analytics_and_exports.py::test_failed_replace_llm_leaves_analytics_unchanged`,
   `::test_analytics_never_reaches_generator_context`, and
   `test_wp26r_snapshot_immutability.py::test_llm_replacement_snapshot_reflects_fixed_target_category`.
   All 3 passed individually and the backend suite was re-run alone,
   clean, immediately after — the exact resource-contention pattern
   `WPs/WP31_ARCHITECT_REPORT.md` §6 already documented for this machine
   when two full suites compete for the same CPU/filesystem, not a defect
   in any changed code. The count reported above, **334 passed, 0
   failed**, is from that clean, isolated, foreground re-run, whose exit
   code was confirmed `0` directly (not through a piped `tail`, which
   silently discards the piped command's own exit status — the mistake
   that made the first, contended run look superficially "exit 0" despite
   3 failures).)
5. Frontend suite / production build: **not re-run.** No frontend file
   changed this WP — `git status --short` / `git diff --stat` for this
   commit touch only `backend/`, `exam_generator` (gitlink), and `WPs/`;
   nothing under `frontend/`. Re-running an unrelated suite would not add
   evidence.
6. Free startup-refresh smoke test, `OPENAI_API_KEY` unset, a temporary
   `/tmp` cache path (never the real runtime cache), the real official
   pricing URL, run as a standalone script (never a collected test, per
   the same convention `WPs/WP31_ARCHITECT_REPORT.md` §2 already
   established for WP31 Part B's live smoke check):
   **duration 0.565s; selected model `gpt-5.6-terra`; outcome
   `pricing startup: refreshed (model='gpt-5.6-terra',
   verified_at=2026-10-17 (0d old))`; cache written: yes.** The downloaded
   document's contents were never printed — only this one summary line.
7. Second start against that same fresh cache, same script, counting real
   calls to `fetch_pricing_markdown`:
   **duration 0.096s; outcome `pricing startup: fresh cache
   (model='gpt-5.6-terra', verified_at=2026-10-17 (0d old))`; network fetch
   calls: 0.** Proves the startup refresh, once successful, turns the next
   start into a true cache hit.

Both temporary smoke-test scripts and the `/tmp` cache directory they used
were deleted after the run; nothing from them was committed.

## Every changed file

Outer (`questions-db`):
- `backend/src/main.py` — `app.debug = True`; new guarded startup
  pricing-refresh call (Part B).
- `backend/src/startup_pricing.py` (new) — Part B's small, testable
  startup function.
- `backend/tests/test_wp31r_pricing_startup.py` (new) — Part B's 13
  required tests.
- `backend/src/integration/generator_pin.py` — `EXPECTED_GENERATOR_PIN` /
  `..._LABEL` advanced to the generator's new WP31RG commit (required
  because the generator changed; see Git/delivery ordering below).
- `WPs/WP31_ARCHITECT_REPORT.md` — dated correction note added (Part C).
- `WPs/ARCHITECT_HANDOFF.md` — dated correction note + WP31R summary added
  (Part C).
- `WPs/WP31R_ARCHITECT_REPORT.md` (new) — this report.
- `WPs/WP31R_Closeout_Test_Startup_Pricing_And_History.md` — the WP brief
  itself, committed alongside the report per the established convention
  (e.g. WP29/WP30's own brief docs were committed the same way); it is not
  one of the three pre-existing owner audit files this WP was told to
  leave untracked.
- `exam_generator` gitlink — advanced to `e0cf4bfca3f5febb77b47fe58264c15cd9947798`.

Generator (`exam_generator`, pushed separately first — see below):
- `WPs/WP28G_ARCHITECT_REPORT.md`, `WPs/WP31G_ARCHITECT_REPORT.md` — narrow
  narrative-prose corrections (Part A).
- `WPs/WP31RG_ARCHITECT_REPORT.md` (new) — generator-side report.
- `WPs/ARCHITECT_HANDOFF.md` — "latest completed WP" line refreshed.

Left deliberately untouched and untracked, per the WP: `WPs/PRE_WP25_LATEST_EXAM_REVIEW.md`,
`WPs/PRE_WP26R_AUDIT.md`, `WPs/PRE_WP28_EXAM_258FFEF8_AUDIT.md`.

## Commits, push status, final submodule pin, final Git status

- **Generator**: committed `e0cf4bfca3f5febb77b47fe58264c15cd9947798`
  ("WP31RG: restore a fully green suite (fix spelling-audit narrative
  prose)"), branch `main`. Pushed to `origin`
  (`https://github.com/yoavmp/exam-generator.git`) **before** the outer
  gitlink was advanced; `git ls-remote origin main` confirmed
  `e0cf4bf…` landed on the remote. `git status --short` in the submodule
  after: clean.
- **Outer**: gitlink advanced to `e0cf4bfca3f5febb77b47fe58264c15cd9947798`;
  `backend/src/integration/generator_pin.py::EXPECTED_GENERATOR_PIN`
  updated to match (confirmed equal to the submodule's actual `HEAD`;
  `backend/tests/test_wp18_readiness.py` re-run green against it, 6
  passed).
- Outer commit: *(recorded in the final response to the owner below, per
  the WP's own rule that a commit cannot truthfully contain its own SHA —
  no follow-up documentation-only commit was created solely to record it;
  the owner's closing terminal response is the authoritative record, same
  as this WP's own Part C reconciliation explains)*.
- Pushed to `origin` (`https://github.com/yoavmp/questions-db.git`),
  branch `main`, no force-push, no rebase.
- Final `git status --short` in the outer repo: clean apart from the three
  pre-existing untracked owner audit files listed above.

## Deviations, unresolved risks, owner decisions needed

- **`should_refresh_at_this_process`'s "no reloader" branch is currently
  unexercised by this app's real entrypoint.** `run.py` always calls
  `app.run(debug=True)`, so in actual use the function's `debug=False`
  branch (always refresh, no reloader to worry about) never fires today;
  it exists so a future non-debug/production WSGI entrypoint still gets
  the refresh exactly once rather than silently never. If the owner adds
  such an entrypoint, worth re-confirming this guard still behaves as
  intended against it.
- **A local `pytest -q` output quirk** (full detail:
  `exam_generator/WPs/WP31RG_ARCHITECT_REPORT.md` §3) occasionally omits
  the final one-line pass/fail summary from captured stdout on this
  machine's pytest/CPython combination, even though the run completes
  normally with exit code `0`. Not a defect in this WP's changes; worked
  around here with `-p no:cacheprovider --no-header -ra` for the
  authoritative counts. Mentioning it so a future WP does not mistake a
  missing summary line for a hang or a swallowed failure.
- No other deviation or unresolved risk. Every required suite finished
  with a known, clean exit code before being described as passing.
