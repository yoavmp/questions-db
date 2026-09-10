"""Read-only adapter to the pinned exam generator (WP17 section 5).

This adapter *imports and invokes* the pinned generator's published one-question
primitive (``exam_generator.orchestrator.generate_one_question``) after
assembling its inputs from the generator's own published loaders. It does not:

* copy or vendor generator code;
* invoke a WP runner (``live_run*`` / ``wp*_commands``);
* shell out / use a subprocess or the CLI.

It preserves the generator's WP16R behaviour end to end -- generation -> combined
review -> safe deterministic/reviewer repair -> validation -- because that whole
pipeline lives inside ``generate_one_question``; the adapter only feeds it and
classifies its result. Model choice stays dynamic (from
``exam_generator/config/llm.yaml``) and provider-side response storage stays
disabled (``store: false``, enforced by the generator's own config loader and
re-asserted here).

Paths are resolved from this file's location, so the adapter works from any
backend working directory.

--------------------------------------------------------------------------------
MISSING CONSOLIDATED BOUNDARY (WP17 section 5, "lacks a suitable public Python
boundary"):

The pinned generator has NO single production entrypoint that takes
(canonical category, question number, previous seven-field questions, attempt /
cost budget, audit destination) and returns an accepted seven-field question +
audit/cost or a typed failure. ``generate_one_question`` needs a pre-assembled
context package, terminology records, provider, config and prompt library; the
only code that assembles those today is inside the WP live-runners
(``live_run.build_live_inputs`` etc.), which WP17 forbids calling.

This adapter therefore re-implements that assembly in the OUTER repo from the
generator's *published, non-runner* functions. That is a deliberate, documented
stopgap. A dedicated generator work package should expose, e.g.:

    exam_generator.production.generate_exam_question(
        *, category_name, number, previous_public_questions,
        max_attempts, cost_ceiling_usd, price_snapshot, audit_dir, provider=None,
    ) -> ExamQuestionResult   # seven fields + audit + cost, or typed failure

including the cost preflight / ceiling enforcement and audit writing that this
adapter can only partially reproduce offline. Until then, keep this adapter and
its assembly in lock-step with the generator's runners on every re-pin.
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import os
import sys
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
]

FailureKind = Literal[
    "question_rejected",
    "provider_output_failure",
    "systemic_failure",
    "cost_ceiling",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GENERATOR_ROOT = _REPO_ROOT / "exam_generator"
_GENERATOR_SRC = _GENERATOR_ROOT / "src"


def generator_paths() -> dict:
    """Absolute paths the adapter depends on (for diagnostics / tests)."""
    return {
        "repo_root": str(_REPO_ROOT),
        "generator_root": str(_GENERATOR_ROOT),
        "generator_src": str(_GENERATOR_SRC),
        "llm_config": str(_GENERATOR_ROOT / "config" / "llm.yaml"),
        "catalog": str(_GENERATOR_ROOT / "config" / "categories.json"),
        "terminology": str(_GENERATOR_ROOT / "config" / "terminology.yaml"),
        "source_facts": str(_GENERATOR_ROOT / "config" / "source_fact_corrections.yaml"),
        "index_dir": str(_GENERATOR_ROOT / "Data" / "index"),
        "prompts_dir": str(_GENERATOR_ROOT / "prompts"),
    }


def _ensure_importable() -> None:
    src = str(_GENERATOR_SRC)
    if not (_GENERATOR_SRC / "exam_generator" / "__init__.py").is_file():
        raise _Systemic(
            f"pinned generator package not found under {_GENERATOR_SRC}; "
            f"run `git submodule update --init --recursive`"
        )
    if src not in sys.path:
        sys.path.insert(0, src)


class _Systemic(RuntimeError):
    """Internal: any pre-provider assembly failure -> systemic_failure."""


@dataclass(frozen=True)
class AdapterRequest:
    canonical_category: str
    question_number: int
    #: every previous accepted question for THIS category, already projected to
    #: the exact seven public fields (number, question, answer1..4, correct_answer)
    previous_questions: list = field(default_factory=list)
    #: attempt budget for this one slot (owner policy: 2)
    attempt_budget: int = 2
    #: per-exam cost ceiling still available to this slot
    cost_ceiling_usd: Decimal = Decimal("5.00")
    #: conservative cost of the next complete generation+review pair, if known
    #: (offline preflight). When provided and it would breach the ceiling, the
    #: adapter returns ``cost_ceiling`` and makes no provider call.
    conservative_next_pair_usd: Optional[Decimal] = None
    actual_spend_usd: Decimal = Decimal("0")
    #: where the generator audit JSON should be written (caller-owned dir)
    audit_dir: Optional[str] = None


@dataclass
class AdapterResult:
    status: Literal["accepted"] | FailureKind
    question: Optional[dict] = None            # seven public fields, when accepted
    was_repaired: bool = False
    reviewer_confidence: Optional[float] = None
    attempts: int = 0
    generation_calls: int = 0
    review_calls: int = 0
    cost_usd: str = "0"
    audit: Optional[dict] = None
    audit_path: Optional[str] = None
    failure_reason: Optional[str] = None
    rejected_candidate_ids: list = field(default_factory=list)

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
    ``exam_generator.providers.ScriptedFakeProvider``). If it is ``None`` and the
    configured provider is not ``fake`` and no ``OPENAI_API_KEY`` is present, the
    adapter returns ``systemic_failure`` and makes no network call.
    """
    # --- cost-ceiling short-circuit (no generator import, no provider call) ---
    if request.conservative_next_pair_usd is not None:
        projected = Decimal(request.actual_spend_usd) + Decimal(request.conservative_next_pair_usd)
        if projected > Decimal(request.cost_ceiling_usd):
            return AdapterResult(
                status="cost_ceiling",
                failure_reason=(
                    f"actual ${request.actual_spend_usd} + next pair "
                    f"${request.conservative_next_pair_usd} exceeds ceiling "
                    f"${request.cost_ceiling_usd}; no call made"
                ),
            )

    try:
        _ensure_importable()
        from src.integration.category_map import resolve_generator_context

        from exam_generator.catalog import load_catalog
        from exam_generator.context_builder import load_context_package
        from exam_generator.generation_models import PreviousQuestion
        from exam_generator.llm_config import load_llm_config
        from exam_generator.orchestrator import (
            corrected_source_facts,
            generate_one_question,
        )
        from exam_generator.prompts import PromptLibrary
        from exam_generator.providers import ProviderError
        from exam_generator.terminology import (
            load_index_manifest,
            load_terminology,
            validate_terminology,
        )
    except _Systemic as exc:
        return AdapterResult(status="systemic_failure", failure_reason=str(exc))
    except Exception as exc:  # import-time failure of the generator package
        return AdapterResult(
            status="systemic_failure",
            failure_reason=f"cannot import pinned generator: {exc!r}",
        )

    try:
        context_id = resolve_generator_context(request.canonical_category)

        cfg_path = Path(llm_config_path) if llm_config_path else _GENERATOR_ROOT / "config" / "llm.yaml"
        config = load_llm_config(cfg_path)

        # store:false is non-negotiable (re-assert on top of the loader's own check)
        if config.response_storage.store:
            raise _Systemic("llm config resolves to response_storage.store=true; refused")

        # dynamic attempt budget (owner policy), never a model change
        budget = max(1, min(int(request.attempt_budget), 5))
        config = config.model_copy(
            update={"limits": config.limits.model_copy(update={"max_generation_attempts": budget})}
        )

        # provider: injected (tests) or built from config; never silently reach the network
        prov = provider
        if prov is None:
            if config.provider == "fake":
                from exam_generator.providers import build_provider

                prov = build_provider(config)
            elif not os.environ.get("OPENAI_API_KEY", "").strip():
                return AdapterResult(
                    status="systemic_failure",
                    failure_reason="no provider injected and OPENAI_API_KEY absent; no call made",
                )
            else:
                from exam_generator.providers import build_provider

                prov = build_provider(config)

        prompts = PromptLibrary.from_config(config, root=_GENERATOR_ROOT)
        catalog = load_catalog(_GENERATOR_ROOT / "config" / "categories.json")

        index_dir = _GENERATOR_ROOT / "Data" / "index"
        if not index_dir.is_dir():
            raise _Systemic(
                f"generator source index missing at {index_dir}; supply "
                f"exam_generator/Data/index (git-ignored runtime input)"
            )
        inventory = load_terminology(_GENERATOR_ROOT / "config" / "terminology.yaml")
        report = validate_terminology(
            inventory,
            catalog,
            pdf_path=_GENERATOR_ROOT / "Data" / "Course_Material_Summary.pdf",
            index_manifest=load_index_manifest(index_dir),
        )
        package, _cm = load_context_package(index_dir, context_id)
        if package.get("category_id") != context_id:
            raise _Systemic(f"context package is {package.get('category_id')!r}, expected {context_id!r}")
        if not package.get("term_fidelity_approved"):
            raise _Systemic(f"generator context {context_id!r} is not strict-ready")

        category_terms = report.terms_for_category.get(context_id, [])
        all_terms = list(inventory.terms)

        source_facts_path = _GENERATOR_ROOT / "config" / "source_fact_corrections.yaml"
        source_facts = []
        if source_facts_path.is_file():
            from exam_generator.source_facts import load_source_facts

            source_facts = corrected_source_facts(load_source_facts(source_facts_path), context_id)

        previous: list = []
        for i, pq in enumerate(request.previous_questions, 1):
            missing = [f for f in _SEVEN if f not in pq]
            if missing:
                raise _Systemic(f"previous question #{i} missing public fields {missing}")
            previous.append(PreviousQuestion.model_validate({f: pq[f] for f in _SEVEN}))

    except _Systemic as exc:
        return AdapterResult(status="systemic_failure", failure_reason=str(exc))
    except Exception as exc:
        return AdapterResult(
            status="systemic_failure",
            failure_reason=f"generator input assembly failed: {exc!r}",
        )

    # --- the pinned generator's own one-question pipeline --------------------
    try:
        outcome, audit = generate_one_question(
            category_id=context_id,
            category_name=package["name"],
            context_package=package,
            category_terms=category_terms,
            all_terms=all_terms,
            previous_questions=previous,
            provider=prov,
            config=config,
            prompts=prompts,
            ambiguous_shared_variants=report.ambiguous_shared_variants,
            source_facts=source_facts,
        )
    except ProviderError as exc:
        return AdapterResult(status="systemic_failure", failure_reason=f"provider error: {exc}")
    except Exception as exc:
        return AdapterResult(status="systemic_failure", failure_reason=f"generator raised: {exc!r}")

    audit_obj = audit.to_json_obj()
    audit_path = None
    if request.audit_dir:
        import json

        d = Path(request.audit_dir)
        d.mkdir(parents=True, exist_ok=True)
        audit_path = str(d / f"question_audit_{context_id}_{request.question_number}.json")
        Path(audit_path).write_text(
            json.dumps(audit_obj, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )

    # classify the generator outcome
    from exam_generator.orchestrator import ApprovedQuestionCandidate  # local import

    if isinstance(outcome, ApprovedQuestionCandidate):
        cand = outcome.candidate
        seven = {
            "number": request.question_number,
            "question": cand.question,
            "answer1": cand.correct_answer,
            "answer2": cand.distractors[0],
            "answer3": cand.distractors[1],
            "answer4": cand.distractors[2],
            "correct_answer": 1,
        }
        return AdapterResult(
            status="accepted",
            question=seven,
            was_repaired=outcome.was_repaired,
            reviewer_confidence=outcome.reviewer_confidence,
            attempts=len(audit.attempts),
            generation_calls=audit.generation_calls,
            review_calls=audit.review_calls,
            audit=audit_obj,
            audit_path=audit_path,
        )

    # GenerationFailure -> typed failure. The generator's own failure_kind is
    # authoritative ("question_rejected" | "provider_output_failure" |
    # "systemic_failure"); "cost_ceiling" is only ever raised by this adapter.
    kind = getattr(outcome, "failure_kind", "question_rejected")
    if kind not in ("question_rejected", "provider_output_failure", "systemic_failure"):
        kind = "question_rejected"
    return AdapterResult(
        status=kind,  # type: ignore[arg-type]
        attempts=len(audit.attempts),
        generation_calls=audit.generation_calls,
        review_calls=audit.review_calls,
        audit=audit_obj,
        audit_path=audit_path,
        failure_reason=getattr(outcome, "reason", "generation failed"),
        rejected_candidate_ids=list(getattr(outcome, "rejected_candidate_ids", []) or []),
    )
