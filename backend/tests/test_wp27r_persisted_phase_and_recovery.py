"""WP27R -- persisted workflow phase, atomic Continue claim, and recovery.

Corrects two WP27 production-state gaps (see WPs/WP27_ARCHITECT_REPORT.md
§13 / WPs/WP27R_Persisted_Phase_Atomic_Continue_And_Recovery.md):

1. An async Continue's ``202`` could be followed by an immediate GET of the
   stale pre-claim ``queued``/``db_review`` state.
2. Retrying one interrupted slot while later planned slots stayed ``queued``
   could compute the derived phase as ``complete``, hiding Continue and
   stranding the untouched planned work.

``workflow_phase`` is now a persisted ``Job`` field (see ``model.py``); the
continuation boundary is split into ``claim_llm_continuation`` (atomic,
synchronous, persisted before returning) and ``run_claimed_llm_generation``
(the actual batch, run in the calling thread or a spawned worker).

Offline, deterministic: temp DB, fake in-process providers
(``tests._wp18_fakes``), sockets blocked. Zero real provider calls.
"""

from __future__ import annotations

import json
import socket
import threading

import pytest

from tests._wp18_fakes import ApprovingProvider, Dispatch, RejectingProvider, dispatch_factory

from src.jobs import service, store

CAT = "היסטולוגיה"
OTHER_CAT = "גרעיני הבסיס"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted during a WP27R test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom)


# --------------------------------------------------------------------------- #
# 1/2. persisted phase for new/mutated jobs
# --------------------------------------------------------------------------- #
def test_new_mixed_job_persists_db_review_b_zero_persists_complete(jobs_app, jobs_root):
    with jobs_app.app_context():
        mixed = service.create_job({
            "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": 1,
        })
    assert mixed.workflow_phase == "db_review"
    raw = json.loads(store._job_file(mixed.job_id).read_text("utf-8"))
    assert raw["workflow_phase"] == "db_review"

    with jobs_app.app_context():
        b_zero = service.create_job({
            "categories": {CAT: {"total": 2, "database": 2, "llm": 0}},
            "cost_ceiling_usd": "5.00", "_seed": 2,
        })
    assert b_zero.workflow_phase == "complete"
    raw2 = json.loads(store._job_file(b_zero.job_id).read_text("utf-8"))
    assert raw2["workflow_phase"] == "complete"


# --------------------------------------------------------------------------- #
# 3. legacy JSON: safe load, no rewrite-on-read, gains the field only on save
# --------------------------------------------------------------------------- #
def test_legacy_json_loads_safely_and_gains_the_field_only_on_legitimate_save(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": 3,
        })
    path = store._job_file(job.job_id)
    raw = json.loads(path.read_text("utf-8"))
    del raw["workflow_phase"]  # simulate a genuinely pre-WP27R file
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_text("utf-8")

    loaded = store.load(job.job_id)
    assert loaded.workflow_phase == "db_review"  # inferred: queued + a planned llm slot
    assert path.read_text("utf-8") == before  # merely loading never rewrites the file

    # the field appears on disk once this job is legitimately mutated/saved
    with jobs_app.app_context():
        mutated = service.replace_from_db(job.job_id, next(
            s.instance_id for s in loaded.slots if s.kind == "database"
        ))
    after = json.loads(path.read_text("utf-8"))
    assert after["workflow_phase"] == "db_review"
    assert mutated.workflow_phase == "db_review"


