"""WP26 §1/§2/§4/§8 -- HTTP-level coverage for the new jobs-list, branch, and
exclusion-preview endpoints. Offline, temp DB/job store (see conftest).
"""

from __future__ import annotations

import socket
from io import BytesIO

import pytest
from openpyxl import Workbook

CAT = "היסטולוגיה"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted during a WP26 route test")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom)


def _create(jobs_client, jobs_app=None, **overrides):
    if jobs_app is not None:
        jobs_app.config["EXAM_JOB_SYNC"] = True  # DB-only: finishes synchronously
    payload = {
        "categories": {CAT: {"total": 2, "database": 2, "llm": 0}},
        "cost_ceiling_usd": "5.00",
        "_seed": 1,
    }
    payload.update(overrides)
    resp = jobs_client.post("/api/exam-jobs", json=payload)
    assert resp.status_code == 202, resp.get_json()
    return resp.get_json()


def test_create_job_route_returns_display_name_and_slug(jobs_client, jobs_root):
    body = _create(jobs_client, identity={
        "mode": "structured", "course": "מבנה המוח", "year": "2026",
        "exam_type": "מבחן מסכם", "sitting": "א",
    })
    assert body["display_name"] == "מבנה המוח 2026 מבחן מסכם מועד א"
    assert body["slug"] == "מבנה_המוח_2026_מבחן_מסכם_מועד_א"


def test_get_job_route_includes_naming_and_lineage_fields(jobs_client, jobs_root):
    body = _create(jobs_client)
    resp = jobs_client.get(f"/api/exam-jobs/{body['job_id']}")
    assert resp.status_code == 200
    view = resp.get_json()
    for key in ("display_name", "slug", "parent_job_id", "root_job_id",
                "excluded_db_ids_count", "branchable", "identity"):
        assert key in view


def test_list_jobs_route_newest_first_safe_fields(jobs_client, jobs_root):
    b1 = _create(jobs_client, _seed=1)
    b2 = _create(jobs_client, _seed=2)
    resp = jobs_client.get("/api/exam-jobs")
    assert resp.status_code == 200
    jobs = resp.get_json()["jobs"]
    ids = [j["job_id"] for j in jobs]
    assert b1["job_id"] in ids and b2["job_id"] in ids
    assert ids.index(b2["job_id"]) < ids.index(b1["job_id"]) or \
        jobs[ids.index(b2["job_id"])]["created_utc"] >= jobs[ids.index(b1["job_id"])]["created_utc"]
    for j in jobs:
        assert "questions" not in j and "cost_ledger" not in j


def test_branch_route_creates_child_and_leaves_parent_untouched(jobs_client, jobs_app, jobs_root):
    body = _create(jobs_client, jobs_app, identity={"mode": "custom", "custom_name": "מקור"})
    job_id = body["job_id"]
    before = jobs_client.get(f"/api/exam-jobs/{job_id}").get_json()

    resp = jobs_client.post(
        f"/api/exam-jobs/{job_id}/branch",
        json={"identity": {"mode": "custom", "custom_name": "גרסה חדשה"}},
    )
    assert resp.status_code == 201, resp.get_json()
    child = resp.get_json()
    assert child["job_id"] != job_id
    assert child["parent_job_id"] == job_id
    assert child["display_name"] == "גרסה חדשה"

    after = jobs_client.get(f"/api/exam-jobs/{job_id}").get_json()
    assert after["questions"] == before["questions"]
    assert after["status"] == before["status"]


def test_branch_route_404_for_unknown_job(jobs_client, jobs_root):
    resp = jobs_client.post(
        "/api/exam-jobs/11111111-1111-1111-1111-111111111111/branch", json={},
    )
    assert resp.status_code == 404


def test_create_job_rejects_malformed_excluded_ids(jobs_client, jobs_root):
    resp = jobs_client.post("/api/exam-jobs", json={
        "categories": {CAT: {"total": 1, "database": 1, "llm": 0}},
        "excluded_db_ids": ["not-an-int"],
    })
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# exclusion preview endpoint
# --------------------------------------------------------------------------- #
def _xlsx_bytes(rows, headers=("מזהה_שאלה", "שאלה", "נושא")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_exclusion_preview_route_resolves_by_id(jobs_client, jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        row = Question.query.filter(Question.category == CAT).first()
        row_id = row.id

    data = {"file": (BytesIO(_xlsx_bytes([(row_id, "", "")])), "excl.xlsx")}
    resp = jobs_client.post(
        "/api/exam-jobs/exclusions/preview", data=data, content_type="multipart/form-data",
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["resolved_db_ids"] == [row_id]
    assert body["counts"]["resolved"] == 1


def test_exclusion_preview_route_rejects_non_xlsx(jobs_client, jobs_root):
    data = {"file": (BytesIO(b"hello"), "excl.csv")}
    resp = jobs_client.post(
        "/api/exam-jobs/exclusions/preview", data=data, content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_exclusion_preview_route_requires_a_file(jobs_client, jobs_root):
    resp = jobs_client.post(
        "/api/exam-jobs/exclusions/preview", data={}, content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_create_job_with_preview_ids_then_revalidated_at_creation(jobs_client, jobs_app, jobs_root):
    with jobs_app.app_context():
        from src.models.question import Question

        rows = Question.query.filter(Question.category == CAT).all()
        row_id = rows[0].id

    preview_resp = jobs_client.post(
        "/api/exam-jobs/exclusions/preview",
        data={"file": (BytesIO(_xlsx_bytes([(row_id, "", "")])), "excl.xlsx")},
        content_type="multipart/form-data",
    )
    excluded_ids = preview_resp.get_json()["resolved_db_ids"]

    body = _create(jobs_client, excluded_db_ids=excluded_ids,
                    categories={CAT: {"total": 1, "database": 1, "llm": 0}})
    result = jobs_client.get(f"/api/exam-jobs/{body['job_id']}").get_json()
    assert result["excluded_db_ids_count"] == 1
    selected_db_ids = {q["id"] for q in result["questions"] if q["origin"] == "database"}
    assert row_id not in selected_db_ids
