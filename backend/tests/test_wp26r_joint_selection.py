"""WP26R §4 -- globally feasible unique DB selection across overlapping
categories, replacing the old independent-precheck-plus-greedy-selection
approach. Offline, temp DB + temp job store; zero provider/network calls.
"""

from __future__ import annotations

import pytest

from src.jobs import service, store
from src.utils.category_order import CATEGORY_ORDER

# real canonical categories, in a known relative CATEGORY_ORDER position
A = "היסטולוגיה"                    # index 7
B = "גרעיני הבסיס"                  # index 6 -- processed BEFORE A in canonical order
C = "מבוא"                          # index 0 -- processed first of all


def _wipe_seeded(jobs_app):
    """``jobs_app`` pre-seeds 6 rows each in A/B/C; clear them so each test
    controls its own exact question set."""
    with jobs_app.app_context():
        from src.models.question import Question
        from src.models.user import db

        Question.query.delete()
        db.session.commit()


def _mk(jobs_app, categories: list[str], *, text_prefix="q"):
    """Create one question with the given (ordered) category list; returns its id."""
    with jobs_app.app_context():
        from src.models.question import Question
        from src.models.user import db

        q = Question(
            category=categories[0], question=f"{text_prefix} {categories}",
            answer1="a", answer2="b", answer3="c", answer4="d", correct_answer_id=1,
        )
        q.categories = list(categories)
        db.session.add(q)
        db.session.commit()
        return q.id


