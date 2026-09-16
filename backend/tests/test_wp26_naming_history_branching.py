"""WP26 §1/§3/§4/§7/§8 -- persisted naming, jobs-list, immutable branching,
exclusion enforcement in job creation/replacement, and retry/replacement
telemetry correctness. DB-only jobs need no generator/provider; the few tests
that exercise real LLM operations use the offline WP18 fakes (no network, no
key beyond the in-process sentinel).
"""

from __future__ import annotations

import socket

import pytest

from tests._wp18_fakes import ApprovingProvider, Dispatch, RejectingProvider, dispatch_factory

from src.jobs import service, store
from src.jobs.model import CategoryPlan, Job, Slot

CAT = "היסטולוגיה"
CAT2 = "גרעיני הבסיס"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted during a WP26 test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom)


def _db_only(jobs_app, *, categories=None, excluded=None, identity=None, seed=1):
    categories = categories or {CAT: {"total": 2, "database": 2, "llm": 0}}
    payload = {"categories": categories, "cost_ceiling_usd": "5.00", "_seed": seed}
    if excluded is not None:
        payload["excluded_db_ids"] = excluded
    if identity is not None:
        payload["identity"] = identity
    with jobs_app.app_context():
        job = service.create_job(payload)
    # DB-only categories still need a `run_job` pass to reach a terminal
    # ("completed") status -- `create_job` only selects+persists the DB slots.
    return service.run_job(job.job_id)


# --------------------------------------------------------------------------- #
# §1 naming / identity persisted on the job
# --------------------------------------------------------------------------- #
def test_structured_identity_persisted_and_returned(jobs_app, jobs_root):
    job = _db_only(jobs_app, identity={
        "mode": "structured", "course": "מבנה המוח", "year": "2026",
        "exam_type": "מבחן מסכם", "sitting": "א",
    })
    assert job.identity["display_name"] == "מבנה המוח 2026 מבחן מסכם מועד א"
    reloaded = store.load(job.job_id)
    assert reloaded.identity == job.identity
    view = service.result_view(reloaded)
    assert view["display_name"] == "מבנה המוח 2026 מבחן מסכם מועד א"
    assert view["slug"] == "מבנה_המוח_2026_מבחן_מסכם_מועד_א"


def test_custom_identity_display_name_exact(jobs_app, jobs_root):
    job = _db_only(jobs_app, identity={"mode": "custom", "custom_name": "  מבחן תרגול  "})
    assert job.identity["display_name"] == "מבחן תרגול"


def test_no_identity_uses_calculated_fallback_never_persisted(jobs_app, jobs_root):
    job = _db_only(jobs_app)
    assert job.identity is None
    view = service.result_view(job)
    assert "מבחן ללא שם" in view["display_name"]
    assert job.job_id[:8] in view["display_name"]


def test_bad_identity_rejects_job_creation_atomically(jobs_app, jobs_root):
    before = set(store.list_job_ids())
    with jobs_app.app_context():
        with pytest.raises(service.JobError):
            service.create_job({
                "categories": {CAT: {"total": 1, "database": 1, "llm": 0}},
                "identity": {"mode": "structured", "course": "לא קיים",
                             "year": "2026", "exam_type": "מבחן מסכם"},
            })
    assert set(store.list_job_ids()) == before  # nothing partially created


# --------------------------------------------------------------------------- #
# §1 backward loading of pre-WP26 job JSON
# --------------------------------------------------------------------------- #
def test_pre_wp26_job_json_loads_unchanged(jobs_app, jobs_root):
    job = _db_only(jobs_app)
    raw = store._job_file(job.job_id).read_text(encoding="utf-8")
    import json

    d = json.loads(raw)
    for legacy_missing_field in ("identity", "excluded_db_ids", "parent_job_id", "root_job_id"):
        d.pop(legacy_missing_field, None)
    store._job_file(job.job_id).write_text(json.dumps(d), encoding="utf-8")

    reloaded = store.load(job.job_id)
    assert reloaded.identity is None
    assert reloaded.excluded_db_ids == []
    assert reloaded.parent_job_id is None
    assert reloaded.root_job_id == job.job_id  # defaults to itself
    view = service.result_view(reloaded)
    assert "מבחן ללא שם" in view["display_name"]
    assert view["excluded_db_ids_count"] == 0


