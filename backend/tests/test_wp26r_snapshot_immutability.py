"""WP26R §5 -- immutable question/category snapshots: ``result_view`` (and
everything derived from it -- DOCX input, both Excel exports) must render
from persisted slot data alone, never a live ``Question`` re-query, and a
pre-WP26R job without a category snapshot falls back deterministically
without being rewritten.
"""

from __future__ import annotations

import json

from tests._wp18_fakes import Dispatch, dispatch_factory

from src.jobs import service, store
from src.jobs.model import Job, Slot, CategoryPlan

CAT = "היסטולוגיה"
NEW_CAT = "התעלה השדרתית ותכולתה"


def _db_only_job(jobs_app, *, total=1):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": total, "database": total, "llm": 0}},
            "cost_ceiling_usd": "5.00", "_seed": 1,
        })
    return service.run_job(job.job_id)


def _mutate_and_delete(jobs_app, keep_id, mutate_id):
    """Mutate one DB row's every field the snapshot must be immune to, and
    delete another entirely."""
    with jobs_app.app_context():
        from src.models.question import Question
        from src.models.user import db

        row = Question.query.get(mutate_id)
        row.question = "שאלה שונתה לאחר יצירת המבחן"
        row.answer1 = "תשובה 1 שונתה"
        row.answer2 = "תשובה 2 שונתה"
        row.answer3 = "תשובה 3 שונתה"
        row.answer4 = "תשובה 4 שונתה"
        row.correct_answer_id = 4 if row.correct_answer_id != 4 else 3
        row.categories = [NEW_CAT]  # also changes the primary (categories[0])
        row.accuracy_list = [1.0, 2.0, 3.0]
        row.distinction_list = [0.9]
        if keep_id is not None:
            db.session.delete(Question.query.get(keep_id))
        db.session.commit()


def test_result_view_immune_to_live_db_edit_and_delete(jobs_app, jobs_root):
    done = _db_only_job(jobs_app, total=2)
    with jobs_app.app_context():
        before = service.result_view(done)
    db_ids = [s.db_id for s in done.slots if s.kind == "database"]

    _mutate_and_delete(jobs_app, db_ids[0], db_ids[1])  # delete one, mutate the other

    reloaded = store.load(done.job_id)
    with jobs_app.app_context():
        after = service.result_view(reloaded)

    # every field of every question -- text, answers, correct answer, primary
    # category, full category list, analytics -- is byte-stable
    assert after["questions"] == before["questions"]


def test_export_full_xlsx_immune_to_live_db_edit(jobs_app, jobs_root):
    done = _db_only_job(jobs_app, total=1)
    before_bytes = service.export_full_xlsx(done)
    db_id = done.slots[0].db_id
    _mutate_and_delete(jobs_app, None, db_id)
    reloaded = store.load(done.job_id)
    after_bytes = service.export_full_xlsx(reloaded)
    assert before_bytes == after_bytes


def test_docx_view_input_immune_to_live_db_edit(jobs_app, jobs_root):
    """`result_view`'s per-question dict is exactly what the frontend strips
    down to the seven public fields for DOCX -- proving it here proves DOCX
    input is snapshot-based transitively."""
    done = _db_only_job(jobs_app, total=1)
    with jobs_app.app_context():
        before = service.result_view(done)["questions"][0]
    db_id = done.slots[0].db_id
    _mutate_and_delete(jobs_app, None, db_id)
    reloaded = store.load(done.job_id)
    with jobs_app.app_context():
        after = service.result_view(reloaded)["questions"][0]
    for f in ("question", "answer1", "answer2", "answer3", "answer4", "correct_answer"):
        assert before[f] == after[f]


def test_branch_after_live_db_mutation_copies_parent_snapshot_not_new_db_state(jobs_app, jobs_root):
    done = _db_only_job(jobs_app, total=1)
    db_id = done.slots[0].db_id
    original_question_text = done.slots[0].question["question"]
    original_categories = list(done.slots[0].categories)

    _mutate_and_delete(jobs_app, None, db_id)

    with jobs_app.app_context():
        child = service.branch_job(done.job_id, None)
    child_slot = child.slots[0]
    assert child_slot.question["question"] == original_question_text
    assert child_slot.categories == original_categories
    assert child_slot.primary_category == done.slots[0].primary_category

    with jobs_app.app_context():
        view = service.result_view(child)
    assert view["questions"][0]["question"] == original_question_text
    assert view["questions"][0]["categories"] == original_categories


