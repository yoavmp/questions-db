"""Job / category-plan / slot data model and its JSON projection (WP18 §2, §5).

Nothing here does IO. :mod:`src.jobs.store` persists these atomically;
:mod:`src.jobs.service` drives them.

Job states (``JOB_STATES``):
    queued       - created, not started
    running      - the single worker is processing it
    completed    - every requested slot produced an accepted question
    partial      - at least one accepted and at least one failed slot
    interrupted  - process died while running; unfinished slots are retryable
    cost_ceiling - stopped because the cumulative cap would be breached
    failed       - LLM work requested but nothing accepted (and not cost_ceiling)

Slot states (``SLOT_STATES``):
    queued | running | accepted | failed | interrupted | cost_ceiling
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

SEVEN = ("number", "question", "answer1", "answer2", "answer3", "answer4", "correct_answer")

JOB_STATES = (
    "queued", "running", "completed", "partial", "interrupted", "cost_ceiling", "failed",
)
SLOT_STATES = ("queued", "running", "accepted", "failed", "interrupted", "cost_ceiling")
SLOT_KINDS = ("database", "llm")

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def missing_analytics() -> dict:
    """JSON-safe "no historical performance data" shape (WP21 §3) -- an LLM
    question, or a DB question that has never been used before."""
    return {"accuracy": None, "distinction": None, "accuracy_list": [], "distinction_list": []}


@dataclass
class Slot:
    slot_id: str
    instance_id: str
    category: str
    context_id: str
    kind: str                      # "database" | "llm"
    order_in_category: int         # 0-based position of this slot within its category block
    number: int                    # final global exam number (stable, preserved on replace)
    status: str = "queued"
    attempts: int = 0
    retries: int = 0
    safe_error: Optional[str] = None
    #: seven-field public question (accepted). For DB slots this is filled at
    #: selection time; for LLM slots on acceptance.
    question: Optional[dict] = None
    #: DB primary key when kind == "database", else None
    db_id: Optional[int] = None
    audit_ref: Optional[str] = None
    was_repaired: bool = False
    #: WP21 §3 -- the DB question's historical accuracy/distinction, snapshotted
    #: at selection/replacement time (never re-fetched live, never for LLM
    #: origin). JSON-safe: ``null`` singles, ``[]`` empty lists -- see
    #: ``missing_analytics()``. Never part of ``question`` (the seven public
    #: fields) and never sent to the generator.
    analytics: dict = field(default_factory=missing_analytics)

    #: WP26R §5 -- selection-time category snapshot, immutable thereafter.
    #: ``primary_category`` is the DB question's singular primary at the
    #: moment it entered this slot (== ``category`` for LLM-origin slots);
    #: ``categories`` is its full ordered category list at that moment
    #: (``[category]`` for LLM-origin). ``None`` on every pre-WP26R slot --
    #: never backfilled onto a legacy persisted job; ``result_view`` applies
    #: the deterministic ``primary_category = category`` /
    #: ``categories = [category]`` fallback at read time instead.
    primary_category: Optional[str] = None
    categories: Optional[list] = None

    def to_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "instance_id": self.instance_id,
            "category": self.category,
            "context_id": self.context_id,
            "kind": self.kind,
            "order_in_category": self.order_in_category,
            "number": self.number,
            "status": self.status,
            "attempts": self.attempts,
            "retries": self.retries,
            "safe_error": self.safe_error,
            "question": self.question,
            "db_id": self.db_id,
            "audit_ref": self.audit_ref,
            "was_repaired": self.was_repaired,
            "analytics": self.analytics,
            "primary_category": self.primary_category,
            "categories": self.categories,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Slot":
        return cls(
            slot_id=d["slot_id"],
            instance_id=d["instance_id"],
            category=d["category"],
            context_id=d["context_id"],
            kind=d["kind"],
            order_in_category=d["order_in_category"],
            number=d["number"],
            status=d.get("status", "queued"),
            attempts=d.get("attempts", 0),
            retries=d.get("retries", 0),
            safe_error=d.get("safe_error"),
            question=d.get("question"),
            db_id=d.get("db_id"),
            audit_ref=d.get("audit_ref"),
            was_repaired=d.get("was_repaired", False),
            analytics=d.get("analytics") or missing_analytics(),
            # WP26R §5: absent on every pre-WP26R slot -- calculated fallback
            # only (see ``service.result_view``), never backfilled here.
            primary_category=d.get("primary_category"),
            categories=d.get("categories"),
        )


@dataclass
class CategoryPlan:
    category: str
    context_id: str
    order_index: int
    total: int
    database: int
    llm: int
    number_base: int               # global number of the last question BEFORE this block
    db_selected_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "context_id": self.context_id,
            "order_index": self.order_index,
            "total": self.total,
            "database": self.database,
            "llm": self.llm,
            "number_base": self.number_base,
            "db_selected_ids": list(self.db_selected_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CategoryPlan":
        return cls(
            category=d["category"],
            context_id=d["context_id"],
            order_index=d["order_index"],
            total=d["total"],
            database=d["database"],
            llm=d["llm"],
            number_base=d["number_base"],
            db_selected_ids=list(d.get("db_selected_ids", [])),
        )


@dataclass
class Job:
    job_id: str
    status: str = "queued"
    created_utc: str = field(default_factory=now_iso)
    updated_utc: str = field(default_factory=now_iso)
    schema: int = SCHEMA_VERSION

    cost_ceiling_usd: str = "5.00"
    accumulated_cost_usd: str = "0"
    cost_basis: str = "none"        # none | calculated | conservative_bound | mixed

    request: dict = field(default_factory=dict)
    categories: list = field(default_factory=list)     # list[CategoryPlan]
    slots: list = field(default_factory=list)          # list[Slot]

    #: immutable per-category history of discarded / replaced LLM questions,
    #: seven-field JSON, in the order they were discarded. Repeated and
    #: non-monotonic ``number`` values are legitimate and are never sorted or
    #: de-duplicated before a generator call.
    category_history: dict = field(default_factory=dict)

    #: cumulative cost ledger: one entry per generator call outcome
    cost_ledger: list = field(default_factory=list)
    pricing_verification: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    terminal_summary: Optional[dict] = None
    safe_error: Optional[str] = None

    #: WP26 §1 -- structured/custom naming. ``None`` on every pre-WP26 job and
    #: on a WP26 job created without an identity payload; both cases fall back
    #: to ``naming.fallback_label`` wherever a display name is needed. Never
    #: derive storage paths from it -- ``job_id`` remains authoritative.
    identity: Optional[dict] = None

    #: WP26 §2-§3 -- normalized, deduplicated DB question ids this job (and
    #: every descendant branch) must never select or replace in. Empty list on
    #: every pre-WP26 job (never rewritten merely to add this field).
    excluded_db_ids: list = field(default_factory=list)

    #: WP26 §4 -- lineage. ``None``/``job_id`` (itself) on every job that was
    #: not created by branching.
    parent_job_id: Optional[str] = None
    root_job_id: Optional[str] = None

    # ----- helpers -------------------------------------------------------
    def touch(self) -> None:
        self.updated_utc = now_iso()

    def slot_by_instance(self, instance_id: str) -> Optional[Slot]:
        for s in self.slots:
            if s.instance_id == instance_id:
                return s
        return None

    def slot_by_id(self, slot_id: str) -> Optional[Slot]:
        for s in self.slots:
            if s.slot_id == slot_id:
                return s
        return None

    def plan_for(self, category: str) -> Optional[CategoryPlan]:
        for p in self.categories:
            if p.category == category:
                return p
        return None

    def remaining_budget(self) -> Decimal:
        return Decimal(self.cost_ceiling_usd) - Decimal(self.accumulated_cost_usd)

    def accepted_questions_ordered(self) -> list:
        """Every accepted slot's DTO-ready dict, in canonical category order then
        DB-first within a category, then LLM in generation order."""
        ordered: list = []
        for plan in sorted(self.categories, key=lambda p: p.order_index):
            block = [s for s in self.slots if s.category == plan.category]
            # preserved global ``number`` drives order (stable across a
            # cross-source replacement, which changes a slot's ``kind``)
            block.sort(key=lambda s: s.number)
            for s in block:
                if s.status == "accepted" and s.question:
                    ordered.append(s)
        return ordered

    # ----- serialization ----------------------------------------------
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "schema": self.schema,
            "status": self.status,
            "created_utc": self.created_utc,
            "updated_utc": self.updated_utc,
            "cost_ceiling_usd": self.cost_ceiling_usd,
            "accumulated_cost_usd": self.accumulated_cost_usd,
            "cost_basis": self.cost_basis,
            "request": self.request,
            "categories": [c.to_dict() for c in self.categories],
            "slots": [s.to_dict() for s in self.slots],
            "category_history": self.category_history,
            "cost_ledger": self.cost_ledger,
            "pricing_verification": self.pricing_verification,
            "warnings": self.warnings,
            "terminal_summary": self.terminal_summary,
            "safe_error": self.safe_error,
            "identity": self.identity,
            "excluded_db_ids": list(self.excluded_db_ids),
            "parent_job_id": self.parent_job_id,
            "root_job_id": self.root_job_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        job_id = d["job_id"]
        return cls(
            job_id=job_id,
            schema=d.get("schema", SCHEMA_VERSION),
            status=d.get("status", "queued"),
            created_utc=d.get("created_utc", now_iso()),
            updated_utc=d.get("updated_utc", now_iso()),
            cost_ceiling_usd=str(d.get("cost_ceiling_usd", "5.00")),
            accumulated_cost_usd=str(d.get("accumulated_cost_usd", "0")),
            cost_basis=d.get("cost_basis", "none"),
            request=d.get("request", {}),
            categories=[CategoryPlan.from_dict(c) for c in d.get("categories", [])],
            slots=[Slot.from_dict(s) for s in d.get("slots", [])],
            category_history=d.get("category_history", {}),
            cost_ledger=d.get("cost_ledger", []),
            pricing_verification=d.get("pricing_verification", {}),
            warnings=d.get("warnings", []),
            terminal_summary=d.get("terminal_summary"),
            safe_error=d.get("safe_error"),
            # WP26: absent on every pre-WP26 job -- calculated fallback only,
            # never backfilled onto the persisted file.
            identity=d.get("identity"),
            excluded_db_ids=list(d.get("excluded_db_ids", []) or []),
            parent_job_id=d.get("parent_job_id"),
            root_job_id=d.get("root_job_id") or job_id,
        )

    # ----- progress view for the API ---------------------------------
    def progress_view(self) -> dict:
        by_cat: dict[str, dict] = {}
        for plan in sorted(self.categories, key=lambda p: p.order_index):
            block = [s for s in self.slots if s.category == plan.category]
            by_cat[plan.category] = {
                "order_index": plan.order_index,
                "total": plan.total,
                "database": plan.database,
                "llm": plan.llm,
                "accepted": sum(1 for s in block if s.status == "accepted"),
                "failed": sum(1 for s in block if s.status in ("failed", "cost_ceiling")),
                "pending": sum(1 for s in block if s.status in ("queued", "running", "interrupted")),
                "slots": [
                    {
                        "slot_id": s.slot_id,
                        "instance_id": s.instance_id,
                        "kind": s.kind,
                        "number": s.number,
                        "status": s.status,
                        "attempts": s.attempts,
                        "retries": s.retries,
                        "safe_error": s.safe_error,
                    }
                    for s in sorted(block, key=lambda s: s.number)
                ],
            }
        llm_slots = [s for s in self.slots if s.kind == "llm"]
        return {
            "job_id": self.job_id,
            "status": self.status,
            "cost_ceiling_usd": self.cost_ceiling_usd,
            "accumulated_cost_usd": self.accumulated_cost_usd,
            "cost_basis": self.cost_basis,
            "remaining_cost_usd": str(self.remaining_budget()),
            "totals": {
                "questions_requested": sum(p.total for p in self.categories),
                "llm_requested": sum(p.llm for p in self.categories),
                "llm_accepted": sum(1 for s in llm_slots if s.status == "accepted"),
                "llm_failed": sum(1 for s in llm_slots if s.status in ("failed", "cost_ceiling")),
                "retries": sum(s.retries for s in llm_slots),
            },
            "pricing_verification": self.pricing_verification,
            "warnings": self.warnings,
            "categories": by_cat,
            "terminal_summary": self.terminal_summary,
            "updated_utc": self.updated_utc,
        }