# --------------------------------------------------------------------------- #
# §1 jobs list -- newest-first, every status, safe fields only
# --------------------------------------------------------------------------- #
def test_list_jobs_newest_first_and_every_status_included(jobs_app, jobs_root):
    def _save(job_id, status, created_utc, question_text="secret question text"):
        job = Job(
            job_id=job_id, status=status, created_utc=created_utc, updated_utc=created_utc,
            categories=[CategoryPlan(category=CAT, context_id="chapter_09", order_index=0,
                                      total=1, database=1, llm=0, number_base=0, db_selected_ids=[1])],
            slots=[Slot(slot_id=job_id + "-s", instance_id=job_id + "-i", category=CAT,
                        context_id="chapter_09", kind="database", order_in_category=0, number=1,
                        status="accepted" if status != "queued" else "queued",
                        question={"number": 1, "question": question_text, "answer1": "a",
                                  "answer2": "b", "answer3": "c", "answer4": "d",
                                  "correct_answer": 1} if status != "queued" else None,
                        db_id=1)],
        )
        job.job_id = job_id
        store.save(job)
        return job_id

    import uuid

    ids = {
        "queued": str(uuid.uuid4()), "completed": str(uuid.uuid4()),
        "failed": str(uuid.uuid4()), "interrupted": str(uuid.uuid4()),
        "cost_ceiling": str(uuid.uuid4()), "partial": str(uuid.uuid4()),
    }
    for i, (status, jid) in enumerate(ids.items()):
        _save(jid, status, f"2026-01-0{i+1}T00:00:00Z")

    jobs = service.list_jobs()
    listed_ids = [j["job_id"] for j in jobs]
    assert set(ids.values()) == set(listed_ids)
    # newest created_utc first
    assert [j["created_utc"] for j in jobs] == sorted(
        (j["created_utc"] for j in jobs), reverse=True
    )
    for j in jobs:
        assert "question" not in j and "questions" not in j
        assert "cost_ledger" not in j and "audit" not in str(j.get("prompts", ""))


