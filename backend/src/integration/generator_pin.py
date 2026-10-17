"""The exact generator commit this outer repo pins (WP18).

Kept in the OUTER repo so readiness can flag an accidental drift between the
checked-out ``exam_generator/`` working tree and the gitlink this repo records.
Update this together with ``git add exam_generator`` whenever the submodule is
re-pinned (see WPs/ARCHITECT_HANDOFF.md "Submodule re-pin procedure").
"""

from __future__ import annotations

EXPECTED_GENERATOR_PIN = "e0cf4bfca3f5febb77b47fe58264c15cd9947798"
EXPECTED_GENERATOR_PIN_LABEL = "WP31RG: restore a fully green suite (fix spelling-audit narrative prose)"

__all__ = ["EXPECTED_GENERATOR_PIN", "EXPECTED_GENERATOR_PIN_LABEL"]
