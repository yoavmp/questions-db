"""WP31 Part A: the exam-level credential circuit breaker, as seen from the
outer job service -- an OpenAI ``401``/authentication failure must stop
immediately, cost exactly ``$0``, never be retried automatically, and block
every other queued LLM slot in the job without another provider call.

Offline: temp DB, fake in-process providers, sockets blocked (conftest).
``OPENAI_API_KEY`` is irrelevant here -- the fake provider raises the typed
failure directly, never touching the real SDK/network.
"""

from __future__ import annotations

from decimal import Decimal

from tests._wp18_fakes import (
    ApprovingProvider,
    Dispatch,
    InvalidKeyProvider,
    RejectingProvider,
    dispatch_factory,
)

from src.jobs import service

CAT = "היסטולוגיה"
CAT2 = "גרעיני הבסיס"


def _lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("[EXAM JOB")]


def test_two_slot_job_with_invalid_key_makes_exactly_one_provider_call_total(
    jobs_app, jobs_root, llm_ready, capsys,
):
    """Two LLM slots requested in the SAME category: the first slot's call
    hits the invalid-key provider, which must stop the whole job -- the
    second slot is marked the same safe failure WITHOUT a second provider
    call, zero review calls ever happen, and the job's charged cost is
    exactly $0."""
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 2, "database": 0, "llm": 2}},
             "cost_ceiling_usd": "5.00", "_seed": 31}
        )
    invalid_key = InvalidKeyProvider()
    done = service.run_job(job.job_id, provider_factory=lambda: invalid_key)

    assert invalid_key.generation_calls == 1
    assert invalid_key.review_calls == 0

    llm_slots = [s for s in done.slots if s.kind == "llm"]
    assert len(llm_slots) == 2
    assert all(s.status == "failed" for s in llm_slots)
    assert all(s.safe_error == service.AUTH_FAILURE_HEBREW_MESSAGE for s in llm_slots)
    # no raw provider/internal diagnostic text leaked to the operator-facing field
    for s in llm_slots:
        assert "sk-" not in s.safe_error
        assert "ProviderAuthenticationError" not in s.safe_error

    assert done.accumulated_cost_usd == "0"
    assert done.safe_error == service.AUTH_FAILURE_HEBREW_MESSAGE
    # the one ledger entry that exists is the zero-cost auth failure itself --
    # the second (blocked) slot never got an entry at all (no call was made)
    assert len(done.cost_ledger) == 1
    assert done.cost_ledger[0]["status"] == "authentication_failure"
    assert done.cost_ledger[0]["total_cost_usd"] == "0"

    out = capsys.readouterr().out
    assert len(_lines(out)) == 1  # WP31 Part D -- still exactly one summary


def test_invalid_key_blocks_queued_slots_in_a_later_category_too(jobs_app, jobs_root, llm_ready):
    """The breaker is exam-level, not per-category: a job spanning two
    categories stops entirely after the first authentication failure, even
    though the second category's slot was never reached by the per-category
    loop."""
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {
                CAT: {"total": 1, "database": 0, "llm": 1},
                CAT2: {"total": 1, "database": 0, "llm": 1},
            }, "cost_ceiling_usd": "5.00", "_seed": 32}
        )
    invalid_key = InvalidKeyProvider()
    done = service.run_job(job.job_id, provider_factory=lambda: invalid_key)

    assert invalid_key.generation_calls == 1
    llm_slots = [s for s in done.slots if s.kind == "llm"]
    assert len(llm_slots) == 2
    assert all(s.status == "failed" and s.safe_error == service.AUTH_FAILURE_HEBREW_MESSAGE
               for s in llm_slots)
    assert done.accumulated_cost_usd == "0"


def test_retrying_during_an_active_credential_failure_adds_no_cost_and_does_not_loop(
    jobs_app, jobs_root, llm_ready, capsys,
):
    """A manual retry while the key is still invalid is one explicit,
    operator-requested call -- it must still cost $0 and must not trigger
    any further automatic attempt."""
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
             "cost_ceiling_usd": "5.00", "_seed": 33}
        )
    first = InvalidKeyProvider()
    done = service.run_job(job.job_id, provider_factory=lambda: first)
    failed_slot = next(s for s in done.slots if s.kind == "llm")
    assert failed_slot.status == "failed"
    capsys.readouterr()  # discard the initial-run summary line

    second = InvalidKeyProvider()
    retried = service.retry_slot(done.job_id, failed_slot.slot_id, provider_factory=lambda: second)

    assert second.generation_calls == 1  # exactly one call for the one retry request
    assert second.review_calls == 0
    updated_slot = retried.slot_by_id(failed_slot.slot_id)
    assert updated_slot.status == "failed"
    assert updated_slot.safe_error == service.AUTH_FAILURE_HEBREW_MESSAGE
    assert retried.accumulated_cost_usd == "0"

    out = capsys.readouterr().out
    assert len(_lines(out)) == 1


def test_ledger_distinguishes_zero_cost_auth_failure_from_charged_upper_bound_fallback(
    jobs_app, jobs_root, llm_ready,
):
    """The cost ledger must tell apart a definite zero-cost authentication
    failure from an ordinary charged failure (here, a fake provider's
    reserved conservative-bound fallback, since no fake ever reports real
    token usage -- the "calculated, token-derived" case is proven at the
    generator level in exam_generator/tests/test_wp31_authentication_failure.py,
    which stubs a real OpenAI client to get genuine usage metadata)."""
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
             "cost_ceiling_usd": "5.00", "_seed": 34}
        )
    # a genuine content rejection: charged at its reserved conservative bound
    rejecting = Dispatch(factory=RejectingProvider)
    charged = service.run_job(job.job_id, provider_factory=dispatch_factory(rejecting))
    charged_slot = next(s for s in charged.slots if s.kind == "llm")
    assert charged_slot.status == "failed"
    assert Decimal(charged.accumulated_cost_usd) > 0
    charged_entry = charged.cost_ledger[-1]
    assert charged_entry["status"] == "failed" or charged_entry["status"] == "question_rejected"
    assert charged_entry["total_cost_basis"] == "conservative_bound"
    assert Decimal(charged_entry["total_cost_usd"]) > 0

    # a second job: a definite authentication failure is charged exactly $0
    with jobs_app.app_context():
        job2 = service.create_job(
            {"categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
             "cost_ceiling_usd": "5.00", "_seed": 35}
        )
    auth_failed = service.run_job(job2.job_id, provider_factory=lambda: InvalidKeyProvider())
    auth_entry = auth_failed.cost_ledger[-1]
    assert auth_entry["status"] == "authentication_failure"
    assert Decimal(auth_entry["total_cost_usd"]) == 0
    assert auth_entry["total_cost_basis"] != "conservative_bound"


def test_a_clean_accepted_job_is_unaffected_by_the_breaker(jobs_app, jobs_root, llm_ready):
    """Sanity: an ordinary successful job never trips the breaker and keeps
    its normal cost accounting -- the new code path is additive, not a
    behaviour change for the non-failing case."""
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
             "cost_ceiling_usd": "5.00", "_seed": 36}
        )
    done = service.run_job(job.job_id, provider_factory=lambda: ApprovingProvider())
    llm_slot = next(s for s in done.slots if s.kind == "llm")
    assert llm_slot.status == "accepted"
    assert done.safe_error is None
    assert Decimal(done.accumulated_cost_usd) > 0
