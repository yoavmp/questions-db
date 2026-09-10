"""Exam-generation job service: validation, sequential worker, cost accounting,
replacements and export (WP18 §2-§5).

Design points enforced here:

* One worker at a time. ``_RUN_LOCK`` serialises every generating operation
  (initial run, slot retry, LLM replacement) across the process; a per-job
  ``job.lock`` file guards across processes. No parallel provider calls.
* Categories are processed in canonical (``CATEGORY_ORDER``) order. All A
  database questions for a category are selected before any of its B LLM
  questions are generated.
* ``Decimal`` money end to end. Every generator call's ``total_cost_usd`` is
  accumulated -- accepted, rejected, refusal, failed attempt, retry, LLM
  replacement. DB operations cost nothing.
* ``remaining = cap - accumulated`` is passed as the ceiling to every call; a
  slot whose start would breach the cap is marked ``cost_ceiling`` and no call
  is made.
* Generated questions never touch ``app.db``.
"""

from __future__ import annotations

import logging
import random
import threading
from decimal import Decimal
from typing import Any, Callable, Optional

from src.integration.category_map import resolve_generator_context
from src.integration.exam_question_dto import ExamQuestionDTO, GenerationMeta
from src.integration.generator_adapter import AdapterRequest, generate_category_question
from src.integration.owner_policy import MAX_ATTEMPTS_PER_LLM_SLOT
from src.integration.readiness import readiness_report
from src.integration.request_contract import RequestContractError, parse_category_request
from src.jobs import store
from src.jobs.model import CategoryPlan, Job, Slot, SEVEN, new_id, now_iso
from src.utils.category_order import CATEGORY_ORDER

log = logging.getLogger("exam_jobs")

#: process-wide: only one generating operation runs at any time
_RUN_LOCK = threading.Lock()

ProviderFactory = Callable[[], Any]  # returns a provider or None


class JobError(ValueError):
    """Bad job request (400)."""


class JobBusy(RuntimeError):
    """A generating operation is already in progress (409)."""


class JobConflict(RuntimeError):
    """The requested mutation is not valid for the job's current state (409)."""


# --------------------------------------------------------------------------- #
# DB selection (needs a Flask app context)
# --------------------------------------------------------------------------- #
def _db_availability(category: str) -> int:
    from src.models.user import db
    from src.models.question import Question

    return Question.query.filter(
        db.or_(
            Question.category == category,
            Question.categories_json.like(f'%"{category}"%'),
        )
    ).count()


def _select_db_questions(category: str, count: int, exclude_ids: set[int], rng: random.Random) -> list:
    """The existing random selector: any row whose primary OR secondary category
    matches, minus rows already in the exam / excluded, sampled uniformly."""
    from src.models.user import db
    from src.models.question import Question

    rows = Question.query.filter(
        db.or_(
            Question.category == category,
            Question.categories_json.like(f'%"{category}"%'),
        )
    ).all()
    pool = [q for q in rows if q.id not in exclude_ids]
    if len(pool) < count:
        raise JobError(
            f"category {category!r}: only {len(pool)} database question(s) available, {count} requested"
        )
    return rng.sample(pool, count)


