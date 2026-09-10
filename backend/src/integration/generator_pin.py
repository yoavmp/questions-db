"""The exact generator commit this outer repo pins (WP18).

Kept in the OUTER repo so readiness can flag an accidental drift between the
checked-out ``exam_generator/`` working tree and the gitlink this repo records.
Update this together with ``git add exam_generator`` whenever the submodule is
re-pinned (see WPs/ARCHITECT_HANDOFF.md "Submodule re-pin procedure").
"""

from __future__ import annotations

EXPECTED_GENERATOR_PIN = "ea59cd857e5618b0260d2bb146dd5573c9ca2309"
EXPECTED_GENERATOR_PIN_LABEL = "WP17GR: harden production boundary and pricing"

__all__ = ["EXPECTED_GENERATOR_PIN", "EXPECTED_GENERATOR_PIN_LABEL"]