# --------------------------------------------------------------------------- #
# legacy (pre-WP26R) jobs: deterministic fallback, never rewritten
# --------------------------------------------------------------------------- #
def _legacy_job_without_category_snapshot():
    job = Job(
        job_id="22222222-2222-2222-2222-222222222222",
        status="completed",
        categories=[CategoryPlan(category=CAT, context_id="chapter_09", order_index=7,
                                  total=1, database=1, llm=0, number_base=0, db_selected_ids=[1])],
        slots=[Slot(
            slot_id="s1", instance_id="i1", category=CAT, context_id="chapter_09",
            kind="database", order_in_category=0, number=1, status="accepted",
            question={"number": 1, "question": "שאלה ישנה", "answer1": "a", "answer2": "b",
                      "answer3": "c", "answer4": "d", "correct_answer": 1},
            db_id=1,
            # primary_category / categories deliberately omitted (pre-WP26R shape)
        )],
    )
    return job


def test_legacy_job_without_snapshot_uses_deterministic_fallback(jobs_app, jobs_root):
    job = _legacy_job_without_category_snapshot()
    store.save(job)
    reloaded = store.load(job.job_id)
    assert reloaded.slots[0].primary_category is None  # not backfilled in memory either
    assert reloaded.slots[0].categories is None

    with jobs_app.app_context():
        view = service.result_view(reloaded)
    q = view["questions"][0]
    assert q["primary_category"] == CAT      # deterministic fallback = Slot.category
    assert q["categories"] == [CAT]


def test_legacy_job_file_never_rewritten_by_reading_it(jobs_app, jobs_root):
    """A genuinely pre-WP26R file (no ``primary_category``/``categories`` keys
    at all, not merely ``null``-valued) must round-trip byte-identical through
    ``store.load`` + ``result_view`` -- the fallback is computed at read time
    only, never backfilled onto disk."""
    job = _legacy_job_without_category_snapshot()
    store.save(job)
    raw = store._job_file(job.job_id).read_text(encoding="utf-8")
    d = json.loads(raw)
    for legacy_missing_field in ("primary_category", "categories"):
        d["slots"][0].pop(legacy_missing_field, None)
    store._job_file(job.job_id).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    raw_before = store._job_file(job.job_id).read_bytes()

    reloaded = store.load(job.job_id)
    assert reloaded.slots[0].primary_category is None
    assert reloaded.slots[0].categories is None
    with jobs_app.app_context():
        view = service.result_view(reloaded)
    assert view["questions"][0]["primary_category"] == CAT
    assert view["questions"][0]["categories"] == [CAT]

    raw_after = store._job_file(job.job_id).read_bytes()
    assert raw_before == raw_after
    d_after = json.loads(raw_after)
    assert "primary_category" not in d_after["slots"][0]
    assert "categories" not in d_after["slots"][0]


# --------------------------------------------------------------------------- #
# replacements create correct NEW snapshots
# --------------------------------------------------------------------------- #
def test_db_replacement_creates_a_fresh_category_snapshot(jobs_app, jobs_root):
    done = _db_only_job(jobs_app, total=1)
    slot = done.slots[0]
    with jobs_app.app_context():
        updated = service.replace_from_db(done.job_id, slot.instance_id)
    new_slot = updated.slot_by_instance(slot.instance_id)
    with jobs_app.app_context():
        from src.models.question import Question

        row = Question.query.get(new_slot.db_id)
    assert new_slot.primary_category == row.category
    assert new_slot.categories == list(row.categories)


def test_llm_replacement_snapshot_reflects_fixed_target_category(jobs_app, jobs_root, llm_ready):
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
            "cost_ceiling_usd": "5.00",
        })
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    llm_slot = done.slots[0]
    assert llm_slot.primary_category == CAT
    assert llm_slot.categories == [CAT]

    updated = service.replace_via_llm(
        done.job_id, llm_slot.instance_id, provider_factory=dispatch_factory(Dispatch()),
    )
    new_slot = updated.slot_by_instance(llm_slot.instance_id)
    assert new_slot.primary_category == CAT
    assert new_slot.categories == [CAT]
