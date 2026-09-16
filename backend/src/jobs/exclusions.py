"""Optional DB-question exclusion workbook: parsing + resolution (WP26 §2-§3).

Local and non-provider: never makes a network/LLM call. Needs a Flask app
context (it queries ``Question``) but nothing else. The raw workbook bytes are
read into memory, parsed as data only (formulas/macros/links are never
evaluated -- ``openpyxl`` with ``data_only=True`` reads cached values only),
and are never written to disk or logged.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "ExclusionParseError",
    "ExclusionPreview",
    "parse_and_resolve",
    "revalidate_ids",
    "normalize_text",
]

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_ROWS = 5000  # data rows, header excluded

_ID_HEADERS = {"מזהה_שאלה", "id"}
_TEXT_HEADERS = {"שאלה", "question"}
_CATEGORY_HEADERS = {"נושא", "קטגוריה", "category"}


class ExclusionParseError(ValueError):
    """The uploaded file could not be accepted (400) -- always a safe,
    actionable Hebrew message; never a raw exception string, a path, or file
    content."""


def normalize_text(value) -> str:
    """Collapse-and-strip whitespace only -- the same safe presentation
    normalisation the existing import path already applies. Never fuzzy /
    semantic."""
    if value is None:
        return ""
    return " ".join(str(value).split())


@dataclass
class ExclusionPreview:
    resolved_db_ids: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    availability_by_category: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "resolved_db_ids": list(self.resolved_db_ids),
            "counts": dict(self.counts),
            "warnings": list(self.warnings),
            "availability_by_category": dict(self.availability_by_category),
        }


def _read_headers(header_row) -> dict:
    """Map column index -> role ('id' | 'question' | 'category') from the
    first row, matching any accepted alias verbatim (already Unicode, no
    case-folding needed for Hebrew; 'id'/'category'/'question' are matched
    case-insensitively for the Latin aliases)."""
    roles: dict[int, str] = {}
    for i, cell in enumerate(header_row or []):
        name = normalize_text(cell)
        name_l = name.lower()
        if name in _ID_HEADERS or name_l in _ID_HEADERS:
            roles[i] = "id"
        elif name in _TEXT_HEADERS or name_l in _TEXT_HEADERS:
            roles[i] = "question"
        elif name in _CATEGORY_HEADERS or name_l in _CATEGORY_HEADERS:
            roles[i] = "category"
    return roles


def _cell(row, idx: Optional[int]):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_and_resolve(file_bytes: bytes, filename: str) -> ExclusionPreview:
    """Parse ``file_bytes`` as an ``.xlsx`` exclusion workbook and resolve it
    against the CURRENT question database. Must run inside a Flask app
    context. Raises :class:`ExclusionParseError` for anything that should stop
    exam creation outright (wrong type, too large, unreadable, empty)."""
    import openpyxl

    from src.models.question import Question
    from src.models.user import db
    from src.utils.category_order import CATEGORY_ORDER

    if not (filename or "").lower().endswith(".xlsx"):
        raise ExclusionParseError("יש להעלות קובץ מסוג xlsx בלבד")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ExclusionParseError(
            f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_BYTES // (1024 * 1024)}MB)"
        )

    try:
        # data_only=True: cached values only, formulas/macros/links are never
        # evaluated. read_only=True: streams rows, never loads embedded
        # objects/links. keep_links=False: drop any external references.
        wb = openpyxl.load_workbook(
            io.BytesIO(file_bytes), data_only=True, read_only=True, keep_links=False,
        )
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
    except ExclusionParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak internals
        raise ExclusionParseError("שגיאה בקריאת קובץ האקסל") from exc

    if header_row is None:
        raise ExclusionParseError("הקובץ ריק")

    roles = _read_headers(header_row)
    id_idx = next((i for i, r in roles.items() if r == "id"), None)
    text_idx = next((i for i, r in roles.items() if r == "question"), None)
    cat_idx = next((i for i, r in roles.items() if r == "category"), None)
    if id_idx is None and text_idx is None:
        raise ExclusionParseError(
            "לא נמצאו כותרות מוכרות (מזהה_שאלה / שאלה) בקובץ"
        )

    warnings: list[str] = []
    resolved_rows = 0
    unresolved_rows = 0
    ambiguous_rows = 0
    rows_total = 0
    resolved_ids: set[int] = set()

    for row_num, row in enumerate(rows_iter, start=2):
        if rows_total >= MAX_ROWS:
            warnings.append(f"הקובץ נחתך אחרי {MAX_ROWS} שורות")
            break
        if row is None or not any(c is not None and str(c).strip() != "" for c in row):
            continue  # blank row -- ignored, not an error
        rows_total += 1

        raw_id = _cell(row, id_idx)
        raw_text = normalize_text(_cell(row, text_idx))
        raw_cat = normalize_text(_cell(row, cat_idx))

        # rule 1: a valid, currently-existing DB id is authoritative
        parsed_id: Optional[int] = None
        if raw_id is not None and str(raw_id).strip() != "":
            try:
                parsed_id = int(str(raw_id).strip())
            except (TypeError, ValueError):
                parsed_id = None
        if parsed_id is not None:
            row_obj = db.session.get(Question, parsed_id)
            if row_obj is not None:
                resolved_ids.add(row_obj.id)
                resolved_rows += 1
                continue
            # nonexistent id -- fall through to text matching below

        if not raw_text:
            unresolved_rows += 1
            continue

        matches = None
        if raw_cat:
            # rule 2: exact normalized text + canonical category
            candidates = Question.query.filter(
                db.or_(
                    Question.category == raw_cat,
                    Question.categories_json.like(f'%"{raw_cat}"%'),
                )
            ).all()
            matches = [q for q in candidates if normalize_text(q.question) == raw_text]
        else:
            # rule 3: exact normalized text across the whole DB
            candidates = Question.query.all()
            matches = [q for q in candidates if normalize_text(q.question) == raw_text]

        if not matches:
            unresolved_rows += 1
        elif len(matches) == 1:
            resolved_ids.add(matches[0].id)
            resolved_rows += 1
        else:
            # rule 5: ambiguous -- exclude every exact match (never guess one),
            # and surface a visible, safe (no row content) warning/count
            ambiguous_rows += 1
            for q in matches:
                resolved_ids.add(q.id)
            warnings.append(f"שורה {row_num}: התאמה למספר שאלות (הוחרגו כולן)")

    sorted_ids = sorted(resolved_ids)

    availability_by_category: dict[str, int] = {}
    for cat in CATEGORY_ORDER:
        total = Question.query.filter(
            db.or_(
                Question.category == cat,
                Question.categories_json.like(f'%"{cat}"%'),
            )
        ).count()
        if resolved_ids:
            excluded_here = Question.query.filter(
                Question.id.in_(resolved_ids),
                db.or_(
                    Question.category == cat,
                    Question.categories_json.like(f'%"{cat}"%'),
                ),
            ).count()
        else:
            excluded_here = 0
        availability_by_category[cat] = total - excluded_here

    return ExclusionPreview(
        resolved_db_ids=sorted_ids,
        counts={
            "rows_total": rows_total,
            "resolved": resolved_rows,
            "deduplicated": len(sorted_ids),
            "unresolved": unresolved_rows,
            "ambiguous": ambiguous_rows,
        },
        warnings=warnings,
        availability_by_category=availability_by_category,
    )


def revalidate_ids(raw_ids) -> tuple[list, list]:
    """Backend job-creation revalidation (WP26 §2): never trust a client's
    preview result blindly. Returns ``(valid_ids, dropped_warnings)`` --
    malformed entries are rejected outright by the caller (``JobError``);
    well-formed ids that no longer exist in the current DB are silently
    dropped with a safe warning, never causing a paid call to fail to start
    for a reason unrelated to the exam itself."""
    from src.models.question import Question
    from src.models.user import db

    if raw_ids is None:
        return [], []
    if not isinstance(raw_ids, list):
        raise ExclusionParseError("excluded_db_ids must be a list")
    parsed: list[int] = []
    for v in raw_ids:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ExclusionParseError(f"excluded_db_ids must be integers, got {v!r}")
        parsed.append(v)
    unique_sorted = sorted(set(parsed))
    if not unique_sorted:
        return [], []
    existing = {
        qid
        for (qid,) in db.session.query(Question.id).filter(Question.id.in_(unique_sorted)).all()
    }
    dropped = [i for i in unique_sorted if i not in existing]
    warnings = []
    if dropped:
        warnings.append(f"{len(dropped)} מזהי שאלות להחרגה כבר אינם קיימים במאגר והוסרו")
    return sorted(existing), warnings