def _row_seven(row: Any, number: int) -> dict:
    return {
        "number": number,
        "question": row.question,
        "answer1": row.answer1,
        "answer2": row.answer2,
        "answer3": row.answer3,
        "answer4": row.answer4,
        "correct_answer": row.correct_answer_id,
    }


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
def create_job(payload: dict, *, seed: Optional[int] = None) -> Job:
    """Validate the request, select every DB question, build the job (``queued``).

    Must run inside a Flask app context (touches the question DB, read-only).
    """
    if not isinstance(payload, dict):
        raise JobError("request body must be an object")
    cats = payload.get("categories")
    if not isinstance(cats, dict) or not cats:
        raise JobError("`categories` must be a non-empty object")

    raw_cap = payload.get("cost_ceiling_usd", "5.00")
    try:
        cap = Decimal(str(raw_cap))
    except Exception as exc:  # noqa: BLE001
        raise JobError(f"cost_ceiling_usd is not a valid decimal: {raw_cap!r}") from exc
    if cap <= 0:
        raise JobError("cost_ceiling_usd must be positive")

    # validate every per-category contract and resolve the canonical context
    parsed = []
    for name, spec in cats.items():
        try:
            req = parse_category_request(name, spec)
        except RequestContractError as exc:
            raise JobError(str(exc)) from exc
        try:
            context_id = resolve_generator_context(name)
        except KeyError as exc:
            raise JobError(f"unknown category {name!r}") from exc
        if name not in CATEGORY_ORDER:
            raise JobError(f"category {name!r} is not in the canonical order")
        parsed.append((req, context_id))

    any_llm = any(req.llm > 0 for req, _ in parsed)
    if any_llm:
        report = readiness_report()
        if not report["ready_for_llm"]:
            raise JobError(
                "LLM generation is not ready: " + "; ".join(report["blocking_reasons"])
            )

    # DB availability check BEFORE creating the job
    for req, _ in parsed:
        avail = _db_availability(req.category)
        if req.database > avail:
            raise JobError(
                f"category {req.category!r}: database={req.database} exceeds availability={avail}"
            )

    job = Job(job_id=new_id(), cost_ceiling_usd=str(cap), request={
        "categories": {req.category: {"total": req.total, "database": req.database, "llm": req.llm}
                       for req, _ in parsed},
        "cost_ceiling_usd": str(cap),
    })

    rng = random.Random(seed)
    exclude_ids: set[int] = set()

    # canonical order + running global number base
    parsed.sort(key=lambda pc: CATEGORY_ORDER.index(pc[0].category))
    number = 0
    for req, context_id in parsed:
        plan = CategoryPlan(
            category=req.category, context_id=context_id,
            order_index=CATEGORY_ORDER.index(req.category),
            total=req.total, database=req.database, llm=req.llm,
            number_base=number,
        )
        # A database questions first
        chosen = _select_db_questions(req.category, req.database, exclude_ids, rng) if req.database else []
        for i, row in enumerate(chosen):
            number += 1
            exclude_ids.add(row.id)
            plan.db_selected_ids.append(row.id)
            job.slots.append(Slot(
                slot_id=new_id(), instance_id=new_id(), category=req.category,
                context_id=context_id, kind="database", order_in_category=i, number=number,
                status="accepted", question=_row_seven(row, number), db_id=row.id,
            ))
        # B LLM slots (queued; generated by run_job)
        for i in range(req.llm):
            number += 1
            job.slots.append(Slot(
                slot_id=new_id(), instance_id=new_id(), category=req.category,
                context_id=context_id, kind="llm", order_in_category=i, number=number,
                status="queued",
            ))
        job.categories.append(plan)

    job.category_history = {req.category: [] for req, _ in parsed}
    store.save(job)
    return job


# --------------------------------------------------------------------------- #
# cost accounting
# --------------------------------------------------------------------------- #
def _fold_basis(existing: str, new: str) -> str:
    if new in ("none", None):
        return existing
    if existing in ("none", None):
        return new
    if existing == new:
        return existing
    return "mixed"


def _record_cost(job: Job, *, kind: str, slot: Slot, result: Any) -> None:
    """Add one generator call's cost to the job ledger + accumulator."""
    cost = Decimal(str(getattr(result, "cost_usd", "0") or "0"))
    job.accumulated_cost_usd = str(Decimal(job.accumulated_cost_usd) + cost)
    job.cost_basis = _fold_basis(job.cost_basis, getattr(result, "total_cost_basis", "none"))
    if getattr(result, "pricing_verification", None):
        job.pricing_verification = dict(result.pricing_verification)
    for w in getattr(result, "warnings", []) or []:
        if w not in job.warnings:
            job.warnings.append(dict(w))
    job.cost_ledger.append({
        "seq": len(job.cost_ledger) + 1,
        "kind": kind,                       # initial | retry | replace_llm
        "slot_id": slot.slot_id,
        "instance_id": slot.instance_id,
        "category": slot.category,
        "number": slot.number,
        "status": result.status,
        "total_cost_usd": str(cost),
        "total_cost_basis": getattr(result, "total_cost_basis", "none"),
        "itemized_cost": list(getattr(result, "itemized_cost", []) or []),
        "attempts": getattr(result, "attempts", 0),
        "retries": getattr(result, "retries", 0),
        "warnings": [w.get("code") for w in getattr(result, "warnings", []) or []],
        "at": now_iso(),
    })


