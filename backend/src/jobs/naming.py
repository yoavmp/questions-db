"""Exam identity: structured/custom naming, safe slugging, legacy fallback
labels (WP26 section 1).

Nothing here does IO; ``src.jobs.service`` validates a raw request payload
through :func:`resolve_identity` and persists the result on ``Job.identity``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

__all__ = [
    "COURSE_CHOICES",
    "EXAM_TYPE_CHOICES",
    "IdentityError",
    "resolve_identity",
    "fallback_label",
    "safe_slug",
]


class IdentityError(ValueError):
    """A structured/custom exam identity payload failed validation (400)."""


COURSE_CHOICES = ("מבנה המוח", "נוירואנטומיה")
EXAM_TYPE_CHOICES = ("מבחן אמצע", "מבחן מסכם")

_MAX_FIELD_LEN = 60
_MAX_CUSTOM_NAME_LEN = 150

#: control characters (except plain space) are never allowed in a name field
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
#: path-traversal / path-separator characters are never allowed in a name --
#: the slug is derived from it and used as a download filename
_PATH_UNSAFE_RE = re.compile(r"[\\/]|\.\.")


def _clean_field(value: Any, field: str, *, max_len: int = _MAX_FIELD_LEN) -> str:
    if not isinstance(value, str):
        raise IdentityError(f"{field} must be a string")
    v = value.strip()
    if not v:
        raise IdentityError(f"{field} must not be empty")
    if _CONTROL_RE.search(v):
        raise IdentityError(f"{field} contains control characters")
    if len(v) > max_len:
        raise IdentityError(f"{field} is too long (max {max_len})")
    return v


def safe_slug(display_name: str) -> str:
    """Filesystem-safe download slug: collapse whitespace to single
    underscores, strip characters unsafe in a filename on any common
    filesystem, never empty. Unicode (Hebrew) letters/digits are preserved."""
    normalized = unicodedata.normalize("NFC", display_name)
    normalized = _CONTROL_RE.sub("", normalized)
    # collapse any run of whitespace to one underscore
    collapsed = re.sub(r"\s+", "_", normalized.strip())
    # drop characters that are unsafe as a filename component
    safe = re.sub(r'[\\/:*?"<>|]', "", collapsed)
    safe = safe.strip("._") or "exam"
    return safe[:120]


def _validate_structured(identity: dict) -> dict:
    course = _clean_field(identity.get("course"), "course")
    if course not in COURSE_CHOICES:
        raise IdentityError(f"course must be one of {COURSE_CHOICES!r}, got {course!r}")
    year = _clean_field(identity.get("year"), "year", max_len=16)
    if not re.fullmatch(r"\d{4}", year):
        raise IdentityError(f"year must be a 4-digit number, got {year!r}")
    exam_type = _clean_field(identity.get("exam_type"), "exam_type")
    if exam_type not in EXAM_TYPE_CHOICES:
        raise IdentityError(
            f"exam_type must be one of {EXAM_TYPE_CHOICES!r}, got {exam_type!r}"
        )
    sitting = _clean_field(identity.get("sitting", "א"), "sitting", max_len=16)

    display_name = f"{course} {year} {exam_type} מועד {sitting}"
    return {
        "mode": "structured",
        "course": course,
        "year": year,
        "exam_type": exam_type,
        "sitting": sitting,
        "custom_name": None,
        "display_name": display_name,
        "slug": safe_slug(display_name),
    }


def _validate_custom(identity: dict) -> dict:
    custom_name = _clean_field(
        identity.get("custom_name"), "custom_name", max_len=_MAX_CUSTOM_NAME_LEN
    )
    if _PATH_UNSAFE_RE.search(custom_name):
        raise IdentityError("custom_name must not contain path separators or '..'")
    return {
        "mode": "custom",
        "course": None,
        "year": None,
        "exam_type": None,
        "sitting": None,
        "custom_name": custom_name,
        "display_name": custom_name,
        "slug": safe_slug(custom_name),
    }


def resolve_identity(payload: Optional[dict]) -> Optional[dict]:
    """Validate the ``identity`` block of an exam-job creation request.

    Returns ``None`` when no identity was submitted at all (the job then
    falls back to :func:`fallback_label` everywhere it is displayed). Raises
    :class:`IdentityError` for a malformed identity block -- callers translate
    this into a 400 (WP26 owner decision: identity is validated the same way
    for every job, but omitting it entirely stays a legal, backward-compatible
    request shape).
    """
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise IdentityError("identity must be an object")
    mode = payload.get("mode")
    if mode == "structured":
        return _validate_structured(payload)
    if mode == "custom":
        return _validate_custom(payload)
    raise IdentityError("identity.mode must be 'structured' or 'custom'")


def fallback_label(job_id: str, created_utc: str) -> str:
    """Calculated (never persisted) display label for a job with no identity:
    ``"מבחן ללא שם – DD.MM.YYYY – <short id>"``."""
    date_part = created_utc
    try:
        # created_utc is "%Y-%m-%dT%H:%M:%SZ"
        y, m, d = created_utc[0:4], created_utc[5:7], created_utc[8:10]
        date_part = f"{d}.{m}.{y}"
    except Exception:  # noqa: BLE001 - malformed timestamp, show it raw
        pass
    short_id = (job_id or "")[:8]
    return f"מבחן ללא שם – {date_part} – {short_id}"


@dataclass(frozen=True)
class ResolvedIdentity:
    """Convenience typed accessor (not used for persistence -- ``Job.identity``
    stays a plain dict, see ``model.py``)."""

    mode: str
    display_name: str
    slug: str
