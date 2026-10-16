"""The exact generator commit this outer repo pins (WP18).

Kept in the OUTER repo so readiness can flag an accidental drift between the
checked-out ``exam_generator/`` working tree and the gitlink this repo records.
Update this together with ``git add exam_generator`` whenever the submodule is
re-pinned (see WPs/ARCHITECT_HANDOFF.md "Submodule re-pin procedure").
"""

from __future__ import annotations

EXPECTED_GENERATOR_PIN = "303cf394cc0b9839c459d1e56f8784e147e80e9f"
EXPECTED_GENERATOR_PIN_LABEL = "WP31G: record final commit SHA and push outcome in architect report"

__all__ = ["EXPECTED_GENERATOR_PIN", "EXPECTED_GENERATOR_PIN_LABEL"]
