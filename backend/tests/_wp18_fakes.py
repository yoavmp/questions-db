"""Offline fake providers + helpers for the WP18 job tests.

No network, no key. A fake provider builds *valid* candidates for a real
generator context (using the generator's own published loaders to get real
term/unit ids), so ``generate_exam_question`` runs its whole pipeline and
accepts them. A category-dispatching wrapper lets one ``provider_factory``
serve a multi-category job.
"""

from __future__ import annotations

import itertools
from functools import lru_cache
from pathlib import Path

#: monotonic across the whole test session so every fake candidate is textually
#: unique (a fresh provider instance keeps producing new questions).
_UNIQ = itertools.count(1)

_REPO = Path(__file__).resolve().parents[2]
_GEN = _REPO / "exam_generator"

CONTEXT_BY_NAME = {
    "היסטולוגיה": "chapter_09",
    "גרעיני הבסיס": "chapter_07",
    "מבוא": "chapter_01",
    "אמבריולוגיה": "chapter_03",
}


@lru_cache(maxsize=None)
def _inputs(context_id: str, category_name: str):
    from exam_generator.llm_config import load_llm_config
    from exam_generator.runtime_inputs import build_runtime_inputs

    cfg = load_llm_config(_GEN / "config/llm.yaml")
    return build_runtime_inputs(
        category_id=context_id, category_name=category_name,
        required_model=cfg.generation.model,
        llm_config_path=_GEN / "config/llm.yaml",
        terms_path=_GEN / "config/terminology.yaml",
        catalog_path=_GEN / "config/categories.json",
        index_dir=_GEN / "Data/index",
        pdf_path=_GEN / "Data/Course_Material_Summary.pdf",
        source_facts_path=_GEN / "config/source_fact_corrections.yaml",
        prompts_root=_GEN,
    )


def _candidate(context_id: str, category_name: str, i: int, cid: str):
    from exam_generator.generation_models import (
        ConceptMention, GroundingEvidence, QuestionCandidate,
    )

    inp = _inputs(context_id, category_name)
    recs = [r for r in inp.records if r.allowed_english]
    rec = recs[i % len(recs)]
    unit = inp.units[i % len(inp.units)]
    eng = rec.allowed_english[0]
    return QuestionCandidate(
        candidate_id=cid,
        question=f"מהו התפקיד של {eng} מספר {i}?",
        correct_answer=eng,
        distractors=["מסיח סינתטי אלפא", "מסיח סינתטי בטא", "מסיח סינתטי גמא"],
        rationale="נימוק לבדיקה בלבד, מבוסס על יחידת המקור המצוטטת.",
        evidence=[GroundingEvidence(page=unit.page, source_unit_id=unit.source_unit_id, quote=unit.text[:40])],
        concept_mentions=[ConceptMention(term_id=rec.term_id, surface=eng, field="question")],
        learning_objective=f"זיהוי התפקיד של {eng}, פריט {i}",
        focus_concept_ids=[rec.term_id],
        focus_correction_ids=[],
    )


class ApprovingProvider:
    """Accepts every candidate; builds the reviewer comparison set from the
    request's actual previous-question numbers (so repeated / non-monotonic
    numbers pass the generator's list-equality check)."""

    name = "fake-approving"

    def __init__(self):
        self.generation_calls = 0
        self.review_calls = 0
        self._i = 0

    def generate_candidates(self, request, *, prompts):
        self.generation_calls += 1
        u = next(_UNIQ)
        cid = f"c{u}"
        cand = _candidate(request.category_id, request.category_name, u, cid)
        from exam_generator.generation_models import CandidateBatch

        self._last_cid = cid
        return CandidateBatch(requested_count=1, candidates=[cand])

    def review_candidates(self, request, *, prompts):
        self.review_calls += 1
        from exam_generator.generation_models import (
            CandidateReview, PriorQuestionComparison, ReviewResult,
        )

        priors = [p.number for p in getattr(request, "previous_questions", [])]
        cid = getattr(self, "_last_cid", "c0")
        review = CandidateReview(
            candidate_id=cid, grounded_in_context=True, avoids_superseded_source_facts=True,
            category_relevant=True, exactly_one_correct_answer=True,
            distractors_incorrect_and_plausible=True, distinct_from_previous_and_siblings=True,
            hebrew_is_clear=True, required_english_preserved=True, no_undeclared_hebrew_paraphrase=True,
            self_contained=True, semantically_distinct_from_previous=True,
            previous_comparisons=[
                PriorQuestionComparison(prior_number=n, same_learning_target=False,
                                        overlap_type="none", reason="עוסק בעובדה שונה לחלוטין",
                                        confidence=0.95)
                for n in priors
            ],
            confidence=0.95, reason="כל הקריטריונים עברו.",
            post_repair_approved=True, answer_identity_preserved=True,
        )
        return ReviewResult(reviews=[review], selected_candidate_id=cid)


