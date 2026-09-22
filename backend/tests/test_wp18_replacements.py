"""WP18 §3 -- DB and LLM replacement, unchanged-on-failure, discarded history."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests._wp18_fakes import Dispatch, RejectingProvider, dispatch_factory

from src.jobs import service, store
from src.models.question import Question


def _mixed_job(jobs_app, *, provider_factory):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"היסטולוגיה": {"total": 4, "database": 2, "llm": 2}},
             "cost_ceiling_usd": "5.00", "_seed": 5}
        )
    return service.run_job(job.job_id, provider_factory=provider_factory)


def test_db_replacement_preserves_instance_and_number_and_excludes_current(jobs_app, jobs_root, llm_ready):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    db_slot = next(s for s in done.slots if s.kind == "database")
    old_iid, old_num, old_id = db_slot.instance_id, db_slot.number, db_slot.db_id
    in_exam_before = {s.db_id for s in done.slots if s.kind == "database"}

    with jobs_app.app_context():
        updated = service.replace_from_db(done.job_id, old_iid)

    new_slot = updated.slot_by_instance(old_iid)
    assert new_slot.instance_id == old_iid          # preserved
    assert new_slot.number == old_num               # preserved
    assert new_slot.db_id != old_id                 # a different question
    assert new_slot.db_id not in in_exam_before     # not one already in the exam
    assert updated.accumulated_cost_usd == done.accumulated_cost_usd  # DB ops cost nothing


def test_llm_replacement_moves_old_to_history_on_success(jobs_app, jobs_root, llm_ready):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    llm_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")
    old_q = dict(llm_slot.question)
    cost_before = Decimal(done.accumulated_cost_usd)

    updated = service.replace_via_llm(
        done.job_id, llm_slot.instance_id, provider_factory=dispatch_factory(Dispatch()),
    )
    new_slot = updated.slot_by_instance(llm_slot.instance_id)
    assert new_slot.status == "accepted"
    assert new_slot.number == llm_slot.number
    assert new_slot.instance_id == llm_slot.instance_id
    assert new_slot.question["question"] != old_q["question"]
    # the discarded question is retained in that category's history
    assert old_q in updated.category_history["היסטולוגיה"]
    # replacement cost is added to the SAME job ledger
    assert Decimal(updated.accumulated_cost_usd) > cost_before
    assert any(e["kind"] == "replace_llm" for e in updated.cost_ledger)


def test_llm_replacement_retains_question_on_failure(jobs_app, jobs_root, llm_ready):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    llm_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")
    old_q = dict(llm_slot.question)
    cost_before = Decimal(done.accumulated_cost_usd)

    # a provider whose reviewer always rejects
    reject_disp = Dispatch(factory=RejectingProvider)
    updated = service.replace_via_llm(
        done.job_id, llm_slot.instance_id, provider_factory=dispatch_factory(reject_disp),
    )
    new_slot = updated.slot_by_instance(llm_slot.instance_id)
    assert new_slot.status == "accepted"                    # unchanged
    assert new_slot.question == old_q                       # exact same question
    assert old_q not in updated.category_history.get("היסטולוגיה", [])  # NOT discarded
    # the failed attempt's cost is still counted
    assert Decimal(updated.accumulated_cost_usd) > cost_before


def test_history_keeps_repeated_numbers_and_feeds_them_to_the_generator(jobs_app, jobs_root, llm_ready):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    llm_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")
    target_number = llm_slot.number

    # replace the same slot twice -> two history entries, both carrying the slot's
    # public number, order preserved, never de-duplicated
    disp = Dispatch()
    service.replace_via_llm(done.job_id, llm_slot.instance_id, provider_factory=dispatch_factory(disp))
    updated = service.replace_via_llm(done.job_id, llm_slot.instance_id, provider_factory=dispatch_factory(disp))

    hist = updated.category_history["היסטולוגיה"]
    assert len(hist) == 2
    assert [h["number"] for h in hist] == [target_number, target_number]  # repeated, not renumbered

    # the previous-question context built for the next generator call carries
    # those repeated numbers, in order, un-deduplicated
    reloaded = store.load(done.job_id)
    prev = service._previous_for_slot(reloaded, reloaded.slot_by_instance(llm_slot.instance_id))
    assert [q["number"] for q in prev].count(target_number) >= 2


def test_replace_db_rejects_when_no_alternative(jobs_app, jobs_root, llm_ready):
    # only 2 hist DB questions available, both go into a 2-DB exam -> no spare
    with jobs_app.app_context():
        from src.models.user import db

        keep = [q.id for q in Question.query.filter(Question.category == "היסטולוגיה").limit(2).all()]
        for q in Question.query.filter(Question.category == "היסטולוגיה").all():
            if q.id not in keep:
                db.session.delete(q)
        db.session.commit()
        done = service.create_job(
            {"categories": {"היסטולוגיה": {"total": 2, "database": 2, "llm": 0}}, "cost_ceiling_usd": "5.00"}
        )
    assert done.status == "completed"  # WP27: DB-only jobs finish inside create_job
    db_slot = next(s for s in done.slots if s.kind == "database")
    with jobs_app.app_context():
        with pytest.raises(service.JobConflict):
            service.replace_from_db(done.job_id, db_slot.instance_id)
    # the slot is unchanged
    still = store.load(done.job_id).slot_by_instance(db_slot.instance_id)
    assert still.db_id == db_slot.db_id
