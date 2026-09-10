"""WP18 §2/§6 -- reload on start, running->interrupted recovery, slot retry."""

from __future__ import annotations

import pytest

from tests._wp18_fakes import Dispatch, RejectingProvider, dispatch_factory

from src.jobs import service, store


def test_running_job_becomes_interrupted_on_reload(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 2, "database": 0, "llm": 2}}, "cost_ceiling_usd": "5.00"}
        )
    # simulate a crash mid-run
    job.status = "running"
    job.slots[0].status = "running"
    store.save(job)

    changed = store.recover_on_start()
    assert job.job_id in changed
    reloaded = store.load(job.job_id)
    assert reloaded.status == "interrupted"
    assert reloaded.slots[0].status == "interrupted"
    assert "restarted" in (reloaded.safe_error or "")

    # an interrupted job is resumable; its queued/interrupted llm slots still run
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.status in ("completed", "partial")


def test_partial_results_and_slot_retry(jobs_app, jobs_root, llm_ready):
    # first llm slot fails every attempt, second accepted -> partial; then retry
    # the failed one with an approving provider.
    reject = RejectingProvider()
    approve = Dispatch()

    class FirstSlotFails:
        """Rejects while fewer than 3 generation calls have been made (slot 1 gets
        up to 2 attempts), then approves everything (slot 2)."""

        name = "fake"

        def __init__(self):
            self.generation_calls = 0

        def generate_candidates(self, request, *, prompts):
            self.generation_calls += 1
            self._impl = reject if self.generation_calls <= 2 else approve
            return self._impl.generate_candidates(request, prompts=prompts)

        def review_candidates(self, request, *, prompts):
            return self._impl.review_candidates(request, prompts=prompts)

    prov = FirstSlotFails()
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 2, "database": 0, "llm": 2}}, "cost_ceiling_usd": "5.00"}
        )
    done = service.run_job(job.job_id, provider_factory=lambda: prov)
    assert done.status == "partial"
    failed = [s for s in done.slots if s.status == "failed"]
    accepted = [s for s in done.slots if s.kind == "llm" and s.status == "accepted"]
    assert len(failed) == 1 and len(accepted) == 1
    cost_after_run = done.accumulated_cost_usd

    # retry the failed slot with an approving provider
    from decimal import Decimal

    retried = service.retry_slot(
        done.job_id, failed[0].slot_id, provider_factory=dispatch_factory(Dispatch()),
    )
    slot = retried.slot_by_id(failed[0].slot_id)
    assert slot.status == "accepted"
    assert slot.retries == 1
    assert retried.status == "completed"
    # retry cost adds to the SAME job ledger / accumulator
    assert Decimal(retried.accumulated_cost_usd) > Decimal(cost_after_run)
    assert any(e["kind"] == "retry" for e in retried.cost_ledger)


def test_retry_rejects_a_non_retryable_slot(jobs_app, jobs_root, llm_ready):
    done = _run_simple(jobs_app)
    accepted_llm = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")
    with pytest.raises(service.JobConflict):
        service.retry_slot(done.job_id, accepted_llm.slot_id, provider_factory=dispatch_factory(Dispatch()))
    db_slot = next(s for s in done.slots if s.kind == "database")
    with pytest.raises(service.JobConflict):
        service.retry_slot(done.job_id, db_slot.slot_id, provider_factory=dispatch_factory(Dispatch()))


def _run_simple(jobs_app):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 2, "database": 1, "llm": 1}}, "cost_ceiling_usd": "5.00"}
        )
    return service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
