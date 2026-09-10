"""WP17 section 6 -- per-category {total, database, llm} request contract."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.integration.owner_policy import ab_to_c, c_to_ab, next_pair_is_within_cap
from src.integration.request_contract import (
    RequestContractError,
    parse_category_request,
)


def test_valid_request_roundtrips():
    r = parse_category_request("מבוא", {"total": 5, "database": 3, "llm": 2})
    assert (r.total, r.database, r.llm) == (5, 3, 2)


@pytest.mark.parametrize(
    "payload",
    [
        {"total": 5, "database": 3, "llm": 3},   # A + B != C
        {"total": 5, "database": 3},              # missing llm
        {"total": 5, "database": 3, "llm": 2, "x": 1},  # extra field
        {"total": 5, "database": -1, "llm": 6},   # negative
        {"total": 5, "database": True, "llm": 4}, # bool
        {"total": 5, "database": 3.0, "llm": 2},  # float
        {"total": "5", "database": "3", "llm": "2"},  # numeric strings
    ],
)
def test_invalid_requests_rejected(payload):
    with pytest.raises(RequestContractError):
        parse_category_request("מבוא", payload)


def test_zero_is_valid():
    r = parse_category_request("מבוא", {"total": 0, "database": 0, "llm": 0})
    assert (r.total, r.database, r.llm) == (0, 0, 0)


def test_db_availability_limits_A_only():
    r = parse_category_request("מבוא", {"total": 4, "database": 3, "llm": 1})
    assert r.with_db_availability(3) is not None          # exactly available: ok
    r.with_db_availability(10)                            # plenty: ok
    with pytest.raises(RequestContractError):
        r.with_db_availability(2)                         # A exceeds availability
    # B (llm=1) is never limited by availability -- nothing raises for it


def test_frontend_arithmetic():
    assert c_to_ab(5) == (3, 2)   # editing C: A=ceil, B=floor
    assert c_to_ab(4) == (2, 2)
    assert c_to_ab(0) == (0, 0)
    assert ab_to_c(3, 2) == 5     # editing A/B: C=A+B


def test_cost_ceiling_rule_is_actual_plus_next_pair_only():
    cap = Decimal("5.00")
    # spent $4.20, next pair conservatively $0.50 -> $4.70 <= cap -> allowed
    assert next_pair_is_within_cap(Decimal("4.20"), Decimal("0.50"), cap) is True
    # spent $4.80, next pair $0.50 -> $5.30 > cap -> blocked
    assert next_pair_is_within_cap(Decimal("4.80"), Decimal("0.50"), cap) is False