# --------------------------------------------------------------------------- #
# previous-question context for one LLM slot
# --------------------------------------------------------------------------- #
def _previous_for_slot(job: Job, slot: Slot, *, exclude_instance: Optional[str] = None) -> list[dict]:
    """That category's selected DB questions, then prior accepted LLM questions,
    then retained/discarded history -- order preserved, repeated ``number``
    values kept, nothing sorted or de-duplicated."""
    prev: list[dict] = []
    block = [s for s in job.slots if s.category == slot.category and s.instance_id != slot.instance_id]
    if exclude_instance:
        block = [s for s in block if s.instance_id != exclude_instance]
    # current-question prefix: DB questions first, then accepted LLM questions,
    # each group in stable exam order (by preserved global ``number``). A slot's
    # ``kind`` reflects its *current* origin, so a cross-source replacement moves
    # it between these groups automatically.
    for s in sorted(block, key=lambda s: s.number):
        if s.kind == "database" and s.question:
            prev.append({f: s.question[f] for f in SEVEN})
    for s in sorted(block, key=lambda s: s.number):
        if s.kind == "llm" and s.status == "accepted" and s.question:
            prev.append({f: s.question[f] for f in SEVEN})
    for h in job.category_history.get(slot.category, []):
        prev.append({f: h[f] for f in SEVEN})
    return prev


# --------------------------------------------------------------------------- #
# one LLM generation call
# --------------------------------------------------------------------------- #
def _generate_one(job: Job, slot: Slot, *, kind: str, provider: Any,
                  previous: list[dict]) -> Any:
    remaining = job.remaining_budget()
    if remaining <= 0:
        slot.status = "cost_ceiling"
        slot.safe_error = (
            f"accumulated ${job.accumulated_cost_usd} already meets the "
            f"${job.cost_ceiling_usd} cap; no call made"
        )
        return None

    slot.status = "running"
    slot.attempts += 1
    store.save(job)

    audit_dir = str(store.slot_audit_dir(job.job_id, slot.slot_id))
    result = generate_category_question(
        AdapterRequest(
            canonical_category=slot.category,
            question_number=slot.number,
            previous_questions=previous,
            attempt_budget=MAX_ATTEMPTS_PER_LLM_SLOT,
            cost_ceiling_usd=remaining,
            actual_spend_usd=Decimal("0"),          # remaining already nets it out
            audit_dir=audit_dir,
        ),
        provider=provider,
    )
    _record_cost(job, kind=kind, slot=slot, result=result)
    slot.audit_ref = f"slots/{slot.slot_id}"
    slot.attempts = max(slot.attempts, getattr(result, "attempts", slot.attempts))

    if result.status == "accepted" and result.question:
        q = {f: result.question[f] for f in SEVEN}
        q["number"] = slot.number
        slot.question = q
        slot.was_repaired = bool(getattr(result, "was_repaired", False))
        slot.status = "accepted"
        slot.safe_error = None
    elif result.status == "cost_ceiling":
        slot.status = "cost_ceiling"
        slot.safe_error = result.failure_reason
    else:
        slot.status = "failed"
        slot.safe_error = result.failure_reason
    return result