# --------------------------------------------------------------------------- #
# 4/5. async claim persisted before 202; GET observes it even with a blocked worker
# --------------------------------------------------------------------------- #
def test_async_claim_persisted_before_202_and_get_observes_it_with_worker_blocked(
    jobs_client, jobs_app, jobs_root, llm_ready, monkeypatch,
):
    jobs_app.config["EXAM_JOB_PROVIDER_FACTORY"] = dispatch_factory(Dispatch())
    # EXAM_JOB_SYNC deliberately NOT set: exercise the real async route path
    resp = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
        "cost_ceiling_usd": "5.00", "_seed": 4,
    })
    jid = resp.get_json()["job_id"]

    started = []

    def _fake_start(self):  # the worker thread is constructed but never runs
        started.append(self)

    monkeypatch.setattr(threading.Thread, "start", _fake_start)
    try:
        cont = jobs_client.post(f"/api/exam-jobs/{jid}/continue-llm")
        assert cont.status_code == 202, cont.get_json()
        body = cont.get_json()
        assert body["status"] == "running"
        assert body["workflow_phase"] == "llm_generation"
        assert len(started) == 1  # exactly one worker thread was created for the claim

        # a GET issued immediately after (the worker never even started)
        # already observes the persisted claim, not the stale db_review state
        view = jobs_client.get(f"/api/exam-jobs/{jid}").get_json()
        assert view["status"] == "running"
        assert view["workflow_phase"] == "llm_generation"
    finally:
        # the claim's locks were never released (the worker never ran) --
        # restore a coherent, released state so later tests are unaffected,
        # reusing the exact same recovery path a real crash would use.
        service.abort_claim_as_interrupted(jid)

    recovered = jobs_client.get(f"/api/exam-jobs/{jid}").get_json()
    assert recovered["status"] == "interrupted"
    assert recovered["workflow_phase"] == "llm_generation"


# --------------------------------------------------------------------------- #
# 6. two concurrent claims: exactly one wins, the loser is honest, no duplicates
# --------------------------------------------------------------------------- #
def test_two_concurrent_claims_yield_one_winner_no_duplicate_cost_or_calls(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": 5,
        })
    disp = Dispatch()
    winner, provider = service.claim_llm_continuation(job.job_id, provider_factory=dispatch_factory(disp))
    assert winner.status == "running" and winner.workflow_phase == "llm_generation"

    with pytest.raises(service.JobBusy):
        service.claim_llm_continuation(job.job_id, provider_factory=dispatch_factory(Dispatch()))

    # the loser made no provider call and left no trace
    mid = store.load(job.job_id)
    assert mid.cost_ledger == []
    assert mid.accumulated_cost_usd == "0"

    done = service.run_claimed_llm_generation(job.job_id, provider=provider)
    assert done.status == "completed"
    assert len(done.cost_ledger) == 1  # exactly one generation call -- never duplicated
    assert sum(p.generation_calls for p in disp.by_context.values()) == 1


def test_route_level_concurrent_continue_returns_409_for_the_loser(jobs_client, jobs_app, jobs_root, llm_ready):
    jobs_app.config["EXAM_JOB_PROVIDER_FACTORY"] = dispatch_factory(Dispatch())
    resp = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
        "cost_ceiling_usd": "5.00", "_seed": 6,
    })
    jid = resp.get_json()["job_id"]

    assert service._RUN_LOCK.acquire(blocking=False)
    try:
        resp2 = jobs_client.post(f"/api/exam-jobs/{jid}/continue-llm")
        assert resp2.status_code == 409
    finally:
        service._RUN_LOCK.release()

    # the job is untouched -- still db_review, ready for a real claim
    view = jobs_client.get(f"/api/exam-jobs/{jid}").get_json()
    assert view["workflow_phase"] == "db_review"
    assert view["status"] == "queued"


# --------------------------------------------------------------------------- #
# 7. repeated Continue after completion cannot replay generation
# --------------------------------------------------------------------------- #
def test_repeated_continue_after_completion_cannot_replay(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": 7,
        })
    done = service.continue_llm_generation(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.workflow_phase == "complete"
    ledger_len = len(done.cost_ledger)

    with pytest.raises(service.JobConflict):
        service.claim_llm_continuation(done.job_id, provider_factory=dispatch_factory(Dispatch()))

    reloaded = store.load(done.job_id)
    assert len(reloaded.cost_ledger) == ledger_len
    assert reloaded.workflow_phase == "complete"


# --------------------------------------------------------------------------- #
# 8. readiness failure leaves exact db_review state, zero cost/calls
# --------------------------------------------------------------------------- #
def test_readiness_failure_leaves_exact_db_review_state(jobs_app, jobs_root, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": 8,
        })
    before = store._job_file(job.job_id).read_text("utf-8")

    with pytest.raises(service.JobError) as exc:
        service.claim_llm_continuation(job.job_id)
    assert "not ready" in str(exc.value)

    after = store._job_file(job.job_id).read_text("utf-8")
    assert after == before  # byte-for-byte untouched
    reloaded = store.load(job.job_id)
    assert reloaded.workflow_phase == "db_review"
    assert reloaded.status == "queued"
    assert reloaded.accumulated_cost_usd == "0"
    assert reloaded.cost_ledger == []


