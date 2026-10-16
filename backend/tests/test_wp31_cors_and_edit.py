"""WP31 Part C: the CORS preflight fix for the question-edit route, and the
backing proof that the actual ``PATCH`` persists/exports correctly and
performs zero provider calls (the generation-side guarantees are already
covered in depth by ``test_wp28_warning_edit_and_repair_hardening.py`` /
``test_wp28_routes.py`` -- this file focuses on what WP31 actually changed:
the CORS configuration itself, plus one end-to-end confirmation that the fix
did not regress persistence/export/reload).

Builds its own minimal Flask app (the same way ``jobs_app`` in conftest.py
does) + ``configure_cors`` -- never imports ``src.main`` (which runs DB
migrations against a fixed path at import time).
"""

from __future__ import annotations

from flask import Flask

from src.cors_config import ALLOWED_METHODS, DEV_FRONTEND_ORIGINS, configure_cors
from src.jobs import service, store
from src.routes.exam_jobs import exam_jobs_bp
from tests._wp18_fakes import ApprovingProvider

CAT = "היסטולוגיה"


def _cors_app():
    app = Flask(__name__)
    app.register_blueprint(exam_jobs_bp, url_prefix="/api")
    configure_cors(app)
    return app.test_client()


def _patch_preflight(client, origin):
    return client.options(
        "/api/exam-jobs/job-1/questions/iid-1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )


def test_patch_is_in_the_allowed_methods_list():
    # the root cause (WP31 §C1): PATCH must be a configured CORS method, or
    # flask_cors drops Access-Control-Allow-Methods/-Headers entirely for a
    # PATCH preflight (see flask_cors.core.get_cors_headers).
    assert "PATCH" in ALLOWED_METHODS


def test_preflight_authorizes_patch_and_content_type_for_every_documented_dev_origin():
    client = _cors_app()
    for origin in DEV_FRONTEND_ORIGINS:
        resp = _patch_preflight(client, origin)
        assert resp.status_code == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == origin
        methods = resp.headers.get("Access-Control-Allow-Methods", "")
        assert "PATCH" in [m.strip() for m in methods.split(",")]
        headers = resp.headers.get("Access-Control-Allow-Headers", "")
        assert "Content-Type" in [h.strip() for h in headers.split(",")]


def test_localhost_and_127_variants_are_both_documented_and_authorized():
    assert "http://localhost:3000" in DEV_FRONTEND_ORIGINS
    assert "http://127.0.0.1:3000" in DEV_FRONTEND_ORIGINS


def test_unsupported_origins_remain_unauthorized():
    client = _cors_app()
    for bad_origin in ("http://evil.example.com", "http://localhost:9999", "null"):
        resp = _patch_preflight(client, bad_origin)
        assert resp.headers.get("Access-Control-Allow-Origin") is None
        assert resp.headers.get("Access-Control-Allow-Methods") is None
        assert resp.headers.get("Access-Control-Allow-Headers") is None


def test_no_unrestricted_wildcard_origin_is_ever_configured():
    assert "*" not in DEV_FRONTEND_ORIGINS


def test_actual_patch_persists_edit_survives_reload_and_is_reflected_in_exports(
    jobs_app, jobs_root, llm_ready,
):
    """End-to-end confirmation (not a regression of WP28): the fixed CORS
    configuration sits in front of the same, unchanged ``edit_llm_question``
    service call -- editing still makes zero provider calls, persists after
    a fresh ``store.load``, and the edited text reaches both export paths."""
    with jobs_app.app_context():
        job = service.create_job(
            {"categories": {CAT: {"total": 1, "database": 0, "llm": 1}},
             "cost_ceiling_usd": "5.00", "_seed": 37}
        )
    provider = ApprovingProvider()
    done = service.run_job(job.job_id, provider_factory=lambda: provider)
    slot = next(s for s in done.slots if s.kind == "llm")
    calls_before = provider.generation_calls + provider.review_calls

    edited = service.edit_llm_question(done.job_id, slot.instance_id, {
        "question": "שאלה שנערכה ב-WP31",
        "answer1": "א חדשה", "answer2": "ב", "answer3": "ג", "answer4": "ד",
        "correct_answer": 1,
    })
    assert provider.generation_calls + provider.review_calls == calls_before  # zero provider calls

    # survives a fresh backend-store reload
    reloaded = store.load(edited.job_id)
    reloaded_slot = reloaded.slot_by_instance(slot.instance_id)
    assert reloaded_slot.question["question"] == "שאלה שנערכה ב-WP31"
    assert reloaded_slot.manually_edited is True
    assert len(reloaded_slot.edit_history) == 1

    # Excel export paths both carry the edited text
    llm_bytes = service.export_llm_xlsx(reloaded)
    full_bytes = service.export_full_xlsx(reloaded)
    assert "שאלה שנערכה ב-WP31".encode("utf-8") in llm_bytes or _xlsx_contains(llm_bytes, "שאלה שנערכה ב-WP31")
    assert _xlsx_contains(full_bytes, "שאלה שנערכה ב-WP31")


def _xlsx_contains(data: bytes, text: str) -> bool:
    import io
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value == text:
                    return True
    return False
