"""WP21R §3 -- one immutable, crash-safe directory per top-level LLM
invocation (initial / retry / replace_llm), plus §1's strengthened
missing-value regression and §2's separated retry/replacement telemetry.

Offline: temp DB, fake in-process providers (tests/_wp18_fakes.py), no real
provider/network calls, no OPENAI_API_KEY read (``llm_ready`` sets only an
in-process sentinel env var so the readiness check passes).
"""

from __future__ import annotations

import json
import re

import pytest

from tests._wp18_fakes import Dispatch, dispatch_factory

from src.jobs import service, store
from src.jobs.model import missing_analytics

CAT = "היסטולוגיה"

#: matches store._INVOCATION_RE -- kept independent here so this test would
#: fail if the production format silently drifted.
_DIR_RE = re.compile(
    r"^(initial|retry|replace_llm)_([0-9]{4})_"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


def _one_llm_job(jobs_app):
    with jobs_app.app_context():
        return service.create_job(
            {"categories": {CAT: {"total": 1, "database": 0, "llm": 1}}, "cost_ceiling_usd": "5.00"}
        )


# --------------------------------------------------------------------------- #
# §3 -- directory naming: UUID is the authoritative identity
# --------------------------------------------------------------------------- #
def test_invocation_directory_name_embeds_an_authoritative_uuid4(jobs_app, jobs_root, llm_ready):
    job = _one_llm_job(jobs_app)
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    assert slot.status == "accepted"

    invocation_id = slot.audit_ref.split("/")[-1]
    m = _DIR_RE.match(invocation_id)
    assert m, f"invocation dir name {invocation_id!r} does not match <op>_<seq>_<uuid4>"
    op, seq, uuid_part = m.groups()
    assert op == "initial"
    assert seq == "0001"
    # version 4 / variant bits, confirming secure uuid.uuid4() generation
    assert uuid_part[14] == "4"
    assert uuid_part[19] in "89ab"

    ledger_entry = done.cost_ledger[-1]
    assert ledger_entry["invocation_uuid"] == uuid_part
    assert ledger_entry["audit_ref"] == slot.audit_ref


def test_two_operations_on_one_slot_get_different_uuids_even_with_the_same_op_and_seq(
    jobs_app, jobs_root, llm_ready,
):
    """Directly exercises the collision the pre-WP21R scheme was vulnerable
    to: two invocations that would compute the identical "<op>_<seq>" prefix
    (here forced, not just crash-simulated) must still land in different,
    non-colliding directories because the UUID -- not the prefix -- is the
    real identity."""
    job = _one_llm_job(jobs_app)
    slot = job.slots[0]

    uuid_a = store.new_invocation_uuid()
    uuid_b = store.new_invocation_uuid()
    assert uuid_a != uuid_b

    name_a = store.invocation_dir_name("initial", 1, uuid_a)
    name_b = store.invocation_dir_name("initial", 1, uuid_b)  # same op, same seq
    assert name_a != name_b

    dir_a = store.invocation_audit_dir(job.job_id, slot.slot_id, name_a)
    dir_b = store.invocation_audit_dir(job.job_id, slot.slot_id, name_b)
    assert dir_a != dir_b
    assert dir_a.is_dir() and dir_b.is_dir()


def test_invocation_audit_dir_never_silently_reuses_an_existing_path(jobs_app, jobs_root, llm_ready):
    """``invocation_audit_dir`` must refuse (not silently reuse/overwrite) a
    name that already exists -- the bug class this WP closes."""
    job = _one_llm_job(jobs_app)
    slot = job.slots[0]
    name = store.invocation_dir_name("initial", 1, store.new_invocation_uuid())
    first = store.invocation_audit_dir(job.job_id, slot.slot_id, name)
    (first / "evidence.txt").write_bytes(b"do-not-touch")
    with pytest.raises(FileExistsError):
        store.invocation_audit_dir(job.job_id, slot.slot_id, name)
    assert (first / "evidence.txt").read_bytes() == b"do-not-touch"


# --------------------------------------------------------------------------- #
# §3 -- crash safety: allocation happens, ledger append never happens
# --------------------------------------------------------------------------- #
def test_crash_after_allocation_before_ledger_append_does_not_collide(jobs_app, jobs_root, llm_ready):
    """Simulates the exact crash window WP21R closes: an invocation directory
    (+ manifest) was allocated for what would be this slot's next ledger
    position, but the process died before ``_record_cost`` ever appended to
    ``cost_ledger`` -- so the ledger is unchanged and the *next* invocation
    recomputes the identical "seq". Before this WP, that recomputed seq
    produced the identical directory name and (with the old ``exist_ok=True``)
    silently reused it. Now the fresh UUID guarantees a different directory,
    and the crashed one is left byte-for-byte untouched."""
    job = _one_llm_job(jobs_app)
    slot = job.slots[0]

    seq = len(job.cost_ledger) + 1  # == 1; the real run below will recompute the same value
    crashed_uuid = store.new_invocation_uuid()
    crashed_name = store.invocation_dir_name("initial", seq, crashed_uuid)
    crashed_dir = store.invocation_audit_dir(job.job_id, slot.slot_id, crashed_name)
    store.write_invocation_manifest(crashed_dir, {
        "job_id": job.job_id, "slot_id": slot.slot_id, "operation": "initial",
        "sequence": seq, "invocation_uuid": crashed_uuid, "created_at": "2026-01-01T00:00:00Z",
    })
    (crashed_dir / "attempt_01").mkdir()
    (crashed_dir / "attempt_01" / "partial_evidence.txt").write_bytes(b"orphaned crash evidence")
    manifest_before = (crashed_dir / "invocation_manifest.json").read_bytes()

    # the real run proceeds untouched by the simulated crash above
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    real_slot = done.slot_by_id(slot.slot_id)
    assert real_slot.status == "accepted"
    real_dir = store.job_dir(done.job_id) / real_slot.audit_ref

    assert real_dir != crashed_dir                 # no collision despite identical op/seq
    assert real_dir.is_dir()
    # the crashed directory's evidence is completely untouched
    assert (crashed_dir / "invocation_manifest.json").read_bytes() == manifest_before
    assert (crashed_dir / "attempt_01" / "partial_evidence.txt").read_bytes() == b"orphaned crash evidence"
    # the crashed invocation never made it into the ledger (it never happened, from the job's view)
    assert crashed_uuid not in [e.get("invocation_uuid") for e in done.cost_ledger]


# --------------------------------------------------------------------------- #
# §3 -- invocation manifest: written before the provider boundary, safe fields only
# --------------------------------------------------------------------------- #
def test_invocation_manifest_written_before_the_provider_boundary_has_only_safe_fields(
    jobs_app, jobs_root, llm_ready,
):
    job = _one_llm_job(jobs_app)
    done = service.run_job(job.job_id, provider_factory=dispatch_factory(Dispatch()))
    slot = next(s for s in done.slots if s.kind == "llm")
    assert slot.status == "accepted"

    audit_dir = store.job_dir(done.job_id) / slot.audit_ref
    manifest_path = audit_dir / "invocation_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert set(manifest.keys()) == {
        "job_id", "slot_id", "operation", "sequence", "invocation_uuid", "created_at",
    }
    assert manifest["job_id"] == done.job_id
    assert manifest["slot_id"] == slot.slot_id
    assert manifest["operation"] == "initial"
    assert manifest["sequence"] == 1
    assert slot.audit_ref.endswith(manifest["invocation_uuid"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", manifest["created_at"])

    # never a question/prompt/response/source/credential, never an absolute path
    blob = manifest_path.read_text(encoding="utf-8")
    for forbidden in ("question", "prompt", "response", "answer", "api_key", "OPENAI", "sk-"):
        assert forbidden not in blob
    assert str(store.jobs_root()) not in blob
    assert not blob.strip().startswith("/")


def test_write_invocation_manifest_rejects_unsafe_fields(jobs_app, jobs_root, llm_ready):
    job = _one_llm_job(jobs_app)
    slot = job.slots[0]
    name = store.invocation_dir_name("initial", 1, store.new_invocation_uuid())
    audit_dir = store.invocation_audit_dir(job.job_id, slot.slot_id, name)
    with pytest.raises(ValueError):
        store.write_invocation_manifest(audit_dir, {
            "job_id": job.job_id, "slot_id": slot.slot_id, "operation": "initial",
            "sequence": 1, "invocation_uuid": "x", "created_at": "now",
            "prompt": "leaked prompt text",
        })
    assert not (audit_dir / "invocation_manifest.json").exists()


# --------------------------------------------------------------------------- #
# §3 -- readability of pre-WP21R (WP18-WP21) audit references is unaffected
# --------------------------------------------------------------------------- #
def test_old_style_audit_ref_without_a_uuid_still_round_trips_through_job_json(jobs_app, jobs_root, llm_ready):
    """``audit_ref`` is stored and displayed as an opaque string -- a job
    persisted before this WP (e.g. ``slots/<slot_id>/initial_0001``, no UUID
    suffix) must keep loading and saving cleanly; nothing here parses or
    validates the format of an ALREADY-STORED ``audit_ref``."""
    job = _one_llm_job(jobs_app)
    slot = job.slots[0]
    slot.audit_ref = f"slots/{slot.slot_id}/initial_0001"  # pre-WP21R shape
    store.save(job)

    reloaded = store.load(job.job_id)
    assert reloaded.slot_by_id(slot.slot_id).audit_ref == f"slots/{slot.slot_id}/initial_0001"


# --------------------------------------------------------------------------- #
# §1 -- strengthened missing-value regression: never 0, never NaN, never fabricated
# --------------------------------------------------------------------------- #
def test_missing_analytics_are_none_not_zero_or_fabricated(jobs_app, jobs_root):
    m = missing_analytics()
    assert m["accuracy"] is None and m["distinction"] is None
    assert m["accuracy_list"] == [] and m["distinction_list"] == []
    # explicitly not the falsy-but-fabricated value 0 (a bare `assert not
    # m["accuracy"]` would also pass for 0 -- this is the stricter check)
    for key in ("accuracy", "distinction"):
        assert m[key] is None
        assert m[key] != 0
        assert not isinstance(m[key], float) or m[key] == m[key]  # never NaN (NaN != NaN)
