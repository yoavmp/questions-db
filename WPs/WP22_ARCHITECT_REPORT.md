# WP22 — Targeted Live Evidence Validation — Architect Report

## 1. Preflight

- Outer `questions-db` HEAD at start and end: `b549afaeb0996be0d30d157879b5843798f75bea` (branch
  `main`, 8 ahead of `origin/main`, not pushed). Working tree at start: `M exam_generator` (the
  already-known advanced submodule checkout) + `?? WPs/WP22_Targeted_Live_Evidence_Validation.md`
  (this WP's own brief). No other drift.
- Generator `exam_generator` HEAD, unchanged throughout: `fdde3ea48272e95dbf53b0c7d14f335a8968b11d`
  (contains WP21GR: `b7d1821` "correct evidence integration contract", `fdde3ea` "note full-suite
  verification overhead"). Working tree: **clean**, before and after.
- Backend health (`GET /`, `GET /health`): `200 "Hebrew Exam System Backend is running"`.
- `GET /api/exam-jobs/readiness`: `ready_for_llm: true`, `blocking_reasons: []`. Pricing: model
  `gpt-5.6-terra`, `verified_at: 2026-09-04`, 10 days old (30-day stale threshold), complete and
  matching both selected models. `openai_api_key_present: true`. One **non-blocking** warning:
  `submodule_pin` — the outer repo's recorded pin (`ea59cd8`, WP17GR) is behind the generator's
  actual checked-out HEAD (`fdde3ea`, post-WP21GR). This is the pre-existing, already-known drift
  the brief explicitly forbids fixing here (no submodule-pointer update in WP22); it did not block
  `ready_for_llm` and required no action.
- `OPENAI_API_KEY` was never displayed, requested, read, or stored by this session at any point;
  every real provider call ran from the owner's own key-bearing terminal (§3.1).
- No automatic retry was made anywhere: each of the three intended operations was attempted exactly
  once as a paid call. Two configuration-only correction cycles preceded Operation 1's real call
  (§2.1) — both made **zero** provider calls and cost **$0**, so neither consumed the "one attempt."

## 2. Operation 1 — Integrated production generation

### 2.1 Two zero-cost configuration corrections, then one real attempt

`POST /api/exam-jobs` was called with `{"categories": {"אמבריולוגיה": {"total": 2, "database": 1,
"llm": 1}}, "cost_ceiling_usd": "0.20"}`. The job's own worst-case pre-flight guard refused before
any provider call: `"the next generation+review attempt (worst-case $0.4216375) plus $0 already
reserved would exceed the $0.20 ceiling; no further provider call was made"` — `accumulated_cost_usd:
"0"`. This was a client-side ceiling misconfiguration on my part, corrected without any real attempt
being spent: the job was reissued with `cost_ceiling_usd: "0.43"` (job `715aa25e-…`), clearing the
guard.

### 2.2 Real result

One real generation+review pair ran. DB slot: category question **id 407** ("החדרים הלטרליים ושתי
ההמיספרות של המוח מהווים, בהתאמה, את החלל והדופן של איזו מבין השלפוחיות הבאות?" — brain-vesicle
lateral-ventricle/hemisphere correspondence) was auto-selected and — confirmed via
`backend/src/jobs/service.py::_previous_for_slot` (DB-origin slots are listed before LLM slots, same
category, stable `number` order) — supplied as the LLM slot's `previous_questions` context, with no
manual intervention required.

LLM slot (`chapter_03_q001`, an *Ectoderm* candidate): **one** real attempt, `question_rejected`.
Real cost **$0.0932765** (generation $0.0300595 + review $0.0632170). The job's second internal
attempt was correctly refused by the same worst-case guard (`worst-case $0.4193625` + `$0.0932765`
already spent `> $0.43` ceiling) — **zero** further cost. Final job status: `cost_ceiling` (no
accepted LLM question this operation), `accumulated_cost_usd: "0.0932765"`.

Cause of rejection (from `attempt_01/repair/question_audit.json`, `parsed/review_result.json`): the
reviewer flagged the candidate's Hebrew phrase "הדיסק התלת-שכבתי" as an undeclared Hebrew paraphrase
of a required-English term and proposed a patch replacing it with "ה-Trilaminar Disk" — but tagged
the patch's `term_id` as `gastrulation`, not the term id for "Trilaminar Disk." The deterministic
patch validator correctly refused it: `"replacement 'ה-Trilaminar Disk' is not a permitted output
form of 'gastrulation'"`. `repaired: null`, `outcome: question_rejected`. **This looks like a
reviewer-side term-id mislabeling, not an evidence-grounding defect** — see §8 for the recommended
smallest fix.

Evidence coverage (unrelated to the rejection cause, and healthy): all three distractors got
`distractor_support` with `evidence_mode` `mapping`/`closed_list` and named `source_unit_ids`;
`exactly_one_correct_answer: true`, `distractors_incorrect_and_plausible: true`,
`grounded_in_context: true`.

Manifest/audit contract: `invocation_manifest.json` contains exactly the six trusted fields
(`job_id, slot_id, operation, sequence, invocation_uuid, created_at`), written once before the
provider call; the generator's own guard (`production.py`'s `_is_trusted_pre_existing_manifest_only`)
never rewrites a pre-existing manifest of that exact shape, and no second manifest or overwrite is
present. `redaction_check.json`: `leaks: []`, `forbidden_keys_found: []`. Audit directory
(`artifacts/exam_jobs/715aa25e-…/slots/<slot_id>/initial_0001_<uuid>/`) is fresh and did not collide
with anything (including the discarded `$0.20`-ceiling job's own, separate, unused directory).

Public candidate content (not accepted — reported for completeness, not as a claim of correctness):
question "איזה שכבה של הדיסק התלת-שכבתי עתידה להתפתח למערכת העצבים?", correct answer *Ectoderm*,
distractors *Mesoderm* / *Endoderm* / *Hypoblast*. Biologically this looks correct; see §7.

## 3. Operations 2–3 — Reviewer-only replays

### 3.1 Credential boundary

No existing safe interface (backend endpoint, CLI command, or script) performs a reviewer-only
replay against a preserved candidate without holding `OPENAI_API_KEY` — confirmed by inspection of
`backend/src/routes/exam_jobs.py` (job API always runs the full generate+review pipeline) and
`exam_generator/src/exam_generator/cli.py` (no review-only command; `wp08_replay.py`/`wp15_replay.py`
replay already-frozen recorded verdicts offline with zero provider calls, not a live call). Per the
brief: no temporary endpoint was added, the API key was never exposed to Claude, and a new,
git-ignored, one-shot script was written, tested offline, and handed to the owner as one exact
command.

Script: `exam_generator/artifacts/wp22/reviewer_replay.py` (untracked; `artifacts/*` is
blanket-ignored in `exam_generator/.gitignore` and `wp22/` is not among the explicit un-ignored
`wp01/03/04/05` exceptions). It:

- reuses each preserved `candidate_batch.json` verbatim (`QuestionCandidate.model_validate(...)`,
  no regeneration) via a thin `ReplayProvider` whose `generate_candidates` returns it locally, at
  zero cost;
- calls `exam_generator.runtime_inputs.build_runtime_inputs` for the category's current context/terms
  (local files only, `required_model="gpt-5.6-terra"` fail-closed against a silent model swap);
- calls the **unmodified** production orchestrator, `exam_generator.orchestrator.
  generate_one_question`, so evidence-pack construction, patch/repair handling, and the deterministic
  post-review validation (`repair.validate_candidate` + `CandidateReview.comparison_problems` +
  `corrected_fact_problems`) are byte-identical to production's own code path — not a
  reimplementation;
- before each real `review_candidates` call, computes a worst-case bound via
  `exam_generator.live_cost.preflight_estimate` (generation side zeroed, using the exact rendered
  review prompt) against the shared remaining budget, and raises a typed `ProviderError` refusal
  (zero cost) rather than calling if it could exceed it;
- computes the real cost of each call actually made via `live_cost.observed_cost` on the real usage
  numbers;
- writes only a structured JSON summary through `runtime_redaction._write_json` (refuses to write any
  text containing the literal key value) and finishes with the same `_sweep_run_dir` /
  `_forbidden_keys_in_dir` sweep production's own audit trail uses — never a raw prompt or raw
  provider response.

Tested offline before being handed to the owner (`--dry-run`, `OPENAI_API_KEY` unset): (a) a
scripted-fake-provider full run completed end to end and produced a clean, redaction-swept output
file; (b) a near-zero `--remaining-budget-usd` correctly refused both calls with zero cost; (c) with
`--dry-run` omitted and no key set, the script refused to start at all. The owner then ran, verbatim,
from their key-bearing terminal:

```
cd /Users/crazyjoe/Projects/questions-db/exam_generator && python3 artifacts/wp22/reviewer_replay.py
```

Both real calls were made; total real cost for Operations 2–3: **$0.0691647** ($0.0272916 +
$0.0418731), each individually well inside the shared remaining budget at the time
(worst-case $0.1741425 vs. $0.4067235 remaining for Operation 2; worst-case $0.2114825 vs.
$0.3794319 remaining for Operation 3).

**Known limitation, disclosed by the script itself in its output:** the replay used
`previous_questions=[]`. The original `a57b0b7b` job's audit preserved only a one-way hash of the
prior-question text (`_question_hash`, sha256[:16]), not the text itself, so the exact original
context could not be reconstructed. `distinct_from_previous_and_siblings`,
`semantically_distinct_from_previous`, and `previous_comparisons` are therefore **not** directly
comparable to the original run and must be read with that caveat; every other criterion is a fair
current-vs-original comparison since neither candidate content nor category context changed.

### 3.2 Operation 2 — `chapter_01_q001` (Foramen Magnum)

Real cost **$0.0272916**. Outcome: **`question_rejected`, unchanged from original.**
`criterion_diff` is **empty** — every one of the 13 compared criteria matches the original verdict
exactly, including the two that gate acceptance: `grounded_in_context: false` and
`distractors_incorrect_and_plausible: false` (both unchanged).

Evidence-pack detail: `distractor_1` got `evidence_mode: "direct"` support (unit
`chapter_01:u031`, "the source explicitly frames the change as a move from the posterior part of the
skull's opening to its underside"). `distractor_2` and `distractor_3` got `evidence_mode: "none"` —
the reviewer's own reasons say the source describes the *skull opening* (u031) and, separately,
*brain-volume growth* (u032) or *the mastication system* (u033), but **never asserts or denies a
causal link** between them, so no closed-list/exclusivity disproof exists for either distractor. The
evidence pack *did* surface all three relevant units (`unit_count: 3` for every field) — this is a
genuine, reasoned "insufficient explicit disproof in the source" judgment, not a retrieval failure.
**WP21GR did not change this outcome**, and on this evidence it looks like a defensible rejection
given the system's strict source-grounding standard, not a proven false rejection — see §7/§8.

### 3.3 Operation 3 — `chapter_03_emb_001` (Neural Tube plates)

Real cost **$0.0418731**. Outcome: **`question_rejected`, but two of four previously-failing
criteria flipped to pass:**

| Criterion | Original | New |
|---|---|---|
| `exactly_one_correct_answer` | `false` | **`true`** |
| `grounded_in_context` | `false` | **`true`** |
| `distractors_incorrect_and_plausible` | `false` | `false` (unchanged) |
| `post_repair_approved` | `false` | `false` (unchanged) |

The still-failing criterion has the same shape as Operation 2: `distractor_1` (*Alar Plate*) got
`evidence_mode: "direct"` support from `chapter_03:u053` (explicitly framed as sensory, contrasting
with the motor *Basal Plate*). `distractor_2` (*Roof Plate*) and `distractor_3` (*Ependymal layer*)
got `evidence_mode: "none"` — again *not* because the evidence pack failed to find anything
(`unit_count: 3` for each, citing `u050`/`u051`) but because, per the reviewer's own stated reasons,
the cited units describe each structure's own known role without an explicit source statement ruling
out a motor-cell contribution. Real, measurable improvement (2 of 4 criteria), no acceptance, and the
gap that remains is the same class of evidentiary strictness as Operation 2.

## 4. Cost accounting

| Operation | Real cost (USD) | Worst-case pre-flight bound |
|---|---:|---:|
| 1 — integrated production generation | $0.0932765 | $0.4193625 (attempt 2, refused) |
| 2 — reviewer replay, `chapter_01_q001` | $0.0272916 | $0.1741425 |
| 3 — reviewer replay, `chapter_03_emb_001` | $0.0418731 | $0.2114825 |
| **Total** | **$0.1624412** | — |

$0.50 ceiling: **not reached** ($0.3375588 unspent). Zero dollars were spent on any call that was
ultimately refused pre-flight — both refusals in §2.1 and the hypothetical Operation-1 second attempt
happened entirely before any socket opened.

**Is the evidence pack cheaper than the retries it prevents?** In this run, neither remaining
false-rejection candidate flipped to accepted, so no retry was literally avoided this time — the
question can't be answered as "yes, N retries were prevented, saving $X" from this data alone.
What the data *does* show: (a) the evidence pack's own marginal cost is small — WP21G's own
measurement (`WP21G_ARCHITECT_REPORT.md` §2) put the `chapter_03_emb_001` prompt-size delta at
+5,631 tokens (+28.5%, 19,778→25,409), which at the current $2.00/M input rate is about **+$0.011
per review call** — far below a full extra generation+review retry (historically $0.03–$0.09,
Operation 1 here $0.0933); (b) it materially improved diagnostic precision — Operation 3 went from
"rejected, unclear why" to "rejected specifically because 2 of 3 distractors lack explicit source
disproof," which is actionable information an owner can use to fix the *source material or the
answer set* deliberately, a cheaper path than blind regeneration retries. On present evidence the
pack looks cost-effective as a diagnostic upgrade; it has not yet been shown, live, to convert a
false rejection into an acceptance.

## 5. Manual judgment of public Hebrew content (acceptance is not being claimed as proof)

- **Operation 1** (*Ectoderm*, not accepted): grammatically clear Hebrew; content is biologically
  correct (ectoderm → nervous system; the three distractors are the other two germ layers plus
  hypoblast, none of which becomes neural tissue). The rejection cause (§2.2) looks like a
  reviewer-side term-id mislabeling on an otherwise sound candidate.
- **Operation 2** (*Foramen Magnum*, not accepted): clear Hebrew, anatomically/evolutionarily
  plausible content (the correct answer's directional claim — posterior-to-inferior repositioning —
  matches the cited source excerpt). The two unsupported distractors (brain-volume growth;
  mastication-system change) are real, commonly-cited alternative hypotheses for the same
  evolutionary change, which is exactly why the source's silence on ruling them out is a genuine gap,
  not just an artifact of narrow retrieval.
- **Operation 3** (*Neural Tube* plates, not accepted): clear Hebrew, and the core distinction
  (Basal Plate → motor, separated from Alar Plate → sensory by the sulcus limitans) is standard,
  well-established embryology. Roof Plate and Ependymal layer are real anatomical structures with
  well-known *non*-motor identities, so the content is very likely correct — the persisting rejection
  is a strict-evidentiary-standard artifact (§8), not a defect in the question.

## 6. Remaining false rejection / false acceptance assessment

No false acceptance was observed (nothing was accepted this WP). Two remaining likely **false
rejections**, both sharing one root cause distinct from WP21GR's own scope:

The reviewer will not mark a distractor `distractors_incorrect_and_plausible: true` unless it can
point to an explicit source statement that disproves that specific distractor (a "direct",
"exclusivity", or "closed_list" `evidence_mode`) — a unit that merely describes the distractor's own
role, without an explicit contrast or negation, is read as `evidence_mode: "none"` even when the
correct/incorrect status is obvious to a domain expert and even when the evidence pack *did* surface
the relevant unit. Both Operation 2 and Operation 3 hit exactly this wall on 2 of their 3 distractors
each. This is a **reviewer-strictness / prompt-instruction issue, not an evidence-retrieval gap** —
WP21GR already closed the retrieval gap (units are being found); the remaining blocker is what the
reviewer is willing to infer from them.

## 7. Smallest recommended corrections (not implemented in WP22)

1. **Operation 1's patch-mislabeling.** The reviewer proposed replacing a Hebrew paraphrase with an
   English term but tagged the patch with the *wrong* `term_id` (`gastrulation` instead of the id for
   "Trilaminar Disk"), so a correct patch was rejected by the (correctly-behaving) deterministic
   validator. Smallest fix: tighten the review-prompt instruction (or add a deterministic
   cross-check) so a proposed patch's `term_id` is verified against the *replacement text itself*,
   not just the *original span* being replaced, before the patch is sent.
2. **Operations 2–3's evidence-mode strictness.** Consider allowing a distractor to pass
   `distractors_incorrect_and_plausible` on strong *implicit* contrastive evidence (e.g., two units
   from the same enumerated list, each independently and exhaustively assigning a distinct role,
   with no unit assigning the correct-answer's role to the distractor) rather than requiring an
   explicit negation. This is a reviewer-instruction change, not an evidence-pack change — the pack
   already retrieves the right units.

Neither correction was implemented here, per the brief's validation-only scope.

## 8. Repository state and secret/audit safety

- Outer HEAD unchanged across the whole WP until this report's own commit: `b549afa…`. Generator HEAD
  unchanged throughout and still clean: `fdde3ea…`. No production code, validation logic, API
  endpoint, or submodule pointer was touched.
- No live artifact, script, prompt, raw response, or course text is staged or committed by this WP
  (§9). `exam_generator/artifacts/wp22/` (the replay script and its output) is untracked and covered
  by the generator's blanket `/artifacts/*` `.gitignore` rule; the outer repo's `artifacts/
  exam_jobs/` (Operation 1's real job/audit trail, and the pre-existing `a57b0b7b` preserved
  candidates) is untracked and covered by the outer `.gitignore`'s blanket `artifacts/` rule.
- Every redaction sweep run during this WP (Operation 1's production-written
  `redaction_check.json`, and the replay script's own `_sweep_run_dir`/`_forbidden_keys_in_dir`
  self-check after both real calls) came back clean: no leaked secret value, no forbidden key.
  `OPENAI_API_KEY` was read only by the OpenAI SDK inside processes the owner started in their own
  terminal; this session never read, displayed, or stored it.

## 9. Git checkpoint

Staged and committed in the **outer** repository only: this WP's brief
(`WPs/WP22_Targeted_Live_Evidence_Validation.md`), this report
(`WPs/WP22_ARCHITECT_REPORT.md`), and the refreshed `WPs/ARCHITECT_HANDOFF.md`. The advanced
`exam_generator` gitlink was **not** staged (it remains at `fdde3ea…`, ahead of the outer repo's
recorded tree entry, exactly as it was before this WP — WP22 explicitly forbids updating the
pointer). No live artifact, replay script, prompt, response, course data, or credential was staged.
Not pushed.