# --------------------------------------------------------------------------- #
# 9. worker-start failure -> recoverable interrupted + llm_generation
# --------------------------------------------------------------------------- #
def test_worker_start_failure_leaves_recoverable_interrupted_llm_generation(
    jobs_client, jobs_app, jobs_root, llm_ready,
):
    jobs_app.config["EXAM_JOB_PROVIDER_FACTORY"] = dispatch_factory(Dispatch())
    resp = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
        "cost_ceiling_usd": "5.00", "_seed": 9,
    })
    jid = resp.get_json()["job_id"]

    def _boom_start(self):
        raise RuntimeError("simulated thread-start failure")

    # managed manually (not via the `monkeypatch` fixture) -- that fixture is
    # SHARED with `jobs_root`'s own EXAM_JOBS_ROOT env patch, and calling
    # `monkeypatch.undo()` reverts everything applied through it, not just
    # this one attribute.
    orig_start = threading.Thread.start
    threading.Thread.start = _boom_start
    try:
        cont = jobs_client.post(f"/api/exam-jobs/{jid}/continue-llm")
        assert cont.status_code == 500
    finally:
        threading.Thread.start = orig_start

    view = jobs_client.get(f"/api/exam-jobs/{jid}").get_json()
    assert view["status"] == "interrupted"
    assert view["workflow_phase"] == "llm_generation"  # never a permanently fake "running"

    # locks were released by the failure path -- a real Continue afterwards
    # (with a working thread implementation) succeeds normally
    jobs_app.config["EXAM_JOB_SYNC"] = True
    cont2 = jobs_client.post(f"/api/exam-jobs/{jid}/continue-llm")
    assert cont2.status_code == 202, cont2.get_json()
    view2 = jobs_client.get(f"/api/exam-jobs/{jid}").get_json()
    assert view2["status"] == "completed"
    assert view2["workflow_phase"] == "complete"


