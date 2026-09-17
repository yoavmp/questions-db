"""Shared DB-question category-list invariants (WP26R section 3).

Single source of truth for every question create / edit / Excel-import /
category-rename write path::

    categories = nonempty, ordered, unique canonical list
    category   = categories[0]

Never fuzzy / substring: a category is either byte-exact in
``CATEGORY_ORDER`` or it is rejected. This module only validates -- it never
repairs or silently drops an invalid entry, and it never touches the
database itself (callers own persistence).
"""

from __future__ import annotations

from src.utils.category_order import CATEGORY_ORDER

__all__ = [
    "CategoryValidationError",
    "is_canonical_category",
    "validate_categories",
    "dedupe_and_validate",
]

_CANONICAL_SET = frozenset(CATEGORY_ORDER)


class CategoryValidationError(ValueError):
    """A categories write violates the WP26R invariants -- always a safe,
    actionable Hebrew message; never raw exception internals."""


def is_canonical_category(name) -> bool:
    return isinstance(name, str) and name in _CANONICAL_SET


def validate_categories(categories) -> list[str]:
    """Validate ``categories`` is a nonempty, ordered, unique canonical list.

    Raises :class:`CategoryValidationError` for: not a list, empty, a
    non-string/empty entry, an unknown (non-canonical) category, or a
    duplicate entry. Never repairs -- returns a fresh list with the exact
    validated values so a caller cannot accidentally alias the input.
    """
    if not isinstance(categories, list) or not categories:
        raise CategoryValidationError("יש לספק רשימת קטגוריות לא ריקה")
    seen: set[str] = set()
    for c in categories:
        if not isinstance(c, str) or not c:
            raise CategoryValidationError(f"קטגוריה לא תקינה: {c!r}")
        if c not in _CANONICAL_SET:
            raise CategoryValidationError(f"קטגוריה לא מוכרת (לא קנונית): '{c}'")
        if c in seen:
            raise CategoryValidationError(f"קטגוריה כפולה ברשימה: '{c}'")
        seen.add(c)
    return list(categories)


def dedupe_and_validate(categories) -> list[str]:
    """Like :func:`validate_categories` but first deduplicates (first
    occurrence wins, order preserved) instead of rejecting a duplicate.

    Used by category rename: renaming category A -> B on a question that
    already lists B is a legitimate merge, not a malformed write.
    """
    if not isinstance(categories, list) or not categories:
        raise CategoryValidationError("יש לספק רשימת קטגוריות לא ריקה")
    seen: set[str] = set()
    deduped: list[str] = []
    for c in categories:
        if not isinstance(c, str) or not c:
            raise CategoryValidationError(f"קטגוריה לא תקינה: {c!r}")
        if c not in seen:
            deduped.append(c)
            seen.add(c)
    return validate_categories(deduped)
