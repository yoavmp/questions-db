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

import json
import logging
import random
import threading
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Optional

from src.integration.category_map import resolve_generator_context
from src.integration.exam_question_dto import ExamQuestionDTO, GenerationMeta
from src.integration.generator_adapter import AdapterRequest, generate_category_question
from src.integration.owner_policy import MAX_ATTEMPTS_PER_LLM_SLOT
from src.integration.readiness import readiness_report
from src.integration.request_contract import RequestContractError, parse_category_request
from src.jobs import naming, store
from src.jobs.exclusions import ExclusionParseError, revalidate_ids
from src.jobs.model import (
    CategoryPlan, Job, Slot, SEVEN, WORKFLOW_PHASES, missing_analytics, new_id, now_iso,
)
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
# WP27 §1 -- explicit two-phase workflow (derived, never a separate persisted
# field -- see the docstring in ``model.py``)
# --------------------------------------------------------------------------- #
def pending_llm_slots(job: Job) -> list:
    """Every LLM slot not yet claimed by a generation attempt -- the WP27
    "planned but not yet generated" work. Stable identity (``slot_id``/
    ``instance_id``, assigned at creation), never rendered/exported as a
    question, never a failure/attempt/retry, never part of semantic context
    (``_previous_for_slot`` only ever scans ``status == \"accepted\"`` LLM
    slots) -- and claimed exactly once each by the sequential loop in
    ``_run_llm_slots``, since a slot is skipped the moment its status leaves
    ``\"queued\"``."""
    return [s for s in job.slots if s.kind == "llm" and s.status == "queued"]


def workflow_phase(job: Job) -> str:
    """WP27R §1: a thin, validating accessor over the PERSISTED
    ``job.workflow_phase`` -- no longer a derivation from ``status`` (that
    was WP27's original design; WP27R replaced it because a derived-only
    phase, recomputed fresh on every read, could observe a stale ``status``
    whenever a reader raced a concurrent/async writer -- see
    WP27R_ARCHITECT_REPORT.md §2 for the incident this fixes).

    ``Job.from_dict`` already guarantees ``job.workflow_phase`` is always one
    of ``WORKFLOW_PHASES`` -- inferring it once, safely, for any legacy job
    that predates this field (see ``model._infer_legacy_workflow_phase``) --
    so this function's job is simply to read it back, with one last defensive
    validation in case some code path ever set it to something else in
    memory without going through ``Job.to_dict``'s own guard.
    """
    if job.workflow_phase not in WORKFLOW_PHASES:
        raise ValueError(
            f"job {job.job_id}: invalid workflow_phase {job.workflow_phase!r} "
            f"(must be one of {WORKFLOW_PHASES})"
        )
    return job.workflow_phase


# --------------------------------------------------------------------------- #
# DB selection (needs a Flask app context)
# --------------------------------------------------------------------------- #
#: WP26R §3 -- eligibility for category X is exact membership of X in the
#: question's full ``categories`` list (parsed JSON, byte-exact canonical
#: strings). Never a substring/LIKE match on ``categories_json`` and never
#: widened by the singular ``category`` alone.
def _candidate_map(exclude_ids: frozenset = frozenset()) -> tuple[dict[str, list[int]], dict[int, Any]]:
    """Load every question once and index it by exact category-list membership.

    Returns ``(candidates_by_category, rows_by_id)`` -- ``candidates_by_category``
    maps each canonical category to the ids currently eligible for it (excluded
    ids removed), ``rows_by_id`` maps every id (excluded or not) to its row so
    callers can still look up an excluded row if needed.
    """
    from src.models.question import Question

    rows = Question.query.all()
    rows_by_id = {q.id: q for q in rows}
    candidates: dict[str, list[int]] = {c: [] for c in CATEGORY_ORDER}
    for q in rows:
        if q.id in exclude_ids:
            continue
        for c in q.categories:
            if c in candidates:
                candidates[c].append(q.id)
    return candidates, rows_by_id


def _select_db_questions(category: str, count: int, exclude_ids: set[int], rng: random.Random) -> list:
    """Single-target-category random selector used by DB replacement: any row
    whose authoritative ``categories`` list contains ``category`` (exact
    membership only), minus rows already in the exam / excluded, sampled
    uniformly."""
    from src.models.question import Question

    rows = Question.query.all()
    pool = [q for q in rows if q.id not in exclude_ids and category in q.categories]
    if len(pool) < count:
        raise JobError(
            f"category {category!r}: only {len(pool)} database question(s) available, {count} requested"
        )
    return rng.sample(pool, count)


def _match_db_slots(
    slot_categories: list[str], candidates_by_category: dict[str, list[int]], rng: random.Random,
) -> Optional[list[int]]:
    """Global feasible unique assignment for every requested DB slot (WP26R §4).

    ``slot_categories`` is the FIXED, canonical-order list of one entry per
    requested DB slot (never shuffled -- only candidate order is randomized).
    Returns a list the same length, each entry a distinct DB id whose category
    list contains that slot's category, or ``None`` if no complete matching
    exists (some DB id would have to fill two slots).

    Dependency-free augmenting-path (Kuhn's algorithm) bipartite matching:
    O(slots * candidates) per augmentation, trivial at the documented scale
    (fewer than 500 DB questions, at most ~40 exam questions). Correctness
    (whether a complete matching is found, given one exists) does not depend
    on visitation order -- only *which* of several possible complete matchings
    is found does -- so shuffling candidate order per attempt is safe
    randomization, not a correctness risk.
    """
    n = len(slot_categories)
    match_of_id: dict[int, int] = {}  # db_id -> slot_index currently holding it

    def try_assign(slot_idx: int, visited: set[int]) -> bool:
        cat = slot_categories[slot_idx]
        cands = list(candidates_by_category.get(cat, ()))
        rng.shuffle(cands)
        for cid in cands:
            if cid in visited:
                continue
            visited.add(cid)
            if cid not in match_of_id or try_assign(match_of_id[cid], visited):
                match_of_id[cid] = slot_idx
                return True
        return False

    for slot_idx in range(n):  # fixed canonical slot order
        if not try_assign(slot_idx, set()):
            return None

    assignment: list[Optional[int]] = [None] * n
    for cid, sidx in match_of_id.items():
        assignment[sidx] = cid
    assert all(a is not None for a in assignment)  # every slot_idx was try_assign'd
    return assignment  # type: ignore[return-value]


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


