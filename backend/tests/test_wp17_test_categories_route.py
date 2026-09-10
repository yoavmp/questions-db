"""WP17 section 4 -- /api/test/categories uses canonical order + DB availability."""

from __future__ import annotations

from src.utils.category_order import CATEGORY_ORDER


def test_returns_all_canonical_categories_in_canonical_order(client, seed_questions):
    resp = client.get("/api/test/categories")
    assert resp.status_code == 200
    names = [row["name"] for row in resp.get_json()]
    assert names[: len(CATEGORY_ORDER)] == list(CATEGORY_ORDER)


def test_counts_are_live_db_availability_not_stale_column(client, seed_questions):
    rows = {r["name"]: r["question_count"] for r in client.get("/api/test/categories").get_json()}
    # 3 primary + 2 secondary ("היסטולוגיה" rows also tagged מבוא) = 5
    assert rows["מבוא"] == 5
    assert rows["היסטולוגיה"] == 2
    assert rows["גזע המוח"] == 1
    # a canonical category with no questions still appears, with 0
    assert rows["אמבריולוגיה"] == 0


def test_no_duplicate_rows(client, seed_questions):
    names = [r["name"] for r in client.get("/api/test/categories").get_json()]
    assert len(names) == len(set(names))
