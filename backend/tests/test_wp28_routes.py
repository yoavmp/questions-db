"""WP28 -- HTTP-level coverage for PATCH /exam-jobs/<job_id>/questions/<iid>.

Offline, temp DB/job store (see conftest); the fake provider never touches a
socket, and the two other permission-boundary cases (missing job/slot,
running job) are already covered at the service layer in
``test_wp28_warning_edit_and_repair_hardening.py`` -- this file only proves
the route itself is wired correctly end to end.
"""

from __future__ import annotations

import socket

import pytest

from tests._wp18_fakes import Dispatch, dispatch_factory

CAT = "היסטולוגיה"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted during a WP28 route test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom)


def _create_llm_job(jobs_client, jobs_app):
    jobs_app.config["EXAM_JOB_SYNC"] = True
    jobs_app.config["EXAM_JOB_PROVIDER_FACTORY"] = dispatch_factory(Dispatch())
    resp = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
        "cost_ceiling_usd": "5.00",
    })
    assert resp.status_code == 202, resp.get_json()
    job_id = resp.get_json()["job_id"]
    resp2 = jobs_client.post(f"/api/exam-jobs/{job_id}/continue-llm")
    assert resp2.status_code == 202, resp2.get_json()
    return jobs_client.get(f"/api/exam-jobs/{job_id}").get_json()


_PAYLOAD = {
    "question": "שאלה מתוקנת דרך ה-API?",
    "answer1": "א חדשה", "answer2": "ב חדשה", "answer3": "ג חדשה", "answer4": "ד חדשה",
    "correct_answer": 3,
}


def test_patch_edits_the_llm_question_and_returns_the_full_view(jobs_client, jobs_app, jobs_root):
    body = _create_llm_job(jobs_client, jobs_app)
    q = next(q for q in body["questions"] if q["origin"] == "llm")
    resp = jobs_client.patch(
        f"/api/exam-jobs/{body['job_id']}/questions/{q['instance_id']}", json=_PAYLOAD,
    )
    assert resp.status_code == 200, resp.get_json()
    updated = resp.get_json()
    edited_q = next(qq for qq in updated["questions"] if qq["instance_id"] == q["instance_id"])
    assert edited_q["question"] == _PAYLOAD["question"]
    assert edited_q["correct_answer"] == 3
    assert edited_q["generation_meta"]["manually_edited"] is True


def test_patch_on_db_origin_question_is_409(jobs_client, jobs_root):
    resp = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 1, "database": 1, "llm": 0}},
        "cost_ceiling_usd": "5.00",
    })
    assert resp.status_code == 202
    body = jobs_client.get(f"/api/exam-jobs/{resp.get_json()['job_id']}").get_json()
    q = body["questions"][0]
    assert q["origin"] == "database"
    resp2 = jobs_client.patch(
        f"/api/exam-jobs/{body['job_id']}/questions/{q['instance_id']}", json=_PAYLOAD,
    )
    assert resp2.status_code == 409


def test_patch_with_malformed_payload_is_400(jobs_client, jobs_app, jobs_root):
    body = _create_llm_job(jobs_client, jobs_app)
    q = next(q for q in body["questions"] if q["origin"] == "llm")
    bad = {**_PAYLOAD, "correct_answer": 9}
    resp = jobs_client.patch(
        f"/api/exam-jobs/{body['job_id']}/questions/{q['instance_id']}", json=bad,
    )
    assert resp.status_code == 400


def test_patch_on_unknown_job_is_404(jobs_client, jobs_root):
    resp = jobs_client.patch(
        "/api/exam-jobs/00000000-0000-0000-0000-000000000000/questions/x", json=_PAYLOAD,
    )
    assert resp.status_code == 404
