"""Versioned exam-generation job API (WP18 §3).

Routes (all under ``/api``)::

    POST   /exam-jobs                                  -> 202 {job_id, url} (DB selection only -- WP27)
    GET    /exam-jobs/<job_id>                          -> progress / partial / final (+ attempt_telemetry)
    POST   /exam-jobs/<job_id>/continue-llm             -> WP27: claim + run the planned LLM batch
    POST   /exam-jobs/<job_id>/slots/<slot_id>/retry    -> retry one failed/interrupted slot
    PUT    /exam-jobs/<job_id>/cost-ceiling             -> raise/lower the cap (>= accumulated)
    POST   /exam-jobs/<job_id>/questions/<iid>/replace-db   -> swap in a DB question (any accepted slot)
    POST   /exam-jobs/<job_id>/questions/<iid>/replace-llm  -> regenerate a question (any accepted slot)
    GET    /exam-jobs/<job_id>/export.xlsx              -> accepted origin=llm questions only
    GET    /exam-jobs/<job_id>/export-full.xlsx         -> every current question, legacy schema (WP21)
    GET    /exam-jobs/readiness                         -> LLM readiness report

As of WP19 ``replace-db`` takes the same process/file run lock as ``replace-llm``
and ``retry`` (``JobBusy`` -> 409), so a double click or concurrent request
cannot cause a lost update or a duplicate DB selection. The legacy synchronous
``/api/test/*`` endpoints are untouched (WP19 switches the frontend).

WP27: ``POST /exam-jobs`` no longer starts LLM generation automatically -- it
only selects DB questions and persists the job (``db_review``, or
``completed`` immediately if no LLM work was ever planned). The new
``POST /exam-jobs/<job_id>/continue-llm`` is the one explicit operation that
claims and runs the originally-planned LLM batch; it follows the exact same
``EXAM_JOB_SYNC`` / background-thread duality as job creation.
"""

from __future__ import annotations

import threading

from flask import Blueprint, current_app, jsonify, request, url_for

from src.integration.readiness import readiness_report
from src.jobs import service, store

exam_jobs_bp = Blueprint("exam_jobs", __name__)


def _provider_factory():
    return current_app.config.get("EXAM_JOB_PROVIDER_FACTORY")


def _err(msg, code):
    return jsonify({"error": msg}), code


@exam_jobs_bp.route("/exam-jobs/readiness", methods=["GET"])
def readiness():
    return jsonify(readiness_report())


@exam_jobs_bp.route("/exam-jobs", methods=["GET"])
def list_jobs():
    """WP26 §1: every persisted job, newest-first, safe list-view fields
    only (no question bodies/prompts/audits/course-source content)."""
    return jsonify({"jobs": service.list_jobs()})


@exam_jobs_bp.route("/exam-jobs", methods=["POST"])
def create_job():
    payload = request.get_json(silent=True)
    if payload is None:
        return _err("request body must be JSON", 400)
    try:
        job = service.create_job(payload, seed=payload.get("_seed"))
    except service.JobError as exc:
        return _err(str(exc), 400)

    # WP27 §2: DB selection only -- no automatic LLM generation here anymore.
    # `job.status` is already the job's real resting state (``queued`` ==
    # ``db_review`` when LLM work is planned, ``completed`` immediately when
    # it is not -- see ``service.create_job``).
    body = {
        "job_id": job.job_id,
        "status": job.status,
        "workflow_phase": service.workflow_phase(job),
        "url": url_for("exam_jobs.get_job", job_id=job.job_id, _external=False),
        "display_name": job.identity["display_name"] if job.identity else None,
        "slug": job.identity["slug"] if job.identity else None,
    }
    return jsonify(body), 202


@exam_jobs_bp.route("/exam-jobs/<job_id>/continue-llm", methods=["POST"])
def continue_llm(job_id):
    """WP27 §3: claim and run the originally-planned LLM batch for a job
    currently awaiting DB-review approval (or resume one left ``interrupted``
    by a restart mid-batch). Follows the exact same ``EXAM_JOB_SYNC`` /
    background-thread duality as ``POST /exam-jobs`` -- the response body is
    always the same small shape; the caller re-fetches ``GET /exam-jobs/<id>``
    for the full (possibly still-in-progress) result, exactly like job
    creation already does.
    """
    pf = _provider_factory()
    if current_app.config.get("EXAM_JOB_SYNC"):
        try:
            job = service.continue_llm_generation(job_id, provider_factory=pf)
        except service.JobError as exc:
            return _err(str(exc), 404 if "not found" in str(exc) else 400)
        except service.JobBusy as exc:
            return _err(str(exc), 409)
        except service.JobConflict as exc:
            return _err(str(exc), 409)
        body = {
            "job_id": job.job_id,
            "status": job.status,
            "workflow_phase": service.workflow_phase(job),
            "url": url_for("exam_jobs.get_job", job_id=job.job_id, _external=False),
        }
        return jsonify(body), 202

    t = threading.Thread(
        target=_continue_bg, args=(job_id, pf), name=f"exam-continue-{job_id[:8]}", daemon=True,
    )
    t.start()
    body = {
        "job_id": job_id,
        "status": "running",
        "workflow_phase": "llm_generation",
        "url": url_for("exam_jobs.get_job", job_id=job_id, _external=False),
    }
    return jsonify(body), 202


