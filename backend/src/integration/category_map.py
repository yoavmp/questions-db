"""Canonical category contract (WP17 section 4).

``backend/src/utils/category_order.py::CATEGORY_ORDER`` is the SOLE external
category spelling and display order for the whole system. This module binds each
canonical category to exactly one strict-ready generator context id
(``chapter_NN``) in the *outer* repository -- never inside the submodule, and
never by fuzzy matching.

Findings recorded during WP17 (pinned generator
``e5f4e0b34dda26f22c56090326f30af7170bcbd3``):

* The 20 canonical names are byte-for-byte identical to the generator catalog
  names in ``exam_generator/config/categories.json``. No spelling alias is
  required; ``ALIASES`` is intentionally empty.
* Every canonical category maps 1:1 to a generator context whose
  ``term_fidelity_approved`` is ``true`` under ``build_mode: strict`` -- there
  are no missing, extra, or ambiguous mappings, so WP18 is not blocked on the
  category contract.
* Display ORDER differs: ``CATEGORY_ORDER`` is a pedagogical ordering, while the
  generator uses chapter order. That divergence is expected and allowed --
  ``CATEGORY_ORDER`` owns display order; the generator owns chapter ids.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.utils.category_order import CATEGORY_ORDER

__all__ = [
    "CANONICAL_TO_GENERATOR_CONTEXT",
    "ALIASES",
    "UnknownCategory",
    "canonicalize",
    "resolve_generator_context",
    "verify_against_generator_catalog",
]


class UnknownCategory(KeyError):
    """Raised when a category string is neither canonical nor a declared alias.

    Never fall back to fuzzy / substring matching: an unrecognised category is a
    hard error that a human must resolve.
    """


#: Explicit canonical-name -> pinned-generator context id. Frozen in the outer
#: repository. Cross-checked against the live generator catalog by
#: :func:`verify_against_generator_catalog` (see the WP17 category-contract test).
CANONICAL_TO_GENERATOR_CONTEXT: dict[str, str] = {
    "מבוא": "chapter_01",
    "התעלה השדרתית ותכולתה": "chapter_02",
    "אמבריולוגיה": "chapter_03",
    "טופוגרפיה של ההמיספרות": "chapter_04",
    "חומר לבן": "chapter_05",
    "חדרי המוח": "chapter_06",
    "גרעיני הבסיס": "chapter_07",
    "היסטולוגיה": "chapter_09",
    "לוקליזציה פונקציונלית": "chapter_10",
    "תאי מערכת העצבים": "chapter_18",
    "מיפוי ודימות מוחי": "chapter_08",
    "אספקת דם": "chapter_11",
    "קרומים וסינוסים דוראליים": "chapter_12",
    "גזע המוח": "chapter_13",
    "עצבים קרניאליים": "chapter_14",
    "מסילות עצביות": "chapter_15",
    "המוח הקטן": "chapter_17",
    "דיאנצפלון": "chapter_16",
    "המערכת הלימבית": "chapter_19",
    "מערכת העצבים ההיקפית": "chapter_20",
}

#: Alternative EXTERNAL spellings that resolve to a canonical name. Must be an
#: exact-string table (no normalisation, no fuzzy match). Empty today: the
#: canonical spellings already match the generator exactly. Add entries here
#: (outer repo only) if a future data source uses a different exact spelling.
ALIASES: dict[str, str] = {}


def canonicalize(category: str) -> str:
    """Return the canonical spelling for ``category`` or raise ``UnknownCategory``."""
    if category in CANONICAL_TO_GENERATOR_CONTEXT:
        return category
    if category in ALIASES:
        return ALIASES[category]
    raise UnknownCategory(
        f"{category!r} is not a canonical category or a declared alias; "
        f"fuzzy matching is not allowed -- add an explicit alias in "
        f"src/integration/category_map.py if this spelling is intentional"
    )


def resolve_generator_context(category: str) -> str:
    """Canonical (or aliased) category name -> pinned generator context id."""
    return CANONICAL_TO_GENERATOR_CONTEXT[canonicalize(category)]


def verify_against_generator_catalog(catalog_path: str | Path) -> dict:
    """Cross-check the frozen map against the live generator catalog file.

    Returns a report dict; raises ``AssertionError`` on any mismatch. Used by the
    WP17 category-contract test and by tooling that re-pins the submodule.
    """
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    gen_names = {c["name"]: c["category_id"] for c in catalog}

    canonical = set(CATEGORY_ORDER)
    generator = set(gen_names)

    missing_in_generator = sorted(canonical - generator)
    extra_in_generator = sorted(generator - canonical)
    assert not missing_in_generator, f"canonical categories absent from generator: {missing_in_generator}"
    assert not extra_in_generator, f"generator categories absent from canonical order: {extra_in_generator}"

    wrong = {
        name: (CANONICAL_TO_GENERATOR_CONTEXT.get(name), gen_names.get(name))
        for name in CATEGORY_ORDER
        if CANONICAL_TO_GENERATOR_CONTEXT.get(name) != gen_names.get(name)
    }
    assert not wrong, f"frozen map disagrees with generator catalog: {wrong}"

    mapped_ids = list(CANONICAL_TO_GENERATOR_CONTEXT.values())
    assert len(mapped_ids) == len(set(mapped_ids)) == len(CATEGORY_ORDER) == 20, (
        "each canonical category must map to exactly one distinct generator context"
    )

    return {
        "pinned_generator_catalog": str(catalog_path),
        "canonical_count": len(CATEGORY_ORDER),
        "generator_count": len(gen_names),
        "byte_exact_names": True,
        "aliases_required": sorted(ALIASES),
        "display_order_matches_chapter_order": [
            CANONICAL_TO_GENERATOR_CONTEXT[n] for n in CATEGORY_ORDER
        ] == [f"chapter_{i:02d}" for i in range(1, 21)],
        "unmapped": [],
        "ambiguous": [],
    }
