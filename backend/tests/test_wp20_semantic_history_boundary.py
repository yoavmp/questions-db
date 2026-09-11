"""WP20 -- semantic-history boundary.

``category_history`` is internal semantic-uniqueness state. WP20 removes it from
the ordinary user-facing exam screen (see ``frontend/src/components/
ExamGenerationSection.jsx`` -- no "displaced questions" card) while requiring it
to stay:

* in backend persistence (it round-trips through the job store), and
* in the previous-question context handed to later LLM generation.

It may still appear in backend diagnostic data (``result_view``); that is not a
UI contract. Offline: temp DB, no provider calls -- the displaced LLM question is
produced by a DB replacement.
"""

from __future__ import annotations

from tests._wp18_fakes import Dispatch, dispatch_factory

from src.jobs import service, store

CAT = "היסטולוגיה"


def _mixed(jobs_app):
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 4, "database": 2, "llm": 2}},
             "cost_ceiling_usd": "5.00", "_seed": 11}
        )
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    assert done.status == "completed"
    return done


def test_displaced_llm_history_persists_and_feeds_llm_context(jobs_app, jobs_root, llm_ready):
    done = _mixed(jobs_app)
    llm_s = next(x for x in done.slots if x.kind == "llm" and x.status == "accepted")
    displaced = llm_s.question["question"]

    with jobs_app.app_context():
        service.replace_from_db(done.job_id, llm_s.instance_id)  # LLM -> DB: displaced LLM -> history

    # 1. persisted -- survives a full store round-trip
    reloaded = store.load(done.job_id)
    hist = reloaded.category_history.get(CAT, [])
    assert any(h["question"] == displaced for h in hist)

    # 2. LLM context -- a remaining LLM slot in the category sees it as a previous question
    other_llm = next(x for x in reloaded.slots
                     if x.kind == "llm" and x.instance_id != llm_s.instance_id)
    prev_texts = [p["question"] for p in service._previous_for_slot(reloaded, other_llm)]
    assert displaced in prev_texts

    # 3. still present as backend diagnostic data (not a UI contract)
    view_hist = service.result_view(reloaded)["category_history"]
    assert displaced in [h["question"] for hs in view_hist.values() for h in hs]