# --------------------------------------------------------------------------- #
# 10. restart recovery preserves llm_generation and accepted slots
# --------------------------------------------------------------------------- #
def test_restart_recovery_preserves_llm_generation_and_accepted_slots(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 3, "database": 0, "llm": 3}},
            "cost_ceiling_usd": "5.00", "_seed": 10,
        })
    claimed, _provider = service.claim_llm_continuation(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    llm_slots = sorted([s for s in claimed.slots if s.kind == "llm"], key=lambda s: s.number)
    # simulate partial progress right before a crash: one accepted, one
    # mid-flight ("running"), one never reached ("queued", untouched)
    llm_slots[0].status = "accepted"
    llm_slots[0].question = {
        "number": llm_slots[0].number, "question": "x", "answer1": "a",
        "answer2": "b", "answer3": "c", "answer4": "d", "correct_answer": 1,
    }
    llm_slots[1].status = "running"
    store.save(claimed)
    # do NOT call run_claimed_llm_generation -- simulate the process dying
    # here; a real restart would construct a fresh, unlocked _RUN_LOCK, so
    # release this test's own hold on it to model that accurately.
    service._RUN_LOCK.release()

    changed = store.recover_on_start()
    assert job.job_id in changed
    recovered = store.load(job.job_id)
    assert recovered.status == "interrupted"
    assert service.workflow_phase(recovered) == "llm_generation"
    assert recovered.slot_by_id(llm_slots[0].slot_id).status == "accepted"  # never regenerated
    assert recovered.slot_by_id(llm_slots[1].slot_id).status == "interrupted"
    assert recovered.slot_by_id(llm_slots[2].slot_id).status == "queued"  # untouched, still eligible


# --------------------------------------------------------------------------- #
# 11. interrupted-slot-retry-plus-later-queued-slots stays resumable
# --------------------------------------------------------------------------- #
def test_interrupted_slot_retry_with_later_queued_slots_stays_resumable(jobs_app, jobs_root, llm_ready):
    # 1. start a planned multi-slot batch across two categories
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {
                CAT: {"total": 1, "database": 0, "llm": 1},
                OTHER_CAT: {"total": 2, "database": 0, "llm": 2},
            },
            "cost_ceiling_usd": "5.00", "_seed": 11,
        })
    claimed, _provider = service.claim_llm_continuation(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    llm_slots = sorted([s for s in claimed.slots if s.kind == "llm"], key=lambda s: s.number)
    assert len(llm_slots) == 3

    # 2. simulate interruption: the first slot crashed mid-flight, the later
    # two were never reached at all
    llm_slots[0].status = "interrupted"
    llm_slots[0].safe_error = "backend restarted while this job was running"
    claimed.status = "interrupted"
    store.save(claimed)
    # model a real restart: a fresh process has a brand-new, unlocked
    # _RUN_LOCK, and store.recover_on_start() releases the file lock too
    service._RUN_LOCK.release()
    store.release_lock(job.job_id)

    reloaded = store.load(job.job_id)
    assert service.workflow_phase(reloaded) == "llm_generation"
    assert len(service.pending_llm_slots(reloaded)) == 2  # the two never-reached slots

    # 3. retry just the interrupted slot
    retried = service.retry_slot(job.job_id, llm_slots[0].slot_id, provider_factory=dispatch_factory(Dispatch()))

    # 4. phase must still be llm_generation -- the later queued slots were
    # untouched by this single-slot retry and remain visible as pending work
    assert retried.slot_by_id(llm_slots[0].slot_id).status == "accepted"
    assert service.workflow_phase(retried) == "llm_generation"
    assert len(service.pending_llm_slots(retried)) == 2
    assert retried.status == "partial"  # WP27R: partial legitimately coexists with llm_generation

    # Continue/resume processes the remaining planned work exactly once
    done = service.continue_llm_generation(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    accepted_llm = [s for s in done.slots if s.kind == "llm" and s.status == "accepted"]
    assert len(accepted_llm) == 3  # all three, no duplicates, no regeneration of the retried one

    # 5. final phase becomes complete only once traversal genuinely finishes
    assert service.workflow_phase(done) == "complete"
    assert done.status == "completed"


# --------------------------------------------------------------------------- #
# 12/13. traversal boundary: complete set only when nothing is left untouched
# --------------------------------------------------------------------------- #
def test_fully_traversed_batch_with_a_rejected_slot_is_complete_with_partial_status(jobs_app, jobs_root, llm_ready):
    reject = RejectingProvider()
    approve = ApprovingProvider()

    class FirstFailsThenApproves:
        name = "fake-first-fails"

        def __init__(self):
            self.generation_calls = 0

        def generate_candidates(self, request, *, prompts):
            self.generation_calls += 1
            # the generator's own internal attempt budget is 2 per slot, so
            # rejecting only the first call would just be absorbed as an
            # in-slot retry, not a real per-slot failure -- reject BOTH of
            # slot 1's attempts, then approve everything after (slot 2).
            self._impl = reject if self.generation_calls <= 2 else approve
            return self._impl.generate_candidates(request, prompts=prompts)

        def review_candidates(self, request, *, prompts):
            return self._impl.review_candidates(request, prompts=prompts)

    prov = FirstFailsThenApproves()
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 2, "database": 0, "llm": 2}},
            "cost_ceiling_usd": "5.00", "_seed": 12,
        })
    done = service.continue_llm_generation(job.job_id, provider_factory=lambda: prov)

    assert done.status == "partial"  # one accepted, one genuinely rejected
    # WP27R §5: a terminal batch that attempted all intended slots is
    # "complete" even though one outcome is individually rejected/retryable
    assert service.workflow_phase(done) == "complete"
    assert service.pending_llm_slots(done) == []
    llm_slots = [s for s in done.slots if s.kind == "llm"]
    assert sum(1 for s in llm_slots if s.status == "accepted") == 1
    assert sum(1 for s in llm_slots if s.status == "failed") == 1


