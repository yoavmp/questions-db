"""The exact generator commit this outer repo pins (WP18).

Kept in the OUTER repo so readiness can flag an accidental drift between the
checked-out ``exam_generator/`` working tree and the gitlink this repo records.
Update this together with ``git add exam_generator`` whenever the submodule is
re-pinned (see WPs/ARCHITECT_HANDOFF.md "Submodule re-pin procedure").
"""

from __future__ import annotations

EXPECTED_GENERATOR_PIN = "eea91b06e2ec5d053eca3a5696656fdd354a05f9"
EXPECTED_GENERATOR_PIN_LABEL = "WP24: make internal concept ids advisory"

__all__ = ["EXPECTED_GENERATOR_PIN", "EXPECTED_GENERATOR_PIN_LABEL"]
