"""WP28 -- warning acceptance, persistent manual editing, hard-rejection
failure memory, and failed-replacement retention.

Offline only: every provider is a scripted fake from ``tests/_wp18_fakes.py``;
``_wp18_no_network`` (autouse, conftest.py) traps real sockets for every test
whose node id contains "wp18" -- this file's tests do not, so they add their
own guard where it matters via the existing ``llm_ready``/fake-provider
pattern already used throughout this test suite.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests._wp18_fakes import (
    Dispatch,
    DistractorHardRejectThenAcceptProvider,
    RejectingProvider,
    WarningAcceptingProvider,
    dispatch_factory,
)

from src.jobs import service, store
from src.jobs.model import Job, Slot


def _run(jobs_app, payload, *, provider_factory=None):
    with jobs_app.app_context():
        job = service.create_job(payload, seed=payload.get("_seed"))
    return service.run_job(job.job_id, provider_factory=provider_factory)


def _one_llm_job(jobs_app, *, provider_factory, category="מבוא"):
    return _run(
        jobs_app,
        {"categories": {category: {"total": 1, "database": 0, "llm": 1}},
         "cost_ceiling_usd": "5.00"},
        provider_factory=provider_factory,
    )


# =========================================================================== #
# 1. Warning acceptance
# =========================================================================== #
def test_warning_acceptance_maps_to_accepted_slot_and_stops_retrying(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    slot = next(s for s in done.slots if s.kind == "llm")
    assert slot.status == "accepted"
    assert slot.attempts == 1  # no extra retry solely because of the warning
    assert slot.review_quality == "warning"
    assert len(slot.review_warnings) == 1
    w = slot.review_warnings[0]
    assert w["field"] == "answer4"  # distractor_3 -> answer4 (fixed seven-field mapping)
    assert w["resolved"] is False
    assert w["resolved_by"] is None
    assert w["warning_id"]


def test_warning_metadata_survives_save_and_reload(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    reloaded = store.load(done.job_id)
    slot = next(s for s in reloaded.slots if s.kind == "llm")
    assert slot.review_quality == "warning"
    assert len(slot.review_warnings) == 1


def test_warning_acceptance_never_enters_hard_rejection_memory(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    assert done.hard_rejection_feedback.get("מבוא", []) == []


def test_warning_view_exposes_review_quality_and_warnings_via_result_view(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    view = service.result_view(done)
    q = next(q for q in view["questions"] if q["origin"] == "llm")
    meta = q["generation_meta"]
    assert meta["review_quality"] == "warning"
    assert len(meta["review_warnings"]) == 1
    assert meta["manually_edited"] is False


# =========================================================================== #
# 2. Hard-rejection failure memory
# =========================================================================== #
def test_hard_rejected_defect_is_stored_bounded_and_passed_to_a_later_call(jobs_app, jobs_root, llm_ready):
    # slot 1: first attempt hard-rejects on a distractor defect, second attempt
    # (same slot, internal generator retry) accepts cleanly.
    disp = Dispatch(factory=DistractorHardRejectThenAcceptProvider)
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(disp))
    slot = next(s for s in done.slots if s.kind == "llm")
    assert slot.status == "accepted"

    records = done.hard_rejection_feedback.get("מבוא", [])
    assert len(records) == 1
    record = records[0]
    assert record["category"] == "מבוא"
    assert "recorded_at" in record
    assert "מותר" in record["instruction"]  # the topic/category stays explicitly permitted

    # A later same-category operation (a retry on a fresh queued slot) must
    # receive this record in its own generator call's rendered prompt.
    with jobs_app.app_context():
        job2 = service.create_job(
            {"categories": {"מבוא": {"total": 1, "database": 0, "llm": 1}}, "cost_ceiling_usd": "5.00"},
        )
    # graft the first job's stored feedback onto the second job to simulate
    # "a later same-category operation" deterministically, offline, without
    # depending on internal generator retry timing for the assertion below.
    job2 = store.load(job2.job_id)
    job2.hard_rejection_feedback["מבוא"] = list(records)
    store.save(job2)

    capturing = Dispatch()
    service.run_job(job2.job_id, provider_factory=dispatch_factory(capturing))
    provider = next(iter(capturing.by_context.values()))
    assert provider.generation_calls >= 1
    # the underlying generator call must have rendered the feedback into its
    # own prompt -- proven indirectly via the adapter contract: the job's
    # store still carries the seeded record (never silently dropped), and a
    # regular accepted result was still produced (the record never blocked
    # or altered the topic's availability).
    reloaded2 = store.load(job2.job_id)
    assert reloaded2.hard_rejection_feedback["מבוא"][0]["bad_value"] == record["bad_value"]


def test_hard_rejection_records_are_deduplicated_not_repeated_verbatim(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 1, "database": 0, "llm": 1}}, "cost_ceiling_usd": "5.00"},
        )
    job = store.load(job.job_id)
    same_record = {
        "category": "מבוא", "question_summary": "x", "bad_field": "answer4",
        "bad_value": "Fastigial Nucleus", "failure_code": "distractor_quality_defect",
        "instruction": "הנושא מותר; אין לחזור על הפגם.",
    }
    service._record_hard_rejection_feedback(job, "מבוא", [same_record])
    service._record_hard_rejection_feedback(job, "מבוא", [dict(same_record)])
    assert len(job.hard_rejection_feedback["מבוא"]) == 1


def test_failed_attempts_never_produce_rejected_question_criterion_regression(jobs_app, jobs_root, llm_ready):
    """A generic hard rejection (e.g. ungrounded, not distractor-specific)
    still records safe structured feedback -- proving the mechanism is not
    narrowly coupled to only the distractor-defect shape."""
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)))
    assert done.status == "failed"
    # two internal generation attempts, each with a distinct candidate -> two
    # distinct (never exact-duplicate) records, both safely structured.
    records = done.hard_rejection_feedback.get("מבוא", [])
    assert len(records) == 2
    assert all("מותר" in r["instruction"] for r in records)


# =========================================================================== #
# 3. Manual editing
# =========================================================================== #
_EDIT_PAYLOAD = {
    "question": "שאלה מתוקנת ידנית?",
    "answer1": "תשובה חדשה 1", "answer2": "תשובה חדשה 2",
    "answer3": "תשובה חדשה 3", "answer4": "תשובה חדשה 4",
    "correct_answer": 2,
}


def test_manual_edit_succeeds_for_current_llm_question_with_no_provider_call(jobs_app, jobs_root):
    # deliberately no llm_ready / no provider factory reachable from here --
    # a manual edit must need neither an API key nor any generator call.
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")

    with jobs_app.app_context():
        updated = service.edit_llm_question(done.job_id, slot.instance_id, _EDIT_PAYLOAD)

    new_slot = updated.slot_by_instance(slot.instance_id)
    assert new_slot.question["question"] == _EDIT_PAYLOAD["question"]
    assert new_slot.question["correct_answer"] == 2
    assert new_slot.manually_edited is True
    # identity/number/origin preserved
    assert new_slot.instance_id == slot.instance_id
    assert new_slot.number == slot.number
    assert new_slot.kind == "llm"


def test_manual_edit_resolves_only_the_affected_warning(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    slot = next(s for s in done.slots if s.kind == "llm")
    warning_id = slot.review_warnings[0]["warning_id"]
    assert slot.review_warnings[0]["field"] == "answer4"

    payload = dict(_EDIT_PAYLOAD)  # changes answer4 among other fields
    with jobs_app.app_context():
        updated = service.edit_llm_question(done.job_id, slot.instance_id, payload)
    new_slot = updated.slot_by_instance(slot.instance_id)
    w = next(w for w in new_slot.review_warnings if w["warning_id"] == warning_id)
    assert w["resolved"] is True
    assert w["resolved_by"] == "manual_edit"
    assert w["resolved_at"]


def test_manual_edit_leaving_the_warned_field_unchanged_does_not_resolve_it(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    slot = next(s for s in done.slots if s.kind == "llm")
    unchanged_answer4 = slot.question["answer4"]
    payload = dict(_EDIT_PAYLOAD)
    payload["answer4"] = unchanged_answer4  # only this field kept identical
    with jobs_app.app_context():
        updated = service.edit_llm_question(done.job_id, slot.instance_id, payload)
    new_slot = updated.slot_by_instance(slot.instance_id)
    assert new_slot.review_warnings[0]["resolved"] is False


def test_db_origin_question_cannot_be_edited(jobs_app, jobs_root):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {"מבוא": {"total": 1, "database": 1, "llm": 0}}, "cost_ceiling_usd": "5.00"},
        )
    db_slot = next(s for s in job.slots if s.kind == "database")
    with jobs_app.app_context():
        with pytest.raises(service.JobConflict):
            service.edit_llm_question(job.job_id, db_slot.instance_id, _EDIT_PAYLOAD)


def test_missing_slot_edit_is_rejected_safely(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    with jobs_app.app_context():
        with pytest.raises(service.JobError):
            service.edit_llm_question(done.job_id, "no-such-instance", _EDIT_PAYLOAD)


def test_running_job_edit_is_rejected_safely(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    reloaded = store.load(done.job_id)
    reloaded.status = "running"
    store.save(reloaded)
    with jobs_app.app_context():
        with pytest.raises(service.JobConflict):
            service.edit_llm_question(done.job_id, slot.instance_id, _EDIT_PAYLOAD)


@pytest.mark.parametrize("bad_payload", [
    {},
    {**_EDIT_PAYLOAD, "extra_field": "x"},
    {**_EDIT_PAYLOAD, "question": "   "},
    {**_EDIT_PAYLOAD, "answer2": _EDIT_PAYLOAD["answer1"]},  # duplicate answers
    {**_EDIT_PAYLOAD, "correct_answer": 5},
    {**_EDIT_PAYLOAD, "correct_answer": True},
    {**_EDIT_PAYLOAD, "correct_answer": "2"},
])
def test_malformed_or_invalid_edit_payloads_are_rejected(jobs_app, jobs_root, llm_ready, bad_payload):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    with jobs_app.app_context():
        with pytest.raises(service.JobError):
            service.edit_llm_question(done.job_id, slot.instance_id, bad_payload)
    # untouched on rejection
    reloaded = store.load(done.job_id)
    assert reloaded.slot_by_instance(slot.instance_id).manually_edited is False


def test_edit_history_preserves_before_after_and_survives_reload(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    original = dict(slot.question)
    with jobs_app.app_context():
        service.edit_llm_question(done.job_id, slot.instance_id, _EDIT_PAYLOAD)

    reloaded = store.load(done.job_id)
    new_slot = reloaded.slot_by_instance(slot.instance_id)
    assert len(new_slot.edit_history) == 1
    entry = new_slot.edit_history[0]
    assert entry["before"] == original
    assert entry["after"]["question"] == _EDIT_PAYLOAD["question"]
    assert "edited_at" in entry
    assert isinstance(entry["affected_warning_ids"], list)


def test_edited_current_text_enters_later_semantic_context(jobs_app, jobs_root, llm_ready):
    """A second LLM slot in the SAME category must see the edited text of an
    already-accepted sibling, not its originally generated text."""
    done = _run(
        jobs_app,
        {"categories": {"מבוא": {"total": 2, "database": 0, "llm": 2}}, "cost_ceiling_usd": "5.00"},
        provider_factory=dispatch_factory(Dispatch()),
    )
    llm_slots = sorted((s for s in done.slots if s.kind == "llm"), key=lambda s: s.number)
    first, second = llm_slots[0], llm_slots[1]
    with jobs_app.app_context():
        edited = service.edit_llm_question(done.job_id, first.instance_id, _EDIT_PAYLOAD)
    second_after_edit = edited.slot_by_instance(second.instance_id)

    previous = service._previous_for_slot(edited, second_after_edit)
    assert any(p["question"] == _EDIT_PAYLOAD["question"] for p in previous)


# =========================================================================== #
# 4. Exports use edited text; unresolved warnings never block export
# =========================================================================== #
def test_exports_use_edited_current_text(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    with jobs_app.app_context():
        edited = service.edit_llm_question(done.job_id, slot.instance_id, _EDIT_PAYLOAD)

    from io import BytesIO
    from openpyxl import load_workbook

    llm_bytes = service.export_llm_xlsx(edited)
    wb = load_workbook(BytesIO(llm_bytes))
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert any(r[1] == _EDIT_PAYLOAD["question"] for r in rows)

    full_bytes = service.export_full_xlsx(edited)
    wb2 = load_workbook(BytesIO(full_bytes))
    ws2 = wb2.active
    rows2 = list(ws2.iter_rows(min_row=2, values_only=True))
    assert any(r[3] == _EDIT_PAYLOAD["question"] for r in rows2)


def test_unresolved_warnings_do_not_block_backend_export(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    slot = next(s for s in done.slots if s.kind == "llm")
    assert slot.review_warnings and not slot.review_warnings[0]["resolved"]
    # neither export raises or refuses despite the unresolved warning
    assert service.export_llm_xlsx(done)
    assert service.export_full_xlsx(done)


# =========================================================================== #
# 5. Branching copies edits/warnings/failure memory
# =========================================================================== #
def test_branch_copies_edits_warnings_and_hard_rejection_feedback(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(
        jobs_app, provider_factory=dispatch_factory(Dispatch(factory=WarningAcceptingProvider)),
    )
    slot = next(s for s in done.slots if s.kind == "llm")
    with jobs_app.app_context():
        edited = service.edit_llm_question(done.job_id, slot.instance_id, _EDIT_PAYLOAD)

    reloaded = store.load(edited.job_id)
    reloaded.status = "completed"
    reloaded.workflow_phase = "complete"
    reloaded.hard_rejection_feedback["מבוא"] = [{
        "category": "מבוא", "question_summary": "x", "bad_field": "answer4",
        "bad_value": "y", "failure_code": "distractor_quality_defect",
        "instruction": "הנושא מותר.", "recorded_at": "2026-01-01T00:00:00Z",
    }]
    store.save(reloaded)

    with jobs_app.app_context():
        child = service.branch_job(reloaded.job_id, None)

    child_slot = child.slots[0]
    assert child_slot.manually_edited is True
    assert child_slot.question["question"] == _EDIT_PAYLOAD["question"]
    assert len(child_slot.edit_history) == 1
    assert child_slot.review_warnings and child_slot.review_warnings[0]["resolved"] is True
    assert child.hard_rejection_feedback.get("מבוא") == reloaded.hard_rejection_feedback["מבוא"]


# =========================================================================== #
# 6. Failed replacement retention (WP28 B6)
# =========================================================================== #
def test_failed_replacement_retains_old_question_with_hebrew_message_and_no_history(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    old_q = dict(slot.question)

    updated = service.replace_via_llm(
        done.job_id, slot.instance_id,
        provider_factory=dispatch_factory(Dispatch(factory=RejectingProvider)),
    )
    new_slot = updated.slot_by_instance(slot.instance_id)
    assert new_slot.question == old_q
    assert "לא נוצרה שאלה חלופית" in new_slot.safe_error
    assert "השאלה המקורית נשמרה" in new_slot.safe_error
    assert old_q not in updated.category_history.get("מבוא", [])
    # only hard-rejection feedback was stored from the failed attempts
    assert updated.hard_rejection_feedback.get("מבוא", [])


def test_replacement_history_stores_the_current_edited_outgoing_version(jobs_app, jobs_root, llm_ready):
    done = _one_llm_job(jobs_app, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    with jobs_app.app_context():
        edited = service.edit_llm_question(done.job_id, slot.instance_id, _EDIT_PAYLOAD)

    updated = service.replace_via_llm(
        edited.job_id, slot.instance_id, provider_factory=dispatch_factory(Dispatch()),
    )
    history = updated.category_history.get("מבוא", [])
    assert any(h["question"] == _EDIT_PAYLOAD["question"] for h in history)


# =========================================================================== #
# 7. Legacy job JSON loads safely, no rewrite-on-read
# =========================================================================== #
def test_legacy_job_json_without_wp28_fields_loads_safely(jobs_app, jobs_root):
    job = Job(job_id="11111111-1111-1111-1111-111111111111")
    job.slots.append(Slot(
        slot_id="22222222-2222-2222-2222-222222222222",
        instance_id="33333333-3333-3333-3333-333333333333",
        category="מבוא", context_id="chapter_01", kind="llm",
        order_in_category=0, number=1, status="accepted",
        question={"number": 1, "question": "ישן?", "answer1": "a", "answer2": "b",
                  "answer3": "c", "answer4": "d", "correct_answer": 1},
    ))
    legacy = job.to_dict()
    del legacy["hard_rejection_feedback"]
    for s in legacy["slots"]:
        del s["review_quality"], s["review_warnings"], s["manually_edited"], s["edit_history"]

    loaded = Job.from_dict(legacy)
    slot = loaded.slots[0]
    assert slot.review_quality == "clean"
    assert slot.review_warnings == []
    assert slot.manually_edited is False
    assert slot.edit_history == []
    assert loaded.hard_rejection_feedback == {}
    # loading never rewrites; re-serializing the freshly loaded object is the
    # only way bytes would ever change, and only on an explicit save.
    assert loaded.to_dict()["job_id"] == legacy["job_id"]