# --------------------------------------------------------------------------- #
# 14. cost ceiling before all planned slots: explicit, cannot strand work
# --------------------------------------------------------------------------- #
def test_cost_ceiling_before_all_planned_slots_stays_llm_generation_not_complete(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 3, "database": 0, "llm": 3}},
            "cost_ceiling_usd": "0.50", "_seed": 13,
        })
    done = service.continue_llm_generation(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.status == "cost_ceiling"
    # WP27R §1: a ceiling that stops traversal while a planned slot is still
    # genuinely untouched ("queued") must not silently pretend it was
    # completed -- phase stays llm_generation.
    assert service.workflow_phase(done) == "llm_generation"
    assert len(service.pending_llm_slots(done)) >= 1
    cost_ceiling_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "cost_ceiling")

    # raising the ceiling and continuing again picks up ONLY the genuinely
    # untouched ("queued") slot(s) -- a slot already marked "cost_ceiling" is
    # a terminal per-attempt outcome, same as "failed": the automatic
    # traversal does not silently re-attempt it (unchanged, pre-existing
    # behavior), only an explicit retry_slot does.
    raised = service.update_cost_ceiling(done.job_id, "5.00")
    finished = service.continue_llm_generation(raised.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert service.pending_llm_slots(finished) == []  # nothing untouched remains
    # WP27R §5: traversal is genuinely done (every slot was attempted at
    # least once) -- phase is "complete" even though the cost_ceiling'd slot
    # is still individually unresolved and job.status still reflects that.
    assert service.workflow_phase(finished) == "complete"
    assert finished.status == "cost_ceiling"
    assert finished.slot_by_id(cost_ceiling_slot.slot_id).status == "cost_ceiling"

    # resolving that one slot explicitly (the existing, unchanged retry
    # rule) can then bring the job itself to "completed" too
    resolved = service.retry_slot(finished.job_id, cost_ceiling_slot.slot_id,
                                   provider_factory=dispatch_factory(Dispatch()))
    assert resolved.status == "completed"
    assert service.workflow_phase(resolved) == "complete"


# --------------------------------------------------------------------------- #
# 15. branching blocked before workflow completion, unchanged afterward
# --------------------------------------------------------------------------- #
def test_branching_requires_both_status_and_phase_complete(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 2, "database": 1, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": 14,
        })
    # a defensive invariant-violating state (status completed, phase not) --
    # branch_job must still refuse it, proving it checks BOTH fields, not
    # just status.
    tampered = store.load(job.job_id)
    tampered.status = "completed"
    store.save(tampered)  # workflow_phase left at "db_review"
    with pytest.raises(service.JobConflict):
        service.branch_job(job.job_id, None)

    # undo the tampering and complete the job for real
    real = store.load(job.job_id)
    real.status = "queued"
    store.save(real)
    done = service.continue_llm_generation(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.status == "completed" and done.workflow_phase == "complete"
    child = service.branch_job(done.job_id, {"mode": "custom", "custom_name": "בדיקת ענף WP27R"})
    assert child.status == "completed" and child.workflow_phase == "complete"


def test_branch_child_workflow_phase_is_complete_not_the_dataclass_default(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 1, "database": 1, "llm": 0}},
            "cost_ceiling_usd": "5.00", "_seed": 15,
        })
    assert job.status == "completed" and job.workflow_phase == "complete"
    child = service.branch_job(job.job_id, {"mode": "custom", "custom_name": "ענף B0"})
    assert child.workflow_phase == "complete"
    view = service.result_view(child)
    assert view["workflow_phase"] == "complete"
    assert view["branchable"] is True


# --------------------------------------------------------------------------- #
# 16. DB-review regressions: manual replacement, exclusions, numbering
# --------------------------------------------------------------------------- #
def test_db_review_regressions_remain_green_with_persisted_phase(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        from src.models.question import Question

        excluded = [Question.query.filter(Question.category == CAT).first().id]
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 3, "database": 1, "llm": 2}},
            "cost_ceiling_usd": "5.00", "excluded_db_ids": excluded,
        })
    assert job.workflow_phase == "db_review"
    db_slot = next(s for s in job.slots if s.kind == "database")
    assert db_slot.db_id not in excluded

    updated = service.replace_via_llm(job.job_id, db_slot.instance_id,
                                       provider_factory=dispatch_factory(Dispatch()))
    assert updated.workflow_phase == "db_review"  # manual op never changes phase
    assert len(service.pending_llm_slots(updated)) == 2  # planned B untouched

    view = service.result_view(updated)
    assert view["workflow_phase"] == "db_review"
    assert [q["number"] for q in view["questions"]] == [1]  # compact interim numbering
