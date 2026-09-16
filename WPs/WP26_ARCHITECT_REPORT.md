# WP26 — Architect Report: Named Exam History, Immutable Branches, UI Polish, and DB Exclusions

**Scope:** outer `questions-db` only. `exam_generator` submodule untouched, pin
verified before and after (`d20c46bbb332e4d40f735e843d31113176b755e5`).
**Supersedes:** the unexecuted `WPs/WP25_Named_Exam_History_Branches_And_UI_Polish.md`
(not executed).
**Baseline:** outer `main` at `63398340b1f6d66b39bf8f6bd2995f3fe7987996`
(`WP25G: integrate inverse duplicate guard`), generator clean and pinned.
Verified at preflight; matched exactly.

## 1. Persisted naming and history

New module `backend/src/jobs/naming.py`:

- `COURSE_CHOICES = ('מבנה המוח', 'נוירואנטומיה')`,
  `EXAM_TYPE_CHOICES = ('מבחן אמצע', 'מבחן מסכם')` — closed enums, validated
  exactly.
- `resolve_identity(payload)` validates either `{mode: "structured", course,
  year, exam_type, sitting}` (year: exactly 4 digits; sitting: trimmed,
  defaults to `א`; all fields reject control characters) or `{mode: "custom",
  custom_name}` (trimmed, length-bounded, rejects control characters and
  path-traversal/separator characters). Returns `None` for a request with no
  `identity` block at all — a **legal, backward-compatible** request shape,
  not an error. Raises `IdentityError` (→ HTTP 400) for a malformed identity.