# --------------------------------------------------------------------------- #
# the worker
# --------------------------------------------------------------------------- #
def run_job(job_id: str, *, provider_factory: Optional[ProviderFactory] = None) -> Job:
    """Process every queued LLM slot, categories in canonical order, one at a
    time. Idempotent-ish: only ``queued`` slots are generated."""
    if not _RUN_LOCK.acquire(blocking=False):
        raise JobBusy("another exam-generation operation is already running")
    got_file_lock = False
    try:
        job = store.load(job_id)
        if job is None:
            raise JobError(f"job {job_id} not found")
        if job.status not in ("queued", "interrupted"):
            raise JobConflict(f"job is {job.status!r}; only queued/interrupted jobs can be run")
        got_file_lock = store.try_acquire_lock(job_id)
        if not got_file_lock:
            raise JobBusy("job is locked by another process")

        job.status = "running"
        store.save(job)

        provider = provider_factory() if provider_factory else None
        stopped_by_ceiling = False

        for plan in sorted(job.categories, key=lambda p: p.order_index):
            if stopped_by_ceiling:
                break
            llm_slots = [s for s in job.slots
                         if s.category == plan.category and s.kind == "llm" and s.status == "queued"]
            for slot in sorted(llm_slots, key=lambda s: s.number):
                # readiness immediately before the (billable) call
                if provider is None:
                    report = readiness_report()
                    if not report["ready_for_llm"]:
                        slot.status = "failed"
                        slot.safe_error = "LLM not ready: " + "; ".join(report["blocking_reasons"])
                        store.save(job)
                        continue
                result = _generate_one(
                    job, slot, kind="initial", provider=provider,
                    previous=_previous_for_slot(job, slot),
                )
                store.save(job)
                if result is not None and result.status == "cost_ceiling":
                    stopped_by_ceiling = True
                    break
                if slot.status == "cost_ceiling":
                    stopped_by_ceiling = True
                    break

        _finalise(job, stopped_by_ceiling=stopped_by_ceiling)
        store.save(job)
        _print_terminal_summary(job, header="EXAM JOB COMPLETE")
        return job
    finally:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()


def _finalise(job: Job, *, stopped_by_ceiling: bool) -> None:
    llm_slots = [s for s in job.slots if s.kind == "llm"]
    accepted = [s for s in llm_slots if s.status == "accepted"]
    failed = [s for s in llm_slots if s.status in ("failed", "cost_ceiling")]
    pending = [s for s in llm_slots if s.status in ("queued", "running", "interrupted")]

    if stopped_by_ceiling or any(s.status == "cost_ceiling" for s in llm_slots):
        job.status = "cost_ceiling"
    elif pending:
        job.status = "partial"
    elif not llm_slots:
        job.status = "completed"
    elif failed and accepted:
        job.status = "partial"
    elif failed and not accepted:
        job.status = "failed"
    else:
        job.status = "completed"

    job.terminal_summary = _summary_dict(job)


def _summary_dict(job: Job) -> dict:
    llm_slots = [s for s in job.slots if s.kind == "llm"]
    return {
        "job_id": job.job_id,
        "status": job.status,
        "final_llm_cost_usd": job.accumulated_cost_usd,
        "cost_basis": job.cost_basis,
        "llm_accepted": sum(1 for s in llm_slots if s.status == "accepted"),
        "llm_failed": sum(1 for s in llm_slots if s.status in ("failed", "cost_ceiling")),
        "llm_requested": len(llm_slots),
        "retries": sum(s.retries for s in llm_slots),
        "pricing_verification": job.pricing_verification,
        "pricing_warnings": sorted({w.get("code") for w in job.warnings if w.get("code")}),
        "cost_ceiling_usd": job.cost_ceiling_usd,
        "generated_at": now_iso(),
    }


def _print_terminal_summary(job: Job, *, header: str) -> None:
    """One visible backend-terminal line. Never prints prompts, answers, raw
    responses or secrets -- only counts and costs."""
    s = job.terminal_summary or _summary_dict(job)
    line = (
        f"[{header}] job={s['job_id']} status={s['status']} "
        f"llm_cost=${s['final_llm_cost_usd']} basis={s['cost_basis']} "
        f"accepted={s['llm_accepted']}/{s['llm_requested']} failed={s['llm_failed']} "
        f"retries={s['retries']} "
        f"pricing_warnings={s['pricing_warnings'] or '-'}"
    )
    log.warning(line)
    print(line, flush=True)


