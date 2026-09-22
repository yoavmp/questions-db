"""WP18 §2/§6 -- job creation, sequential worker, ordering, DB isolation."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from tests._wp18_fakes import ApprovingProvider, Dispatch, dispatch_factory

from src.jobs import service, store
from src.models.question import Question
from src.models.user import db


def _run(jobs_app, payload, *, provider_factory):
    with jobs_app.app_context():
        job = service.create_job(payload, seed=payload.get("_seed"))
    return service.run_job(job.job_id, provider_factory=provider_factory)


# --------------------------------------------------------------------------- #
def test_db_only_job_succeeds_without_llm_readiness(jobs_app, jobs_root):
    """No llm anywhere -> readiness is never consulted, job completes on DB
    alone -- WP27: immediately inside create_job (no llm plan means nothing
    to run; the job is already terminal, not queued/interrupted, so a direct
    run_job call now correctly refuses it)."""
    with jobs_app.app_context():
        done = service.create_job(
            {"categories": {"היסטולוגיה": {"total": 3, "database": 3, "llm": 0}},
             "cost_ceiling_usd": "5.00", "_seed": 1}
        )
    assert done.status == "completed"
    assert done.accumulated_cost_usd == "0"
    with pytest.raises(service.JobConflict):
        service.run_job(done.job_id)
    view = service.result_view(done)
    assert [q["origin"] for q in view["questions"]] == ["database"] * 3
    assert [q["number"] for q in view["questions"]] == [1, 2, 3]


def test_mixed_ab_selection_order_and_previous_question_growth(jobs_app, jobs_root, llm_ready):
    disp = Dispatch()
    done = _run(
        jobs_app,
        {"categories": {"היסטולוגיה": {"total": 5, "database": 2, "llm": 3}},
         "cost_ceiling_usd": "5.00", "_seed": 7},
        provider_factory=dispatch_factory(disp),
    )
    assert done.status == "completed"
    view = service.result_view(done)
    origins = [q["origin"] for q in view["questions"]]
    assert origins == ["database", "database", "llm", "llm", "llm"]  # A first, then B
    assert [q["number"] for q in view["questions"]] == [1, 2, 3, 4, 5]

    # Q3 (first llm) saw 2 prior; Q4 saw 3; Q5 saw 4  (DB 2 + growing llm prefix)
    prov = disp.by_context["chapter_09"]
    # 3 generations, 3 reviews
    assert prov.generation_calls == 3 and prov.review_calls == 3


def test_canonical_category_and_global_ordering(jobs_app, jobs_root, llm_ready):
    disp = Dispatch()
    done = _run(
        jobs_app,
        {"categories": {
            "היסטולוגיה": {"total": 2, "database": 1, "llm": 1},     # canonical idx 7
            "מבוא": {"total": 2, "database": 1, "llm": 1},            # canonical idx 0
            "גרעיני הבסיס": {"total": 2, "database": 1, "llm": 1},    # canonical idx 6
        }, "cost_ceiling_usd": "5.00", "_seed": 3},
        provider_factory=dispatch_factory(disp),
    )
    view = service.result_view(done)
    cats = [q["category"] for q in view["questions"]]
    nums = [q["number"] for q in view["questions"]]
    assert cats == ["מבוא", "מבוא", "גרעיני הבסיס", "גרעיני הבסיס", "היסטולוגיה", "היסטולוגיה"]
    assert nums == [1, 2, 3, 4, 5, 6]
    # DB before LLM inside each category
    assert [q["origin"] for q in view["questions"]] == ["database", "llm"] * 3


def test_one_worker_no_double_execution(jobs_app, jobs_root, llm_ready, monkeypatch):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 1, "database": 0, "llm": 1}},
             "cost_ceiling_usd": "5.00"}
        )
    # hold the global run lock -> a second run must refuse, not run in parallel
    assert service._RUN_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(service.JobBusy):
            service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    finally:
        service._RUN_LOCK.release()

    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.status == "completed"
    # a completed job cannot be run again
    with pytest.raises(service.JobConflict):
        service.run_job(done.job_id, provider_factory=dispatch_factory(Dispatch()))


def test_generated_questions_never_enter_db_and_appdb_untouched(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        before = Question.query.count()
    done = _run(
        jobs_app,
        {"categories": {"היסטולוגיה": {"total": 3, "database": 1, "llm": 2}},
         "cost_ceiling_usd": "5.00", "_seed": 9},
        provider_factory=dispatch_factory(Dispatch()),
    )
    assert done.status == "completed"
    with jobs_app.app_context():
        after = Question.query.count()
        assert after == before  # no inserts
        # none of the generated question texts landed in the DB
        gen_texts = {
            s.question["question"] for s in done.slots if s.kind == "llm" and s.question
        }
        db_texts = {q.question for q in Question.query.all()}
        assert gen_texts.isdisjoint(db_texts)


@pytest.mark.parametrize("payload", [
    {"categories": {}, "cost_ceiling_usd": "5.00"},                                 # empty
    {"categories": {"מבוא": {"total": 3, "database": 2, "llm": 2}}},                # A+B != C
    {"categories": {"מבוא": {"total": 2, "database": True, "llm": 1}}},             # bool
    {"categories": {"מבוא": {"total": 2, "database": "1", "llm": "1"}}},            # strings
    {"categories": {"not a category": {"total": 1, "database": 0, "llm": 1}}},      # unknown
    {"categories": {"מבוא": {"total": 999, "database": 999, "llm": 0}}},            # DB availability
    {"categories": {"מבוא": {"total": 1, "database": 1, "llm": 0}}, "cost_ceiling_usd": "-1"},  # bad cap
])
def test_create_job_rejects_bad_requests(jobs_app, jobs_root, payload):
    with jobs_app.app_context():
        with pytest.raises(service.JobError):
            service.create_job(payload)


def test_job_state_is_json_on_disk_never_in_appdb(jobs_app, jobs_root, llm_ready):
    done = _run(
        jobs_app,
        {"categories": {"מבוא": {"total": 1, "database": 0, "llm": 1}}, "cost_ceiling_usd": "5.00"},
        provider_factory=dispatch_factory(Dispatch()),
    )
    jf = store.job_dir(done.job_id) / "job.json"
    assert jf.is_file()
    blob = json.loads(jf.read_text("utf-8"))
    assert blob["job_id"] == done.job_id
    assert blob["status"] == "completed"
    # per-slot generator audit dir exists for the llm slot
    llm_slot = next(s for s in done.slots if s.kind == "llm")
    assert (store.job_dir(done.job_id) / "slots" / llm_slot.slot_id).is_dir()
