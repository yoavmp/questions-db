"""WP19 §1 -- backend hardening for the job-API frontend.

Covers:

* ``replace_from_db`` now takes the same process/file run lock as every other
  job mutation -- a concurrent op (or a double click) gets ``JobBusy`` (409),
  never a lost update / duplicate selection / corrupt persistence;
* ledger-derived attempt/retry telemetry by category and slot, and the fact
  that a *charged failed attempt* stays diagnosable there even after the LLM
  replacement that produced it has rolled the slot back;
* neither ``progress_view`` nor ``result_view`` reports a recomputed *current*
  DB-vs-LLM composition -- C/A/B stay request provenance only.

Temp DB, offline fakes, sockets blocked. Zero provider calls.
"""

from __future__ import annotations

import socket
from decimal import Decimal

import pytest

from tests._wp18_fakes import Dispatch, RejectingProvider, dispatch_factory

from src.jobs import service, store
from src.models.question import Question

CAT = "היסטולוגיה"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted during a WP19 test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom)


def _mixed(jobs_app, disp: Dispatch | None = None):
    disp = disp or Dispatch()
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 4, "database": 2, "llm": 2}},
             "cost_ceiling_usd": "5.00", "_seed": 11}
        )
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(disp))
    assert done.status == "completed"
    return done


# --------------------------------------------------------------------------- #
# 1. replace_from_db concurrency protection
# --------------------------------------------------------------------------- #
def test_replace_from_db_refuses_while_run_lock_held(jobs_app, jobs_root, llm_ready):
    done = _mixed(jobs_app)
    db_s = next(s for s in done.slots if s.kind == "database")

    assert service._RUN_LOCK.acquire(blocking=False)
    try:
        with jobs_app.app_context():
            with pytest.raises(service.JobBusy):
                service.replace_from_db(done.job_id, db_s.instance_id)
    finally:
        service._RUN_LOCK.release()

    # slot untouched by the refused call
    still = store.load(done.job_id).slot_by_instance(db_s.instance_id)
    assert still.db_id == db_s.db_id and still.kind == "database"


def test_replace_db_route_returns_409_when_busy(jobs_client, jobs_app, jobs_root, llm_ready):
    jobs_app.config["EXAM_JOB_SYNC"] = True
    jobs_app.config["EXAM_JOB_PROVIDER_FACTORY"] = dispatch_factory(Dispatch())
    r = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 4, "database": 2, "llm": 2}},
        "cost_ceiling_usd": "5.00", "_seed": 11,
    })
    assert r.status_code == 202
    jid = r.get_json()["job_id"]
    view = jobs_client.get(f"/api/exam-jobs/{jid}").get_json()
    db_q = next(q for q in view["questions"] if q["origin"] == "database")

    assert service._RUN_LOCK.acquire(blocking=False)
    try:
        resp = jobs_client.post(
            f"/api/exam-jobs/{jid}/questions/{db_q['instance_id']}/replace-db"
        )
    finally:
        service._RUN_LOCK.release()
    assert resp.status_code == 409


def test_sequential_db_replacements_never_duplicate_or_lose_updates(jobs_app, jobs_root, llm_ready):
    """Simulates a double click resolved one-at-a-time: every swap yields a row
    that is not already in the exam, numbers stay 1..N, no duplicate db_id."""
    done = _mixed(jobs_app)
    db_s = next(s for s in done.slots if s.kind == "database")
    iid = db_s.instance_id

    seen = {db_s.db_id}
    for _ in range(3):
        with jobs_app.app_context():
            up = service.replace_from_db(done.job_id, iid)
        ns = up.slot_by_instance(iid)
        db_ids = [s.db_id for s in up.slots if s.kind == "database"]
        assert len(db_ids) == len(set(db_ids))          # no duplicate selection
        assert ns.db_id not in (seen - {ns.db_id})      # different from prior picks / siblings
        seen.add(ns.db_id)
        assert [q["number"] for q in service.result_view(up)["questions"]] == [1, 2, 3, 4]
        plan = up.plan_for(CAT)
        assert sorted(plan.db_selected_ids) == sorted(db_ids)  # persistence stays consistent


