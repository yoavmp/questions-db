"""Per-category integrated request contract (WP17 section 6).

Future per-category exam input is ``{total: C, database: A, llm: B}`` where:

* C, A, B are genuine non-negative integers (no bools, floats, numeric strings);
* A + B == C;
* database availability limits A only (never B).

WP17 defines and tests this contract; the live request/job flow is WP18+.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CategoryRequest", "RequestContractError", "parse_category_request"]


class RequestContractError(ValueError):
    """Raised for any request that violates the per-category contract."""


def _strict_nonneg_int(value, field: str) -> int:
    # bool is an int subclass -- reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestContractError(f"{field} must be a non-negative integer, got {value!r}")
    if value < 0:
        raise RequestContractError(f"{field} must be non-negative, got {value}")
    return value


@dataclass(frozen=True)
class CategoryRequest:
    """A validated per-category request. ``category`` is a canonical spelling."""

    category: str
    total: int
    database: int
    llm: int

    def with_db_availability(self, available: int) -> "CategoryRequest":
        """Return a copy clamped so ``database`` never exceeds DB availability.

        Availability limits A only: if ``database`` would exceed ``available`` the
        request is invalid (callers decide whether to clamp or reject). This
        helper rejects, matching the generator's fail-closed stance.
        """
        if self.database > available:
            raise RequestContractError(
                f"category {self.category!r}: database={self.database} exceeds "
                f"availability={available} (availability limits the DB count only)"
            )
        return self


def parse_category_request(category: str, payload: dict) -> CategoryRequest:
    """Validate one ``{total, database, llm}`` payload for ``category``."""
    if not isinstance(payload, dict):
        raise RequestContractError("payload must be an object")
    missing = {"total", "database", "llm"} - set(payload)
    if missing:
        raise RequestContractError(f"missing field(s): {sorted(missing)}")
    extra = set(payload) - {"total", "database", "llm"}
    if extra:
        raise RequestContractError(f"unexpected field(s): {sorted(extra)}")

    total = _strict_nonneg_int(payload["total"], "total")
    database = _strict_nonneg_int(payload["database"], "database")
    llm = _strict_nonneg_int(payload["llm"], "llm")

    if database + llm != total:
        raise RequestContractError(
            f"database ({database}) + llm ({llm}) must equal total ({total})"
        )
    return CategoryRequest(category=category, total=total, database=database, llm=llm)