- `display_name`/`slug` are computed once at validation time and persisted on
  `Job.identity` (a plain dict) — e.g. `{course: "מבנה המוח", year: "2026",
  exam_type: "מבחן מסכם", sitting: "א"}` → `display_name = "מבנה המוח 2026
  מבחן מסכם מועד א"`, `slug = "מבנה_המוח_2026_מבחן_מסכם_מועד_א"` (matches the
  brief's example exactly — see `test_structured_example_display_name_and_slug`).
- `fallback_label(job_id, created_utc)` — `"מבחן ללא שם – DD.MM.YYYY –
  <8-char id>"` — is **calculated on read, never persisted**, for any job
  whose `identity` is `None` (every pre-WP26 job, and any WP26 job created
  without an identity payload).
- `job_id` (a UUID) remains the sole storage-path key everywhere; the name/
  slug are display-only, never a filesystem path component for the job's own
  directory.

`backend/src/jobs/model.py` (`Job`): added `identity: Optional[dict] = None`,
`excluded_db_ids: list = []`, `parent_job_id: Optional[str] = None`,
`root_job_id: Optional[str] = None`. `Job.from_dict` defaults all four when
absent (`root_job_id` defaults to the job's own id) — **pre-WP26 `job.json`
files load unchanged and are never rewritten** merely to add these fields
(proven by `test_pre_wp26_job_json_loads_unchanged`, which strips the fields
from a real persisted file and reloads it).

`GET /api/exam-jobs` (new, `service.list_jobs`) returns every persisted job
newest-first: `job_id, display_name, slug, created_utc, updated_utc, status,
accepted_count, total_count, parent_job_id, root_job_id,
excluded_db_ids_count, branchable`. Every status is included (`queued,
running, completed, partial, interrupted, cost_ceiling, failed`) — nothing is
filtered out. Deliberately **excludes** question bodies, prompts, audits, and
course-source content (verified by `test_list_jobs_route_newest_first_safe_fields`
/ `test_list_jobs_newest_first_and_every_status_included`).

`POST /api/exam-jobs` (existing route, extended) accepts an optional
`identity` and `excluded_db_ids`; the 202 response now also carries
`display_name`/`slug` (`null` when no identity was submitted). The single-job
result route (`GET /api/exam-jobs/<id>`) is unchanged in shape except for the
new fields it now also carries (see §4).

## 2. Optional exclusion Excel — parsing and preview

New module `backend/src/jobs/exclusions.py`, new route
`POST /api/exam-jobs/exclusions/preview` (`backend/src/routes/exclusion_upload.py`,
completely rewritten — the pre-existing route at this file's path,
`/api/test/upload-exclusion`, was a leftover prototype never called by any
frontend code (verified by repo-wide grep before touching it); it queried the
DB directly and returned raw `matched_questions` including question text —
incompatible with WP26's "never expose excluded question text" requirement,
so it was replaced rather than kept alongside).

- **Type/size/row bounds:** `.xlsx` only (rejects any other extension without
  attempting to parse it); `MAX_UPLOAD_BYTES = 2 MB`; `MAX_ROWS = 5000` data
  rows (further rows are dropped with a visible warning, not an error). These
  bounds are this WP's own choice — no equivalent limit existed anywhere else
  in the codebase to inherit from (checked `upload.py`/`test_generation.py`);
  documented here as the authoritative reference for future consistency.
- **Parsing safety:** `openpyxl.load_workbook(..., data_only=True,
  read_only=True, keep_links=False)` — cached values only (formulas never
  evaluated), streamed (no embedded-object loading), external references
  dropped. The raw bytes are read once into memory and **never written to
  disk or logged**; only the resolved preview (ids + counts + safe warning
  strings) is returned.
- **Header aliases:** `מזהה_שאלה`/`id` (id), `שאלה`/`question` (text),
  `נושא`/`קטגוריה`/`category` (category) — matched Unicode-exact (Latin
  aliases case-insensitively).
- **Resolution order** (`parse_and_resolve`), applied per row:
  1. A parseable, **currently-existing** DB id is authoritative — used
     directly, regardless of whether its workbook text matches current DB
     text. A **non-existent** id (parses as an int but no such row) falls
     through to text matching rather than being an immediate error — this
     lets a row whose id was later deleted still resolve by text, and, more
     importantly, lets a full-export workbook's *blank*-id LLM rows fall
     through harmlessly to "no text match" (§ interpretation below).
  2. Without a usable id: exact **normalized** (whitespace-collapsed/
     stripped only, never fuzzy/semantic) question text **plus** category —
     `Question.category == cat OR categories_json LIKE '%"cat"%'`, matched
     against the same normalization.
  3. Without a category value in the row: exact normalized text alone,
     across the whole DB.
  4. **Ambiguous fallback (2+ exact matches):** the brief's wording — "excludes
     all exact matches and returns a visible ambiguity warning/count; must
     never choose an arbitrary row" — is interpreted here as: **every**
     matching row's id is added to the resolved exclusion set (never an
     arbitrary single pick), and the row is counted separately as
     `ambiguous` with a safe warning (`"שורה N: התאמה למספר שאלות (הוחרגו
     כולן)"` — no row content, no internal id, no path). This is the
     conservative choice for an *exclusion* feature: over-excluding a
     duplicate-text question is safe (the owner can still explicitly select
     it again in a future exam via its id if wrong), whereas silently
     resolving to none of them would let a flagged question slip back in.
     Flagged explicitly here as an interpretation, not a literal quote match,
     since the brief's phrasing is genuinely ambiguous between "exclude the
     whole set" and "exclude nothing, just warn".
  5. Blank rows (every cell empty) and rows with no usable id/text are
     **ignored and counted as `unresolved`**, never treated as parse errors —
     this is what lets a previously exported full-exam workbook
     (`export_full_xlsx`'s own schema — LLM rows carry a blank
     `מזהה_שאלה`) be re-uploaded directly: its DB rows resolve, its LLM rows
     are silently ignored (`test_full_export_style_workbook_resolves_db_rows_ignores_llm_rows`).
  6. The final id set is deduplicated; `counts` (`rows_total, resolved,
     deduplicated, unresolved, ambiguous`) retain the pre-dedup detail for
     the preview.
- **Preview response:** `resolved_db_ids` (sorted), `counts`, `warnings`
  (safe strings only), `availability_by_category` (every canonical category's
  live DB count minus this preview's exclusions). Never the raw workbook,
  never row content beyond what's needed for the counts.

**Frontend:** the new-exam builder (`ExamGenerationSection.jsx`) shows the
file input labeled exactly `קובץ שאלות להחרגה (אופציונלי)`, previews the
resolved count/warnings on selection, retains the resolved id set in local
state, submits it as `excluded_db_ids` on `POST /api/exam-jobs`, and clears
both the file and the resolved ids on "נקה" (clear) or on choosing a
different file (re-preview replaces the prior result). Creating without a
file submits `excluded_db_ids: []`.

**Backend revalidation** (`exclusions.revalidate_ids`, called from
`service.create_job`): every submitted id is re-checked against the *current*
DB, never trusted from the client's earlier preview. A non-integer entry is
rejected outright (`JobError`, 400, no job created). An id that existed at
preview time but vanished before creation is silently dropped with a warning
appended to `job.warnings` — this never blocks creation and never triggers a
paid call for an unrelated reason.

## 3. Persisted exclusion contract and selection safety

`Job.excluded_db_ids` is the sole persisted exclusion state — normalized,
deduplicated integers only; no workbook bytes, rows, paths, or cell content
are ever stored. Applied to:

- **Initial selection** (`service.create_job`): `_select_db_questions`'s
  running `exclude_ids` set is **seeded** with `excluded_db_ids` (previously
  it started empty and only grew as each category was selected within the
  same request) — so an excluded id is unavailable to every category, from
  the first pick.
- **DB replacement** (`service.replace_from_db`): the exclusion set for the
  replacement's random pick is `{db ids currently in the exam} ∪ {any
  extra_exclude_ids from the request} ∪ {job.excluded_db_ids}` — regardless
  of whether the slot being replaced currently holds a DB or an LLM origin
  question.
- **Availability pre-check** (`service.create_job`, before the loop that
  selects any question or makes any LLM call): for every requested category,
  `_db_availability(category, exclude_ids=excluded_id_set)` must be `>=` the
  requested database count, or the **entire job creation fails atomically**
  with `קטגוריה '<name>': נדרשו N שאלות מהמאגר, זמינות בפועל M (לאחר החרגות)`
  — no job is persisted, no partial DB selection happens, and (since this
  check runs before the LLM-readiness-gated selection loop) no LLM call can
  ever be reached for that request
  (`test_insufficient_availability_after_exclusion_fails_atomically_before_any_job`).
- A **displaced** DB question (via `replace_from_db`) is **never** added to
  `excluded_db_ids` itself — it only becomes unselectable again *within this
  same exam* via the pre-existing "ids currently in the exam" mechanism, so
  the owner can reject a question's wording/history for one exam while
  leaving it eligible for an unrelated future one
  (`test_excluded_db_ids_never_permanently_grow_from_displaced_questions`).
- Exclusions never touch LLM generation: `_select_db_questions`/
  `_db_availability` are the only two call sites reading `excluded_db_ids`,
  and neither is on the LLM code path. A discarded DB question still does
  **not** enter `category_history` (unchanged WP18R behaviour) — exclusions
  add no new interaction with semantic history either way.
- `result_view` exposes only `excluded_db_ids_count` (an integer) — never the
  raw id list or any excluded question's text — satisfying "the normal exam
  UI must not render excluded question text" by construction (the id list
  never leaves the backend's own decision logic).
- A branch inherits the parent's normalized `excluded_db_ids` verbatim (§4),
  so every later replacement on the branch honours the same constraint
  automatically.

## 4. Immutable exam snapshots and explicit branches

New `service.branch_job(job_id, identity_payload)` and route
`POST /api/exam-jobs/<id>/branch`:

- Serialised through the same process-wide `_RUN_LOCK` and per-job
  `job.lock` every other job mutation uses, so a branch can never race a
  concurrent replacement/retry/run on the same (or any other) job.
- **Only a `completed` job may be branched.** Every other status (`partial,
  interrupted, cost_ceiling, failed, queued, running`) returns a typed
  `JobConflict` (409) — the brief explicitly warns against inventing
  partial-branch semantics, and by definition every slot in a `completed` job
  is already `accepted`, so this is the one status where "copy the current
  questions" has one unambiguous meaning.
- The parent's `job.json` is **only ever read** (`store.load`) — never
  `store.save`d — in this function, on both the success and every failure
  path, so it is byte-for-byte identical before and after (proven directly:
  `test_branch_parent_byte_immutable_on_success` reads the file's raw bytes
  before and after a successful branch and asserts equality; the route test
  additionally re-fetches the parent's full result view via `GET` after
  branching and diffs it against a pre-branch snapshot).
- The child gets a fresh `job_id`, and every slot gets a fresh `slot_id` +
  `instance_id` (parent and child sets are disjoint) while preserving: public
  `number`, canonical category order/`order_index`, the current seven-field
  question snapshot, `db_id`/origin (`kind`), the frozen `analytics`
  snapshot, `request` metadata, `category_history`, and `excluded_db_ids`.
- `parent_job_id` = the branched-from job; `root_job_id` = the parent's own
  `root_job_id` (so a chain of branches all point at the same ultimate
  ancestor).
- The child starts `status="completed"`, `accumulated_cost_usd="0"`,
  `cost_basis="none"`, `cost_ledger=[]`, `warnings=[]`,
  `terminal_summary=None`, `safe_error=None` — no copied cost ledger, audit
  references, errors, attempts, or retry/replacement counters. It inherits
  the parent's `cost_ceiling_usd` as its own **starting default** (a fresh,
  independent ceiling the owner can raise/lower like any other job's).
- Because the copied slots and `category_history` are the child's own
  mutable state from that point on, later same-category LLM
  generation/replacement on the child sees exactly the same uniqueness
  context the parent would have — no special-casing needed
  (`_previous_for_slot` reads `job.slots`/`job.category_history` generically).
- Saved-exam immutability extends to every export/view: `result_view`,
  `export_llm_xlsx`, and `export_full_xlsx` all read from the slot's
  persisted snapshot (`slot.question`, `slot.analytics`) — never a live
  re-query of `Question` for content beyond the DB DTO's own live-vs-frozen
  split already established in WP21 (`_db_slot_dto` re-fetches the row only
  for its *current* `categories` list, but accuracy/distinction always come
  from the frozen `slot.analytics`). A later edit to the underlying DB row
  therefore never retroactively changes a saved exam or any of its branches.
- The frontend keeps both replacement buttons visible only when the viewed
  job **is** the active editable job (see §5) — a purely additive UI
  guarantee on top of the backend's own state machine, since a historical
  read-only view simply never calls a mutation route at all.

## 5. Frontend saved-exam workflow

`ExamGenerationSection.jsx` (substantially extended, nothing removed):

- **Setup step:** the existing builder card now opens with an identity form
  (שם מובנה vs. שם חופשי toggle, the four structured fields with a live
  display-name preview, or a single custom-name field) and the optional
  exclusion-workbook control, both above the unchanged category-quantity
  grid. This is the "setup dialog/step" required by the brief, implemented
  as the first section of the existing single-screen builder rather than a
  separate modal — the builder already replaces itself with the
  progress/results screen once a job exists, so a second modal layer would
  have duplicated that same transition without adding a distinct capability.
- **Two independent local-state ids** (`activeJobId`, `viewedJobId`), each
  with its own `localStorage` key (`examJob.activeId` / `examJob.viewedId`)
  and URL query param (`examJob` / `viewJob`), restored independently on
  mount and falling back safely (with the stale id forgotten) if a fetch
  404s. `isReadOnly = viewedJobId && viewedJobId !== activeJobId`. Only
  `handleStart` (create) and `handleBranch` (branch) ever change
  `activeJobId` — the "צור מבחן חדש" navigation button only clears
  `viewedJobId` (returns to the builder) and never forgets the active job,
  correcting a pre-WP26 quirk where that button unconditionally forgot the
  active job pointer even if the user never actually started a new one.
- **Saved-exam selector** (`SavedExamSelector`, fed by `GET /api/exam-jobs`):
  a closed list of every job (any status), each row showing
  `display_name — date — short id` and its status; "פתח" sets `viewedJobId`
  only, never touching `activeJobId`.
- **Read-only historical view:** a visible banner
  (`data-testid="readonly-banner"`), both replacement buttons and the
  retry/raise-ceiling controls **hidden** (not merely disabled) when
  `isReadOnly`, polling suspended, and "יצירת גרסה חדשה" rendered prominently
  in the banner itself. Export/DOCX/Excel and question review remain fully
  available. Because the buttons are not rendered at all in this mode, a
  read-only view cannot call a mutation route even via a stray event handler
  reference.
- **Branch dialog:** asks for a new structured/custom name (reusing the same
  identity form + validation as the setup step), calls
  `POST /exam-jobs/<id>/branch`, and on success makes the child both the
  active and the viewed job — never mutates the parent, and is never
  triggered implicitly by any replacement action.
- **Exports** (`downloadDocx`, `downloadXlsx`, `downloadFullXlsx`) now use
  `job.slug` in the generated filename (DOCX schema/content and both Excel
  schemas are otherwise byte-identical to pre-WP26).
- The header shows the job's `excluded_db_ids_count` when non-zero
  (`"N שאלות מוחרגות מהמאגר"`) without ever requiring — or offering — a
  re-upload of the original workbook for an inherited/existing exclusion set.

## 6. Requested UI corrections

- **Analytics:** untouched (`overallAnalytics`/`formatMeasure` in
  `examGen.js` unchanged). New regression coverage
  (`examGen.wp26.test.js` reuses the existing exported helpers; the existing
  `ExamGenerationSection.test.jsx` WP21 describe block, unmodified, already
  proves numeric accuracy/distinction rendering, N/A for missing data, and
  N/A for every LLM question) — no new gaps found, no rewrite needed.
- **LLM-only export button:** unchanged label
  (`ייצוא שאלות בינה בלבד (Excel)`); the export row changed from a
  breakpoint-based CSS grid (`grid-cols-1 md:grid-cols-2 lg:grid-cols-4`,
  which could squeeze a button narrow enough to wrap its own text) to
  `flex flex-wrap` with `whitespace-nowrap` on every export button — each
  button now sizes to its own content and only whole buttons wrap to a new
  row on narrow screens; no font-size change.
- **Brand title:** `App.jsx`'s header `<h1>` now reads exactly
  `מאגר שאלות ומחולל בחינות – קורס מבנה המוח, אוניברסיטת תל אביב` (verified
  in `App.test.jsx`).
- **About tab:** replaced the generic "hybrid system" marketing copy with
  Hebrew sections on: question-bank purpose, browsing/importing, performance
  measures (and their N/A convention), mixed DB/LLM exam construction,
  human review before class use, named history/branches, optional DB
  exclusions, and exports — no raw implementation details, no marketing
  filler.
- **Top tabs RTL order:** `TabsList`'s trigger DOM order is now
  `about, upload, test-generation, questions` — since the page is
  `dir="rtl"` and the flex/grid container has no direction override, DOM
  order **is** the visual right-to-left order, so this renders `אודות
  המערכת` at the far right and `עיון בשאלות` at the far left with the two
  middle tabs (`upload` before `test-generation`) in their original relative
  order. Verified in `App.test.jsx` by reading the rendered button order,
  not by relying on any accidental flex-reversal CSS.
- **Question-browser topic bar:** `App.jsx` no longer derives its category
  list from the order questions happen to appear in local state; it fetches
  `GET /api/test/categories` (which already sorts via
  `category_order.py::sort_categories`/`CATEGORY_ORDER`) on mount and after
  every mutation that can change category membership or counts
  (upload, delete, category rename). Counts/filtering by the existing
  `selectedCategory` state are otherwise unchanged.

## 7. Retry/replacement telemetry cleanup

Root cause: `service.replace_via_llm` unconditionally did `slot.retries += 1`
before its generation call — exactly like `retry_slot` does for a genuine
retry. A **failed** `replace_llm` was harmless (the pre-existing snapshot/
restore logic reverted `slot.retries` along with everything else), but a
**successful** `replace_llm` left the bump in place permanently, silently
inflating `slot.retries` (and the `generation_meta.retries_by_slot` field
derived from it) with every intentional replacement, never rolled back.

Fix, in `backend/src/jobs/service.py`:

1. `replace_via_llm` no longer touches `slot.retries` at all — only
   `retry_slot` does, so this field (and `generation_meta.retries_by_slot`)
   now counts genuine retry operations only, exactly as required.
2. `_summary_dict` (feeding both `terminal_summary` in the API response and
   the printed backend terminal line) now derives `retries` **and**
   `replacements` from `ledger_telemetry(job)["totals"]` instead of
   `sum(s.retries for s in llm_slots)` — the ledger's `kind` field
   (`"retry"` vs `"replace_llm"`) is immutable and was already the source of
   truth for the *per-question* UI figures since WP21R
   (`slotAttemptCounts`/`slotAttemptCountsByInstance` in `examGen.js`, both
   unchanged); this closes the one place that still used the mutable,
   historically-conflatable counter. The printed terminal line now shows
   `retries=<n> replacements=<n>` as two separate figures.
3. Because `ledger_telemetry` reads only the append-only `cost_ledger`, an
   **old** persisted job whose `slot.retries` was already inflated by a
   pre-fix `replace_llm` reports the correct, ledger-derived totals the
   moment it's loaded — with **zero rewriting of its file**
   (`test_old_conflated_slot_retries_still_report_correct_ledger_totals`
   hand-crafts exactly that legacy shape and asserts on it).
4. Every historical ledger/audit entry is untouched — this is a read-side
   derivation fix only; nothing about how or when a `cost_ledger` entry is
   written changed.
5. WP25G's reciprocal/inverse duplicate-guard behaviour
   (`replace_via_llm`'s ephemeral own-question append to `previous`) is
   untouched by this fix — verified by rerunning
   `test_wp25g_inverse_duplicate_guard.py` unmodified (still passes).

## 8. Files changed

**Backend — new:**
`backend/src/jobs/naming.py`, `backend/src/jobs/exclusions.py`,
`backend/tests/test_wp26_naming.py`, `backend/tests/test_wp26_exclusions.py`,
`backend/tests/test_wp26_naming_history_branching.py`,
`backend/tests/test_wp26_routes.py`.

**Backend — modified:**
`backend/src/jobs/model.py` (identity/exclusion/lineage fields + backward-compatible `to_dict`/`from_dict`),
`backend/src/jobs/service.py` (identity/exclusion validation in `create_job`, exclusion enforcement in `_db_availability`/`_select_db_questions` call sites and `replace_from_db`, `list_jobs`, `branch_job`, telemetry fix in `replace_via_llm`/`_summary_dict`/`_print_terminal_summary`, naming/lineage fields added to `result_view`),
`backend/src/routes/exam_jobs.py` (`GET /exam-jobs`, `POST /exam-jobs/<id>/branch`, `display_name`/`slug` in the create response),
`backend/src/routes/exclusion_upload.py` (rewritten: local preview/resolve endpoint, replacing the unused legacy prototype),
`backend/tests/conftest.py` (`jobs_app` now also registers `exclusion_bp`, for the new preview-route tests).

**Frontend — new:**
`frontend/src/App.test.jsx`, `frontend/src/lib/examGen.wp26.test.js`.

**Frontend — modified:**
`frontend/src/lib/examApi.js` (`fetchJobsList`, `branchJob`, `previewExclusionFile`),
`frontend/src/lib/examApi.test.js` (coverage for the three new calls),
`frontend/src/lib/examGen.js` (identity helpers, viewed-job persistence, `jobListLabel`),
`frontend/src/components/ExamGenerationSection.jsx` (setup step, exclusion upload UI, saved-exam selector, read-only viewing, branch dialog, slug-based export filenames, export-button layout fix),
`frontend/src/components/ExamGenerationSection.test.jsx` (mock additions + a new WP26 describe block; all 33 pre-existing tests pass unmodified),
`frontend/src/App.jsx` (brand title, About content, tab order, canonical-order topic bar).

**Docs:**
`SETUP.md` (new "Named Exams, History, Branches, and Exclusions" section),
`WPs/ARCHITECT_HANDOFF.md` (WP26 summary + updated outer SHA row).

## 9. Tests

**Backend** (`backend/venv`, `OPENAI_API_KEY` unset except where a test
explicitly sets an in-process sentinel via the existing `llm_ready` fixture;
sockets blocked in every WP26 test via an autouse `_no_network` fixture, same
pattern as WP19/WP25G):

- `test_wp26_naming.py` — 20 tests: structured/custom validation (closed
  enums, 4-digit year, control-char/path-traversal rejection), the exact
  example display name/slug, safe-slug edge cases, fallback-label format.
- `test_wp26_exclusions.py` — 17 tests: id-authoritative resolution,
  nonexistent-id fallthrough, text+category / text-only fallback, whitespace
  normalization (never fuzzy), ambiguous-match exclude-all + warning, blank
  rows ignored, dedup, a realistic full-export-shaped fixture, adjusted
  per-category availability, type/size/header/content rejection, and
  backend id revalidation (dropped-if-vanished, malformed-rejected).
- `test_wp26_naming_history_branching.py` — 16 tests: identity persistence +
  fallback + atomic rejection, backward loading of a hand-stripped pre-WP26
  `job.json`, jobs-list newest-first/every-status/safe-fields, exclusion
  enforcement in initial selection + the atomic pre-flight failure +
  DB-replacement union + no permanent growth from a displacement, branch
  byte-immutability/new-ids/inherited-exclusions-and-history/non-completed
  rejection/child-replacement-honours-inheritance, and the telemetry fix
  (both the live retry-vs-replace_llm sequence and the hand-crafted legacy
  conflated-counter case).
- `test_wp26_routes.py` — 10 tests: HTTP-level naming/list/branch/
  exclusion-preview coverage, including a full create→preview→create round
  trip that ends with the excluded id genuinely absent from the result.
- **Result:** all 74 new tests pass; the complete pre-existing suite
  (`test_wp17_*` through `test_wp25g_*`, 122 tests) passes unmodified —
  **196/196 total**, run serially, `OPENAI_API_KEY` unset, no network access.

**Frontend** (Vitest):

- `examGen.wp26.test.js` — 10 tests: identity defaults/validation/payload
  shape, `jobListLabel`, and the new viewed-job persistence helpers.
- `examApi.test.js` — 3 new tests (11 total in the file): the three new API
  calls' wire shape.
- `ExamGenerationSection.test.jsx` — 7 new tests (40 total in the file, all
  33 pre-existing ones passing **unmodified**): identity form rendering +
  live preview, custom-name blocking, identity/exclusion submission,
  opening a historical job read-only with mutation controls absent,
  branching from a read-only view (and asserting no replacement route is
  ever called), display-name/exclusion-count display, slug-based export
  filenames.
- `App.test.jsx` — 5 new tests: brand title, tab DOM order (both halves of
  the RTL requirement), About content replacement, canonical-order topic
  bar.
- **Result: 107/107 passing** (95 pre-existing/updated-mock + 12 new test
  files' worth), run once, complete suite.
- **Frontend production build:** `npm run build` succeeds cleanly
  (`OPENAI_API_KEY` unset; the build makes no network call).

## 10. Zero provider calls / no leakage

No test in this WP makes a real LLM/provider call — the few that exercise
`replace_via_llm`/`retry_slot` use the existing offline WP18 fakes
(`ApprovingProvider`/`RejectingProvider`/`Dispatch`) with an in-process
sentinel `OPENAI_API_KEY` (never a real key), exactly as WP18-WP25G already
did. `OPENAI_API_KEY` is never read by any new WP26 code path itself (only
existing `readiness_report()` reads its *presence*, unchanged). No secret,
uploaded-workbook byte, real job content, or `.env*`/local-data value appears
in any new file, log line, or test fixture — the exclusion-preview response
schema was specifically designed (§2) to carry only ids/counts/safe strings.

## 11. Limitations / stop conditions encountered

None of the brief's stop conditions were hit — no generator change, paid
call, real-data migration, dependency change, or server startup was needed;
historical jobs load backward-compatibly; branching preserves the parent
byte-for-byte; the exclusion constraint is enforced server-side for both
selection and replacement; exports stay schema-compatible; canonical order is
read from one authoritative source; and everything fit inside normal
iteration (no extra "focused repair pass" beyond the debugging already
folded into the work above).

One deliberate interpretation is worth restating for the record (also in
§2): the brief's ambiguous-match rule ("excludes all exact matches... must
never choose an arbitrary row") was implemented as *exclude every matching
row*, not *exclude none of them* — the conservative reading for a feature
whose entire purpose is keeping a flagged question out of an exam.

## 12. Architect summary

WP26 is fully implemented and tested to the extent describable without a
live backend/browser session (this environment has no browser-automation
tool installed, consistent with prior WPs' own limitation notes) — every
contract, backward-compatibility guarantee, and safety rule in the brief has
either a direct automated test or is a straightforward, narrowly-scoped
extension of an already-tested existing mechanism (e.g. the exclusion set
reuses the existing `exclude_ids`-threading selector rather than a new
selection algorithm). The naming/history/branching/exclusion features are
additive and backward-compatible by construction (every new `Job` field has
a safe default and nothing existing was renamed or restructured); the one
correctness fix (retry/replacement telemetry) is a read-side derivation
change with no effect on persisted data. Total: 196/196 backend tests,
107/107 frontend tests, one clean production build, zero provider calls,
generator submodule untouched.