# --------------------------------------------------------------------------- #
# manual: retry one slot
# --------------------------------------------------------------------------- #
def retry_slot(job_id: str, slot_id: str, *, provider_factory: Optional[ProviderFactory] = None) -> Job:
    if not _RUN_LOCK.acquire(blocking=False):
        raise JobBusy("another exam-generation operation is already running")
    got_file_lock = False
    try:
        job = store.load(job_id)
        if job is None:
            raise JobError(f"job {job_id} not found")
        slot = job.slot_by_id(slot_id)
        if slot is None:
            raise JobError(f"slot {slot_id} not found in job {job_id}")
        if slot.kind != "llm":
            raise JobConflict("only LLM slots can be retried")
        if slot.status not in ("failed", "interrupted", "cost_ceiling"):
            raise JobConflict(f"slot is {slot.status!r}; only failed/interrupted/cost_ceiling slots retry")
        got_file_lock = store.try_acquire_lock(job_id)
        if not got_file_lock:
            raise JobBusy("job is locked by another process")

        provider = provider_factory() if provider_factory else None
        slot.retries += 1
        slot.status = "queued"
        store.save(job)

        result = _generate_one(
            job, slot, kind="retry", provider=provider,
            previous=_previous_for_slot(job, slot),
        )
        _finalise(job, stopped_by_ceiling=(result is not None and result.status == "cost_ceiling"))
        store.save(job)
        _print_terminal_summary(job, header="EXAM JOB UPDATED (retry)")
        return job
    finally:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()


# --------------------------------------------------------------------------- #
# manual: replace one current question (cross-source, WP18R)
# --------------------------------------------------------------------------- #
#: slot fields that describe the *currently held* question / its origin. Snapshot
#: + restore these so a failed cross-source replacement leaves the slot (and its
#: Excel/DOCX projection) byte-identical to before -- no history / origin /
#: metadata mutation on failure.
_SLOT_STATE_FIELDS = (
    "kind", "status", "attempts", "retries", "safe_error",
    "question", "db_id", "audit_ref", "was_repaired",
)


def _snapshot_slot(slot: Slot) -> dict:
    snap = {k: getattr(slot, k) for k in _SLOT_STATE_FIELDS}
    if snap["question"] is not None:
        snap["question"] = dict(snap["question"])
    return snap


def _restore_slot(slot: Slot, snap: dict) -> None:
    for k, v in snap.items():
        setattr(slot, k, dict(v) if k == "question" and v is not None else v)


def _apply_db_origin(slot: Slot, row: Any) -> None:
    """Make ``slot`` a current DB question: ``kind=database``, integer ``db_id``,
    the row's seven fields, DB defaults, no LLM generation metadata."""
    slot.kind = "database"
    slot.db_id = row.id
    slot.question = _row_seven(row, slot.number)
    slot.status = "accepted"
    slot.attempts = 0
    slot.retries = 0
    slot.was_repaired = False
    slot.audit_ref = None
    slot.safe_error = None


def _apply_llm_origin(slot: Slot) -> None:
    """Make ``slot`` a current LLM question: ``kind=llm``, ``db_id=None``. The
    seven fields / generation metadata were already set by ``_generate_one`` on
    the accepted result."""
    slot.kind = "llm"
    slot.db_id = None


def _recompute_db_selected_ids(job: Job, category: str) -> None:
    plan = job.plan_for(category)
    if plan is not None:
        plan.db_selected_ids = [
            s.db_id for s in job.slots
            if s.category == category and s.kind == "database" and s.db_id is not None
        ]


