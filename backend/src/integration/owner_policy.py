"""Owner integration policy (WP17 section 6).

Single source of truth, in the OUTER repository, for the owner decisions that
govern how generated (LLM) questions participate in an exam. Nothing here is
stored in the generator submodule. These are contracts for WP18+; WP17 only
freezes and tests them.
"""

from __future__ import annotations

from decimal import Decimal

__all__ = [
    "GENERATED_QUESTIONS_ARE_EXAM_SESSION_ONLY",
    "AUTO_INSERT_GENERATED_INTO_DB",
    "MAX_ATTEMPTS_PER_LLM_SLOT",
    "DEFAULT_PER_EXAM_COST_CAP_USD",
    "PER_EXAM_COST_CAP_EDITABLE",
    "MIN_SUPPORTED_LLM_QUESTIONS",
    "ANSWER_RANDOMIZATION_OWNER",
    "PRESERVE_SUCCESSFUL_PARTIAL_WORK",
    "FAILED_SLOTS_ARE_RETRYABLE",
    "c_to_ab",
    "ab_to_c",
    "next_pair_is_within_cap",
]

# --- DB ownership --------------------------------------------------------------
#: Generated questions live only in the exam session. They are NEVER written
#: back into the question bank automatically.
GENERATED_QUESTIONS_ARE_EXAM_SESSION_ONLY = True
AUTO_INSERT_GENERATED_INTO_DB = False

# --- Attempt budget ---------------------------------------------------------
#: At most two generation attempts per requested LLM slot (a rejected attempt is
#: never carried forward as prior input).
MAX_ATTEMPTS_PER_LLM_SLOT = 2

# --- Cost ceiling ---------------------------------------------------------------
#: Editable per-exam spend cap. Default $5.00.
DEFAULT_PER_EXAM_COST_CAP_USD = Decimal("5.00")
PER_EXAM_COST_CAP_EDITABLE = True

#: Preflight must estimate/warn before a run and must support at least this many
#: LLM questions in one exam.
MIN_SUPPORTED_LLM_QUESTIONS = 20

# --- Randomisation ownership ------------------------------------------------
#: The existing exam / DOCX code remains responsible for answer randomisation.
#: The adapter and DTO keep ``correct_answer`` exactly as the generator returns
#: it (position 1) and do not shuffle.
ANSWER_RANDOMIZATION_OWNER = "exam_docx"

# --- Partial-work / retry policy ------------------------------------------------
PRESERVE_SUCCESSFUL_PARTIAL_WORK = True
FAILED_SLOTS_ARE_RETRYABLE = True


def c_to_ab(total: int) -> tuple[int, int]:
    """Editing the combined count C yields A=ceil(C/2) DB, B=floor(C/2) LLM."""
    if total < 0:
        raise ValueError("total must be non-negative")
    a = (total + 1) // 2
    b = total // 2
    return a, b


def ab_to_c(database: int, llm: int) -> int:
    """Editing A or B yields C = A + B."""
    if database < 0 or llm < 0:
        raise ValueError("database and llm must be non-negative")
    return database + llm


def next_pair_is_within_cap(
    actual_spend_usd: Decimal,
    conservative_next_pair_usd: Decimal,
    cap_usd: Decimal,
) -> bool:
    """Cost-ceiling rule: allow the next slot only if actual spend so far plus a
    conservative estimate of ONE more complete generation+review pair stays at or
    under the cap. Not the sum of all hypothetical retries.
    """
    return (Decimal(actual_spend_usd) + Decimal(conservative_next_pair_usd)) <= Decimal(cap_usd)