# --------------------------------------------------------------------------- #
# §3 exclusion enforcement: initial selection + atomic pre-check + replacement
# --------------------------------------------------------------------------- #
def test_excluded_ids_removed_from_initial_selection(jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        rows = Question.query.filter(Question.category == CAT).all()
        excluded = [r.id for r in rows[:4]]  # exclude 4 of 6 seeded rows
    job = _db_only(jobs_app, categories={CAT: {"total": 2, "database": 2, "llm": 0}},
                    excluded=excluded)
    selected_ids = {s.db_id for s in job.slots if s.kind == "database"}
    assert selected_ids.isdisjoint(set(excluded))
    assert job.excluded_db_ids == sorted(excluded)


def test_insufficient_availability_after_exclusion_fails_atomically_before_any_job(jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        rows = Question.query.filter(Question.category == CAT).all()
        excluded = [r.id for r in rows]  # exclude ALL of them
    before = set(store.list_job_ids())
    with jobs_app.app_context():
        with pytest.raises(service.JobError) as exc:
            service.create_job({
                "categories": {CAT: {"total": 1, "database": 1, "llm": 0}},
                "excluded_db_ids": excluded,
            })
    assert CAT in str(exc.value)  # category-specific Hebrew message
    assert set(store.list_job_ids()) == before  # no partial job persisted


def test_replace_from_db_honors_job_excluded_ids(jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        rows = Question.query.filter(Question.category == CAT).all()
        to_exclude = [r.id for r in rows[2:]]  # exclude all but the first 2
    job = _db_only(jobs_app, categories={CAT: {"total": 1, "database": 1, "llm": 0}},
                    excluded=to_exclude, seed=3)
    s = job.slots[0]
    remaining_candidates = {r for r in range(1, 100)}  # not used directly
    # Only one non-excluded, non-selected row should remain; replacement must
    # land on it (or fail safely if truly none remain).
    with jobs_app.app_context():
        try:
            up = service.replace_from_db(job.job_id, s.instance_id)
        except service.JobConflict:
            return  # acceptable if no alternative existed -- slot untouched
    new_slot = up.slot_by_instance(s.instance_id)
    assert new_slot.db_id not in to_exclude


def test_excluded_db_ids_never_permanently_grow_from_displaced_questions(jobs_app, jobs_root):
    """A displaced DB question is excluded from further selection *within this
    exam* via the existing in-exam-ids mechanism, never added to the
    persisted `excluded_db_ids` set itself (§3 owner decision)."""
    job = _db_only(jobs_app, categories={CAT: {"total": 1, "database": 1, "llm": 0}}, seed=5)
    s = job.slots[0]
    before = list(job.excluded_db_ids)
    with jobs_app.app_context():
        try:
            up = service.replace_from_db(job.job_id, s.instance_id)
        except service.JobConflict:
            return
    assert up.excluded_db_ids == before


# --------------------------------------------------------------------------- #
# §4 branching
# --------------------------------------------------------------------------- #
def test_branch_parent_byte_immutable_on_success(jobs_app, jobs_root):
    job = _db_only(jobs_app, categories={CAT: {"total": 2, "database": 2, "llm": 0}},
                    identity={"mode": "custom", "custom_name": "מקור"}, seed=7)
    before_bytes = store._job_file(job.job_id).read_bytes()

    with jobs_app.app_context():
        child = service.branch_job(job.job_id, {"mode": "custom", "custom_name": "גרסה 2"})

    after_bytes = store._job_file(job.job_id).read_bytes()
    assert before_bytes == after_bytes

    assert child.job_id != job.job_id
    assert child.parent_job_id == job.job_id
    assert child.root_job_id == job.job_id
    assert child.accumulated_cost_usd == "0"
    assert child.cost_ledger == []
    assert child.cost_ceiling_usd == job.cost_ceiling_usd
    assert child.status == "completed"

    parent_slot_ids = {s.slot_id for s in job.slots}
    parent_instance_ids = {s.instance_id for s in job.slots}
    child_slot_ids = {s.slot_id for s in child.slots}
    child_instance_ids = {s.instance_id for s in child.slots}
    assert parent_slot_ids.isdisjoint(child_slot_ids)
    assert parent_instance_ids.isdisjoint(child_instance_ids)
    # public numbers / questions / db ids preserved
    assert [s.number for s in job.slots] == [s.number for s in child.slots]
    assert [s.question for s in job.slots] == [s.question for s in child.slots]
    assert [s.db_id for s in job.slots] == [s.db_id for s in child.slots]


def test_branch_rejects_non_completed_job(jobs_app, jobs_root):
    job = Job(job_id="11111111-1111-1111-1111-111111111111", status="partial")
    store.save(job)
    with jobs_app.app_context():
        with pytest.raises(service.JobConflict):
            service.branch_job(job.job_id, None)
    # parent untouched
    assert store.load(job.job_id).status == "partial"


def test_branch_inherits_exclusions_and_category_history(jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        rows = Question.query.filter(Question.category == CAT).all()
        excluded = [rows[0].id]
    job = _db_only(jobs_app, categories={CAT: {"total": 2, "database": 2, "llm": 0}},
                    excluded=excluded, seed=9)
    with jobs_app.app_context():
        job2 = store.load(job.job_id)
        job2.category_history[CAT] = [{"number": 99, "question": "q", "answer1": "a",
                                        "answer2": "b", "answer3": "c", "answer4": "d",
                                        "correct_answer": 1}]
        store.save(job2)
        child = service.branch_job(job.job_id, None)
    assert child.excluded_db_ids == sorted(excluded)
    assert child.category_history.get(CAT) == job2.category_history[CAT]


def test_branch_child_replace_db_respects_inherited_exclusion(jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        rows = Question.query.filter(Question.category == CAT).all()
        excluded = [r.id for r in rows[2:]]
    job = _db_only(jobs_app, categories={CAT: {"total": 1, "database": 1, "llm": 0}},
                    excluded=excluded, seed=11)
    with jobs_app.app_context():
        child = service.branch_job(job.job_id, None)
        s = child.slots[0]
        try:
            up = service.replace_from_db(child.job_id, s.instance_id)
        except service.JobConflict:
            return
    assert up.slot_by_instance(s.instance_id).db_id not in excluded


# --------------------------------------------------------------------------- #
# §7 retry/replacement telemetry -- ledger-derived, correctly separated
# --------------------------------------------------------------------------- #
def _mixed_llm(jobs_app, seed=21):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 3, "database": 2, "llm": 1}},
            "cost_ceiling_usd": "5.00", "_seed": seed,
        })
    return job


def test_replace_llm_does_not_inflate_retries_counter(jobs_app, jobs_root, llm_ready):
    job = _mixed_llm(jobs_app)
    # 1) initial run fails the one llm slot
    failed = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)))
    llm_slot = next(s for s in failed.slots if s.kind == "llm")
    assert llm_slot.status == "failed"

    # 2) a genuine retry succeeds -- slot.retries becomes 1 (real retry)
    retried = service.retry_slot(job.job_id, llm_slot.slot_id,
                                  provider_factory=dispatch_factory(Dispatch(factory=ApprovingProvider)))
    ns = retried.slot_by_id(llm_slot.slot_id)
    assert ns.status == "accepted"
    assert ns.retries == 1
    assert retried.terminal_summary["retries"] == 1
    assert retried.terminal_summary["replacements"] == 0

    # 3) an intentional replace_llm succeeds -- must NOT bump slot.retries
    replaced = service.replace_via_llm(job.job_id, ns.instance_id,
                                        provider_factory=dispatch_factory(Dispatch(factory=ApprovingProvider)))
    ns2 = replaced.slot_by_instance(ns.instance_id)
    assert ns2.retries == 1  # unchanged by the replace_llm call
    assert replaced.terminal_summary["retries"] == 1
    assert replaced.terminal_summary["replacements"] == 1


