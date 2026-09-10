"""WP17 section 4 -- canonical category contract vs the pinned generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.integration.category_map import (
    ALIASES,
    CANONICAL_TO_GENERATOR_CONTEXT,
    UnknownCategory,
    canonicalize,
    resolve_generator_context,
    verify_against_generator_catalog,
)
from src.utils.category_order import CATEGORY_ORDER

_GENERATOR_CATALOG = (
    Path(__file__).resolve().parents[2] / "exam_generator" / "config" / "categories.json"
)


def test_canonical_order_is_20_unique_names():
    assert len(CATEGORY_ORDER) == 20
    assert len(set(CATEGORY_ORDER)) == 20


def test_every_canonical_category_maps_to_one_distinct_context():
    assert set(CANONICAL_TO_GENERATOR_CONTEXT) == set(CATEGORY_ORDER)
    ids = list(CANONICAL_TO_GENERATOR_CONTEXT.values())
    assert len(ids) == len(set(ids)) == 20
    assert all(cid.startswith("chapter_") for cid in ids)


@pytest.mark.skipif(not _GENERATOR_CATALOG.is_file(), reason="submodule not checked out")
def test_frozen_map_agrees_with_pinned_generator_catalog():
    report = verify_against_generator_catalog(_GENERATOR_CATALOG)
    assert report["byte_exact_names"] is True
    assert report["aliases_required"] == []
    assert report["unmapped"] == []
    assert report["ambiguous"] == []
    assert report["canonical_count"] == report["generator_count"] == 20


@pytest.mark.skipif(not _GENERATOR_CATALOG.is_file(), reason="submodule not checked out")
def test_display_order_differs_from_chapter_order_but_names_match():
    # documented divergence: CATEGORY_ORDER is pedagogical, not chapter order
    report = verify_against_generator_catalog(_GENERATOR_CATALOG)
    assert report["display_order_matches_chapter_order"] is False


def test_resolver_is_exact_only_never_fuzzy():
    assert resolve_generator_context("מבוא") == "chapter_01"
    assert canonicalize("היסטולוגיה") == "היסטולוגיה"
    with pytest.raises(UnknownCategory):
        canonicalize("מבוא ")  # trailing space -> not a fuzzy hit
    with pytest.raises(UnknownCategory):
        resolve_generator_context("neuroanatomy intro")


def test_aliases_table_is_exact_string_map():
    assert isinstance(ALIASES, dict)
    for k, v in ALIASES.items():
        assert isinstance(k, str) and v in CANONICAL_TO_GENERATOR_CONTEXT
