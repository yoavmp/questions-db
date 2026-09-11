"""WP20 follow-up -- backend-terminal cost log.

``service._print_terminal_summary`` must fire exactly once per generating
operation reaching a terminal state:

* the initial job run (``operation="initial"``), whatever its final status;
* every LLM retry (``operation="retry"``), accepted or failed alike;
* every LLM replacement (``operation="replace_llm"``), accepted or failed alike;

and must **not** fire for a DB-only replacement (``replace_from_db`` makes no
provider call and changes no cost). Each line must carry job id, operation,
cumulative cost, pricing basis, remaining ceiling and warnings -- and nothing
that looks like question content, a rendered prompt, or a secret.

Offline: temp DB, fake in-process providers, sockets blocked (conftest). Zero
network / provider calls.
"""

from __future__ import annotations

from decimal import Decimal

from tests._wp18_fakes import Dispatch, RejectingProvider, dispatch_factory

from src.jobs import service

CAT = "היסטולוגיה"

REQUIRED_FIELDS = ("job=", "operation=", "status=", "llm_cost=$", "basis=", "remaining=$",
                   "pricing_warnings=")
FORBIDDEN_SUBSTRINGS = ("prompt", "system_prompt", "OPENAI_API_KEY", "sk-", "Authorization")


def _lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("[EXAM JOB")]


def _assert_well_formed(line: str, *, operation: str) -> None:
    for f in REQUIRED_FIELDS:
        assert f in line, f"missing {f!r} in {line!r}"
    assert f"operation={operation}" in line
    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad.lower() not in line.lower(), f"leaked {bad!r} in {line!r}"


def _mixed_job(jobs_app, *, provider_factory, llm=1):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": llm + 1, "database": 1, "llm": llm}},
             "cost_ceiling_usd": "5.00", "_seed": 21}
        )
    return service.run_job(job.job_id, provider_factory=provider_factory)


def test_initial_run_prints_one_well_formed_cost_line(jobs_app, jobs_root, llm_ready, capsys):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    out = capsys.readouterr().out
    lines = _lines(out)
    assert len(lines) == 1
    _assert_well_formed(lines[0], operation="initial")
    assert "[EXAM JOB COMPLETE]" in lines[0]

    # no question text leaked
    llm_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")
    assert llm_slot.question["question"] not in out


def test_retry_prints_a_cost_line_on_success(jobs_app, jobs_root, llm_ready, capsys):
    # a rejecting provider so the initial LLM slot fails and becomes retryable
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)))
    failed_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "failed")
    capsys.readouterr()  # discard the initial-run line

    updated = service.retry_slot(done.job_id, failed_slot.slot_id,
                                 provider_factory=dispatch_factory(Dispatch()))
    out = capsys.readouterr().out
    lines = _lines(out)
    assert len(lines) == 1
    _assert_well_formed(lines[0], operation="retry")
    assert updated.slot_by_id(failed_slot.slot_id).status == "accepted"
    assert "accepted=1/1" in lines[0]


def test_retry_prints_a_cost_line_on_failure_too(jobs_app, jobs_root, llm_ready, capsys):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)))
    failed_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "failed")
    capsys.readouterr()

    service.retry_slot(done.job_id, failed_slot.slot_id,
                       provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)))
    out = capsys.readouterr().out
    lines = _lines(out)
    assert len(lines) == 1
    _assert_well_formed(lines[0], operation="retry")
    assert "failed=1" in lines[0]  # the charged failure is reflected, not hidden


def test_replace_llm_prints_a_cost_line_on_success_and_on_failure(jobs_app, jobs_root, llm_ready, capsys):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    llm_slot = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")
    capsys.readouterr()

    service.replace_via_llm(done.job_id, llm_slot.instance_id,
                            provider_factory=dispatch_factory(Dispatch()))
    out = capsys.readouterr().out
    lines = _lines(out)
    assert len(lines) == 1
    _assert_well_formed(lines[0], operation="replace_llm")

    # a failed replacement attempt is charged and must still be logged
    service.replace_via_llm(done.job_id, llm_slot.instance_id,
                            provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)))
    out2 = capsys.readouterr().out
    lines2 = _lines(out2)
    assert len(lines2) == 1
    _assert_well_formed(lines2[0], operation="replace_llm")


def test_replace_from_db_prints_no_cost_line(jobs_app, jobs_root, llm_ready, capsys):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    db_slot = next(s for s in done.slots if s.kind == "database")
    cost_before = Decimal(done.accumulated_cost_usd)
    capsys.readouterr()

    with jobs_app.app_context():
        updated = service.replace_from_db(done.job_id, db_slot.instance_id)
    out = capsys.readouterr().out
    assert _lines(out) == []                                    # no new terminal line
    assert Decimal(updated.accumulated_cost_usd) == cost_before  # and no cost moved


def test_remaining_ceiling_reflects_accumulated_spend(jobs_app, jobs_root, llm_ready, capsys):
    done = _mixed_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    out = capsys.readouterr().out
    line = _lines(out)[0]
    remaining = Decimal(line.split("remaining=$")[1].split()[0])
    expected = Decimal(done.cost_ceiling_usd) - Decimal(done.accumulated_cost_usd)
    assert remaining == expected
