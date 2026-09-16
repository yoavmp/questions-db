"""WP26 §2/§3/§8 -- exclusion workbook parsing, resolution, and backend
revalidation. Local, non-provider, offline; the raw uploaded bytes are never
persisted or logged (nothing here writes to disk except the in-memory
workbook fixture)."""

from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import Workbook

from src.jobs.exclusions import (
    ExclusionParseError,
    parse_and_resolve,
    revalidate_ids,
)

CAT = "היסטולוגיה"
OTHER_CAT = "גרעיני הבסיס"


def _xlsx(rows, headers=("מזהה_שאלה", "שאלה", "נושא")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _seed(app_ctx):
    from src.models.question import Question
    from src.models.user import db

    ids = {}
    for i in range(3):
        q = Question(
            category=CAT, question=f"שאלה מספר {i}",
            answer1="a", answer2="b", answer3="c", answer4="d", correct_answer_id=1,
        )
        q.categories = [CAT]
        db.session.add(q)
        db.session.flush()
        ids[f"cat_{i}"] = q.id
    # two rows with the exact same normalized text -> ambiguous fallback
    for i in range(2):
        q = Question(
            category=OTHER_CAT, question="שאלה כפולה",
            answer1="a", answer2="b", answer3="c", answer4="d", correct_answer_id=1,
        )
        q.categories = [OTHER_CAT]
        db.session.add(q)
        db.session.flush()
        ids[f"dup_{i}"] = q.id
    db.session.commit()
    return ids


def test_id_is_authoritative_even_if_text_does_not_match(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([(ids["cat_0"], "טקסט שלא קיים בכלל", CAT)])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_0"]]
        assert preview.counts["resolved"] == 1


def test_nonexistent_id_falls_through_to_text_match(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([(999999, "שאלה מספר 1", CAT)])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_1"]]


def test_text_and_category_exact_match(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([("", "שאלה מספר 2", CAT)])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_2"]]


def test_text_only_fallback_without_category(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([("", "שאלה מספר 0", "")])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_0"]]


def test_whitespace_only_normalization_never_fuzzy(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([("", "  שאלה   מספר    1  ", CAT)])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_1"]]

        content2 = _xlsx([("", "שאלה מספר משהו אחר לגמרי", CAT)])
        preview2 = parse_and_resolve(content2, "x.xlsx")
        assert preview2.resolved_db_ids == []
        assert preview2.counts["unresolved"] == 1


def test_ambiguous_text_match_excludes_all_and_warns(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([("", "שאלה כפולה", OTHER_CAT)])
        preview = parse_and_resolve(content, "x.xlsx")
        assert set(preview.resolved_db_ids) == {ids["dup_0"], ids["dup_1"]}
        assert preview.counts["ambiguous"] == 1
        assert preview.warnings  # a visible warning was raised
        assert "מזהה" not in preview.warnings[0]  # no internal ids/paths leaked


def test_blank_rows_ignored_not_errors(jobs_app):
    with jobs_app.app_context():
        _seed(jobs_app)
        content = _xlsx([(None, None, None), ("", "", "")])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.counts["rows_total"] == 0
        assert preview.resolved_db_ids == []


def test_deduplicates_repeated_ids(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([(ids["cat_0"], "", ""), (ids["cat_0"], "", "")])
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_0"]]
        assert preview.counts["resolved"] == 2
        assert preview.counts["deduplicated"] == 1


def test_full_export_style_workbook_resolves_db_rows_ignores_llm_rows(jobs_app):
    """A previously exported full-exam workbook (see export_full_xlsx) has
    LLM rows with a blank id column -- those must be ignored, not error."""
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        headers = ("מספר_שאלה", "מזהה_שאלה", "נושא", "שאלה", "תשובה1", "תשובה2",
                   "תשובה3", "תשובה4", "תשובה_נכונה", "דיוק", "הבחנה", "תאריך_יצירה")
        rows = [
            (1, ids["cat_0"], CAT, "שאלה מספר 0", "a", "b", "c", "d", 1, "", "", "now"),
            (2, "", CAT, "שאלה שנוצרה בבינה מלאכותית ולא קיימת במאגר",
             "a", "b", "c", "d", 1, "", "", "now"),
        ]
        content = _xlsx(rows, headers=headers)
        preview = parse_and_resolve(content, "x.xlsx")
        assert preview.resolved_db_ids == [ids["cat_0"]]
        assert preview.counts["unresolved"] == 1


def test_availability_by_category_reflects_exclusions(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        content = _xlsx([(ids["cat_0"], "", "")])
        preview = parse_and_resolve(content, "x.xlsx")
        # jobs_app already seeds 6 rows in CAT; this test adds 3 more, then
        # excludes 1 -- the adjusted count must reflect the CURRENT total.
        from src.models.question import Question

        total_before = Question.query.filter(Question.category == CAT).count()
        assert preview.availability_by_category[CAT] == total_before - 1


def test_rejects_non_xlsx_extension(jobs_app):
    with jobs_app.app_context():
        with pytest.raises(ExclusionParseError):
            parse_and_resolve(b"not really a workbook", "x.csv")


def test_rejects_oversized_upload(jobs_app):
    with jobs_app.app_context():
        from src.jobs import exclusions as exc_mod

        big = b"0" * (exc_mod.MAX_UPLOAD_BYTES + 1)
        with pytest.raises(ExclusionParseError):
            parse_and_resolve(big, "x.xlsx")


def test_rejects_unreadable_content(jobs_app):
    with jobs_app.app_context():
        with pytest.raises(ExclusionParseError):
            parse_and_resolve(b"garbage-not-a-workbook", "x.xlsx")


def test_missing_recognized_headers_rejected(jobs_app):
    with jobs_app.app_context():
        _seed(jobs_app)
        content = _xlsx([("x", "y", "z")], headers=("colA", "colB", "colC"))
        with pytest.raises(ExclusionParseError):
            parse_and_resolve(content, "x.xlsx")


# --------------------------------------------------------------------------- #
# backend revalidation of client-supplied ids -- never trust the preview blindly
# --------------------------------------------------------------------------- #
def test_revalidate_drops_ids_that_vanished_since_preview(jobs_app):
    with jobs_app.app_context():
        ids = _seed(jobs_app)
        from src.models.question import Question
        from src.models.user import db

        stale = ids["cat_0"]
        db.session.delete(db.session.get(Question, stale))
        db.session.commit()

        valid, warnings = revalidate_ids([stale, ids["cat_1"]])
        assert valid == [ids["cat_1"]]
        assert warnings


def test_revalidate_rejects_malformed_ids(jobs_app):
    with jobs_app.app_context():
        with pytest.raises(ExclusionParseError):
            revalidate_ids(["not-an-int"])
        with pytest.raises(ExclusionParseError):
            revalidate_ids([True])  # bool is not a legitimate id


def test_revalidate_empty_or_none_is_a_noop(jobs_app):
    with jobs_app.app_context():
        assert revalidate_ids(None) == ([], [])
        assert revalidate_ids([]) == ([], [])
