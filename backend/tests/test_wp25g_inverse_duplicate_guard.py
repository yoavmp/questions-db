"""WP25G -- the displaced question reaches its own replacement's context.

An accepted question was displaced by a "replacement" that tested the exact
same fact with the stem and answer roles reversed:

    displaced (accepted):
        "איזה מבנה מאפשר זרימה חד־כיוונית וסלקטיבית של CSF מן החלל
        הסאב־אראכנואידי אל הסינוסים?" -> Arachnoid Villi

    accepted replacement (the bug):
        "מהו כיוון הזרימה החד-כיוונית של CSF המתווך באמצעות Arachnoid Villi?"
        -> "מן החלל הסאב-אראכנואידי אל הסינוסים."

Both texts are the real, preserved public seven-field wording from the live
incident (``artifacts/exam_jobs/14f2a1ea-.../job.json``, read only, never
modified) -- not a raw provider response, not a prompt, not source PDF text.

WP25G Section 1's root-cause finding: ``replace_via_llm`` builds its
``previous`` context via ``_previous_for_slot`` *before* the paid call, and
that helper always excludes the target slot's own current question (by
``instance_id``, since it is one of the "other slots" in scope for every
other purpose); ``category_history`` cannot supply it either, because the
displaced question is appended there only *after* this exact call succeeds.
Net effect: the one question being displaced was the one question never shown
to the generator/reviewer judging its own replacement -- a plumbing/missing-
context bug, not a reviewer false negative. The fix appends the slot's own
old question to ``previous`` ephemerally, for this one call, without touching
``category_history`` before success.

Offline, deterministic: a capturing fake provider records exactly what
``request.previous_questions`` contained on the call that stands in for the
real (paid) generation call -- proving the displaced question reached that
context before any provider call, not just after success. Temp DB, sockets
blocked (see ``conftest``). Zero real provider calls.
"""

from __future__ import annotations

from tests._wp18_fakes import ApprovingProvider, Dispatch, dispatch_factory

from src.jobs import service, store

CAT = "היסטולוגיה"

#: The real displaced question (WP25G brief) -- see module docstring. Only
#: ``number`` is remapped per use-site to the slot's own stable exam number;
#: the semantic content (question/answers/correct_answer) is exactly the
#: preserved incident text.
DISPLACED_FIELDS = {
    "question": "איזה מבנה מאפשר זרימה חד־כיוונית וסלקטיבית של CSF מן החלל "
                "הסאב־אראכנואידי אל הסינוסים?",
    "answer1": "Arachnoid Villi",
    "answer2": "Trabeculae",
    "answer3": "Lateral Apertures",
    "answer4": "choroid plexus",
    "correct_answer": 1,
}


class CapturingDispatch(Dispatch):
    """Records exactly what each category-dispatched generation call would
    send as ``previous_questions`` -- the same object a real provider call
    receives -- before delegating to a real :class:`ApprovingProvider` so the
    call still succeeds normally."""

    def __init__(self):
        super().__init__(factory=ApprovingProvider)
        self.seen_previous: list[list[dict]] = []

    def generate_candidates(self, request, *, prompts):
        self.seen_previous.append(
            [
                {
                    "number": p.number,
                    "question": p.question,
                    "answer1": p.answer1,
                    "answer2": p.answer2,
                    "answer3": p.answer3,
                    "answer4": p.answer4,
                    "correct_answer": p.correct_answer,
                }
                for p in request.previous_questions
            ]
        )
        return super().generate_candidates(request, prompts=prompts)


def _mixed(jobs_app):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 4, "database": 2, "llm": 2}},
             "cost_ceiling_usd": "5.00", "_seed": 11}
        )
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.status == "completed"
    return done


def test_displaced_question_reaches_its_own_replacement_context_before_the_call(
    jobs_app, jobs_root, llm_ready,
):
    """Section 1's exact proof: the question being displaced is present in
    ``request.previous_questions`` -- what would be sent to the real provider
    -- on the call that replaces it, before that call is ever made."""
    done = _mixed(jobs_app)
    s = next(x for x in done.slots if x.kind == "llm" and x.status == "accepted")

    # Overwrite the slot's current question with the real displaced fixture
    # (WP25G brief), keeping its own stable exam ``number``.
    displaced_question = {"number": s.number, **DISPLACED_FIELDS}
    with jobs_app.app_context():
        job = store.load(done.job_id)
        slot = job.slot_by_instance(s.instance_id)
        slot.question = dict(displaced_question)
        store.save(job)

    assert job.category_history.get(CAT, []) == []  # nothing persisted yet

    capturing = CapturingDispatch()
    up = service.replace_via_llm(
        done.job_id, s.instance_id, provider_factory=dispatch_factory(capturing),
    )

    assert capturing.seen_previous, "no generation call was made"
    first_call_previous = capturing.seen_previous[0]
    matches = [
        p for p in first_call_previous
        if p["question"] == displaced_question["question"]
        and p["answer1"] == displaced_question["answer1"]
        and p["correct_answer"] == displaced_question["correct_answer"]
    ]
    assert matches, (
        "the displaced question never reached request.previous_questions on "
        "the call that replaced it"
    )
    # It is the last entry: every other current same-category question and
    # earlier displaced-LLM history precede it, order preserved.
    assert first_call_previous[-1]["question"] == displaced_question["question"]

    # category_history is still untouched until success, then holds exactly
    # the displaced question -- unchanged WP18R behaviour.
    assert displaced_question in up.category_history.get(CAT, [])
    # The ephemeral append happens exactly once per call, not once per
    # provider retry: every generation call this invocation makes carries the
    # displaced question exactly once.
    for call_previous in capturing.seen_previous:
        occurrences = [
            p for p in call_previous if p["question"] == displaced_question["question"]
        ]
        assert len(occurrences) == 1
