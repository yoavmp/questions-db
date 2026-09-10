# questions-db — Architect Handoff

**Repository:** `questions-db` (outer) — Hebrew exam question bank + test builder
(Flask backend, React/Vite frontend) integrating the Hebrew neuroanatomy
question **generator** as a Git submodule.
**Updated:** 2026-09-10 · **Latest completed WP:** WP17 (integration foundation).
**Next:** WP18 (live integrated request + background generation flow) — blocked
on two generator-side items, see §4.

## 1. Repository SHAs

| Repo | Path | SHA at handoff | State |
|---|---|---|---|
| Outer `questions-db` | `.` | *(set by the `WP17: establish integration foundation` commit — see `git -C . rev-parse HEAD`)* | branch `main`; not pushed |
| Generator `exam-generator` | `exam_generator/` (submodule) | `e5f4e0b34dda26f22c56090326f30af7170bcbd3` | `heads/main`, clean, **do not commit/push here** |

Generator remote: `https://github.com/yoavmp/exam-generator.git`.
Pre-submodule snapshot preserved at `../exam_generator_pre_submodule_backup/`
(253 files) until WP17 is approved.

## 2. Submodule update / re-pin procedure

```bash
# fresh clone
git clone --recurse-submodules https://github.com/yoavmp/questions-db.git

# existing clone missing the submodule
git submodule update --init --recursive

# move the submodule to the commit this repo currently pins
git submodule update --init --recursive
```

To **re-pin** to a newer generator commit (its own WP delivered it):

```bash
git -C exam_generator fetch origin
git -C exam_generator checkout <new_sha>          # detached, exact commit
cd .. && git add exam_generator                   # stages ONLY the gitlink
# then re-run the WP17 contract tests before relying on it:
cd backend && python -m pytest tests/ -q          # category map + adapter + DTO
# and re-verify the category contract against the new catalog:
python -c "from src.integration.category_map import verify_against_generator_catalog as v; \
           print(v('../exam_generator/config/categories.json'))"
```

Rules: the outer repo tracks **only** `.gitmodules` and the `exam_generator`
gitlink. Never `git add exam_generator/<file>`. Never commit or push inside
`exam_generator/`. `exam_generator/Data/` is git-ignored course runtime input,
supplied out of band (kept locally; copy it into the submodule working tree
after any re-clone).

## 3. WP17 integration surface (outer repo)

| Area | Location |
|---|---|
| Canonical categories (spelling + display order) | `backend/src/utils/category_order.py::CATEGORY_ORDER` |
| Canonical ↔ generator context binding, aliases, strict resolver | `backend/src/integration/category_map.py` |
| Owner policy (attempts, $5 cap, arithmetic, DB ownership) | `backend/src/integration/owner_policy.py` |
| Per-category `{total,database,llm}` request contract | `backend/src/integration/request_contract.py` |
| Exam-question DTO (7 fields + meta, `docx_view()`) | `backend/src/integration/exam_question_dto.py` |
| Read-only generator adapter (composes `generate_one_question`) | `backend/src/integration/generator_adapter.py` |
| Category map table | `WPs/WP17_CATEGORY_MAPPING.md` |
| Contract tests (temp DB, fake provider, network-blocked) | `backend/tests/` |

`/api/test/categories` returns all 20 canonical categories in `CATEGORY_ORDER`
with live DB availability counts. Backend real entrypoint: `backend/run.py`,
**port 4567**.

## 4. Blockers before WP18

1. **Generator lacks a consolidated production one-question API.** Only
   `generate_one_question` (needs pre-assembled context/terms/provider/config/
   prompts) is public; the assembly lives in WP live-runners. The WP17 adapter
   re-implements that assembly in the outer repo as a stopgap. A generator WP
   should expose `exam_generator.production.generate_exam_question(*,
   category_name, number, previous_public_questions, max_attempts,
   cost_ceiling_usd, price_snapshot, audit_dir, provider=None)` with its own
   cost preflight + audit redaction.
2. **Generator cross-platform test hygiene.** Network-blocked full suite: 869
   collected; with a dummy `OPENAI_API_KEY` set (zero network) → 692 passed /
   174 skipped / 3 failed. The 3 failures are CRLF vs LF in Windows-authored CSV
   fixtures (`test_cli_wp05` ×2, `test_cli_wp06` ×1); the 9 live-runner tests
   that need `OPENAI_API_KEY` merely *present* pass once a dummy value is set;
   the 174 skips are PDF-rebuild tests that need a fully built
   `exam_generator/Data/` (only partially preserved). Generator-side fixes: LF
   fixtures, self-set dummy key, dependency lockfile, and document the full
   `Data/` build.
3. Confirm `/api/test/categories` exposing zero-count canonical categories is
   desired for the integrated builder UI.

## 5. Authority order

Newest owner ruling → verified outer repo + tests → this handoff → WP briefs →
older records. The generator is authoritative for question generation behaviour
and is changed only by its own WPs.
