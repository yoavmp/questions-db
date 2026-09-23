"""Thin adapter over the pinned generator's production one-question API (WP18 §1).

WP17 shipped a *stopgap* adapter that re-implemented the generator's input
assembly in this repo because the generator had no consolidated production
entrypoint. WP17G/WP17GR added one:

    exam_generator.production.generate_exam_question(
        *, category_name, number, previous_public_questions, cost_ceiling_usd,
        audit_dir, max_attempts=2, provider=None,
        pricing_stale_after_days=30, <path overrides> ,
    ) -> ProductionGenerationResult

This module is now a **thin** adapter over that function. It does NOT:

* copy or vendor generator pipeline logic;
* invoke a WP runner (``live_run*`` / ``wp*_commands``);
* shell out / use a subprocess or the CLI;
* manipulate ``sys.path`` -- the generator package is installed into the
  environment by the documented root install flow (``scripts/dev_install.sh``);
  if it is not importable the adapter fails closed as ``systemic_failure``.

It only: resolves the canonical category, points the generator at the submodule's
own config/data, forwards an injected provider (tests) or lets the generator
build its own, and maps the typed :class:`ProductionGenerationResult` onto the
:class:`AdapterResult` the rest of the backend already consumes.

Paths are resolved from this file's location, so the adapter works from any
backend working directory.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional

__all__ = [
    "AdapterRequest",
    "AdapterResult",
    "FailureKind",
    "generate_category_question",
    "generator_paths",
    "GENERATOR_IMPORT_ERROR",
]

FailureKind = Literal[
    "question_rejected",
    "provider_output_failure",
    "systemic_failure",
    "cost_ceiling",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
#: Module attribute (not a constant) so tests can monkeypatch it to point the
#: adapter at an empty tree and prove the fail-closed path.
_GENERATOR_ROOT = _REPO_ROOT / "exam_generator"
_GENERATOR_SRC = _GENERATOR_ROOT / "src"

#: Set at import time if ``exam_generator.production`` cannot be imported. The
#: readiness service reports this; every adapter call fails closed with it.
GENERATOR_IMPORT_ERROR: Optional[str] = None
try:  # pragma: no cover - import availability is environment-dependent
    from exam_generator.production import generate_exam_question as _generate_exam_question
except Exception as _exc:  # noqa: BLE001 - any import failure disables LLM only
    _generate_exam_question = None  # type: ignore[assignment]
    GENERATOR_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"


def generator_paths() -> dict:
    """Absolute paths the adapter depends on (for diagnostics / tests)."""
    root = _GENERATOR_ROOT
    return {
        "repo_root": str(_REPO_ROOT),
        "generator_root": str(root),
        "generator_src": str(_GENERATOR_SRC),
        "llm_config": str(root / "config" / "llm.yaml"),
        "catalog": str(root / "config" / "categories.json"),
        "terminology": str(root / "config" / "terminology.yaml"),
        "source_facts": str(root / "config" / "source_fact_corrections.yaml"),
        "pricing": str(root / "config" / "pricing.yaml"),
        "index_dir": str(root / "Data" / "index"),
        "pdf": str(root / "Data" / "Course_Material_Summary.pdf"),
        "prompts_dir": str(root / "prompts"),
    }


@dataclass(frozen=True)
class AdapterRequest:
    canonical_category: str
    question_number: int
    #: every previous question for THIS category (accepted LLM + selected DB +
    #: retained/discarded history), already projected to the exact seven public
    #: fields. Order and repeated ``number`` values are preserved as given.
    previous_questions: list = field(default_factory=list)
    #: attempt budget for this one slot (owner policy: 2; generator clamps 1..2)
    attempt_budget: int = 2
    #: the budget still available to this slot == cap - accumulated job cost
    cost_ceiling_usd: Decimal = Decimal("5.00")
    #: optional pre-import short-circuit (kept from WP17): a caller-supplied
    #: conservative estimate of the next complete generation+review pair. When
    #: given and ``actual_spend + this`` would breach the ceiling, the adapter
    #: returns ``cost_ceiling`` and imports/calls nothing.
    conservative_next_pair_usd: Optional[Decimal] = None
    actual_spend_usd: Decimal = Decimal("0")
    #: where the generator writes its redacted audit (caller-owned dir)
    audit_dir: Optional[str] = None
    #: pricing staleness threshold in days (owner policy default 30)
    pricing_stale_after_days: int = 30
    #: WP28 §B2 -- bounded, structured hard-rejection records (the generator's
    #: own ``HardRejectionFeedback`` shape) from prior same-category
    #: operations, forwarded as-is to the generator so it never repeats an
    #: already-demonstrated defect. Never defines semantic exclusion, never
    #: bans a topic.
    hard_rejection_feedback: list = field(default_factory=list)


@dataclass
class AdapterResult:
    status: Literal["accepted"] | FailureKind
    question: Optional[dict] = None            # seven public fields, when accepted
    was_repaired: bool = False
    reviewer_confidence: Optional[float] = None
    attempts: int = 0
    retries: int = 0
    generation_calls: int = 0
    review_calls: int = 0
    cost_usd: str = "0"
    total_cost_basis: str = "none"
    itemized_cost: list = field(default_factory=list)
    remaining_cost_usd: Optional[str] = None
    pricing_verification: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    audit: Optional[dict] = None
    audit_path: Optional[str] = None
    failure_reason: Optional[str] = None
    rejected_candidate_ids: list = field(default_factory=list)
    #: WP28 §B1 -- ``"clean"`` or ``"warning"`` when ``status == "accepted"``.
    review_quality: str = "clean"
    #: WP28 §B1 -- the (0 or 1) structured distractor warning(s), remapped to
    #: the public field the generator's seven-field mapping always uses
    #: (``correct_answer`` -> ``answer1``, ``distractor_1..3`` ->
    #: ``answer2..4``): ``{"code", "field", "message_he"}``.
    review_warnings: list = field(default_factory=list)
    #: WP28 §B2 -- bounded, structured hard-rejection records produced by
    #: *this* call's own failed attempts (never the ones supplied as input).
    hard_rejection_feedback: list = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


_SEVEN = ("number", "question", "answer1", "answer2", "answer3", "answer4", "correct_answer")


def generate_category_question(
    request: AdapterRequest,
    *,
    provider: Any | None = None,
    llm_config_path: str | Path | None = None,
) -> AdapterResult:
    """Produce one accepted seven-field question for ``request`` or a typed failure.

    ``provider`` is injected in tests (a network-blocked
    ``exam_generator.providers.ScriptedFakeProvider``). When it is ``None`` the
    generator constructs its own OpenAI provider; with no ``OPENAI_API_KEY`` in
    the environment it returns ``systemic_failure`` and makes no network call
    (that check lives inside ``generate_exam_question``).
    """
    # --- pre-import cost-ceiling short-circuit (no generator import, no call) --
    if request.conservative_next_pair_usd is not None:
        projected = Decimal(request.actual_spend_usd) + Decimal(request.conservative_next_pair_usd)
        if projected > Decimal(request.cost_ceiling_usd):
            return AdapterResult(
                status="cost_ceiling",
                remaining_cost_usd=str(Decimal(request.cost_ceiling_usd) - Decimal(request.actual_spend_usd)),
                failure_reason=(
                    f"actual ${request.actual_spend_usd} + next pair "
                    f"${request.conservative_next_pair_usd} exceeds ceiling "
                    f"${request.cost_ceiling_usd}; no call made"
                ),
            )

    if _generate_exam_question is None:
        return AdapterResult(
            status="systemic_failure",
            failure_reason=(
                "pinned generator is not importable "
                f"({GENERATOR_IMPORT_ERROR}); run scripts/dev_install.sh"
            ),
        )

    root = _GENERATOR_ROOT
    cfg = Path(llm_config_path) if llm_config_path else root / "config" / "llm.yaml"
    audit_dir = request.audit_dir or tempfile.mkdtemp(prefix="wp18_adapter_audit_")

    try:
        previous = _project_previous(request.previous_questions)
    except ValueError as exc:
        return AdapterResult(status="systemic_failure", failure_reason=str(exc))

    try:
        result = _generate_exam_question(
            category_name=request.canonical_category,
            number=int(request.question_number),
            previous_public_questions=previous,
            cost_ceiling_usd=Decimal(request.cost_ceiling_usd),
            audit_dir=audit_dir,
            max_attempts=max(1, min(int(request.attempt_budget), 2)),
            provider=provider,
            llm_config_path=cfg,
            terms_path=root / "config" / "terminology.yaml",
            catalog_path=root / "config" / "categories.json",
            index_dir=root / "Data" / "index",
            pdf_path=root / "Data" / "Course_Material_Summary.pdf",
            source_facts_path=root / "config" / "source_fact_corrections.yaml",
            pricing_path=root / "config" / "pricing.yaml",
            pricing_stale_after_days=int(request.pricing_stale_after_days),
            hard_rejection_feedback=list(request.hard_rejection_feedback or []),
        )
    except ValueError as exc:
        # unknown category / bad argument -> caller error surfaced as systemic
        return AdapterResult(status="systemic_failure", failure_reason=f"invalid generator request: {exc}")
    except Exception as exc:  # noqa: BLE001 - any generator-side blow-up fails closed
        return AdapterResult(status="systemic_failure", failure_reason=f"generator raised: {type(exc).__name__}: {exc}")

    return _to_adapter_result(result)


def _project_previous(previous_questions: list) -> list[dict]:
    out: list[dict] = []
    for i, pq in enumerate(previous_questions, 1):
        if not isinstance(pq, dict):
            raise ValueError(f"previous question #{i} is not an object")
        missing = [f for f in _SEVEN if f not in pq]
        if missing:
            raise ValueError(f"previous question #{i} missing public fields {missing}")
        out.append({f: pq[f] for f in _SEVEN})
    return out


#: WP28 §B1: the generator's internal distractor field naming -> the public
#: field it always lands on, given the fixed seven-field mapping
#: (``exam_generator.sequence._to_public_question``: correct answer always
#: ``answer1``, distractors always ``answer2..4`` in order).
_GENERATOR_FIELD_TO_PUBLIC = {
    "correct_answer": "answer1",
    "distractor_1": "answer2",
    "distractor_2": "answer3",
    "distractor_3": "answer4",
    "question": "question",
}


def _remap_review_warnings(raw: list) -> list[dict]:
    out = []
    for w in raw or []:
        w = dict(w)
        w["field"] = _GENERATOR_FIELD_TO_PUBLIC.get(w.get("field"), w.get("field"))
        out.append(w)
    return out


def _to_adapter_result(result: Any) -> AdapterResult:
    """Map a generator ``ProductionGenerationResult`` onto ``AdapterResult``."""
    common = dict(
        attempts=int(getattr(result, "attempts", 0)),
        retries=int(getattr(result, "retries", 0)),
        generation_calls=int(getattr(result, "generation_calls", 0)),
        review_calls=int(getattr(result, "review_calls", 0)),
        cost_usd=str(getattr(result, "total_cost_usd", "0")),
        total_cost_basis=str(getattr(result, "total_cost_basis", "none")),
        itemized_cost=[
            c.to_json_obj() if hasattr(c, "to_json_obj") else dict(c)
            for c in getattr(result, "itemized_cost", [])
        ],
        remaining_cost_usd=str(getattr(result, "remaining_cost_usd", None)),
        pricing_verification=dict(getattr(result, "pricing_verification", {}) or {}),
        warnings=[dict(w) for w in getattr(result, "warnings", []) or []],
        audit=None,
        audit_path=str(getattr(result, "audit_dir", "") or "") or None,
        # WP28 §B2: only records newly produced by this call, unconditionally
        # -- present on both success and failure, since a caller may need
        # them even for a failed attempt (e.g. replace_llm keeping the old
        # question while still learning from the failed attempt).
        hard_rejection_feedback=[
            dict(r) for r in getattr(result, "hard_rejection_feedback", []) or []
        ],
    )

    if getattr(result, "status", None) == "success":
        return AdapterResult(
            status="accepted",
            question=dict(result.question) if result.question else None,
            was_repaired=bool(getattr(result, "was_repaired", False)),
            review_quality=str(getattr(result, "review_quality", "clean")),
            review_warnings=_remap_review_warnings(getattr(result, "review_warnings", [])),
            **common,
        )

    kind = getattr(result, "failure_kind", None) or getattr(result, "status", "question_rejected")
    if kind not in ("question_rejected", "provider_output_failure", "systemic_failure", "cost_ceiling"):
        kind = "question_rejected"
    return AdapterResult(
        status=kind,  # type: ignore[arg-type]
        failure_reason=getattr(result, "failure_reason", None) or f"generation failed ({kind})",
        **common,
    )