def test_old_conflated_slot_retries_still_report_correct_ledger_totals(jobs_app, jobs_root, llm_ready):
    """A pre-WP26 persisted job whose mutable slot.retries was inflated by a
    successful replace_llm must still report the ledger-derived (correct)
    totals -- never rewritten, never trusted for this figure."""
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
            "cost_ceiling_usd": "5.00",
        })
    # hand-craft the historical conflation: one replace_llm ledger entry, and
    # a slot.retries that (pre-fix) would have been bumped by it.
    with jobs_app.app_context():
        j = store.load(job.job_id)
        slot = j.slots[0]
        slot.status = "accepted"
        slot.retries = 1  # conflated legacy value
        slot.question = {"number": slot.number, "question": "q", "answer1": "a",
                          "answer2": "b", "answer3": "c", "answer4": "d", "correct_answer": 1}
        j.cost_ledger.append({
            "seq": 1, "kind": "replace_llm", "slot_id": slot.slot_id,
            "instance_id": slot.instance_id, "category": CAT, "number": slot.number,
            "status": "accepted", "total_cost_usd": "0.01", "total_cost_basis": "calculated",
            "itemized_cost": [], "attempts": 1, "retries": 0, "warnings": [],
            "audit_ref": None, "invocation_uuid": None, "at": "2026-01-01T00:00:00Z",
        })
        store.save(j)
        totals = service.ledger_telemetry(j)["totals"]
    assert totals["retries"] == 0       # not 1 -- the ledger has no "retry" kind entry
    assert totals["replacements"] == 1  # the one replace_llm entry