def _continue_bg(job_id, provider_factory):
    try:
        service.continue_llm_generation(job_id, provider_factory=provider_factory)
    except (service.JobBusy, service.JobError, service.JobConflict):
        pass  # a benign, expected outcome of a race/readiness gate -- not a bug
    except Exception:  # noqa: BLE001 - never crash the daemon thread
        import logging
        logging.getLogger("exam_jobs").exception("continue-llm background job %s failed", job_id)


@exam_jobs_bp.route("/exam-jobs/<job_id>/branch", methods=["POST"])
def branch_job(job_id):
    """WP26 §4: create a new editable job from a completed saved exam. The
    parent is never mutated on success or failure."""
    payload = request.get_json(silent=True) or {}
    try:
        child = service.branch_job(job_id, payload.get("identity"))
    except service.JobError as exc:
        return _err(str(exc), 404 if "not found" in str(exc) else 400)
    except service.JobBusy as exc:
        return _err(str(exc), 409)
    except service.JobConflict as exc:
        return _err(str(exc), 409)
    return jsonify(service.result_view(child)), 201


def _run_bg(job_id, provider_factory):
    try:
        service.run_job(job_id, provider_factory=provider_factory)
    except service.JobBusy:
        pass  # another worker already has it
    except Exception:  # noqa: BLE001 - never crash the daemon thread
        import logging
        logging.getLogger("exam_jobs").exception("background job %s failed", job_id)


@exam_jobs_bp.route("/exam-jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    try:
        job = store.load(job_id)
    except ValueError:
        return _err("invalid job id", 400)
    if job is None:
        return _err("job not found", 404)
    return jsonify(service.result_view(job))


@exam_jobs_bp.route("/exam-jobs/<job_id>/slots/<slot_id>/retry", methods=["POST"])
def retry_slot(job_id, slot_id):
    try:
        job = service.retry_slot(job_id, slot_id, provider_factory=_provider_factory())
    except service.JobError as exc:
        return _err(str(exc), 404 if "not found" in str(exc) else 400)
    except service.JobBusy as exc:
        return _err(str(exc), 409)
    except service.JobConflict as exc:
        return _err(str(exc), 409)
    return jsonify(service.result_view(job))


@exam_jobs_bp.route("/exam-jobs/<job_id>/cost-ceiling", methods=["PUT"])
def put_cost_ceiling(job_id):
    payload = request.get_json(silent=True) or {}
    if "cost_ceiling_usd" not in payload:
        return _err("cost_ceiling_usd is required", 400)
    try:
        job = service.update_cost_ceiling(job_id, payload["cost_ceiling_usd"])
    except service.JobError as exc:
        return _err(str(exc), 404 if "not found" in str(exc) else 400)
    except service.JobConflict as exc:
        return _err(str(exc), 409)
    return jsonify(service.result_view(job))


@exam_jobs_bp.route("/exam-jobs/<job_id>/questions/<instance_id>/replace-db", methods=["POST"])
def replace_db(job_id, instance_id):
    payload = request.get_json(silent=True) or {}
    extra = tuple(payload.get("exclude_ids", []) or [])
    try:
        job = service.replace_from_db(job_id, instance_id, extra_exclude_ids=extra)
    except service.JobError as exc:
        return _err(str(exc), 404 if "not found" in str(exc) else 400)
    except service.JobBusy as exc:
        return _err(str(exc), 409)
    except service.JobConflict as exc:
        return _err(str(exc), 409)
    return jsonify(service.result_view(job))


@exam_jobs_bp.route("/exam-jobs/<job_id>/questions/<instance_id>/replace-llm", methods=["POST"])
def replace_llm(job_id, instance_id):
    try:
        job = service.replace_via_llm(job_id, instance_id, provider_factory=_provider_factory())
    except service.JobError as exc:
        return _err(str(exc), 404 if "not found" in str(exc) else 400)
    except service.JobBusy as exc:
        return _err(str(exc), 409)
    except service.JobConflict as exc:
        return _err(str(exc), 409)
    return jsonify(service.result_view(job))


@exam_jobs_bp.route("/exam-jobs/<job_id>/export.xlsx", methods=["GET"])
def export_xlsx(job_id):
    """LLM-only export (unchanged since WP18/19): accepted origin=llm questions,
    upload-compatible 7-column schema, for later manual database upload."""
    job = store.load(job_id)
    if job is None:
        return _err("job not found", 404)
    data = service.export_llm_xlsx(job)
    from flask import make_response

    resp = make_response(data)
    resp.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="generated_questions_{job_id[:8]}.xlsx"'
    )
    return resp


@exam_jobs_bp.route("/exam-jobs/<job_id>/export-full.xlsx", methods=["GET"])
def export_full_xlsx(job_id):
    """Full current-exam export (WP21): every current DB + LLM question,
    complete legacy 12-column schema (see service.FULL_EXPORT_HEADERS). A
    distinct route/label from ``export.xlsx`` on purpose -- one label never
    means two things (WP21 §5)."""
    job = store.load(job_id)
    if job is None:
        return _err("job not found", 404)
    data = service.export_full_xlsx(job)
    from flask import make_response

    resp = make_response(data)
    resp.headers["Content-Type"] = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="full_exam_{job_id[:8]}.xlsx"'
    )
    return resp