def _db_analytics(row: Any) -> dict:
    """Snapshot a DB question's historical accuracy/distinction at the moment
    it enters the exam (selection or replacement) -- WP21 §3. Never re-fetched
    live afterwards, so the persisted job result stays stable and correct even
    if the row is later edited or deleted, or the DB is unavailable. Mirrors
    ``Question.accuracy`` / ``.distinction`` (mean of history, ``None`` if
    empty) and ``.accuracy_list`` / ``.distinction_list`` (raw history,
    possibly multiple values) exactly -- the same JSON-safe shape the legacy
    screen and this DTO's ``from_db_question`` have always used."""
    return {
        "accuracy": row.accuracy,
        "distinction": row.distinction,
        "accuracy_list": list(row.accuracy_list),
        "distinction_list": list(row.distinction_list),
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

    # WP27 §2 -- initial creation is DB selection ONLY: no readiness/pricing/
    # API-key check here (moved to ``continue_llm_generation`` / manual
    # ``replace_via_llm``, immediately before their own first provider call).
    # This route must work with no ``OPENAI_API_KEY`` at all.

    # WP26 §1 -- structured/custom identity (optional; a job without one falls
    # back to naming.fallback_label everywhere it is displayed).
    try:
        identity = naming.resolve_identity(payload.get("identity"))
    except naming.IdentityError as exc:
        raise JobError(str(exc)) from exc

    # WP26 §2-§3 -- backend revalidation of client-supplied exclusion ids:
    # never trust the preview result blindly. Malformed ids are rejected
    # outright; well-formed ids that vanished since the preview are dropped
    # with a warning, never blocking job creation for an unrelated reason.
    try:
        excluded_ids, excl_warnings = revalidate_ids(payload.get("excluded_db_ids"))
    except ExclusionParseError as exc:
        raise JobError(str(exc)) from exc
    excluded_id_set = set(excluded_ids)

    # canonical order (established before both the feasibility check and job
    # assembly, so slot order is identical either way)
    parsed.sort(key=lambda pc: CATEGORY_ORDER.index(pc[0].category))

    # WP26R §4 -- one global feasible-unique-assignment proof for EVERY
    # requested DB slot, before the job or any slot exists and before any
    # provider code is reachable. Independent per-category availability is
    # a necessary-but-not-sufficient precheck (fast, specific message); the
    # bipartite match is the actual joint-feasibility proof (categories may
    # overlap, so passing every independent check does not guarantee a joint
    # assignment exists).
    candidates_by_category, rows_by_id = _candidate_map(exclude_ids=frozenset(excluded_id_set))
    slot_categories: list[str] = []
    for req, _ in parsed:
        avail = len(candidates_by_category.get(req.category, ()))
        if req.database > avail:
            raise JobError(
                f"קטגוריה '{req.category}': נדרשו {req.database} שאלות מהמאגר, "
                f"זמינות בפועל {avail} (לאחר החרגות)"
            )
        slot_categories.extend([req.category] * req.database)

    rng = random.Random(seed)
    assignment: list[int] = []
    if slot_categories:
        matched = _match_db_slots(slot_categories, candidates_by_category, rng)
        if matched is None:
            counts_msg = "; ".join(
                f"{req.category}: נדרשו {req.database}, זמינות עצמאית "
                f"{len(candidates_by_category.get(req.category, ()))}"
                for req, _ in parsed if req.database
            )
            raise JobError(
                "לא ניתן להקצות שאלות ייחודיות מהמאגר לכל הקטגוריות המבוקשות: "
                "לאחר חפיפת קטגוריות והחרגות אין הקצאה ייחודית אפשרית, גם אם כל "
                f"קטגוריה בנפרד נראית זמינה בנפרד ({counts_msg})"
            )
        assignment = matched

    job = Job(
        job_id=new_id(), cost_ceiling_usd=str(cap),
        request={
            "categories": {req.category: {"total": req.total, "database": req.database, "llm": req.llm}
                           for req, _ in parsed},
            "cost_ceiling_usd": str(cap),
        },
        identity=identity,
        excluded_db_ids=sorted(excluded_id_set),
    )
    job.root_job_id = job.job_id
    if excl_warnings:
        for msg in excl_warnings:
            job.warnings.append({"code": "excluded_id_dropped", "message": msg})

    # running global number base; DB slots consume ``assignment`` in the same
    # fixed canonical order used to build ``slot_categories`` above
    number = 0
    assignment_cursor = 0
    for req, context_id in parsed:
        plan = CategoryPlan(
            category=req.category, context_id=context_id,
            order_index=CATEGORY_ORDER.index(req.category),
            total=req.total, database=req.database, llm=req.llm,
            number_base=number,
        )
        # A database questions first -- each ID already proven globally unique
        # across the WHOLE exam by the matching above; every listed category of
        # the matched row is equally eligible, never only its primary.
        chosen_ids = assignment[assignment_cursor:assignment_cursor + req.database]
        assignment_cursor += req.database
        for i, qid in enumerate(chosen_ids):
            row = rows_by_id[qid]
            number += 1
            plan.db_selected_ids.append(row.id)
            job.slots.append(Slot(
                slot_id=new_id(), instance_id=new_id(), category=req.category,
                context_id=context_id, kind="database", order_in_category=i, number=number,
                status="accepted", question=_row_seven(row, number), db_id=row.id,
                analytics=_db_analytics(row),
                primary_category=row.category, categories=list(row.categories),
            ))
        # B LLM slots (queued; generated by run_job). Category metadata
        # deterministically reflects the fixed target category (WP26R §5).
        for i in range(req.llm):
            number += 1
            job.slots.append(Slot(
                slot_id=new_id(), instance_id=new_id(), category=req.category,
                context_id=context_id, kind="llm", order_in_category=i, number=number,
                status="queued",
                primary_category=req.category, categories=[req.category],
            ))
        job.categories.append(plan)

    job.category_history = {req.category: [] for req, _ in parsed}

    # WP27R §1 -- ``Job.workflow_phase`` defaults to "db_review" (the Job()
    # call above never overrides it), matching the fresh job built here when
    # any LLM work is planned: nothing else runs until the explicit
    # continuation is claimed. If nothing is planned to generate, the job is
    # done the moment DB selection finishes -- ``_finalise`` (below) sets
    # both ``status="completed"`` and ``workflow_phase="complete"`` in one
    # place, no Continue ever exposed. WP27's A=0/B>0 case (zero DB, some
    # LLM planned) stays "db_review" the same way -- LLM count alone decides.
    total_llm = sum(req.llm for req, _ in parsed)
    if total_llm == 0:
        _finalise(job, stopped_by_ceiling=False)

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


def _record_cost(job: Job, *, kind: str, slot: Slot, result: Any,
                 audit_ref: Optional[str] = None,
                 invocation_uuid: Optional[str] = None) -> None:
    """Add one generator call's cost to the job ledger + accumulator.

    ``audit_ref`` (WP21 §7) is the safe *relative* invocation-directory path
    for this specific call (e.g. ``slots/<slot_id>/replace_llm_0003_<uuid>``)
    -- never an absolute path, never prompt/response content -- so a failed
    attempt stays traceable to its own on-disk evidence even after the slot
    itself rolls back to a different (or no) ``audit_ref``. ``invocation_uuid``
    (WP21R §3) is the same call's authoritative collision-proof identity,
    also embedded in ``audit_ref`` -- kept as its own field so a ledger
    record can be matched to its on-disk manifest without parsing the ref.
    """
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
        "audit_ref": audit_ref,
        "invocation_uuid": invocation_uuid,
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

    # WP21R §3: the directory name's "<kind>_<seq>" prefix (seq = this call's
    # *expected* cost_ledger position) is human-readable context only -- it is
    # NOT collision-proof on its own. If the process crashes anywhere inside
    # `generate_category_question` below, `_record_cost` never runs, so
    # `len(job.cost_ledger) + 1` recomputes to this SAME seq on the next
    # invocation for this slot. What actually prevents a collision is
    # `invocation_uuid`: freshly drawn every call, never derived from mutable
    # state, so two invocations can never collide even if they share a
    # "<kind>_<seq>" prefix. `invocation_audit_dir` also refuses (rather than
    # silently reusing) any path that already exists.
    seq = len(job.cost_ledger) + 1
    invocation_uuid = store.new_invocation_uuid()
    invocation_id = store.invocation_dir_name(kind, seq, invocation_uuid)
    audit_dir_path = store.invocation_audit_dir(job.job_id, slot.slot_id, invocation_id)
    audit_dir = str(audit_dir_path)
    audit_ref = f"slots/{slot.slot_id}/{invocation_id}"

    # WP21R §3: a small, atomic, secret-free manifest written BEFORE the
    # provider boundary -- if the process dies anywhere inside the call
    # below, this manifest alone (no prompt/response/source content, no
    # credential, no absolute path) is enough to diagnose the orphaned
    # directory.
    store.write_invocation_manifest(audit_dir_path, {
        "job_id": job.job_id,
        "slot_id": slot.slot_id,
        "operation": kind,
        "sequence": seq,
        "invocation_uuid": invocation_uuid,
        "created_at": now_iso(),
    })

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
    _record_cost(job, kind=kind, slot=slot, result=result, audit_ref=audit_ref,
                 invocation_uuid=invocation_uuid)
    slot.audit_ref = audit_ref
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
def _run_llm_slots(job: Job, *, provider: Any) -> bool:
    """Process every currently ``queued`` LLM slot, categories in canonical
    order, one at a time, sequential within a category. Shared by ``run_job``
    (legacy/direct-driven callers -- every pre-WP27 test still calls this via
    ``run_job``) and ``continue_llm_generation`` (WP27 §3). The caller must
    already hold ``_RUN_LOCK`` + the per-job file lock and have persisted
    ``status=\"running\"`` before calling this. Returns ``stopped_by_ceiling``.

    Semantic context (WP27 §5) needs no change here: ``_previous_for_slot``
    already scans only *currently accepted* slots (DB, and LLM with
    ``status == \"accepted\"``) plus ``category_history`` -- a still-``queued``
    planned slot is invisible to it by construction, and a slot generated
    earlier in this same loop is already persisted ``accepted`` before the
    next slot's context is built, so "earlier accepted planned LLM question
    generated during this continuation" falls out for free from the existing
    sequential loop.
    """
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
    return stopped_by_ceiling


def run_job(job_id: str, *, provider_factory: Optional[ProviderFactory] = None) -> Job:
    """Process every queued LLM slot, categories in canonical order, one at a
    time. Idempotent-ish: only ``queued`` slots are generated.

    Unchanged since WP18/WP26R: kept for every existing direct caller (tests
    that drive DB selection + LLM generation as two explicit steps without
    going through the HTTP route). WP27's ``POST /exam-jobs`` route no longer
    calls this automatically -- see ``continue_llm_generation`` for the new
    explicit-continuation entry point the route now uses instead.
    """
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
        # WP27R §1: legacy/direct-driven callers (this function, unlike
        # ``claim_llm_continuation``) still flip ``workflow_phase`` here too,
        # so every job this function ever touches stays phase-consistent
        # even though it never goes through the new claim/worker split.
        job.workflow_phase = "llm_generation"
        store.save(job)

        provider = provider_factory() if provider_factory else None
        stopped_by_ceiling = _run_llm_slots(job, provider=provider)

        _finalise(job, stopped_by_ceiling=stopped_by_ceiling)
        store.save(job)
        _print_terminal_summary(job, operation="initial")
        return job
    finally:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()


# --------------------------------------------------------------------------- #
# WP27R §3 -- continuation split into an atomic claim and a claimed worker
# --------------------------------------------------------------------------- #
def claim_llm_continuation(
    job_id: str, *, provider_factory: Optional[ProviderFactory] = None,
) -> tuple[Job, Any]:
    """Atomically validate and claim a job's planned LLM batch.

    On success, returns ``(job, provider)`` with the job ALREADY persisted as
    ``workflow_phase=\"llm_generation\"``, ``status=\"running\"`` -- and with
    the process-wide ``_RUN_LOCK`` and the per-job file lock BOTH STILL HELD.
    This is deliberate (WP27R §3: "must not create a gap where another
    mutation can alter the same job after claim but before the worker
    obtains protection"): the ONLY correct continuations from here are
    exactly one subsequent call to ``run_claimed_llm_generation`` (the normal
    path) or, if a worker could not even be started, to
    ``abort_claim_as_interrupted`` -- never anything else, and never a second
    call to this function for the same claim. Any thread may release a
    ``threading.Lock`` it did not itself acquire, so handing the held locks
    from this call (typically the request thread) to a spawned background
    worker thread is safe and leaves no gap for another mutation to observe
    or alter the job in between.

    Eligible starting points:

    * ``workflow_phase == \"db_review\"`` (``status == \"queued\"``) -- the
      first claim;
    * ``workflow_phase == \"llm_generation\"`` and ``status != \"running\"``
      (i.e. ``partial``/``interrupted``/``cost_ceiling`` with real planned
      work still ``\"queued\"``) -- resuming a batch that was cut short,
      reusing the exact same claim path rather than a separate mechanism.

    Readiness/pricing/API-key readiness (WP27 §3/§8, WP27R §3) is checked
    once, up front, inside the held lock -- but BEFORE any state is
    persisted, so a failure raises with the job completely untouched (still
    ``db_review``/recoverable ``llm_generation``), Continue safely retryable
    once the environment is fixed, and both locks released by this same call
    (see the ``except`` below) rather than left dangling.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        raise JobBusy("another exam-generation operation is already running")
    got_file_lock = False
    try:
        job = store.load(job_id)
        if job is None:
            raise JobError(f"job {job_id} not found")

        phase = job.workflow_phase
        if phase == "db_review":
            if job.status != "queued":
                raise JobConflict(f"job is {job.status!r}; expected queued for db_review")
        elif phase == "llm_generation":
            # unreachable in practice (an active worker would already hold
            # _RUN_LOCK, which we just acquired above) -- kept as an explicit,
            # documented invariant check rather than a silent assumption.
            if job.status == "running":
                raise JobConflict("a continuation is already running for this job")
        else:
            raise JobConflict("job has no planned LLM work to continue")

        if not pending_llm_slots(job):
            raise JobConflict("job has no planned LLM work to continue")

        got_file_lock = store.try_acquire_lock(job_id)
        if not got_file_lock:
            raise JobBusy("job is locked by another process")

        provider = provider_factory() if provider_factory else None
        if provider is None:
            report = readiness_report()
            if not report["ready_for_llm"]:
                raise JobError(
                    "LLM generation is not ready: " + "; ".join(report["blocking_reasons"])
                )

        # the claim itself: persisted BEFORE returning / before any provider
        # call (WP27 §3, hardened by WP27R §3/§4 to also be synchronous with
        # the HTTP request that triggered it -- see routes/exam_jobs.py).
        job.workflow_phase = "llm_generation"
        job.status = "running"
        store.save(job)
        return job, provider
    except Exception:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()
        raise


def run_claimed_llm_generation(job_id: str, *, provider: Any) -> Job:
    """Run a just-claimed batch to a terminal (or, on an unexpected crash
    mid-call, recoverably ``interrupted`` -- unchanged crash story, see
    ``store.recover_on_start``) outcome.

    MUST be called exactly once, immediately after a successful
    ``claim_llm_continuation`` for the SAME ``job_id``, passing the exact
    ``provider`` it returned. Assumes (and requires) both locks are already
    held on entry -- this function is the sole owner of releasing them, on
    every exit path, exactly like every other lock-holding function in this
    module.
    """
    try:
        job = store.load(job_id)
        stopped_by_ceiling = _run_llm_slots(job, provider=provider)

        _finalise(job, stopped_by_ceiling=stopped_by_ceiling)
        store.save(job)
        _print_terminal_summary(job, operation="continue")
        return job
    finally:
        store.release_lock(job_id)
        _RUN_LOCK.release()


def abort_claim_as_interrupted(job_id: str) -> None:
    """WP27R §3: called ONLY when a worker could not even be started after a
    successful ``claim_llm_continuation`` (e.g. background-thread creation
    itself raised). Marks the job recoverably ``interrupted`` --
    ``workflow_phase`` stays ``\"llm_generation\"`` -- instead of leaving a
    permanently fake ``\"running\"`` job that no worker will ever finish, and
    releases the locks the claim was holding. Mirrors ``store.
    recover_on_start``'s own process-crash recovery, applied synchronously
    here instead of at the next backend boot.
    """
    try:
        job = store.load(job_id)
        if job is not None and job.status == "running":
            job.status = "interrupted"
            job.safe_error = "worker failed to start; unfinished slots are retryable"
            for s in job.slots:
                if s.status == "running":
                    s.status = "interrupted"
            store.save(job)
    finally:
        store.release_lock(job_id)
        _RUN_LOCK.release()


def continue_llm_generation(job_id: str, *, provider_factory: Optional[ProviderFactory] = None) -> Job:
    """Convenience synchronous wrapper over the claim/worker split above:
    claim, then immediately run to a terminal outcome in the calling thread.

    Used directly by tests (and by the HTTP route's ``EXAM_JOB_SYNC`` path)
    that want one call covering the whole continuation deterministically.
    A production/async caller should use ``claim_llm_continuation`` and
    ``run_claimed_llm_generation`` separately instead, so the claim can be
    persisted before an HTTP response returns while the run itself happens
    in a spawned background worker -- see ``routes/exam_jobs.py``.
    """
    job, provider = claim_llm_continuation(job_id, provider_factory=provider_factory)
    return run_claimed_llm_generation(job_id, provider=provider)


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

    # WP27R §1/§5 -- workflow_phase tracks whether the planned automatic
    # batch has genuinely finished TRAVERSING its work, independent of the
    # operational ``status`` above: any slot still "queued"/"running"/
    # "interrupted" means real planned work nobody has attempted (or fully
    # attempted) yet, so phase stays "llm_generation" even when ``status``
    # itself reads "partial" or "cost_ceiling" ("partial can coexist with
    # llm_generation", "interrupted must coexist with llm_generation", "a
    # ceiling ... must not silently pretend those slots were completed").
    # Once every planned slot has reached a TERMINAL per-attempt outcome
    # (accepted / failed / cost_ceiling), traversal is done and phase
    # becomes "complete" -- even if some outcomes are individually
    # rejected/retryable ("a terminal batch that attempted all intended
    # slots may have phase complete even when some individual slots remain
    # rejected/retryable"). This reuses the exact same ``pending`` set
    # already computed for ``status`` above -- one source of truth, not two.
    job.workflow_phase = "llm_generation" if pending else "complete"

    job.terminal_summary = _summary_dict(job)


def _summary_dict(job: Job) -> dict:
    llm_slots = [s for s in job.slots if s.kind == "llm"]
    # WP26 §7: retries/replacements are derived ONLY from the immutable
    # cost_ledger's operation `kind` -- never from the mutable, historically
    # conflated `slot.retries` counter -- so an old persisted job whose slots
    # still carry a pre-WP26 conflated count reports correctly here too,
    # without rewriting its file.
    ledger_totals = ledger_telemetry(job)["totals"]
    return {
        "job_id": job.job_id,
        "status": job.status,
        "final_llm_cost_usd": job.accumulated_cost_usd,
        "cost_basis": job.cost_basis,
        "remaining_cost_usd": str(job.remaining_budget()),
        "llm_accepted": sum(1 for s in llm_slots if s.status == "accepted"),
        "llm_failed": sum(1 for s in llm_slots if s.status in ("failed", "cost_ceiling")),
        "llm_requested": len(llm_slots),
        "retries": ledger_totals["retries"],
        "replacements": ledger_totals["replacements"],
        "pricing_verification": job.pricing_verification,
        "pricing_warnings": sorted({w.get("code") for w in job.warnings if w.get("code")}),
        "cost_ceiling_usd": job.cost_ceiling_usd,
        "generated_at": now_iso(),
    }


#: operation code (matches ``cost_ledger`` ``kind``) -> human-readable terminal header
_OPERATION_HEADERS = {
    "initial": "EXAM JOB COMPLETE",
    "continue": "EXAM JOB COMPLETE",  # WP27: the (formerly automatic) LLM batch, now explicit
    "retry": "EXAM JOB UPDATED (retry)",
    "replace_llm": "EXAM JOB UPDATED (llm replace)",
}


def _print_terminal_summary(job: Job, *, operation: str) -> None:
    """One visible backend-terminal line per paid LLM operation.

    Called once initial exam generation reaches a terminal state (``operation=
    "initial"``), and after every LLM retry / LLM replacement (``"retry"`` /
    ``"replace_llm"``) -- accepted or failed alike, since a failed attempt is
    still charged. Never called for a DB-only replacement (``replace_from_db``
    makes no provider call and changes no cost -- no line for it).

    Carries only job id, operation, cumulative cost, pricing basis, remaining
    ceiling and warnings -- never prompts, provider responses, question
    content or secrets.
    """
    s = job.terminal_summary or _summary_dict(job)
    header = _OPERATION_HEADERS.get(operation, f"EXAM JOB UPDATED ({operation})")
    line = (
        f"[{header}] job={s['job_id']} operation={operation} status={s['status']} "
        f"llm_cost=${s['final_llm_cost_usd']} basis={s['cost_basis']} "
        f"remaining=${s['remaining_cost_usd']} "
        f"accepted={s['llm_accepted']}/{s['llm_requested']} failed={s['llm_failed']} "
        f"retries={s['retries']} replacements={s['replacements']} "
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
        _print_terminal_summary(job, operation="retry")
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
    "question", "db_id", "audit_ref", "was_repaired", "analytics",
)


def _snapshot_slot(slot: Slot) -> dict:
    snap = {k: getattr(slot, k) for k in _SLOT_STATE_FIELDS}
    if snap["question"] is not None:
        snap["question"] = dict(snap["question"])
    snap["analytics"] = dict(snap["analytics"])
    return snap


def _restore_slot(slot: Slot, snap: dict) -> None:
    for k, v in snap.items():
        setattr(slot, k, dict(v) if k in ("question", "analytics") and v is not None else v)


def _apply_db_origin(slot: Slot, row: Any) -> None:
    """Make ``slot`` a current DB question: ``kind=database``, integer ``db_id``,
    the row's seven fields, DB defaults, a fresh accuracy/distinction snapshot
    (WP21 §3), and a fresh category snapshot (WP26R §5) -- the row's primary
    and full category list AT THIS MOMENT, never re-read afterwards."""
    slot.kind = "database"
    slot.db_id = row.id
    slot.question = _row_seven(row, slot.number)
    slot.status = "accepted"
    slot.attempts = 0
    slot.retries = 0
    slot.was_repaired = False
    slot.audit_ref = None
    slot.safe_error = None
    slot.analytics = _db_analytics(row)
    slot.primary_category = row.category
    slot.categories = list(row.categories)


def _apply_llm_origin(slot: Slot) -> None:
    """Make ``slot`` a current LLM question: ``kind=llm``, ``db_id=None``, no
    performance history (WP21 §3). The seven fields / generation metadata
    were already set by ``_generate_one`` on the accepted result. Category
    metadata deterministically reflects the slot's fixed target category
    (WP26R §5) -- an LLM question has no independent category of its own."""
    slot.kind = "llm"
    slot.db_id = None
    slot.analytics = missing_analytics()
    slot.primary_category = slot.category
    slot.categories = [slot.category]


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

    Concurrency (WP19 §1): although a DB swap makes no provider call, it does a
    read-modify-write of ``job.json`` (and, for LLM->DB, appends to
    ``category_history``). It therefore takes the same process-wide ``_RUN_LOCK``
    and per-job ``job.lock`` as every other job mutation, so a double click or a
    concurrent ``run_job`` / retry / LLM replacement cannot lose an update,
    select the same row twice or corrupt persistence. A held lock raises
    ``JobBusy`` (HTTP 409); the slot is never touched in that case.
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
        old_question = {f: slot.question[f] for f in SEVEN}

        # exclude DB rows currently in the exam. For DB->DB the current slot's
        # own db_id is in this set, so the swap always yields a *different*
        # question; for LLM->DB the current slot has no db_id and nothing extra
        # is excluded.
        in_exam = {s.db_id for s in job.slots if s.kind == "database" and s.db_id is not None}
        exclude = in_exam | set(extra_exclude_ids) | set(job.excluded_db_ids)
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
    finally:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()


def replace_via_llm(job_id: str, instance_id: str, *,
                    provider_factory: Optional[ProviderFactory] = None) -> Job:
    """LLM replacement for **any** accepted slot -- DB->LLM or LLM->LLM (WP18R).

    The generator call receives every OTHER current category question, that
    category's prior displaced **LLM** questions (order + repeated numbers
    preserved), and -- WP25G -- the slot's OWN old question, appended
    ephemerally for this one call only. ``_previous_for_slot`` excludes the
    target slot by ``instance_id`` (it is, after all, one of the "other"
    slots' own comparison set), and ``category_history`` cannot yet contain
    this call's own old question -- it is only appended there *after* this
    same call succeeds (see below). Left uncorrected, that means the one
    question this call is about to displace is the one question never shown
    to the generator/reviewer judging its replacement: WP25G's incident (an
    accepted question displaced by its own stem/answer-reversed duplicate)
    traced to exactly this gap. The ephemeral append here closes it without
    touching persisted history before success.

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

        # WP27 §4: capture BEFORE this call whether the job is currently in
        # db_review -- other planned LLM slots are legitimately still
        # "queued" (not yet claimed by Continue) throughout db_review, which
        # `_finalise`'s pending-slot check would otherwise misread as an
        # in-progress/partial batch and use to prematurely flip job.status
        # away from "queued", ending db_review as a side effect of an
        # unrelated manual replacement. "On success, keeps the job in
        # db_review" applies on failure too -- nothing about a manual
        # replacement may change the workflow phase either way. WP27R §1:
        # reads the persisted ``workflow_phase`` directly rather than
        # inferring it from ``status`` (the two still always agree by
        # invariant, but the phase is the authoritative field now).
        was_db_review = job.workflow_phase == "db_review"
        was_llm = slot.kind == "llm"
        snap = _snapshot_slot(slot)
        old_question = {f: slot.question[f] for f in SEVEN}
        provider = provider_factory() if provider_factory else None
        # WP25G: _previous_for_slot already excludes this slot's old question
        # (by instance_id, from the "other slots" scan) and category_history
        # cannot yet hold it either (appended only after this call succeeds,
        # below) -- so without this ephemeral append, the very question being
        # displaced would never reach the generator/reviewer judging its own
        # replacement. Appended for this call only; category_history itself
        # is still touched only after success, unchanged from before.
        previous = _previous_for_slot(job, slot) + [old_question]

        # WP26 §7: an intentional replace_llm is not a failure-driven retry --
        # `slot.retries` (surfaced as `generation_meta.retries_by_slot`) must
        # count genuine retry_slot operations only. The ledger's own `kind`
        # field already distinguishes "retry" from "replace_llm" regardless
        # (see `ledger_telemetry` / `_summary_dict`), but the mutable
        # per-slot counter used to be bumped here too and, unlike a failed
        # attempt, a SUCCESSFUL replace_llm never rolled it back -- silently
        # inflating every later "retries" reading for this slot.
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

        if was_db_review:
            # keep job.status == "queued" (db_review) -- only refresh the
            # informational cost/telemetry summary (WP27 §6: terminal
            # summaries continue after every paid operation), never job.status.
            job.terminal_summary = _summary_dict(job)
        else:
            _finalise(job, stopped_by_ceiling=(result is not None and result.status == "cost_ceiling"))
        store.save(job)
        _print_terminal_summary(job, operation="replace_llm")
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
# --------------------------------------------------------------------------- #
# attempt / retry telemetry -- derived ONLY from the immutable cost ledger
# --------------------------------------------------------------------------- #
def ledger_telemetry(job: Job) -> dict:
    """Attempt / retry / charged-failure telemetry folded from ``job.cost_ledger``.

    The ledger is append-only: every generator call outcome (initial, retry,
    LLM replacement -- accepted, rejected, refusal, systemic, cost-ceiling) is
    recorded with its ``attempts``, ``kind``, ``status`` and ``total_cost_usd``.
    A failed LLM replacement rolls the *slot* back (attempts/retries reset), but
    its ledger row stays -- so a charged failed attempt remains diagnosable here
    even though the slot shows no trace of it.

    Shape::

        {
          "by_category": {<canonical>: {attempts, charged_failed_attempts,
                                        retries, replacements, failed_attempts,
                                        accepted, cost_usd, entries}},
          "by_slot":     {<slot_id>:  {number, instance_id, category, kind,
                                        ...same counters..., outcomes:[...]}},
          "totals":      {...same counters..., ledger_entries},
        }

    ``by_category`` / ``by_slot`` never partition by *current* origin -- they are
    a diagnostic history of generation effort, not a DB-vs-LLM balance.
    """
    def _blank() -> dict:
        return {
            "attempts": 0,
            "failed_attempts": 0,
            "charged_failed_attempts": 0,
            "retries": 0,
            "replacements": 0,
            "accepted": 0,
            "cost_usd": Decimal("0"),
            "entries": 0,
        }

    by_cat: dict[str, dict] = {}
    by_slot: dict[str, dict] = {}
    totals = _blank()

    for e in job.cost_ledger:
        cat = e.get("category", "")
        sid = e.get("slot_id", "")
        status = e.get("status")
        kind = e.get("kind")
        attempts = int(e.get("attempts", 0) or 0)
        cost = Decimal(str(e.get("total_cost_usd", "0") or "0"))
        is_failure = status != "accepted"

        cbucket = by_cat.setdefault(cat, _blank())
        sbucket = by_slot.setdefault(sid, {
            **_blank(),
            "number": e.get("number"),
            "instance_id": e.get("instance_id"),
            "category": cat,
            "kind": None,
            "outcomes": [],
        })
        for b in (cbucket, sbucket, totals):
            b["entries"] += 1
            b["attempts"] += attempts
            b["cost_usd"] += cost
            if kind == "retry":
                b["retries"] += 1
            if kind == "replace_llm":
                b["replacements"] += 1
            if is_failure:
                b["failed_attempts"] += 1
                if cost > 0:
                    b["charged_failed_attempts"] += 1
            else:
                b["accepted"] += 1
        sbucket["outcomes"].append(status)

    # match each slot's telemetry to its *current* kind for display convenience
    for s in job.slots:
        if s.slot_id in by_slot:
            by_slot[s.slot_id]["kind"] = s.kind

    def _finish(b: dict) -> dict:
        out = dict(b)
        out["cost_usd"] = str(b["cost_usd"])
        return out

    return {
        "by_category": {k: _finish(v) for k, v in by_cat.items()},
        "by_slot": {k: _finish(v) for k, v in by_slot.items()},
        "totals": {**_finish(totals), "ledger_entries": len(job.cost_ledger)},
    }


def result_view(job: Job) -> dict:
    """Full/partial exam result: accepted questions as DTO dicts in canonical
    order, plus job progress.

    Note (WP19 §1): neither this view nor ``progress_view`` reports a *current*
    DB-vs-LLM composition. ``categories[*].database`` / ``.llm`` are the original
    request quotas (provenance only); per-question origin is the ``origin`` field
    on each entry of ``questions``. Replacements may move that balance freely and
    nothing here recomputes or enforces it.

    WP27 §7/§9 -- numbering has two distinct meanings depending on phase:

    * during ``db_review``, ``slot.number`` (the eventual full-exam number,
      already assigned at creation time across BOTH the selected DB slots and
      the still-``queued`` planned LLM slots -- see ``create_job``) would show
      gaps wherever a category has planned-but-not-yet-generated LLM slots
      interleaved before a later category's DB slots. The interim view/export
      contract instead needs a genuinely compact ``1..N`` numbering of only
      the currently accepted questions -- so ``d["number"]`` here is the
      accepted-list POSITION (``pos``), display/export-only, never persisted
      and never confused with a slot's stable ``instance_id``/``slot_id``.
    * once Continue is claimed (``workflow_phase`` leaves ``db_review``), the
      persisted ``slot.number`` -- already the correct final full-exam
      number, established once at creation time and immutable across
      generation/failure/retry/replacement -- is shown as-is again, exactly
      as before WP27.
    """
    phase = workflow_phase(job)
    interim_numbering = phase == "db_review"
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
        d["number"] = pos if interim_numbering else slot.number
        dtos.append(d)
    view = job.progress_view()
    view["questions"] = dtos
    view["category_history"] = job.category_history
    view["cost_ledger"] = job.cost_ledger
    view["attempt_telemetry"] = ledger_telemetry(job)
    # WP26 §1/§4/§5 -- naming + lineage. `display_name` is always present
    # (calculated fallback for a job with no `identity`, never persisted).
    # `excluded_db_ids_count` is a safe diagnostic (§3): the raw ids and
    # excluded question TEXT are never surfaced here.
    view["identity"] = job.identity
    view["display_name"] = (
        job.identity["display_name"] if job.identity else naming.fallback_label(job.job_id, job.created_utc)
    )
    view["slug"] = job.identity["slug"] if job.identity else naming.safe_slug(view["display_name"])
    view["parent_job_id"] = job.parent_job_id
    view["root_job_id"] = job.root_job_id
    view["excluded_db_ids_count"] = len(job.excluded_db_ids)
    view["branchable"] = job.status == "completed" and job.workflow_phase == "complete"
    # WP27 §1/§9 -- explicit workflow phase + how much planned LLM work is
    # still pending. `accepted_count` mirrors `list_jobs`'s existing field.
    view["workflow_phase"] = phase
    view["pending_llm_total"] = len(pending_llm_slots(job))
    view["accepted_count"] = len(dtos)
    return view


# --------------------------------------------------------------------------- #
# WP26 §1 -- read-only jobs list (newest-first, safe fields only)
# --------------------------------------------------------------------------- #
def list_jobs() -> list[dict]:
    """Every persisted job, newest-first. Deliberately excludes question
    bodies, prompts, audits and course-source content -- see ``result_view``
    (via ``GET /exam-jobs/<id>``) for the full detail of one job."""
    jobs: list[Job] = []
    for jid in store.list_job_ids():
        job = store.load(jid)
        if job is not None:
            jobs.append(job)
    jobs.sort(key=lambda j: j.created_utc, reverse=True)

    out = []
    for job in jobs:
        display_name = (
            job.identity["display_name"] if job.identity
            else naming.fallback_label(job.job_id, job.created_utc)
        )
        slug = job.identity["slug"] if job.identity else naming.safe_slug(display_name)
        accepted = sum(1 for s in job.slots if s.status == "accepted")
        out.append({
            "job_id": job.job_id,
            "display_name": display_name,
            "slug": slug,
            "created_utc": job.created_utc,
            "updated_utc": job.updated_utc,
            "status": job.status,
            "accepted_count": accepted,
            "total_count": len(job.slots),
            "parent_job_id": job.parent_job_id,
            "root_job_id": job.root_job_id,
            "excluded_db_ids_count": len(job.excluded_db_ids),
            "branchable": job.status == "completed" and job.workflow_phase == "complete",
            # WP27 §9 -- workflow phase/user-facing status + pending planned
            # LLM count, so the saved-exam list can distinguish a job
            # awaiting DB-review approval from one still running or done.
            "workflow_phase": workflow_phase(job),
            "pending_llm_total": len(pending_llm_slots(job)),
        })
    return out


# --------------------------------------------------------------------------- #
# WP26 §4 -- immutable snapshot branching
# --------------------------------------------------------------------------- #
def branch_job(job_id: str, identity_payload: Optional[dict]) -> Job:
    """Create a new, independent, editable job from a completed saved exam.

    The parent's ``job.json`` is only ever read here, never written -- on
    both success and failure it stays byte-for-byte unchanged. Only a
    ``completed`` job may be branched (every slot is accepted by definition);
    any other status is a typed safe conflict rather than an invented
    partial-branch semantic.

    The child gets a fresh job id and fresh slot/instance ids, starts with an
    empty cost ledger/audit trail/error/attempt/retry history (new LLM
    activity is charged only to the child), inherits the parent's cost
    ceiling as its own default and its normalized ``excluded_db_ids``, and
    copies the parent's current question snapshots + ``category_history`` so
    later same-category uniqueness context and DB-replacement exclusions
    carry over automatically.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        raise JobBusy("another exam-generation operation is already running")
    got_file_lock = False
    try:
        parent = store.load(job_id)
        if parent is None:
            raise JobError(f"job {job_id} not found")
        # WP27R §5: branching requires BOTH the existing status rule AND the
        # persisted workflow phase to agree the job is genuinely finished --
        # the two always agree by invariant for a correctly-computed job, but
        # checking both is a deliberate belt-and-braces guard against ever
        # branching a job whose planned LLM batch has not actually finished
        # traversing (db_review or a recoverable/active llm_generation).
        if parent.status != "completed" or parent.workflow_phase != "complete":
            raise JobConflict(
                "ניתן ליצור גרסה חדשה רק ממבחן שהושלם במלואו"
            )
        got_file_lock = store.try_acquire_lock(job_id)
        if not got_file_lock:
            raise JobBusy("job is locked by another process")

        try:
            identity = naming.resolve_identity(identity_payload)
        except naming.IdentityError as exc:
            raise JobError(str(exc)) from exc

        new_slots = []
        for s in parent.slots:
            if s.status != "accepted" or not s.question:
                continue  # a completed job has none of these, kept defensive
            new_slots.append(Slot(
                slot_id=new_id(), instance_id=new_id(), category=s.category,
                context_id=s.context_id, kind=s.kind, order_in_category=s.order_in_category,
                number=s.number, status="accepted", attempts=0, retries=0,
                safe_error=None, question=dict(s.question), db_id=s.db_id,
                audit_ref=None, was_repaired=False, analytics=dict(s.analytics),
                # WP26R §5: deep-copy the category snapshot as-is (including a
                # pre-WP26R ``None``, which the child renders via the same
                # deterministic fallback as the parent) -- never refreshed
                # from the live DB.
                primary_category=s.primary_category,
                categories=list(s.categories) if s.categories is not None else None,
            ))
        new_categories = [
            CategoryPlan(
                category=c.category, context_id=c.context_id, order_index=c.order_index,
                total=c.total, database=c.database, llm=c.llm, number_base=c.number_base,
                db_selected_ids=list(c.db_selected_ids),
            )
            for c in parent.categories
        ]
        child = Job(
            job_id=new_id(),
            status="completed",
            # WP27R §1: a branch only ever copies ACCEPTED slots (nothing
            # "queued"/planned survives branching) -- its workflow_phase is
            # unambiguously "complete", never the dataclass default
            # ("db_review"), which would otherwise wrongly hide the child's
            # own branchability and show a stale DB-review banner for it.
            workflow_phase="complete",
            cost_ceiling_usd=parent.cost_ceiling_usd,
            accumulated_cost_usd="0",
            cost_basis="none",
            request=dict(parent.request),
            categories=new_categories,
            slots=new_slots,
            category_history={k: [dict(h) for h in v] for k, v in parent.category_history.items()},
            cost_ledger=[],
            pricing_verification={},
            warnings=[],
            terminal_summary=None,
            safe_error=None,
            identity=identity,
            excluded_db_ids=list(parent.excluded_db_ids),
            parent_job_id=parent.job_id,
            root_job_id=parent.root_job_id or parent.job_id,
        )
        store.save(child)
        return child
    finally:
        if got_file_lock:
            store.release_lock(job_id)
        _RUN_LOCK.release()


def _db_slot_dto(slot: Slot) -> ExamQuestionDTO:
    """Rich DTO for a DB slot, built ENTIRELY from persisted slot data (WP26R
    §5) -- never a live query of the ``Question`` table. Question text,
    answers, correct answer, primary category, full category list and
    analytics all come from the slot's own selection-time snapshot, so a
    saved exam stays byte-stable across later DB edits/deletes and renders
    identically with or without an app context.

    ``primary_category`` / ``categories`` fall back deterministically to
    ``slot.category`` / ``[slot.category]`` for a pre-WP26R slot that has no
    snapshot (never enriched from the live DB)."""
    primary_category = slot.primary_category if slot.primary_category is not None else slot.category
    categories = list(slot.categories) if slot.categories is not None else [slot.category]
    dto = ExamQuestionDTO(
        **{f: slot.question[f] for f in SEVEN},
        origin="database", id=slot.db_id, instance_id=slot.instance_id,
        category=slot.category, primary_category=primary_category, categories=categories,
    )
    dto.accuracy = slot.analytics.get("accuracy")
    dto.distinction = slot.analytics.get("distinction")
    dto.accuracy_list = list(slot.analytics.get("accuracy_list") or [])
    dto.distinction_list = list(slot.analytics.get("distinction_list") or [])
    return dto


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


# --------------------------------------------------------------------------- #
# full current-exam export -- complete legacy schema (WP21 §1 / §5)
# --------------------------------------------------------------------------- #
#: Recovered verbatim from the pre-WP19 ``/api/test/export-excel`` route
#: (``git show 4cd86d1:backend/src/routes/test_generation.py``), removed when
#: WP19 deleted the legacy frontend's only caller. Column order and Hebrew
#: labels unchanged.
FULL_EXPORT_HEADERS = [
    "מספר_שאלה", "מזהה_שאלה", "נושא", "שאלה", "תשובה1", "תשובה2",
    "תשובה3", "תשובה4", "תשובה_נכונה", "דיוק", "הבחנה", "תאריך_יצירה",
]


def _legacy_perf_cell(avg: Optional[float], values: list) -> str:
    """The exact legacy missing/multi-value convention for one performance
    column: a single historical value renders as ``"[v]"``; several as a JSON
    array string (``json.dumps``); no data at all renders as an empty string.
    Never a fabricated ``0`` and never the literal text ``"NaN"`` -- neither
    ever appeared in the recovered legacy code (see WP21_ARCHITECT_REPORT.md
    §1)."""
    if values:
        return f"[{values[0]}]" if len(values) == 1 else json.dumps(values)
    if avg is not None:
        return f"[{avg}]"
    return ""


def export_full_xlsx(job: Job) -> bytes:
    """Every CURRENT accepted question (DB + LLM, post-replacement), canonical
    order, using the complete legacy schema/column order/missing-value
    convention above. DB rows carry their real id + analytics snapshot; LLM
    rows use the same columns with id/accuracy/distinction rendered by the
    same missing-value convention (never fabricated -- WP21 §5). Never
    inserts anything into the DB; ``תאריך_יצירה`` is this export's own
    timestamp for every row, exactly as the legacy route did (it was never
    the question's own upload date).

    WP27 §7/§9: during ``db_review`` the number column uses the same compact
    ``1..N`` interim position as ``result_view`` (see its docstring) instead
    of the persisted final ``slot.number``; after Continue is claimed the
    real, stable final number is used, exactly as before WP27."""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Exam"
    ws.append(FULL_EXPORT_HEADERS)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    interim_numbering = workflow_phase(job) == "db_review"
    for pos, slot in enumerate(job.accepted_questions_ordered(), 1):
        q = slot.question
        analytics = slot.analytics or missing_analytics()
        ws.append([
            pos if interim_numbering else slot.number,
            slot.db_id if slot.db_id is not None else "",
            slot.category,
            q["question"], q["answer1"], q["answer2"], q["answer3"], q["answer4"],
            q["correct_answer"],
            _legacy_perf_cell(analytics.get("accuracy"), analytics.get("accuracy_list") or []),
            _legacy_perf_cell(analytics.get("distinction"), analytics.get("distinction_list") or []),
            generated_at,
        ])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