def replace_from_db(job_id: str, instance_id: str, *, extra_exclude_ids: tuple = ()) -> Job:
    """DB replacement for **any** accepted slot -- DB->DB or LLM->DB (WP18R).

    Uses the existing random selector, excluding DB questions currently in the
    exam. Preserves the slot's ``instance_id``, category, order and public
    ``number``. Costs nothing. Needs an app context.

    Semantic history: a displaced **LLM** question is appended to that category's
    ``category_history`` *after* the swap succeeds; a displaced **DB** question
    is not (it may have been rejected for prior use / wording, not its concept).
    On failure the slot is left exactly as it was.
    """
    job = store.load(job_id)
    if job is None:
        raise JobError(f"job {job_id} not found")
    slot = job.slot_by_instance(instance_id)
    if slot is None:
        raise JobError(f"question {instance_id} not found in job {job_id}")
    if slot.status != "accepted" or not slot.question:
        raise JobConflict("only an accepted question can be replaced")

    was_llm = slot.kind == "llm"
    old_question = {f: slot.question[f] for f in SEVEN}

    # exclude DB rows currently in the exam. For DB->DB the current slot's own
    # db_id is in this set, so the swap always yields a *different* question; for
    # LLM->DB the current slot has no db_id and nothing extra is excluded.
    in_exam = {s.db_id for s in job.slots if s.kind == "database" and s.db_id is not None}
    exclude = in_exam | set(extra_exclude_ids)
    rng = random.Random()
    try:
        chosen = _select_db_questions(slot.category, 1, exclude, rng)[0]
    except JobError as exc:
        raise JobConflict(str(exc)) from exc  # slot untouched

    _apply_db_origin(slot, chosen)
    if was_llm:
        job.category_history.setdefault(slot.category, []).append(old_question)
    _recompute_db_selected_ids(job, slot.category)
    store.save(job)
    return job


