# WP17 — Canonical Category Mapping

**Outer canonical source:** `backend/src/utils/category_order.py::CATEGORY_ORDER`
(the sole external category spelling and display order for the whole system).

**Pinned generator:** `exam_generator` submodule @
`e5f4e0b34dda26f22c56090326f30af7170bcbd3` (WP16R).
Generator catalog: `exam_generator/config/categories.json` (20 categories,
chapters 1–20).

**Outer binding module:** `backend/src/integration/category_map.py`
(`CANONICAL_TO_GENERATOR_CONTEXT`, `ALIASES`, `resolve_generator_context`,
`verify_against_generator_catalog`).

## Result

| # | Canonical name (`CATEGORY_ORDER`) | Generator context id | Generator chapter | Strict-ready\* |
|--:|---|---|--:|:--:|
| 1 | מבוא | `chapter_01` | 1 | ✅ |
| 2 | התעלה השדרתית ותכולתה | `chapter_02` | 2 | ✅ |
| 3 | אמבריולוגיה | `chapter_03` | 3 | ✅ |
| 4 | טופוגרפיה של ההמיספרות | `chapter_04` | 4 | ✅ |
| 5 | חומר לבן | `chapter_05` | 5 | ✅ |
| 6 | חדרי המוח | `chapter_06` | 6 | ✅ |
| 7 | גרעיני הבסיס | `chapter_07` | 7 | ✅ |
| 8 | היסטולוגיה | `chapter_09` | 9 | ✅ |
| 9 | לוקליזציה פונקציונלית | `chapter_10` | 10 | ✅ |
| 10 | תאי מערכת העצבים | `chapter_18` | 18 | ✅ |
| 11 | מיפוי ודימות מוחי | `chapter_08` | 8 | ✅ |
| 12 | אספקת דם | `chapter_11` | 11 | ✅ |
| 13 | קרומים וסינוסים דוראליים | `chapter_12` | 12 | ✅ |
| 14 | גזע המוח | `chapter_13` | 13 | ✅ |
| 15 | עצבים קרניאליים | `chapter_14` | 14 | ✅ |
| 16 | מסילות עצביות | `chapter_15` | 15 | ✅ |
| 17 | המוח הקטן | `chapter_17` | 17 | ✅ |
| 18 | דיאנצפלון | `chapter_16` | 16 | ✅ |
| 19 | המערכת הלימבית | `chapter_19` | 19 | ✅ |
| 20 | מערכת העצבים ההיקפית | `chapter_20` | 20 | ✅ |

\* Strict-ready = `exam_generator/Data/index/<pdf_sha256>/contexts/manifest.json`
reports `build_mode: strict`, `all_term_fidelity_approved: true`,
`readiness_gate: true`, `unapproved_categories: []`, and every category
`term_fidelity_approved: true` with `unresolved_term_count: 0`. (Some categories
carry `blocking_english_run` counts > 0, but the WP04 readiness ledger — the
authority — clears them, so `term_fidelity_approved` is `true`.) Verified against
the restored `exam_generator/Data/` runtime input, pdf sha256
`65be18765eb5cb856e9dc4d72202cb19c502596016428ef430b5126c4a48ced9`.

## Comparison findings

- **Names:** all 20 canonical names are **byte-for-byte identical** to the
  generator catalog names (verified programmatically — no niqqud/whitespace
  drift). No spelling alias is needed; `ALIASES` in the outer config is
  intentionally **empty**.
- **Coverage:** set-equal. **0 missing**, **0 extra**, **0 ambiguous**. Each
  canonical category maps to **exactly one** strict-ready generator context, and
  each generator context is used exactly once → **WP18 is not blocked** on the
  category contract.
- **Order:** `CATEGORY_ORDER` is a *pedagogical* order and deliberately differs
  from the generator's chapter order at positions 8–16 and 17–18
  (`היסטולוגיה`/`מיפוי ודימות מוחי`/`תאי מערכת העצבים` are pulled forward;
  `דיאנצפלון`/`המוח הקטן` are swapped). This is expected: the outer repo owns
  **display order**, the generator owns **chapter ids**. `resolve_generator_context`
  binds by name, never by position.
- **No fuzzy matching anywhere.** `resolve_generator_context` / `canonicalize`
  do exact-string lookups only and raise `UnknownCategory` otherwise. A trailing
  space or transliteration is a hard error, not a near-match.

## `/api/test/categories`

Reworked (WP17 §4) to return **all 20 canonical categories in `CATEGORY_ORDER`**
(then any extra DB-only category, Hebrew-collated, at the end) with
`question_count` = **live DB availability** (primary category OR secondary
category match), not the stale `Category.question_count` column. The frontend
renders this order verbatim; the duplicate hard-coded order in
`frontend/src/utils/categoryOrder.js` was deleted.

## Re-pinning procedure

On any future submodule bump, re-run
`verify_against_generator_catalog("exam_generator/config/categories.json")` (the
`backend/tests/test_wp17_category_contract.py` suite does this). A non-empty
`missing`, `extra`, `ambiguous`, or a map/catalog disagreement **blocks WP18**
until `CANONICAL_TO_GENERATOR_CONTEXT` / `ALIASES` are updated in the outer repo.