# --------------------------------------------------------------------------- #
# the audit's exact overlapping-category counterexample -- genuinely infeasible
# --------------------------------------------------------------------------- #
def test_audit_counterexample_correctly_rejected_atomically(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    _mk(jobs_app, [A])       # q1: A only
    _mk(jobs_app, [A, B])    # q2: A and B
    _mk(jobs_app, [B])       # q3: B only
    # A needs 2 (only {q1,q2} eligible -> both forced into A), B needs 2 (only
    # {q2,q3} eligible -> both forced into B) -- q2 cannot fill both -> infeasible,
    # even though independent per-category availability is 2/2 for both.
    before = set(store.list_job_ids())
    with jobs_app.app_context():
        with pytest.raises(service.JobError) as exc:
            service.create_job({
                "categories": {
                    A: {"total": 2, "database": 2, "llm": 0},
                    B: {"total": 2, "database": 2, "llm": 0},
                },
                "cost_ceiling_usd": "5.00",
            })
    assert A in str(exc.value) or B in str(exc.value)
    assert set(store.list_job_ids()) == before  # no partial job persisted


# --------------------------------------------------------------------------- #
# a feasible overlap that a naive greedy (no backtracking) selector can miss
# depending on which candidate it happens to draw first
# --------------------------------------------------------------------------- #
def test_feasible_overlap_always_found_regardless_of_random_draw(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    q_shared = _mk(jobs_app, [A, B])   # eligible for BOTH A and B
    q_a_only = _mk(jobs_app, [A])      # eligible for A only
    # A needs 1, B needs 1: the only feasible assignment is q_a_only -> A,
    # q_shared -> B (q_shared can't satisfy A, since then nothing is left for
    # B). A greedy, non-backtracking selector that happens to draw q_shared
    # for A first would incorrectly report infeasibility.
    for seed in range(20):
        with jobs_app.app_context():
            job = service.create_job({
                "categories": {
                    A: {"total": 1, "database": 1, "llm": 0},
                    B: {"total": 1, "database": 1, "llm": 0},
                },
                "cost_ceiling_usd": "5.00", "_seed": seed,
            })
        db_slots = {s.category: s.db_id for s in job.slots if s.kind == "database"}
        assert db_slots[A] == q_a_only        # the only question with A is q_a_only... wait
        assert db_slots[B] == q_shared
        assert db_slots[A] != db_slots[B]


def test_deterministic_assignment_for_a_fixed_seed(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    for i in range(4):
        _mk(jobs_app, [A, B], text_prefix=f"shared{i}")
    spec = {
        "categories": {
            A: {"total": 2, "database": 2, "llm": 0},
            B: {"total": 2, "database": 2, "llm": 0},
        },
        "cost_ceiling_usd": "5.00", "_seed": 42,
    }
    with jobs_app.app_context():
        job1 = service.create_job(dict(spec))
    with jobs_app.app_context():
        job2 = service.create_job(dict(spec))
    ids1 = sorted(s.db_id for s in job1.slots if s.kind == "database")
    ids2 = sorted(s.db_id for s in job2.slots if s.kind == "database")
    assert ids1 == ids2  # same seed -> same assignment


def test_a_multi_category_db_id_appears_at_most_once_across_the_whole_exam(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    for i in range(5):
        _mk(jobs_app, [A, B, C], text_prefix=f"tri{i}")
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {
                A: {"total": 2, "database": 2, "llm": 0},
                B: {"total": 2, "database": 2, "llm": 0},
                C: {"total": 1, "database": 1, "llm": 0},
            },
            "cost_ceiling_usd": "5.00", "_seed": 7,
        })
    db_ids = [s.db_id for s in job.slots if s.kind == "database"]
    assert len(db_ids) == len(set(db_ids)) == 5  # every id distinct, none reused


def test_every_selected_question_snapshot_contains_its_slot_category(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    for i in range(5):
        _mk(jobs_app, [A, B, C], text_prefix=f"tri{i}")
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {
                A: {"total": 2, "database": 2, "llm": 0},
                B: {"total": 2, "database": 2, "llm": 0},
                C: {"total": 1, "database": 1, "llm": 0},
            },
            "cost_ceiling_usd": "5.00", "_seed": 3,
        })
    for s in job.slots:
        if s.kind == "database":
            assert s.category in s.categories


def test_fixed_canonical_slot_order_independent_of_request_dict_order(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    for i in range(6):
        _mk(jobs_app, [A, B, C], text_prefix=f"tri{i}")
    with jobs_app.app_context():
        job = service.create_job({
            "categories": {  # deliberately NOT canonical order in the dict
                A: {"total": 1, "database": 1, "llm": 0},
                C: {"total": 1, "database": 1, "llm": 0},
                B: {"total": 1, "database": 1, "llm": 0},
            },
            "cost_ceiling_usd": "5.00", "_seed": 1,
        })
    plan_order = [p.category for p in job.categories]
    assert plan_order == sorted(plan_order, key=lambda c: CATEGORY_ORDER.index(c))


def test_exclusions_participate_in_the_global_plan(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    q1 = _mk(jobs_app, [A, B])
    q2 = _mk(jobs_app, [A])
    # excluding q2 leaves only q1 (shared A/B) -- A=1,B=1 becomes infeasible
    # (only one question left, needed by both slots).
    with jobs_app.app_context():
        with pytest.raises(service.JobError):
            service.create_job({
                "categories": {
                    A: {"total": 1, "database": 1, "llm": 0},
                    B: {"total": 1, "database": 1, "llm": 0},
                },
                "cost_ceiling_usd": "5.00",
                "excluded_db_ids": [q2],
            })


def test_independent_availability_message_shown_but_not_relied_on_for_infeasible_case(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    _mk(jobs_app, [A])
    _mk(jobs_app, [A, B])
    _mk(jobs_app, [B])
    with jobs_app.app_context():
        with pytest.raises(service.JobError) as exc:
            service.create_job({
                "categories": {
                    A: {"total": 2, "database": 2, "llm": 0},
                    B: {"total": 2, "database": 2, "llm": 0},
                },
                "cost_ceiling_usd": "5.00",
            })
    msg = str(exc.value)
    # independent counts are surfaced for diagnostics...
    assert "2" in msg
    # ...but the message must not claim the independent counts guarantee feasibility
    assert "לא ניתן להקצות" in msg


# --------------------------------------------------------------------------- #
# DB replacement: Slot.category as target, secondary-category candidates,
# excludes every current DB id, retains on exhaustion
# --------------------------------------------------------------------------- #
def test_db_replacement_accepts_secondary_category_candidate(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    q_primary = _mk(jobs_app, [A])       # A is the PRIMARY category here
    q_secondary = _mk(jobs_app, [B, A])  # A is only a SECONDARY category here
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {A: {"total": 1, "database": 1, "llm": 0}}, "cost_ceiling_usd": "5.00"}
        )
    slot = job.slots[0]
    assert slot.db_id in (q_primary, q_secondary)  # either is a valid initial pick
    with jobs_app.app_context():
        updated = service.replace_from_db(job.job_id, slot.instance_id)
    new_slot = updated.slot_by_instance(slot.instance_id)

    # the only other question is the correct (and only) replacement -- proving
    # a secondary-category-only match is accepted regardless of which one
    # happened to be selected initially
    assert new_slot.db_id != slot.db_id
    assert {slot.db_id, new_slot.db_id} == {q_primary, q_secondary}
    assert new_slot.category == A                # target category preserved
    assert A in new_slot.categories               # matched via list membership
    if new_slot.db_id == q_secondary:
        assert new_slot.primary_category == B     # the row's own primary, unchanged


def test_db_replacement_excludes_every_current_db_id_and_retains_on_exhaustion(jobs_app, jobs_root):
    _wipe_seeded(jobs_app)
    only = _mk(jobs_app, [A])
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {A: {"total": 1, "database": 1, "llm": 0}}, "cost_ceiling_usd": "5.00"}
        )
    slot = job.slots[0]
    assert slot.db_id == only
    with jobs_app.app_context():
        with pytest.raises(service.JobConflict):
            service.replace_from_db(job.job_id, slot.instance_id)
    still = store.load(job.job_id).slot_by_instance(slot.instance_id)
    assert still.db_id == only  # retained unchanged
    assert still.question == slot.question