def replace_via_llm(job_id: str, instance_id: str, *,
                    provider_factory: Optional[ProviderFactory] = None) -> Job:
    """LLM replacement for **any** accepted slot -- DB->LLM or LLM->LLM (WP18R).

    The generator call receives every OTHER current category question plus that
    category's prior displaced **LLM** questions (order + repeated numbers
    preserved). The target's own old question is excluded from that context.

    On success the slot becomes a current LLM question and -- only if it *was*
    LLM-origin -- its old question is appended to ``category_history``. On failure
    the slot (and its Excel/DOCX projection) is restored exactly, with no
    history / origin / metadata mutation; the cost of the failed attempt is still
    ledgered against the cumulative job budget.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        raise JobBusy("another exam-generation operation is already running")
    got_file_lock = False
    try:
        job = store.load(job_id)
        if job is None:
            raise JobError(f"job {job_id} not found")
        slot = job.slot_by_instance(instance_id)
        if slot is None:
            raise JobError(f"question {instance_id} not found in job {job_id}")
        if slot.status != "accepted" or not slot.question:
            raise JobConflict("only an accepted question can be replaced")
        got_file_lock = store.try_acquire_lock(job_id)
        if not got_file_lock:
            raise JobBusy("job is locked by another process")

        was_llm = slot.kind == "llm"
        snap = _snapshot_slot(slot)
        old_question = {f: slot.question[f] for f in SEVEN}
        provider = provider_factory() if provider_factory else None
        previous = _previous_for_slot(job, slot)  # already excludes this slot's old question

        slot.retries += 1
        result = _generate_one(job, slot, kind="replace_llm", provider=provider, previous=previous)

        if result is not None and result.status == "accepted":
            _apply_llm_origin(slot)  # kind=llm, db_id=None; question/meta already set
            if was_llm:
                job.category_history.setdefault(slot.category, []).append(old_question)
            _recompute_db_selected_ids(job, slot.category)
        else:
            # failure: restore the slot exactly (question, origin, metadata),
            # keeping only a safe_error describing why nothing changed.
            reason = (
                getattr(result, "failure_reason", None) if result is not None else None
            ) or "LLM replacement did not produce an accepted question; original kept"
            _restore_slot(slot, snap)
            slot.safe_error = reason

        _finalise(job, stopped_by_ceiling=(result is not None and result.status == "cost_ceiling"))
        store.save(job)
        _print_terminal_summary(job, header="EXAM JOB UPDATED (llm replace)")
        return job
    finally:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()


# --------------------------------------------------------------------------- #
# cost-ceiling update
# --------------------------------------------------------------------------- #
def update_cost_ceiling(job_id: str, new_cap: Any) -> Job:
    job = store.load(job_id)
    if job is None:
        raise JobError(f"job {job_id} not found")
    try:
        cap = Decimal(str(new_cap))
    except Exception as exc:  # noqa: BLE001
        raise JobError(f"cost_ceiling_usd is not a valid decimal: {new_cap!r}") from exc
    if cap < Decimal(job.accumulated_cost_usd):
        raise JobConflict(
            f"new cap ${cap} is below the ${job.accumulated_cost_usd} already accumulated"
        )
    if cap <= 0:
        raise JobError("cost_ceiling_usd must be positive")
    job.cost_ceiling_usd = str(cap)
    job.request["cost_ceiling_usd"] = str(cap)
    if job.terminal_summary:
        job.terminal_summary["cost_ceiling_usd"] = str(cap)
    store.save(job)
    return job


# --------------------------------------------------------------------------- #
# result view + export
# --------------------------------------------------------------------------- #
def result_view(job: Job) -> dict:
    """Full/partial exam result: accepted questions as DTO dicts in canonical
    order with contiguous global numbers, plus job progress."""
    dtos: list[dict] = []
    for pos, slot in enumerate(job.accepted_questions_ordered(), 1):
        if slot.kind == "database":
            dto = _db_slot_dto(slot)
        else:
            meta = GenerationMeta(
                attempts=slot.attempts, retries_by_slot=slot.retries,
                cost_usd=_slot_cost(job, slot), was_repaired=slot.was_repaired,
                audit_ref=slot.audit_ref, outcome="accepted",
            )
            dto = ExamQuestionDTO.from_generated(
                {f: slot.question[f] for f in SEVEN}, number=slot.question["number"],
                category=slot.category, generation_meta=meta,
            )
            dto.instance_id = slot.instance_id
        d = dto.to_dict()
        d["number"] = slot.number  # contiguous global number wins
        dtos.append(d)
    view = job.progress_view()
    view["questions"] = dtos
    view["category_history"] = job.category_history
    view["cost_ledger"] = job.cost_ledger
    return view


def _db_slot_dto(slot: Slot) -> ExamQuestionDTO:
    """Rich DTO for a DB slot: re-fetch the row for its performance history /
    categories when an app context is available, else fall back to the stored
    seven fields."""
    row = None
    try:
        from src.models.question import Question
        from src.models.user import db

        if slot.db_id is not None:
            row = db.session.get(Question, slot.db_id)
    except Exception:  # noqa: BLE001 - no app context / row gone
        row = None
    if row is not None:
        dto = ExamQuestionDTO.from_db_question(row, number=slot.number, category=slot.category)
        dto.instance_id = slot.instance_id
        return dto
    return ExamQuestionDTO(
        **{f: slot.question[f] for f in SEVEN},
        origin="database", id=slot.db_id, instance_id=slot.instance_id,
        category=slot.category, primary_category=slot.category, categories=[slot.category],
    )


def _slot_cost(job: Job, slot: Slot) -> str:
    total = Decimal("0")
    for e in job.cost_ledger:
        if e.get("slot_id") == slot.slot_id:
            total += Decimal(str(e.get("total_cost_usd", "0")))
    return str(total)


# Upload-compatible Hebrew headers (subset the /api/upload-excel route maps)
EXPORT_HEADERS = ["נושא", "שאלה", "תשובה1", "תשובה2", "תשובה3", "תשובה4", "תשובה_נכונה"]


def export_llm_xlsx(job: Job) -> bytes:
    """Only accepted ``origin=llm`` questions, with the exact headers the
    existing ``/api/upload-excel`` route expects. Does not insert anything."""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Generated"
    ws.append(EXPORT_HEADERS)
    for slot in job.accepted_questions_ordered():
        if slot.kind != "llm":
            continue
        q = slot.question
        ws.append([
            slot.category, q["question"],
            q["answer1"], q["answer2"], q["answer3"], q["answer4"],
            q["correct_answer"],
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