class WarningAcceptingProvider(ApprovingProvider):
    """WP28: accepts every candidate, but every review carries exactly one
    structured distractor warning (the candidate is still a full acceptance
    -- ``distractors_incorrect_and_plausible=True``)."""

    name = "fake-warning-accepting"

    def review_candidates(self, request, *, prompts):
        self.review_calls += 1
        from exam_generator.generation_models import (
            CandidateReview, DistractorSupport, DistractorWarning,
            PriorQuestionComparison, ReviewResult,
        )

        priors = [p.number for p in getattr(request, "previous_questions", [])]
        cid = getattr(self, "_last_cid", "c0")
        review = CandidateReview(
            candidate_id=cid, grounded_in_context=True, avoids_superseded_source_facts=True,
            category_relevant=True, exactly_one_correct_answer=True,
            distractors_incorrect_and_plausible=True, distinct_from_previous_and_siblings=True,
            hebrew_is_clear=True, required_english_preserved=True, no_undeclared_hebrew_paraphrase=True,
            self_contained=True, semantically_distinct_from_previous=True,
            previous_comparisons=[
                PriorQuestionComparison(prior_number=n, same_learning_target=False,
                                        overlap_type="none", reason="עוסק בעובדה שונה לחלוטין",
                                        confidence=0.95)
                for n in priors
            ],
            distractor_support=[
                DistractorSupport(field="distractor_3", evidence_mode="source_mentioned",
                                   reason="מושג אמיתי ומעוגן-מקור, אך מסוג שונה ממה שהשאלה מבקשת."),
            ],
            distractor_warnings=[
                DistractorWarning(code="weak_distractor_type_mismatch", field="distractor_3",
                                   message_he="מסיח 4 אינו מן הסוג שגוף השאלה מבקש."),
            ],
            confidence=0.95, reason="כל הקריטריונים עברו, מסיח אחד חלש.",
            post_repair_approved=True, answer_identity_preserved=True,
        )
        return ReviewResult(reviews=[review], selected_candidate_id=cid)


class DistractorHardRejectThenAcceptProvider(ApprovingProvider):
    """WP28: the FIRST review call hard-rejects on a distractor-quality
    defect (``distractors_incorrect_and_plausible=False`` +
    ``distractor_support``); every later call accepts normally -- for
    proving a later attempt/operation receives the resulting bounded
    hard-rejection feedback."""

    name = "fake-hard-reject-then-accept"

    def __init__(self):
        super().__init__()
        self._rejected_once = False

    def review_candidates(self, request, *, prompts):
        self.review_calls += 1
        if not self._rejected_once:
            self._rejected_once = True
            from exam_generator.generation_models import (
                CandidateReview, DistractorSupport, ReviewResult,
            )

            cid = getattr(self, "_last_cid", "c0")
            review = CandidateReview(
                candidate_id=cid, grounded_in_context=True, avoids_superseded_source_facts=True,
                category_relevant=True, exactly_one_correct_answer=True,
                distractors_incorrect_and_plausible=False, distinct_from_previous_and_siblings=True,
                hebrew_is_clear=True, required_english_preserved=True, no_undeclared_hebrew_paraphrase=True,
                self_contained=True, semantically_distinct_from_previous=True,
                previous_comparisons=[], distractor_support=[
                    DistractorSupport(field="distractor_1", evidence_mode="none",
                                       reason="אינו מופיע כלל בחומר המקור הרלוונטי."),
                ],
                confidence=0.9, reason="מסיח מומצא, אינו מעוגן במקור.",
                post_repair_approved=False, answer_identity_preserved=True,
            )
            return ReviewResult(reviews=[review], selected_candidate_id=None,
                                 no_selection_reason="distractor not grounded")
        return super().review_candidates(request, prompts=prompts)


class RejectingProvider(ApprovingProvider):
    """Generates a valid candidate but the reviewer fails it (a real, non-systemic
    rejection)."""

    name = "fake-rejecting"

    def review_candidates(self, request, *, prompts):
        self.review_calls += 1
        from exam_generator.generation_models import (
            CandidateReview, ReviewResult,
        )

        cid = getattr(self, "_last_cid", "c0")
        review = CandidateReview(
            candidate_id=cid, grounded_in_context=False, avoids_superseded_source_facts=True,
            category_relevant=True, exactly_one_correct_answer=True,
            distractors_incorrect_and_plausible=True, distinct_from_previous_and_siblings=True,
            hebrew_is_clear=True, required_english_preserved=True, no_undeclared_hebrew_paraphrase=True,
            self_contained=True, semantically_distinct_from_previous=True,
            previous_comparisons=[], confidence=0.9, reason="לא מבוסס בהקשר.",
            post_repair_approved=False, answer_identity_preserved=True,
        )
        return ReviewResult(reviews=[review], selected_candidate_id=None, no_selection_reason="rejected")


class Dispatch:
    """One provider object that routes each call to a per-category delegate,
    creating an :class:`ApprovingProvider` on first use of a category."""

    name = "fake-dispatch"

    def __init__(self, factory=ApprovingProvider, overrides=None):
        self._factory = factory
        self._overrides = overrides or {}
        self.by_context: dict = {}

    def _for(self, context_id):
        if context_id in self._overrides:
            return self._overrides[context_id]
        return self.by_context.setdefault(context_id, self._factory())

    def generate_candidates(self, request, *, prompts):
        return self._for(request.category_id).generate_candidates(request, prompts=prompts)

    def review_candidates(self, request, *, prompts):
        return self._for(request.category_id).review_candidates(request, prompts=prompts)


def approving_factory():
    d = Dispatch()
    return lambda: d


def dispatch_factory(dispatch: Dispatch):
    return lambda: dispatch