# --------------------------------------------------------------------------- #
# 2. ledger-derived attempt / retry telemetry
# --------------------------------------------------------------------------- #
def test_attempt_telemetry_folds_the_ledger_by_category_and_slot(jobs_app, jobs_root, llm_ready):
    disp = Dispatch()
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 3, "database": 1, "llm": 2}},
             "cost_ceiling_usd": "5.00", "_seed": 6}
        )
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(disp))

    tel = service.ledger_telemetry(done)
    assert set(tel) == {"by_category", "by_slot", "totals"}
    assert tel["totals"]["ledger_entries"] == len(done.cost_ledger)
    # one category touched by LLM work
    assert CAT in tel["by_category"]
    cat = tel["by_category"][CAT]
    assert cat["accepted"] == 2 and cat["attempts"] >= 2
    assert Decimal(cat["cost_usd"]) == Decimal(done.accumulated_cost_usd)
    # per-slot rows only for slots that made a generator call (the 2 LLM slots)
    llm_slot_ids = {s.slot_id for s in done.slots if s.kind == "llm"}
    assert set(tel["by_slot"]) == llm_slot_ids
    for sid, row in tel["by_slot"].items():
        assert row["kind"] == "llm"
        assert row["outcomes"] and row["accepted"] == 1
    # telemetry sums to the job total
    assert Decimal(tel["totals"]["cost_usd"]) == Decimal(done.accumulated_cost_usd)
    # exposed on result_view / the GET route payload
    assert service.result_view(done)["attempt_telemetry"] == tel


def test_charged_failed_attempt_survives_slot_rollback(jobs_app, jobs_root, llm_ready):
    """A rejected LLM replacement restores the slot (attempts back to 0) but its
    charged attempt stays visible in the ledger telemetry."""
    done = _mixed(jobs_app)
    db_s = next(s for s in done.slots if s.kind == "database")
    iid = db_s.instance_id
    tel_before = service.ledger_telemetry(done)

    up = service.replace_via_llm(
        done.job_id, iid,
        provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)),
    )
    ns = up.slot_by_instance(iid)
    # slot fully rolled back
    assert ns.kind == "database" and ns.attempts == 0 and ns.retries == 0

    tel = service.ledger_telemetry(up)
    cat = tel["by_category"][CAT]
    assert cat["charged_failed_attempts"] >= 1
    assert cat["replacements"] >= 1
    # the failed attempt is attributed to the slot even though the slot shows nothing
    srow = tel["by_slot"][db_s.slot_id]
    assert srow["charged_failed_attempts"] >= 1
    assert any(o != "accepted" for o in srow["outcomes"])
    # and it only grew the ledger (immutably) relative to before
    assert tel["totals"]["ledger_entries"] > tel_before["totals"]["ledger_entries"]
    assert Decimal(tel["totals"]["cost_usd"]) > Decimal(tel_before["totals"]["cost_usd"])


# --------------------------------------------------------------------------- #
# 3. no recomputed / current DB-vs-LLM aggregate
# --------------------------------------------------------------------------- #
_ORIGIN_AGGREGATE_HINTS = (
    "current_database", "current_llm", "realized", "realised",
    "db_count", "llm_count", "database_current", "llm_current",
    "composition", "actual_database", "actual_llm",
)


def _assert_no_origin_aggregate(view: dict) -> None:
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                lk = str(k).lower()
                assert not any(h in lk for h in _ORIGIN_AGGREGATE_HINTS), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(view)


def test_views_never_report_a_current_db_vs_llm_balance(jobs_app, jobs_root, llm_ready):
    done = _mixed(jobs_app)
    db_s = next(s for s in done.slots if s.kind == "database")
    llm_s = next(s for s in done.slots if s.kind == "llm" and s.status == "accepted")

    # flip both origins
    service.replace_via_llm(done.job_id, db_s.instance_id,
                            provider_factory=dispatch_factory(Dispatch()))
    with jobs_app.app_context():
        service.replace_from_db(done.job_id, llm_s.instance_id)

    reloaded = store.load(done.job_id)
    view = service.result_view(reloaded)
    prog = reloaded.progress_view()

    # request provenance is unchanged (still 2 / 2), NOT recomputed to realised
    assert view["categories"][CAT]["database"] == 2
    assert view["categories"][CAT]["llm"] == 2
    # the only per-question composition signal is the origin field
    origins = {q["instance_id"]: q["origin"] for q in view["questions"]}
    assert origins[db_s.instance_id] == "llm"
    assert origins[llm_s.instance_id] == "database"
    # no key anywhere that looks like a recomputed origin tally
    _assert_no_origin_aggregate(view)
    _assert_no_origin_aggregate(prog)
